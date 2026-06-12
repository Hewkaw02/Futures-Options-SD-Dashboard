/* ═══════════════════════════════════════════════════════════════
   FUTURES OPTIONS TRADING DASHBOARD — Application Logic
   Handles: Data fetching, chart rendering, navigation
   ═══════════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────
const state = {
  currentAsset: 'GC',
  currentIndex: -1,        // index into manifest timestamps
  manifest: [],            // sorted array of "YYYY-MM-DD/HH00"
  cache: {},               // "GC:2026-05-08/1100" -> data
  fetchPromises: {},       // coalesce concurrent fetch requests
  charts: {},              // chart instance refs for cleanup
  resizeObservers: {},     // resize observer refs for cleanup
  activeTabs: {            // active tab per image chart group
    'hybrid': 'hybrid_15m',
    'intraday-master': 'intraday_master_5m',
  },
  toggles: {
    hybrid: {
      sdBands: true,
      sessionLevels: true,
      oiWalls: true
    },
    master: {
      vwap: true,
      tradeSetup: true,
      oiWalls: true
    }
  }
};


// ── Decision Terminal Toggles & Helper Functions ─────────────
function toggleLayer(chartType, layerKey) {
  let checkboxId = '';
  if (chartType === 'hybrid') {
    if (layerKey === 'sdBands') checkboxId = 'toggle-hybrid-sdbands';
    else if (layerKey === 'sessionLevels') checkboxId = 'toggle-hybrid-session';
    else if (layerKey === 'oiWalls') checkboxId = 'toggle-hybrid-oiwalls';
  } else if (chartType === 'master') {
    if (layerKey === 'vwap') checkboxId = 'toggle-master-vwap';
    else if (layerKey === 'tradeSetup') checkboxId = 'toggle-master-setup';
    else if (layerKey === 'oiWalls') checkboxId = 'toggle-master-walls';
  }

  const checkbox = document.getElementById(checkboxId);
  if (checkbox) {
    state.toggles[chartType][layerKey] = checkbox.checked;
  } else {
    state.toggles[chartType][layerKey] = !state.toggles[chartType][layerKey];
  }

  // Live update the affected chart!
  const ts = state.manifest[state.currentIndex];
  if (ts) {
    const cacheKey = `${state.currentAsset}:${ts}`;
    const data = state.cache[cacheKey];
    if (data) {
      if (chartType === 'hybrid') {
        renderHybridChart(data);
      } else {
        renderIntradayMasterChart(data);
      }
    }
  }
}

// Wall Strength Scoring Logic
function calculateWallStrength(strike, isRes, oi, vol, price, vwap, step, maxOI, maxVol) {
  if (!price) return 0;
  
  // 1. Normalized OI (up to 3.5 points)
  const oiScore = maxOI > 0 ? Math.min(3.5, (oi / maxOI) * 3.5) : 0;
  
  // 2. Normalized Volume (up to 2.5 points)
  const volScore = maxVol > 0 ? Math.min(2.5, (vol / maxVol) * 2.5) : 0;
  
  // 3. Proximity to price (up to 1.5 points)
  const distance = Math.abs(strike - price);
  const proximityScore = step ? Math.max(0, 1.5 * (1 - (distance / (step * 3)))) : 0;
  
  // 4. Confluence with VWAP or SD bands (up to 1.5 points)
  let confluenceScore = 0;
  if (vwap && Math.abs(strike - vwap) < (step * 0.15)) {
    confluenceScore = 1.5;
  } else if (step) {
    // SD levels confluence
    for (let i = 1; i <= 3; i++) {
      if (Math.abs(strike - (price + step * i)) < (step * 0.15) || 
          Math.abs(strike - (price - step * i)) < (step * 0.15)) {
        confluenceScore = 1.0;
        break;
      }
    }
  }
  
  // 5. Persistence Score (base 1.0 points)
  const persistenceScore = 1.0;
  
  const score = oiScore + volScore + proximityScore + confluenceScore + persistenceScore;
  return Math.min(10, Math.max(1, score));
}

// Tactical Trade Setup Generator & Live Tracker
function getSetupDetails(data, currentPrice, vwap, step) {
  const biasLabel = data.bias ? data.bias.label || 'Neutral' : 'Neutral';
  const isBull = biasLabel.toLowerCase().includes('bull');
  const isBear = biasLabel.toLowerCase().includes('bear');
  
  // Find strongest option/volume walls from real-time Intraday Volume Profile S/R
  let maxSupport = null;
  let maxResistance = null;
  
  if (data.intraday_levels) {
    const supports = data.intraday_levels.vol_supports || [];
    const resistances = data.intraday_levels.vol_resistances || [];
    
    if (supports.length > 0) {
      const sorted = [...supports].sort((a,b) => b[1] - a[1]);
      maxSupport = sorted[0][0]; // strike
    }
    if (resistances.length > 0) {
      const sorted = [...resistances].sort((a,b) => b[1] - a[1]);
      maxResistance = sorted[0][0]; // strike
    }
  }
  
  // Fallbacks to OI if volume profile is empty
  if (!maxSupport && data.intraday_levels) {
    const supports = data.intraday_levels.oi_supports || [];
    if (supports.length > 0) {
      const sorted = [...supports].sort((a,b) => b[1] - a[1]);
      maxSupport = sorted[0][0]; // strike
    }
  }
  if (!maxResistance && data.intraday_levels) {
    const resistances = data.intraday_levels.oi_resistances || [];
    if (resistances.length > 0) {
      const sorted = [...resistances].sort((a,b) => b[1] - a[1]);
      maxResistance = sorted[0][0]; // strike
    }
  }
  
  if (!maxSupport) maxSupport = currentPrice - (step || 50);
  if (!maxResistance) maxResistance = currentPrice + (step || 50);
  if (!step) step = (maxResistance - maxSupport) / 2;
  
  let entryMin, entryMax, stopLoss, target1, target2, action, prefPlay;
  
  if (isBull) {
    action = "BUY / LONG";
    prefPlay = "Buy Support Rejection";
    entryMin = maxSupport - step * 0.05;
    entryMax = maxSupport + step * 0.10;
    stopLoss = maxSupport - step * 0.15; // Tighter stop loss (15% of SD)
    target1 = Math.min(maxResistance, maxSupport + step * 0.40); // Highly achievable T1
    target2 = Math.min(maxResistance + step * 0.20, maxSupport + step * 0.70); // Stretch T2
  } else if (isBear) {
    action = "SELL / SHORT";
    prefPlay = "Sell Resistance Rejection";
    entryMin = maxResistance - step * 0.10;
    entryMax = maxResistance + step * 0.05;
    stopLoss = maxResistance + step * 0.15; // Tighter stop loss
    target1 = Math.max(maxSupport, maxResistance - step * 0.40); // Achievable T1
    target2 = Math.max(maxSupport - step * 0.20, maxResistance - step * 0.70); // Stretch T2
  } else {
    action = "RANGE PLAY";
    prefPlay = "Buy Support / Sell Resistance";
    entryMin = maxSupport;
    entryMax = maxResistance;
    stopLoss = maxSupport - step * 0.15;
    target1 = Math.min((maxSupport + maxResistance) / 2, maxSupport + step * 0.40);
    target2 = Math.min(maxResistance, maxSupport + step * 0.70);
  }
  
  let status = "ACTIVE";
  let statusClass = "active";
  if (isBull && currentPrice < stopLoss) {
    status = "SETUP FAILED";
    statusClass = "failed";
  } else if (isBear && currentPrice > stopLoss) {
    status = "SETUP FAILED";
    statusClass = "failed";
  }
  
  let rr = "1 : 2.0";
  let risk = 0;
  let reward = 0;
  
  if (isBull) {
    risk = Math.abs(maxSupport - stopLoss);
    reward = Math.abs(target1 - maxSupport);
  } else if (isBear) {
    risk = Math.abs(maxResistance - stopLoss);
    reward = Math.abs(target1 - maxResistance);
  } else {
    risk = Math.abs(maxSupport - stopLoss);
    reward = Math.abs(target1 - maxSupport);
  }
  
  if (risk > 0) {
    rr = `1 : ${(reward / risk).toFixed(1)}`;
  }
  
  return {
    bias: biasLabel,
    action,
    prefPlay,
    entryMin,
    entryMax,
    stopLoss,
    target1,
    target2,
    status,
    statusClass,
    rr
  };
}

// Detect and analyze option wall collisions & breakouts during the current trading day
function getWallInteractionDetails(ohlcv, currentPrice, maxSupport, maxResistance, step, gexRegime, datePart) {
  let callStatus = "STABLE";
  let callColor = "var(--text-primary)";
  let putStatus = "STABLE";
  let putColor = "var(--text-primary)";
  
  if (!ohlcv || ohlcv.length === 0 || !step || !datePart) {
    return { callStatus, callColor, putStatus, putColor, hedgingFlow: "No data available", flowColor: "var(--text-muted)" };
  }
  
  // Filter candles to only include bars from 00:00 UTC of the current trading day
  const startOfDayMs = new Date(datePart + "T00:00:00Z").getTime();
  const scanBars = ohlcv.filter(bar => bar[0] >= startOfDayMs);
  
  const isNegGex = (gexRegime || '').toUpperCase() === 'VOLTL';
  
  // 1. Call Wall Interactions
  let hasCallBreakout = false;
  let hasCallRejection = false;
  
  for (const bar of scanBars) {
    const high = bar[2];
    const close = bar[4];
    
    if (close > maxResistance) {
      hasCallBreakout = true;
    } else if (Math.abs(high - maxResistance) < step * 0.08 && close < maxResistance - step * 0.05) {
      hasCallRejection = true;
    }
  }
  
  if (currentPrice > maxResistance) {
    hasCallBreakout = true;
  }
  
  if (hasCallBreakout) {
    callStatus = "BROKEN (UP)";
    callColor = "var(--accent-bull)";
  } else if (hasCallRejection) {
    callStatus = "REJECTED (DOWN)";
    callColor = "var(--accent-bear)";
  } else if (Math.abs(currentPrice - maxResistance) < step * 0.03) {
    callStatus = "TESTING WALL";
    callColor = "#FEB019";
  }
  
  // 2. Put Wall Interactions
  let hasPutBreakout = false;
  let hasPutRejection = false;
  
  for (const bar of scanBars) {
    const low = bar[3];
    const close = bar[4];
    
    if (close < maxSupport) {
      hasPutBreakout = true;
    } else if (Math.abs(low - maxSupport) < step * 0.08 && close > maxSupport + step * 0.05) {
      hasPutRejection = true;
    }
  }
  
  if (currentPrice < maxSupport) {
    hasPutBreakout = true;
  }
  
  if (hasPutBreakout) {
    putStatus = "BROKEN (DOWN)";
    putColor = "var(--accent-bear)";
  } else if (hasPutRejection) {
    putStatus = "REJECTED (UP)";
    putColor = "var(--accent-bull)";
  } else if (Math.abs(currentPrice - maxSupport) < step * 0.03) {
    putStatus = "TESTING WALL";
    putColor = "#FEB019";
  }
  
  // 3. Gamma Hedging Flow determination
  let hedgingFlow = "⚪ Stable Neutral Flow: Standard market balance";
  let flowColor = "var(--text-muted)";
  
  if (callStatus === "BROKEN (UP)") {
    if (isNegGex) {
      hedgingFlow = "🔴 GAMMA SQUEEZE: Dealer short covering (fast buy flow)";
      flowColor = "var(--accent-bull)";
    } else {
      hedgingFlow = "🟢 Dealer Short Hedging: Selling futures (reins in rise)";
      flowColor = "rgba(0, 227, 150, 0.7)";
    }
  } else if (putStatus === "BROKEN (DOWN)") {
    if (isNegGex) {
      hedgingFlow = "🔴 DELTA CASCADE: Dealer shorting underlying (fast sell flow)";
      flowColor = "var(--accent-bear)";
    } else {
      hedgingFlow = "🟢 Dealer Long Hedging: Buying futures (reins in drop)";
      flowColor = "rgba(255, 69, 96, 0.7)";
    }
  } else if (callStatus === "REJECTED (DOWN)") {
    hedgingFlow = "🟢 SELLER DEFENSE: Dealer short hedging active (mean reversion)";
    flowColor = "rgba(255, 69, 96, 0.8)";
  } else if (putStatus === "REJECTED (UP)") {
    hedgingFlow = "🟢 BUYER DEFENSE: Dealer long hedging active (mean reversion)";
    flowColor = "rgba(0, 227, 150, 0.8)";
  } else if (callStatus === "TESTING WALL" || putStatus === "TESTING WALL") {
    hedgingFlow = "🟡 VOLATILITY TRIGGER: Expect heavy hedging adjustments";
    flowColor = "#FEB019";
  }
  
  return { callStatus, callColor, putStatus, putColor, hedgingFlow, flowColor };
}

// Bias score flow timeline loader
async function renderBiasTimeline() {
  const container = document.getElementById('bias-timeline-flow');
  if (!container) return;
  
  const count = 4;
  const startIndex = Math.max(0, state.currentIndex - count + 1);
  const snapshots = [];
  
  for (let i = startIndex; i <= state.currentIndex; i++) {
    snapshots.push(state.manifest[i]);
  }
  
  if (snapshots.length === 0) {
    container.innerHTML = '<span class="timeline-empty">No historical data available.</span>';
    return;
  }
  
  const promises = snapshots.map(async (ts) => {
    try {
      const d = await fetchDataWithCache(state.currentAsset, ts);
      return { ts, bias: d ? d.bias : null };
    } catch (e) {
      console.warn("Failed to prefetch for timeline:", e);
    }
    return { ts, bias: null };
  });
  
  const results = await Promise.all(promises);
  
  let html = '';
  results.forEach((r, idx) => {
    const timeLabel = r.ts.split('/')[1] || '';
    const biasLabel = r.bias ? r.bias.label || '—' : '—';
    
    let score = '0';
    let scoreClass = 'neutral';
    
    const labelLower = biasLabel.toLowerCase();
    if (labelLower.includes('strong bull')) { score = '+4'; scoreClass = 'bull'; }
    else if (labelLower.includes('bull')) { score = '+2'; scoreClass = 'bull'; }
    else if (labelLower.includes('strong bear')) { score = '-4'; scoreClass = 'bear'; }
    else if (labelLower.includes('bear')) { score = '-2'; scoreClass = 'bear'; }
    else if (labelLower.includes('neutral')) { score = '0'; scoreClass = 'neutral'; }
    
    html += `
      <div class="timeline-step">
        <span class="time">${timeLabel}</span>
        <span class="score ${scoreClass}">${score}</span>
        <span class="label" style="font-size: 0.65rem;">${biasLabel}</span>
      </div>
    `;
    
    if (idx < results.length - 1) {
      html += `<span class="timeline-arrow">➔</span>`;
    }
  });
  
  container.innerHTML = html;
}

// PCR / GEX / Skew Mini-Panels Updater
function updateMiniPanels(data) {
  if (!data || !data.bias) return;
  
  const bias = data.bias;
  
  // 1. PCR
  const pcrVal = parseFloat(bias.pcr_vol) || 0;
  document.getElementById('mini-pcr-vol').textContent = pcrVal ? pcrVal.toFixed(2) : '—';
  const pcrPercent = Math.min(100, (pcrVal / 2.0) * 100);
  const pcrBar = document.getElementById('mini-pcr-bar');
  if (pcrBar) {
    pcrBar.style.width = `${pcrPercent}%`;
    pcrBar.style.background = pcrVal > 1.0 ? 'var(--accent-bear)' : 'var(--accent-bull)';
  }
  
  // 2. GEX Regime
  const gexVal = bias.gex || '—';
  document.getElementById('mini-gex-state').textContent = gexVal;
  const gexBanner = document.getElementById('mini-gex-banner');
  if (gexBanner) {
    gexBanner.textContent = gexVal.toUpperCase();
    gexBanner.className = 'gex-status-banner';
    if (gexVal.toLowerCase().includes('pos') || gexVal.toLowerCase().includes('bull')) {
      gexBanner.classList.add('bull');
    } else if (gexVal.toLowerCase().includes('neg') || gexVal.toLowerCase().includes('bear')) {
      gexBanner.classList.add('bear');
    }
  }
  
  // 3. Skew
  const skewStr = bias.skew || '0%';
  document.getElementById('mini-skew-val').textContent = skewStr;
  const skewVal = parseFloat(skewStr.replace('%', '')) || 0;
  const skewPercent = Math.min(100, Math.abs(skewVal) * 10);
  const skewBar = document.getElementById('mini-skew-bar');
  if (skewBar) {
    skewBar.style.width = `${skewPercent}%`;
    skewBar.style.background = skewVal > 0 ? 'var(--accent-bull)' : 'var(--accent-bear)';
  }
}

// Freshness Badge Updater
function updateFreshnessBadge(ts) {
  const statusEl = document.getElementById('freshness-status');
  const ageEl = document.getElementById('freshness-age');
  const dotEl = document.querySelector('#freshness-badge .pulse-dot');
  
  if (!statusEl || !ageEl || !dotEl) return;
  
  try {
    const parts = ts.split('/');
    const dateStr = parts[0];
    const hourStr = parts[1];
    
    const year = parseInt(dateStr.substring(0, 4));
    const month = parseInt(dateStr.substring(5, 7)) - 1;
    const day = parseInt(dateStr.substring(8, 10));
    const hour = parseInt(hourStr.substring(0, 2));
    
    const snapUtc = Date.UTC(year, month, day, hour, 0, 0);
    const nowUtc = Date.now();
    
    const diffMs = nowUtc - snapUtc;
    const diffMin = Math.max(0, Math.floor(diffMs / 60000));
    
    ageEl.textContent = `${diffMin}m`;
    
    if (diffMin < 15) {
      statusEl.textContent = 'Fresh';
      dotEl.className = 'pulse-dot';
    } else if (diffMin < 60) {
      statusEl.textContent = 'Delayed';
      dotEl.className = 'pulse-dot delayed';
    } else {
      statusEl.textContent = 'Stale';
      dotEl.className = 'pulse-dot stale';
    }
  } catch (e) {
    console.warn("Freshness parse error:", e);
    statusEl.textContent = '—';
    ageEl.textContent = '—';
  }
}


const ASSET_LABELS = {
  GC: 'GC — GOLD',
  ES: 'ES — S&P 500',
  NQ: 'NQ — NASDAQ',
};

// ── Bootstrap ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadManifest();
  setupKeyboardNav();
});

// ── Manifest Loading ─────────────────────────────────────────
async function loadManifest() {
  try {
    const res = await fetch('data/manifest.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.manifest = data.timestamps || [];
    if (state.manifest.length === 0) {
      showGlobalError('No data available yet. Run the analysis pipeline first.');
      return;
    }
    // Start at the latest timestamp
    state.currentIndex = state.manifest.length - 1;
    loadCurrentData();
  } catch (err) {
    console.error('Failed to load manifest:', err);
    showGlobalError('Could not load data manifest. Ensure data/manifest.json exists.');
  }
}

// Global fetch promise cache to prevent redundant concurrent fetches
async function fetchDataWithCache(asset, ts) {
  const cacheKey = `${asset}:${ts}`;
  
  // 1. Check if we already have the data in cache
  if (state.cache[cacheKey]) {
    return state.cache[cacheKey];
  }
  
  // 2. Check if there is already an active fetch promise for this key
  if (state.fetchPromises[cacheKey]) {
    return state.fetchPromises[cacheKey];
  }
  
  // 3. Create a new fetch promise
  const promise = (async () => {
    const url = `data/${ts}/${asset}_data.json`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.cache[cacheKey] = data;
    return data;
  })();
  
  // Store it in the promise cache
  state.fetchPromises[cacheKey] = promise;
  
  // Clean up promise cache once resolved or rejected
  promise.finally(() => {
    delete state.fetchPromises[cacheKey];
  });
  
  return promise;
}

// ── Data Loading ─────────────────────────────────────────────
async function loadCurrentData() {
  const ts = state.manifest[state.currentIndex];
  if (!ts) return;

  updateTimeDisplay(ts);
  updateNavButtons();

  const cacheKey = `${state.currentAsset}:${ts}`;

  // Show loading state
  showLoading(true);

  try {
    const data = await fetchDataWithCache(state.currentAsset, ts);
    renderAll(data);
  } catch (err) {
    console.warn(`No data for ${cacheKey}:`, err);
    renderAll(null);
  } finally {
    showLoading(false);
  }
}


// ── Navigation ───────────────────────────────────────────────
function switchAsset(asset) {
  if (state.currentAsset === asset) return;
  state.currentAsset = asset;

  // Update button states
  document.querySelectorAll('.asset-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.asset === asset);
  });

  // Update asset label
  document.getElementById('bias-asset-label').textContent = ASSET_LABELS[asset] || asset;

  loadCurrentData();
}

function navigateTime(direction) {
  const newIndex = state.currentIndex + direction;
  if (newIndex < 0 || newIndex >= state.manifest.length) return;
  state.currentIndex = newIndex;
  loadCurrentData();
}

function updateTimeDisplay(ts) {
  const parts = ts.split('/');
  const dateStr = parts[0] || '';
  const hourStr = parts[1] || '';
  const displayText = `${dateStr}  ${hourStr}`;
  document.getElementById('time-label').textContent = displayText;
  document.getElementById('time-index').textContent =
    `[${state.currentIndex + 1}/${state.manifest.length}]`;
  document.getElementById('footer-updated').textContent =
    `Last updated: ${displayText} UTC`;
}

function updateNavButtons() {
  document.getElementById('btn-prev').disabled = state.currentIndex <= 0;
  document.getElementById('btn-next').disabled = state.currentIndex >= state.manifest.length - 1;
}

function setupKeyboardNav() {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { navigateTime(-1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { navigateTime(1); e.preventDefault(); }
    if (e.key === '1') switchAsset('GC');
    if (e.key === '2') switchAsset('ES');
    if (e.key === '3') switchAsset('NQ');
  });
}

// ── UI Helpers ───────────────────────────────────────────────
function showLoading(visible) {
  // simple opacity approach
  const cards = document.querySelectorAll('.card');
  cards.forEach(c => {
    c.style.opacity = visible ? '0.5' : '1';
    c.style.transition = 'opacity 0.15s ease';
  });
}

function showGlobalError(msg) {
  document.getElementById('time-label').textContent = 'NO DATA';
  document.getElementById('time-index').textContent = '';
  document.getElementById('bias-direction').textContent = '—';
  document.getElementById('bias-direction').className = 'bias-label neutral';
  document.getElementById('bias-price').textContent = msg;
  document.getElementById('bias-price').style.fontSize = '0.9rem';
}

function getAnalysisDate() {
  const ts = state.manifest[state.currentIndex];
  let analysisDate = new Date();
  if (ts) {
    const dateStr = ts.split('/')[0];
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      analysisDate = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    }
  }
  return analysisDate;
}

function getAnalysisTimestampMs(ts) {
  if (!ts) return Date.now();
  const parts = ts.split('/');
  const datePart = parts[0];
  const hourPart = parts[1] || '0000';
  const formattedStr = `${datePart}T${hourPart.substring(0, 2)}:${hourPart.substring(2, 4)}:00Z`;
  return new Date(formattedStr).getTime();
}

function getAnalysisDateUtcRange(ts) {
  if (!ts) return null;
  const datePart = ts.split('/')[0];
  return {
    start: new Date(`${datePart}T00:00:00Z`).getTime(),
    end: new Date(`${datePart}T23:59:59Z`).getTime()
  };
}

function getOneDayBackMinTs(ohlcv, analysisDateStr) {
  let prevDateStr = null;
  let minTs = ohlcv[0][0];

  for (let i = ohlcv.length - 1; i >= 0; i--) {
    const ts = ohlcv[i][0];
    const dStr = new Date(ts).toLocaleDateString();
    if (dStr !== analysisDateStr) {
      if (!prevDateStr) prevDateStr = dStr;
      if (dStr !== prevDateStr) {
        minTs = ohlcv[i + 1][0];
        break;
      }
    }
  }
  return minTs;
}

// ── Render All ───────────────────────────────────────────────
function renderAll(data) {
  // Sync vol_resistances and vol_supports directly with the intraday_volume_profile to guarantee 100% chart/widget data alignment
  if (data && data.intraday_volume_profile && data.intraday_volume_profile.length > 0) {
    const sortedCalls = [...data.intraday_volume_profile]
      .filter(p => p.call_vol > 0)
      .sort((a, b) => b.call_vol - a.call_vol);
    const topCalls = sortedCalls.slice(0, 3).map(p => [p.strike, p.call_vol]);

    const sortedPuts = [...data.intraday_volume_profile]
      .filter(p => p.put_vol > 0)
      .sort((a, b) => b.put_vol - a.put_vol);
    const topPuts = sortedPuts.slice(0, 3).map(p => [p.strike, p.put_vol]);

    if (!data.intraday_levels) {
      data.intraday_levels = {};
    }
    data.intraday_levels.vol_resistances = topCalls;
    data.intraday_levels.vol_supports = topPuts;
  }

  const ts = state.manifest[state.currentIndex];
  if (ts) {
    updateFreshnessBadge(ts);
    renderBiasTimeline();
  }

  if (!data) {
    renderBiasCard(null);
    clearChart('chart-oi-walls');
    clearChart('chart-net-oi');
    clearChart('chart-gex');
    clearChart('chart-vanna');
    clearChart('chart-iv-smile');
    clearChart('chart-oi-change');
    clearChart('chart-max-pain');
    clearChart('chart-hybrid');
    clearChart('chart-intraday-master');
    clearChart('chart-intraday-vol');
    return;
  }

  renderBiasCard(data.bias);
  renderHybridChart(data);
  renderIntradayMasterChart(data);
  renderIntradayVolChart(data);
  renderOIWallsChart(data.oi_walls, data);
  renderNetOIChart(data.net_oi, data);
  renderGEXChart(data.gex_profile, data);
  renderVannaChart(data.vanna, data);
  renderIVSmileChart(data.iv_smile, data.bias, data);
  renderOIChangeChart(data.oi_change, data);
  renderMaxPainChart(data.oi_walls, data.max_pain, data.bias, data);
  
  updateMiniPanels(data);
}

// ── Bias Card ────────────────────────────────────────────────
function renderBiasCard(bias) {
  const dirEl = document.getElementById('bias-direction');
  const confEl = document.getElementById('bias-confidence');
  const priceEl = document.getElementById('bias-price');

  if (!bias) {
    dirEl.textContent = '—';
    dirEl.className = 'bias-label neutral';
    confEl.textContent = 'Confidence: —';
    priceEl.textContent = '—';
    priceEl.style.fontSize = '';
    ['metric-iv', 'metric-pcr', 'metric-skew', 'metric-activity', 'metric-gex', 'metric-walls', 'metric-max-pain']
      .forEach(id => {
        const el = document.getElementById(id);
        el.textContent = '—';
        el.className = 'metric-value';
      });
    return;
  }

  // Direction
  dirEl.textContent = bias.label || '—';
  const isBull = (bias.label || '').toLowerCase().includes('bull');
  const isBear = (bias.label || '').toLowerCase().includes('bear');
  dirEl.className = 'bias-label ' + (isBull ? 'bull' : isBear ? 'bear' : 'neutral');

  // Confidence
  confEl.textContent = `Confidence: ${bias.confidence || '—'}`;

  // Price
  priceEl.textContent = formatNumber(bias.price);
  priceEl.style.fontSize = '';

  // Metrics
  setMetric('metric-iv', bias.iv || '—');
  setMetric('metric-pcr', bias.pcr_vol != null ? bias.pcr_vol.toFixed(2) : '—',
    bias.pcr_vol < 0.8 ? 'bull' : bias.pcr_vol > 1.2 ? 'bear' : '');
  setMetric('metric-skew', bias.skew || '—',
    parseSkewClass(bias.skew));
  setMetric('metric-activity', bias.activity || '—');

  // GEX regime
  const gexEl = document.getElementById('metric-gex');
  const isStable = (bias.gex || '').toUpperCase() === 'STABLE';
  gexEl.textContent = bias.gex || '—';
  gexEl.className = 'metric-value ' + (isStable ? 'bull' : 'bear');

  // Update regime badge on GEX chart card
  const regBadge = document.getElementById('gex-regime-badge');
  regBadge.textContent = isStable ? '● STABLE' : '● VOLATILE';
  regBadge.className = 'card-badge regime-badge ' + (isStable ? 'stable' : 'volatile');

  // Walls
  setMetric('metric-walls', bias.walls || '—');

  // Max Pain
  const maxPainEl = document.getElementById('metric-max-pain');
  if (maxPainEl) {
    maxPainEl.textContent = '—';
    maxPainEl.className = 'metric-value';
  }
}

function setMetric(id, value, colorClass) {
  const el = document.getElementById(id);
  el.textContent = value;
  el.className = 'metric-value' + (colorClass ? ` ${colorClass}` : '');
}

function parseSkewClass(skew) {
  if (!skew) return '';
  const val = parseFloat(skew);
  if (isNaN(val)) return '';
  return val > 0 ? 'bear' : val < 0 ? 'bull' : '';
}

// ── Chart: OI Walls ──────────────────────────────────────────
function renderOIWallsChart(oiData, data) {
  if (!oiData || !oiData.strikes) {
    clearChart('chart-oi-walls');
    return;
  }

  const sdAnnotations = getSDBandAnnotations(data, oiData.strikes);

  const options = {
    chart: {
      type: 'bar',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [
      { name: 'Call OI', data: oiData.call_oi || [] },
      { name: 'Put OI', data: oiData.put_oi || [] },
    ],
    xaxis: {
      categories: (oiData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: { style: { colors: '#6B6B75', fontSize: '10px' } },
    },
    colors: ['#00CC52', '#CC0044'],
    plotOptions: {
      bar: { borderRadius: 0, columnWidth: '70%' },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    legend: {
      position: 'top',
      horizontalAlign: 'right',
      labels: { colors: '#9A9AA5' },
      markers: { radius: 0 },
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => v.toLocaleString() },
    },
    dataLabels: { enabled: false },
    annotations: {
      xaxis: sdAnnotations,
    },
  };

  renderApexChart('chart-oi-walls', options);
}

// ── Chart: Net OI ────────────────────────────────────────────
function renderNetOIChart(netData, data) {
  if (!netData || !netData.strikes) {
    clearChart('chart-net-oi');
    return;
  }

  const colors = (netData.net || []).map(v => v >= 0 ? '#00FF66' : '#FF0055');
  const sdAnnotations = getSDBandAnnotations(data, netData.strikes);

  const options = {
    chart: {
      type: 'bar',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [{
      name: 'Net OI',
      data: netData.net || [],
    }],
    xaxis: {
      categories: (netData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: { style: { colors: '#6B6B75', fontSize: '10px' } },
    },
    colors: ['#4D9EFF'], // base, overridden per-point
    plotOptions: {
      bar: {
        borderRadius: 0,
        columnWidth: '70%',
        colors: {
          ranges: [
            { from: -999999, to: 0, color: '#FF0055' },
            { from: 0, to: 999999, color: '#00FF66' },
          ],
        },
      },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => v.toLocaleString() },
    },
    dataLabels: { enabled: false },
    annotations: {
      yaxis: [{
        y: 0,
        borderColor: '#6B6B75',
        strokeDashArray: 0,
        borderWidth: 1,
      }],
      xaxis: sdAnnotations,
    },
  };

  renderApexChart('chart-net-oi', options);
}

// ── Chart: GEX Profile ───────────────────────────────────────
function renderGEXChart(gexData, data) {
  if (!gexData || !gexData.strikes) {
    clearChart('chart-gex');
    return;
  }

  const sdAnnotations = getSDBandAnnotations(data, gexData.strikes);
  const flipAnnotation = gexData.flip_price ? [{
    x: gexData.flip_price.toString(),
    borderColor: '#FFB800',
    strokeDashArray: 4,
    label: {
      text: `FLIP: ${formatNumber(gexData.flip_price)}`,
      position: 'top',
      orientation: 'horizontal',
      style: {
        color: '#FFB800',
        background: '#1C1C22',
        fontSize: '10px',
        fontFamily: "'JetBrains Mono', monospace",
        fontWeight: 'bold',
      },
    },
  }] : [];
  const xAnnotations = [...sdAnnotations, ...flipAnnotation];

  const options = {
    chart: {
      type: 'area',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [{
      name: 'GEX ($)',
      data: gexData.gex || [],
    }],
    xaxis: {
      categories: (gexData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        formatter: v => formatCompact(v),
      },
    },
    colors: ['#4D9EFF'],
    fill: {
      type: 'gradient',
      gradient: {
        shadeIntensity: 1,
        type: 'vertical',
        opacityFrom: 0.4,
        opacityTo: 0.05,
        colorStops: [
          { offset: 0, color: '#4D9EFF', opacity: 0.3 },
          { offset: 100, color: '#4D9EFF', opacity: 0.02 },
        ],
      },
    },
    stroke: { width: 2, curve: 'smooth' },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => '$' + formatCompact(v) },
    },
    dataLabels: { enabled: false },
    annotations: {
      yaxis: [{
        y: 0,
        borderColor: '#6B6B75',
        strokeDashArray: 0,
        borderWidth: 1,
        label: {
          text: 'GAMMA FLIP',
          position: 'left',
          style: {
            color: '#FFB800',
            background: '#111115',
            fontSize: '10px',
            fontFamily: "'JetBrains Mono', monospace",
          },
        },
      }],
      xaxis: xAnnotations,
    },
  };

  renderApexChart('chart-gex', options);
}

// ── Chart: Vanna ─────────────────────────────────────────────
function renderVannaChart(vannaData, data) {
  if (!vannaData || !vannaData.strikes) {
    clearChart('chart-vanna');
    return;
  }

  const sdAnnotations = getSDBandAnnotations(data, vannaData.strikes);

  const options = {
    chart: {
      type: 'bar',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [{
      name: 'Vanna Exp',
      data: vannaData.vanna_exp || [],
    }],
    xaxis: {
      categories: (vannaData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        formatter: v => formatCompact(v),
      },
    },
    colors: ['#A855F7'],
    plotOptions: {
      bar: {
        borderRadius: 0,
        columnWidth: '65%',
        colors: {
          ranges: [
            { from: -999999999, to: 0, color: '#FF0055' },
            { from: 0, to: 999999999, color: '#A855F7' },
          ],
        },
      },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => formatCompact(v) },
    },
    dataLabels: { enabled: false },
    annotations: {
      yaxis: [{
        y: 0,
        borderColor: '#6B6B75',
        strokeDashArray: 0,
        borderWidth: 1,
      }],
      xaxis: sdAnnotations,
    },
  };

  renderApexChart('chart-vanna', options);
}

// ── Chart: IV Smile / Skew Curve ───────────────────────────────────────
function renderIVSmileChart(ivData, bias, data) {
  if (!ivData || !ivData.strikes || ivData.strikes.length < 3) {
    clearChart('chart-iv-smile');
    return;
  }

  // Compute SD bands and ATM annotations
  const xAnnotations = getSDBandAnnotations(data, ivData.strikes);

  // Detect skew direction for badge
  const badgeEl = document.getElementById('iv-smile-badge');
  if (badgeEl) {
    const callAvg = ivData.call_iv.filter(v => v > 0).reduce((a, b) => a + b, 0) / (ivData.call_iv.filter(v => v > 0).length || 1);
    const putAvg = ivData.put_iv.filter(v => v > 0).reduce((a, b) => a + b, 0) / (ivData.put_iv.filter(v => v > 0).length || 1);
    if (putAvg > callAvg * 1.05) {
      badgeEl.textContent = '🟥 PUT SKEW (Fear)';
      badgeEl.className = 'card-badge bear';
    } else if (callAvg > putAvg * 1.05) {
      badgeEl.textContent = '🟩 CALL SKEW (Greed)';
      badgeEl.className = 'card-badge bull';
    } else {
      badgeEl.textContent = '⬜ ATM BALANCED';
      badgeEl.className = 'card-badge neutral';
    }
  }

  // Parse prices for ATM line
  const price = data && data.bias ? parseFloat(data.bias.price) || 0 : 0;
  if (price > 0) {
    // Add ATM line annotation
    const atmAnnotation = {
      x: price.toString(),
      borderColor: '#FEB019',
      strokeDashArray: 4,
      borderWidth: 2,
      label: {
        text: `ATM: ${formatNumber(price)}`,
        position: 'top',
        orientation: 'horizontal',
        style: {
          color: '#FEB019',
          background: '#1C1C22',
          fontSize: '10px',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 'bold',
        },
      },
    };
    xAnnotations.push(atmAnnotation);
  }

  // Setup options
  const options = {
    chart: {
      type: 'line',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [
      {
        name: 'Call IV',
        data: ivData.strikes.map((s, i) => ({ x: s.toString(), y: ivData.call_iv[i] ? ivData.call_iv[i] * 100 : null })).filter(pt => pt.y !== null)
      },
      {
        name: 'Put IV',
        data: ivData.strikes.map((s, i) => ({ x: s.toString(), y: ivData.put_iv[i] ? ivData.put_iv[i] * 100 : null })).filter(pt => pt.y !== null)
      }
    ],
    xaxis: {
      type: 'category',
      categories: (ivData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        formatter: v => v ? v.toFixed(1) + '%' : '',
      },
    },
    colors: ['#00E396', '#FF4560'],
    stroke: {
      width: 3,
      curve: 'straight'
    },
    fill: {
      type: 'solid',
      opacity: 1.0
    },
    markers: {
      size: 4,
      strokeWidth: 0,
      hover: { size: 6 },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    legend: {
      position: 'top',
      horizontalAlign: 'right',
      labels: { colors: '#9A9AA5' },
      markers: { radius: 0 },
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => v ? v.toFixed(2) + '%' : '' },
    },
    dataLabels: { enabled: false },
    annotations: {
      xaxis: xAnnotations,
    },
  };

  renderApexChart('chart-iv-smile', options);
}

// ── Chart: Change in OI (ΔOI) ─────────────────────────────────────
function renderOIChangeChart(oiChangeData, data) {
  if (!oiChangeData || !oiChangeData.strikes || oiChangeData.strikes.length === 0) {
    clearChart('chart-oi-change');
    return;
  }

  const sdAnnotations = getSDBandAnnotations(data, oiChangeData.strikes);

  const options = {
    chart: {
      type: 'bar',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [
      { name: 'Call ΔOI', data: oiChangeData.call_chg || [] },
      { name: 'Put ΔOI', data: oiChangeData.put_chg || [] },
    ],
    xaxis: {
      categories: (oiChangeData.strikes || []).map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        formatter: v => formatCompact(v),
      },
    },
    colors: ['#00CC52', '#CC0044'],
    plotOptions: {
      bar: { borderRadius: 0, columnWidth: '70%' },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    legend: {
      position: 'top',
      horizontalAlign: 'right',
      labels: { colors: '#9A9AA5' },
      markers: { radius: 0 },
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => (v >= 0 ? '+' : '') + v.toLocaleString() },
    },
    dataLabels: { enabled: false },
    annotations: {
      yaxis: [{
        y: 0,
        borderColor: '#6B6B75',
        strokeDashArray: 0,
        borderWidth: 1,
      }],
      xaxis: sdAnnotations,
    },
  };

  renderApexChart('chart-oi-change', options);
}

// ── Chart: Max Pain Analysis ─────────────────────────────────────
function renderMaxPainChart(oiData, maxPainData, bias, data) {
  if (!oiData || !oiData.strikes || !maxPainData) {
    clearChart('chart-max-pain');
    return;
  }

  // Update Max Pain metric in Bias Card
  const maxPainMetric = document.getElementById('metric-max-pain');
  if (maxPainMetric && maxPainData.price) {
    maxPainMetric.textContent = maxPainData.price.toLocaleString();
    const underlying = bias && bias.price ? parseFloat(bias.price) || 0 : 0;
    if (underlying > 0) {
      const diff = underlying - maxPainData.price;
      const isBull = diff > 0;
      maxPainMetric.className = 'metric-value ' + (isBull ? 'bull' : diff < 0 ? 'bear' : 'neutral');
    }
  }

  // Draw chart
  const strikes = maxPainData.strikes || [];
  const painPerStrike = maxPainData.pain || [];
  const minPain = Math.min(...painPerStrike);

  const options = {
    chart: {
      type: 'bar',
      height: '100%',
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "'JetBrains Mono', monospace",
    },
    series: [{
      name: 'Total Pain ($)',
      data: painPerStrike,
    }],
    xaxis: {
      categories: strikes.map(s => s.toString()),
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true,
      },
      axisBorder: { color: '#1A1B20' },
      axisTicks: { color: '#1A1B20' },
    },
    yaxis: {
      labels: {
        style: { colors: '#6B6B75', fontSize: '10px' },
        formatter: v => formatCompact(v),
      },
    },
    colors: ['#4D9EFF'],
    plotOptions: {
      bar: {
        borderRadius: 0,
        columnWidth: '70%',
        distributed: true,
        colors: {
          ranges: painPerStrike.map((p, i) => {
            if (p === minPain) return { from: p - 1, to: p + 1, color: '#FFB800' };
            return null;
          }).filter(Boolean),
        },
      },
    },
    grid: {
      borderColor: '#1A1B20',
      strokeDashArray: 3,
    },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => '$' + formatCompact(v) },
    },
    dataLabels: { enabled: false },
    legend: { show: false },
    annotations: {
      xaxis: xaxisAnnotations,
    },
  };

  renderApexChart('chart-max-pain', options);
}


// Helper to calculate standard deviation bands annotations
function getSDBandAnnotations(data, strikes) {
  if (!data || !strikes || strikes.length === 0) return [];
  const price = data.sd_bands?.price || data.bias?.price;
  const sd1 = data.sd_bands?.sd1 || data.sd_step;
  if (!price || !sd1 || sd1 <= 0) return [];

  // Find closest strike in the list
  const getClosestStrike = (target) => {
    let closest = strikes[0];
    let minDist = Math.abs(target - closest);
    for (const s of strikes) {
      const dist = Math.abs(target - s);
      if (dist < minDist) {
        minDist = dist;
        closest = s;
      }
    }
    return closest;
  };

  const sd1_low = getClosestStrike(price - sd1);
  const sd1_high = getClosestStrike(price + sd1);
  const sd2_low = getClosestStrike(price - 2 * sd1);
  const sd2_high = getClosestStrike(price + 2 * sd1);
  const sd3_low = getClosestStrike(price - 3 * sd1);
  const sd3_high = getClosestStrike(price + 3 * sd1);

  const atmStrike = getClosestStrike(price);

  return [
    {
      x: sd3_low.toString(),
      x2: sd3_high.toString(),
      fillColor: '#FF4560',
      opacity: 0.02,
      label: {
        text: '3 SD',
        borderColor: 'transparent',
        style: {
          color: '#9A9AA5',
          background: 'transparent',
          fontSize: '9px',
          fontFamily: "'JetBrains Mono', monospace"
        },
        offsetY: 10
      }
    },
    {
      x: sd2_low.toString(),
      x2: sd2_high.toString(),
      fillColor: '#008FFB',
      opacity: 0.04,
      label: {
        text: '2 SD',
        borderColor: 'transparent',
        style: {
          color: '#9A9AA5',
          background: 'transparent',
          fontSize: '9px',
          fontFamily: "'JetBrains Mono', monospace"
        },
        offsetY: 20
      }
    },
    {
      x: sd1_low.toString(),
      x2: sd1_high.toString(),
      fillColor: '#00E396',
      opacity: 0.07,
      label: {
        text: '1 SD',
        borderColor: 'transparent',
        style: {
          color: '#9A9AA5',
          background: 'transparent',
          fontSize: '9px',
          fontFamily: "'JetBrains Mono', monospace"
        },
        offsetY: 30
      }
    },
    {
      x: atmStrike.toString(),
      borderColor: '#FEB019',
      strokeDashArray: 4,
      borderWidth: 2,
      label: {
        text: `ATM: ${formatNumber(price)}`,
        position: 'top',
        orientation: 'horizontal',
        style: {
          color: '#FEB019',
          background: '#1C1C22',
          fontSize: '10px',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 'bold',
        },
      },
    }
  ];
}


// ── Chart Utilities ──────────────────────────────────────────
function destroyChart(id) {
  if (state.charts[id]) {
    try {
      if (typeof state.charts[id].remove === 'function') {
        state.charts[id].remove(); // Lightweight Charts uses remove()
      } else if (typeof state.charts[id].destroy === 'function') {
        state.charts[id].destroy(); // ApexCharts uses destroy()
      }
    } catch (e) {
      console.warn(`Error destroying chart ${id}:`, e);
    }
    delete state.charts[id];
  }
  if (state.resizeObservers && state.resizeObservers[id]) {
    try {
      state.resizeObservers[id].disconnect();
    } catch (e) { /* ignore */ }
    delete state.resizeObservers[id];
  }
}

function clearChart(id) {
  destroyChart(id);
  const el = document.getElementById(id);
  if (el) {
    el.innerHTML = '<div class="no-data">NO DATA AVAILABLE</div>';
  }
}

function renderApexChart(id, options) {
  let chart = state.charts[id];
  const el = document.getElementById(id);
  if (!el) return;
  
  if (chart && typeof chart.updateOptions === 'function') {
    try {
      chart.updateOptions(options, true, true);
    } catch (e) {
      console.warn(`Error updating ApexChart ${id}, recreating:`, e);
      destroyChart(id);
      chart = new ApexCharts(el, options);
      chart.render();
      state.charts[id] = chart;
    }
  } else {
    destroyChart(id);
    chart = new ApexCharts(el, options);
    chart.render();
    state.charts[id] = chart;
  }
}

// ── Formatting ───────────────────────────────────────────────
function formatNumber(n) {
  if (n == null || isNaN(n)) return '—';
  const num = Number(n);
  if (num >= 10000) return num.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  if (num >= 100) return num.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCompact(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toFixed(0);
}

// ── Interactive Chart Rendering ────────────────────────────────
// ── Interactive Chart Rendering — TradingView Lightweight Charts ────────────────
function createTradingViewChart(containerId, ohlcv, vwap, options = {}) {
  const container = document.getElementById(containerId);
  if (!container) return null;

  // Clear any existing chart DOM
  container.innerHTML = '';

  // 1. Create custom HTML tooltip element inside the container
  const tooltip = document.createElement('div');
  tooltip.className = 'tv-chart-tooltip';
  container.appendChild(tooltip);

  // 2. Create the chart element
  const chartEl = document.createElement('div');
  chartEl.className = 'tv-chart-container';
  container.appendChild(chartEl);

  // 3. Create Lightweight Chart instance with price scale on the LEFT
  const chart = LightweightCharts.createChart(chartEl, {
    width: container.clientWidth || 600,
    height: container.clientHeight || 400,
    layout: {
      background: { type: 'solid', color: '#111115' },
      textColor: '#9A9AA5',
    },
    grid: {
      vertLines: { color: 'rgba(26, 27, 32, 0.4)' },
      horzLines: { color: 'rgba(26, 27, 32, 0.4)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      visible: false, // Turn off right axis completely!
    },
    leftPriceScale: {
      visible: true,  // Turn on left axis!
      borderColor: '#1A1B20',
      autoScale: true,
    },
    timeScale: {
      borderColor: '#1A1B20',
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // [NEW] Yellow Background highlight for Today's Active Intraday session (Day-bounded)
  if (options.datePart && ohlcv.length > 0) {
    const startOfDayMs = new Date(options.datePart + "T00:00:00Z").getTime();
    const scanBars = ohlcv.filter(bar => bar[0] >= startOfDayMs);
    
    if (scanBars.length > 0) {
      const prices = ohlcv.flatMap(c => [c[1], c[2], c[3], c[4]]);
      const viewMax = Math.max(...prices);
      const viewMin = Math.min(...prices);
      
      const todayBgSeries = chart.addAreaSeries({
        priceScaleId: 'left',
        topColor: 'rgba(254, 176, 25, 0.15)',
        bottomColor: 'rgba(254, 176, 25, 0.01)',
        lineColor: 'rgba(254, 176, 25, 0.18)',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => ({
          priceRange: {
            min: viewMin,
            max: viewMax,
          },
        }),
      });
      
      const backgroundData = scanBars.map(bar => ({
        time: bar[0] / 1000,
        value: viewMax * 1.1
      }));
      todayBgSeries.setData(backgroundData);
    }
  }

  // 4. Add Candlestick Series bound to the LEFT scale
  const candlestickSeries = chart.addCandlestickSeries({
    priceScaleId: 'left', // Bind candlestick to left scale!
    upColor: '#00E396',
    downColor: '#FF4560',
    borderUpColor: '#00E396',
    borderDownColor: '#FF4560',
    wickUpColor: '#00E396',
    wickDownColor: '#FF4560',
  });

  // Map OHLCV and set data
  const mappedCandles = ohlcv.map(d => ({
    time: d[0] / 1000,
    open: d[1],
    high: d[2],
    low: d[3],
    close: d[4],
  }));
  candlestickSeries.setData(mappedCandles);

  // 5. Add VWAP Series (if available) bound to the LEFT scale
  let vwapSeries = null;
  if (vwap && vwap.length > 0) {
    vwapSeries = chart.addLineSeries({
      priceScaleId: 'left', // Bind VWAP to left scale!
      color: '#4D9EFF',
      lineWidth: 1.5,
      priceLineVisible: false,
      title: 'VWAP',
    });
    const mappedVwap = vwap
      .filter(d => d[1] != null)
      .map(d => ({
        time: d[0] / 1000,
        value: d[1],
      }));
    vwapSeries.setData(mappedVwap);
  }

  // 6. Draw Horizontal Levels (SD Bands, S/R Levels)
  if (options.levels && options.levels.length > 0) {
    options.levels.forEach(level => {
      candlestickSeries.createPriceLine({
        price: level.price,
        color: level.color || '#FEB019',
        lineWidth: level.lineWidth || 1,
        lineStyle: level.lineStyle || LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.title || '',
      });
    });
  }

  // 7. Subscribe to crosshair movement to update the custom HTML tooltip
  chart.subscribeCrosshairMove(param => {
    if (
      param.point === undefined ||
      !param.time ||
      param.point.x < 0 ||
      param.point.x > container.clientWidth ||
      param.point.y < 0 ||
      param.point.y > container.clientHeight
    ) {
      tooltip.style.display = 'none';
      return;
    }

    const candle = param.seriesData.get(candlestickSeries);
    if (!candle) {
      tooltip.style.display = 'none';
      return;
    }

    const dateStr = new Date(param.time * 1000).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    let vwapValueText = '—';
    if (vwapSeries) {
      const vwapVal = param.seriesData.get(vwapSeries);
      if (vwapVal && vwapVal.value != null) {
        vwapValueText = formatNumber(vwapVal.value);
      }
    }

    tooltip.style.display = 'block';
    tooltip.innerHTML = `
      <div class="tv-chart-tooltip-title">${dateStr}</div>
      <div class="tv-chart-tooltip-row">
        <span class="tv-chart-tooltip-label">O</span>
        <span class="tv-chart-tooltip-value">${formatNumber(candle.open)}</span>
      </div>
      <div class="tv-chart-tooltip-row">
        <span class="tv-chart-tooltip-label">H</span>
        <span class="tv-chart-tooltip-value bull">${formatNumber(candle.high)}</span>
      </div>
      <div class="tv-chart-tooltip-row">
        <span class="tv-chart-tooltip-label">L</span>
        <span class="tv-chart-tooltip-value bear">${formatNumber(candle.low)}</span>
      </div>
      <div class="tv-chart-tooltip-row">
        <span class="tv-chart-tooltip-label">C</span>
        <span class="tv-chart-tooltip-value">${formatNumber(candle.close)}</span>
      </div>
      <div class="tv-chart-tooltip-row">
        <span class="tv-chart-tooltip-label">VWAP</span>
        <span class="tv-chart-tooltip-value" style="color: #4D9EFF">${vwapValueText}</span>
      </div>
    `;

    // Position the tooltip
    const coordinate = param.point.x;
    const tooltipWidth = 140;
    const tooltipHeight = 150;

    let left = coordinate + 15;
    if (left > container.clientWidth - tooltipWidth - 20) {
      left = coordinate - tooltipWidth - 15;
    }

    let top = param.point.y + 15;
    if (top > container.clientHeight - tooltipHeight - 20) {
      top = param.point.y - tooltipHeight - 15;
    }

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  });

  // 8. Handle responsiveness with requestAnimationFrame and positive size checks
  const resizeObserver = new ResizeObserver(entries => {
    if (entries.length === 0 || !entries[0].contentRect) return;
    const { width, height } = entries[0].contentRect;
    if (width > 0 && height > 0) {
      requestAnimationFrame(() => {
        try {
          chart.resize(width, height);
        } catch (e) { /* ignore */ }
      });
    }
  });
  resizeObserver.observe(container);

  // Cache ResizeObserver for cleanup
  if (!state.resizeObservers) state.resizeObservers = {};
  state.resizeObservers[containerId] = resizeObserver;

  return chart;
}

function renderHybridChart(data) {
  if (!data || !data.candlesticks) {
    clearChart('chart-hybrid');
    document.getElementById('hybrid-nodata').style.display = 'flex';
    return;
  }
  document.getElementById('hybrid-nodata').style.display = 'none';

  const tabKey = state.activeTabs['hybrid'] || 'hybrid_15m';
  const tf = tabKey.split('_')[1]; // 1d, 1h, 15m
  const candleData = data.candlesticks[tf];

  if (!candleData || !candleData.ohlcv || candleData.ohlcv.length === 0) {
    clearChart('chart-hybrid');
    document.getElementById('hybrid-nodata').style.display = 'flex';
    return;
  }

  // Filter candles if not the latest run to prevent future leak
  const isLatest = state.currentIndex === state.manifest.length - 1;
  const ts = state.manifest[state.currentIndex];
  let ohlcv = candleData.ohlcv;
  let vwap = candleData.vwap;

  if (!isLatest && ts) {
    const maxTs = getAnalysisTimestampMs(ts);
    ohlcv = ohlcv.filter(c => c[0] <= maxTs);
    vwap = vwap ? vwap.filter(d => d[0] <= maxTs) : null;
  }

  if (ohlcv.length === 0) {
    clearChart('chart-hybrid');
    document.getElementById('hybrid-nodata').style.display = 'flex';
    return;
  }

  const levels = [];

  // 1. Calculate price and SD bands (if toggled)
  if (state.toggles.hybrid.sdBands) {
    const price = data.sd_bands?.price || data.bias?.price;
    const step = data.sd_step;
    if (price && step && step > 0) {
      for (let i = 1; i <= 3; i++) {
        levels.push({
          price: price + (step * i),
          color: '#FEB019',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `+${i}SD`
        });
        levels.push({
          price: price - (step * i),
          color: '#008FFB',
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `-${i}SD`
        });
      }
    }
  }

  // 2. Extract Session Levels (PDH, PDL, Session H/L) (if toggled)
  if (state.toggles.hybrid.sessionLevels) {
    // Previous Day High/Low
    if (data.candlesticks && data.candlesticks["1d"] && data.candlesticks["1d"].ohlcv) {
      const d1 = data.candlesticks["1d"].ohlcv;
      if (d1.length >= 2) {
        const pdCandle = d1[d1.length - 2];
        levels.push({
          price: pdCandle[2],
          color: '#B57CFF',
          lineWidth: 1.5,
          lineStyle: LightweightCharts.LineStyle.Solid,
          title: `PDH (${pdCandle[2]})`
        });
        levels.push({
          price: pdCandle[3],
          color: '#B57CFF',
          lineWidth: 1.5,
          lineStyle: LightweightCharts.LineStyle.Solid,
          title: `PDL (${pdCandle[3]})`
        });
      }
    }

    // Session High/Low
    if (ohlcv && ohlcv.length > 0) {
      let sH = -Infinity;
      let sL = Infinity;
      ohlcv.forEach(c => {
        if (c[2] > sH) sH = c[2];
        if (c[3] < sL) sL = c[3];
      });
      if (sH !== -Infinity) {
        levels.push({
          price: sH,
          color: '#FF9F43',
          lineWidth: 1.2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `Session High (${sH})`
        });
      }
      if (sL !== Infinity) {
        levels.push({
          price: sL,
          color: '#FF9F43',
          lineWidth: 1.2,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `Session Low (${sL})`
        });
      }
    }
  }

  // 3. Add OI Walls (if toggled)
  if (state.toggles.hybrid.oiWalls && data.intraday_levels) {
    const allOI = [...data.intraday_levels.oi_resistances, ...data.intraday_levels.oi_supports].map(x => x[1]);
    const maxOI = allOI.length > 0 ? Math.max(...allOI) : 1;

    data.intraday_levels.oi_resistances.forEach(r => {
      const isHigh = r[1] >= maxOI * 0.7;
      const isLow = r[1] <= maxOI * 0.3;
      levels.push({
        price: r[0],
        color: isHigh ? 'rgba(255, 69, 96, 0.9)' : (isLow ? 'rgba(255, 69, 96, 0.3)' : 'rgba(255, 69, 96, 0.6)'),
        lineWidth: isHigh ? 2 : 1,
        lineStyle: isLow ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
        title: `OI Res: ${r[0]} (${formatCompact(r[1])})`
      });
    });

    data.intraday_levels.oi_supports.forEach(s => {
      const isHigh = s[1] >= maxOI * 0.7;
      const isLow = s[1] <= maxOI * 0.3;
      levels.push({
        price: s[0],
        color: isHigh ? 'rgba(0, 227, 150, 0.9)' : (isLow ? 'rgba(0, 227, 150, 0.3)' : 'rgba(0, 227, 150, 0.6)'),
        lineWidth: isHigh ? 2 : 1,
        lineStyle: isLow ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
        title: `OI Sup: ${s[0]} (${formatCompact(s[1])})`
      });
    });
  }

  destroyChart('chart-hybrid');

  const datePart = ts ? ts.split('/')[0] : null;
  const chart = createTradingViewChart('chart-hybrid', ohlcv, vwap, { levels, datePart });
  state.charts['chart-hybrid'] = chart;

  // Zoom visible viewport on load: Show last day of action for intraday (15m)
  if (tf === '15m' && ohlcv.length > 0 && chart) {
    const latestTimestamp = ohlcv[ohlcv.length - 1][0];
    const analysisDateStr = getAnalysisDate().toLocaleDateString();
    const minTs = getOneDayBackMinTs(ohlcv, analysisDateStr);
    chart.timeScale().setVisibleRange({
      from: minTs / 1000,
      to: latestTimestamp / 1000
    });
  } else if (chart) {
    chart.timeScale().fitContent();
  }
}

function renderIntradayMasterChart(data) {
  if (!data || !data.candlesticks) {
    clearChart('chart-intraday-master');
    document.getElementById('intraday-master-nodata').style.display = 'flex';
    return;
  }
  document.getElementById('intraday-master-nodata').style.display = 'none';

  const tabKey = state.activeTabs['intraday-master'] || 'intraday_master_5m';
  const tf = tabKey.split('_')[2]; // 5m, 1h
  const candleData = data.candlesticks[tf];

  if (!candleData || !candleData.ohlcv || candleData.ohlcv.length === 0) {
    clearChart('chart-intraday-master');
    document.getElementById('intraday-master-nodata').style.display = 'flex';
    return;
  }

  // Filter candles if not the latest run to prevent future leak
  const isLatest = state.currentIndex === state.manifest.length - 1;
  const ts = state.manifest[state.currentIndex];
  let ohlcv = candleData.ohlcv;
  let vwap = candleData.vwap;

  if (!isLatest && ts) {
    const maxTs = getAnalysisTimestampMs(ts);
    ohlcv = ohlcv.filter(c => c[0] <= maxTs);
    vwap = vwap ? vwap.filter(d => d[0] <= maxTs) : null;
  }

  if (ohlcv.length === 0) {
    clearChart('chart-intraday-master');
    document.getElementById('intraday-master-nodata').style.display = 'flex';
    return;
  }

  const levels = [];

  // Filter viewport min/max bounds so we only show levels close to the trading range
  let viewMin = 0;
  let viewMax = Infinity;
  if (ohlcv.length > 0) {
    const prices = ohlcv.flatMap(c => [c[1], c[2], c[3], c[4]]);
    viewMin = Math.min(...prices);
    viewMax = Math.max(...prices);
  }
  const tolerance = (viewMax - viewMin) * 0.5 || viewMax * 0.05;

  const currentPrice = ohlcv[ohlcv.length - 1][4];
  const step = data.sd_step;
  const latestVwap = vwap && vwap.length > 0 ? vwap[vwap.length - 1][1] : null;

  // 1. Calculate Option Walls and Strength Scores (if toggled)
  if (state.toggles.master.oiWalls && data.intraday_levels) {
    const supports = data.intraday_levels.vol_supports || [];
    const resistances = data.intraday_levels.vol_resistances || [];
    
    // Find max Vol for normalization
    let maxVol = 0;
    supports.forEach(s => { if (s[1] > maxVol) maxVol = s[1]; });
    resistances.forEach(r => { if (r[1] > maxVol) maxVol = r[1]; });

    // Process resistances (Intraday Call Volume Walls)
    resistances.forEach(r => {
      const strike = r[0];
      if (strike < viewMin - tolerance || strike > viewMax + tolerance) return;
      
      const vol = r[1];
      // Use vol as both oi and vol for dynamic volume wall strength scoring!
      const score = calculateWallStrength(strike, true, vol, vol, currentPrice, latestVwap, step, maxVol, maxVol);
      
      // Determine line styles based on score
      let color = 'rgba(255, 69, 96, 0.4)';
      let lineWidth = 1;
      let lineStyle = LightweightCharts.LineStyle.Dotted;
      if (score >= 8.0) {
        color = 'rgba(255, 69, 96, 1.0)';
        lineWidth = 2.5;
        lineStyle = LightweightCharts.LineStyle.Solid;
      } else if (score >= 5.0) {
        color = 'rgba(255, 69, 96, 0.7)';
        lineWidth = 1.5;
        lineStyle = LightweightCharts.LineStyle.Dashed;
      }

      levels.push({
        price: strike,
        color,
        lineWidth,
        lineStyle,
        title: `Intraday Call Wall: ${strike} (${formatCompact(vol)} Vol, Score: ${score.toFixed(1)})`
      });
    });

    // Process supports (Intraday Put Volume Walls)
    supports.forEach(s => {
      const strike = s[0];
      if (strike < viewMin - tolerance || strike > viewMax + tolerance) return;
      
      const vol = s[1];
      const score = calculateWallStrength(strike, false, vol, vol, currentPrice, latestVwap, step, maxVol, maxVol);
      
      let color = 'rgba(0, 227, 150, 0.4)';
      let lineWidth = 1;
      let lineStyle = LightweightCharts.LineStyle.Dotted;
      if (score >= 8.0) {
        color = 'rgba(0, 227, 150, 1.0)';
        lineWidth = 2.5;
        lineStyle = LightweightCharts.LineStyle.Solid;
      } else if (score >= 5.0) {
        color = 'rgba(0, 227, 150, 0.7)';
        lineWidth = 1.5;
        lineStyle = LightweightCharts.LineStyle.Dashed;
      }

      levels.push({
        price: strike,
        color,
        lineWidth,
        lineStyle,
        title: `Intraday Put Wall: ${strike} (${formatCompact(vol)} Vol, Score: ${score.toFixed(1)})`
      });
    });
  }

  // 2. Compute Distance to Dynamic Real-time Volume Profile Walls
  let nearestCall = null;
  let nearestPut = null;
  if (data.intraday_levels) {
    const resistances = data.intraday_levels.vol_resistances || [];
    const supports = data.intraday_levels.vol_supports || [];
    
    // Find the nearest among the top Call volume strikes above spot price
    const callsAbove = resistances.filter(r => r[0] > currentPrice).sort((a,b) => a[0] - b[0]);
    if (callsAbove.length > 0) nearestCall = callsAbove[0][0];
    
    // Find the nearest among the top Put volume strikes below spot price
    const putsBelow = supports.filter(s => s[0] < currentPrice).sort((a,b) => b[0] - a[0]);
    if (putsBelow.length > 0) nearestPut = putsBelow[0][0];
  }
  
  // Safe Fallback to OI levels if Volume profile has no active strikes
  if (!nearestCall && data.intraday_levels) {
    const resistances = data.intraday_levels.oi_resistances || [];
    const callsAbove = resistances.filter(r => r[0] > currentPrice).sort((a,b) => a[0] - b[0]);
    if (callsAbove.length > 0) nearestCall = callsAbove[0][0];
  }
  if (!nearestPut && data.intraday_levels) {
    const supports = data.intraday_levels.oi_supports || [];
    const putsBelow = supports.filter(s => s[0] < currentPrice).sort((a,b) => b[0] - a[0]);
    if (putsBelow.length > 0) nearestPut = putsBelow[0][0];
  }
  
  const callDistEl = document.getElementById('distance-call');
  if (callDistEl) {
    if (nearestCall) {
      const diff = nearestCall - currentPrice;
      const pct = (diff / currentPrice) * 100;
      callDistEl.textContent = `+${diff.toFixed(1)} pts (+${pct.toFixed(2)}%)`;
    } else {
      callDistEl.textContent = 'None Above';
    }
  }
  
  const putDistEl = document.getElementById('distance-put');
  if (putDistEl) {
    if (nearestPut) {
      const diff = currentPrice - nearestPut;
      const pct = (diff / currentPrice) * 100;
      putDistEl.textContent = `-${diff.toFixed(1)} pts (-${pct.toFixed(2)}%)`;
    } else {
      putDistEl.textContent = 'None Below';
    }
  }

  // 3. Trade Setup Calculations & UI Widget updates
  const setup = getSetupDetails(data, currentPrice, latestVwap, step);
  
  // Calculate Wall Interaction & Gamma Hedging Status (Day-bounded intraday scan)
  const gexRegime = data.bias ? data.bias.gex : 'NEUTRAL';
  const maxSupportVal = setup.entryMin + step * 0.15; // Put wall strike (aligned with Tighter tactical Entry)
  const maxResistanceVal = setup.entryMax - step * 0.15; // Call wall strike (aligned with Tighter tactical Entry)
  const datePart = ts ? ts.split('/')[0] : null;
  const wallInteractions = getWallInteractionDetails(ohlcv, currentPrice, maxSupportVal, maxResistanceVal, step, gexRegime, datePart);
  
  const setElVal = (id, val, color) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = val;
      if (color) el.style.color = color;
    }
  };
  setElVal('wall-call-status', wallInteractions.callStatus, wallInteractions.callColor);
  setElVal('wall-put-status', wallInteractions.putStatus, wallInteractions.putColor);
  setElVal('wall-hedging-flow', wallInteractions.hedgingFlow, wallInteractions.flowColor);

  const hedgingWidget = document.getElementById('hedging-widget');
  const hedgingLiveBadge = document.getElementById('hedging-live-badge');
  if (hedgingWidget) {
    if (isLatest) {
      hedgingWidget.classList.add('live-today');
      if (hedgingLiveBadge) hedgingLiveBadge.style.display = 'inline-block';
    } else {
      hedgingWidget.classList.remove('live-today');
      if (hedgingLiveBadge) hedgingLiveBadge.style.display = 'none';
    }
  }

  const setupStatusEl = document.getElementById('setup-status');
  if (setupStatusEl) {
    setupStatusEl.textContent = setup.status;
    setupStatusEl.className = `setup-status-badge ${setup.statusClass}`;
  }
  
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  setVal('setup-bias', setup.bias);
  setVal('setup-action', setup.action);
  setVal('setup-entry', `${setup.entryMin.toFixed(1)} - ${setup.entryMax.toFixed(1)}`);
  setVal('setup-invalidation', setup.stopLoss.toFixed(1));
  setVal('setup-targets', `${setup.target1.toFixed(1)} / ${setup.target2.toFixed(1)}`);
  setVal('setup-rr', setup.rr);

  // Draw setup zones on chart (if toggled)
  if (state.toggles.master.tradeSetup) {
    // Invalidation
    levels.push({
      price: setup.stopLoss,
      color: '#FF4560',
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      title: `STOP LOSS (INVALIDATION): ${setup.stopLoss.toFixed(1)}`
    });
    // Entry Min/Max
    levels.push({
      price: setup.entryMin,
      color: '#FEB019',
      lineWidth: 1.5,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: `ENTRY ZONE MIN: ${setup.entryMin.toFixed(1)}`
    });
    levels.push({
      price: setup.entryMax,
      color: '#FEB019',
      lineWidth: 1.5,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: `ENTRY ZONE MAX: ${setup.entryMax.toFixed(1)}`
    });
    // Targets
    levels.push({
      price: setup.target1,
      color: '#00E396',
      lineWidth: 1.5,
      lineStyle: LightweightCharts.LineStyle.Solid,
      title: `TARGET 1: ${setup.target1.toFixed(1)}`
    });
    levels.push({
      price: setup.target2,
      color: '#00E396',
      lineWidth: 1.5,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: `TARGET 2: ${setup.target2.toFixed(1)}`
    });
  }

  destroyChart('chart-intraday-master');

  // If VWAP is toggled off, pass null vwap to createTradingViewChart
  const activeVwap = state.toggles.master.vwap ? vwap : null;

  const chart = createTradingViewChart('chart-intraday-master', ohlcv, activeVwap, { levels, datePart });
  state.charts['chart-intraday-master'] = chart;

  // Zoom visible viewport on load: Show last day of action for intraday (5m)
  if (tf === '5m' && ohlcv.length > 0 && chart) {
    const latestTimestamp = ohlcv[ohlcv.length - 1][0];
    const analysisDateStr = getAnalysisDate().toLocaleDateString();
    const minTs = getOneDayBackMinTs(ohlcv, analysisDateStr);
    chart.timeScale().setVisibleRange({
      from: minTs / 1000,
      to: latestTimestamp / 1000
    });
  } else if (chart) {
    chart.timeScale().fitContent();
  }
}

function renderIntradayVolChart(data) {
  if (!data || !data.intraday_volume_profile) {
    clearChart('chart-intraday-vol');
    document.getElementById('intraday-vol-nodata').style.display = 'flex';
    return;
  }
  document.getElementById('intraday-vol-nodata').style.display = 'none';

  const tf = state.selectedTf || '5m';
  let viewMin = 0;
  let viewMax = Infinity;
  if (data.candlesticks && data.candlesticks[tf] && data.candlesticks[tf].ohlcv) {
    const ohlcv = data.candlesticks[tf].ohlcv;
    if (ohlcv.length > 0) {
      const prices = ohlcv.flatMap(c => [c[1], c[2], c[3], c[4]]);
      viewMin = Math.min(...prices);
      viewMax = Math.max(...prices);
    }
  }

  let profile = data.intraday_volume_profile;
  // Smart Filter: Focus strikes exactly within the active chart view window (plus 30% margin) to prevent unreadable cluttered bars
  if (viewMin > 0 && viewMax < Infinity && profile.length > 10) {
    const margin = (viewMax - viewMin) * 0.3;
    const minStrike = viewMin - margin;
    const maxStrike = viewMax + margin;
    const filtered = profile.filter(p => p.strike >= minStrike && p.strike <= maxStrike);
    // Only apply if it keeps a reasonable number of strikes for context
    if (filtered.length >= 5) {
      profile = filtered;
    }
  }

  const strikes = profile.map(p => p.strike);
  const callVol = profile.map(p => p.call_vol);
  const putVol = profile.map(p => p.put_vol);

  // Calculate Put vs Call Volume Dominance
  const totalCallVol = callVol.reduce((a, b) => a + b, 0);
  const totalPutVol = putVol.reduce((a, b) => a + b, 0);
  const totalVol = totalCallVol + totalPutVol;
  const badgeEl = document.getElementById('vol-dominance-badge');
  if (badgeEl && totalVol > 0) {
    const callPct = ((totalCallVol / totalVol) * 100).toFixed(1);
    const putPct = ((totalPutVol / totalVol) * 100).toFixed(1);
    const ratio = totalCallVol > 0 ? (totalPutVol / totalCallVol).toFixed(2) : '∞';
    if (totalCallVol > totalPutVol) {
      badgeEl.textContent = `🟢 CALL DOMINANT: ${callPct}% (Ratio: ${ratio})`;
      badgeEl.className = 'card-badge bull';
    } else if (totalPutVol > totalCallVol) {
      badgeEl.textContent = `🔴 PUT DOMINANT: ${putPct}% (Ratio: ${ratio})`;
      badgeEl.className = 'card-badge bear';
    } else {
      badgeEl.textContent = `🟡 BALANCED (Ratio: 1.00)`;
      badgeEl.className = 'card-badge neutral';
    }
  }

  const sdAnnotations = getSDBandAnnotations(data, strikes);

  const options = {
    series: [
      { name: 'Put Vol', data: putVol },
      { name: 'Call Vol', data: callVol }
    ],
    chart: { type: 'bar', height: '100%', stacked: true, background: 'transparent', toolbar: { show: false }, animations: { enabled: false } },
    plotOptions: { bar: { horizontal: false, dataLabels: { position: 'top' }, columnWidth: '70%' } },
    colors: ['#FF4560', '#00E396'],
    dataLabels: { enabled: false },
    stroke: { width: 1, colors: ['#1E1E24'] },
    xaxis: {
      categories: strikes.map(String),
      labels: {
        style: { colors: 'var(--text-muted)', fontSize: '10px' },
        rotate: -45,
        rotateAlways: true
      },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: { formatter: val => formatCompact(val), style: { colors: 'var(--text-dim)' } }
    },
    grid: { borderColor: 'var(--border-color)', strokeDashArray: 2 },
    theme: { mode: 'dark' },
    tooltip: { y: { formatter: val => formatNumber(val) } },
    legend: { position: 'top', labels: { colors: 'var(--text-dim)' } },
    annotations: {
      xaxis: sdAnnotations,
    }
  };

  renderApexChart('chart-intraday-vol', options);
}

function switchChartTab(group, tabKey) {
  // Update tab button states
  const tabGroup = document.getElementById(`${group}-tabs`);
  if (tabGroup) {
    tabGroup.querySelectorAll('.chart-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabKey);
    });
  }

  // Store active tab
  state.activeTabs[group] = tabKey;

  // Re-render the chart using cached data
  const ts = state.manifest[state.currentIndex];
  if (!ts) return;

  const cacheKey = `${state.currentAsset}:${ts}`;
  const data = state.cache[cacheKey];
  if (!data) return;

  if (group === 'hybrid') {
    renderHybridChart(data);
  } else if (group === 'intraday-master') {
    renderIntradayMasterChart(data);
  }
}

