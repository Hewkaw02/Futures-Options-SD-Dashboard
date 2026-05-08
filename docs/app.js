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
  charts: {},              // chart instance refs for cleanup
  activeTabs: {            // active tab per image chart group
    'hybrid': 'hybrid_15m',
    'intraday-master': 'intraday_master_5m',
  },
};

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

// ── Data Loading ─────────────────────────────────────────────
async function loadCurrentData() {
  const ts = state.manifest[state.currentIndex];
  if (!ts) return;

  updateTimeDisplay(ts);
  updateNavButtons();

  const cacheKey = `${state.currentAsset}:${ts}`;

  if (state.cache[cacheKey]) {
    renderAll(state.cache[cacheKey]);
    return;
  }

  // Show loading state
  showLoading(true);

  try {
    const url = `data/${ts}/${state.currentAsset}_data.json`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.cache[cacheKey] = data;
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

// ── Render All ───────────────────────────────────────────────
function renderAll(data) {
  if (!data) {
    renderBiasCard(null);
    clearChart('chart-oi-walls');
    clearChart('chart-net-oi');
    clearChart('chart-gex');
    clearChart('chart-vanna');
    clearChart('chart-hybrid');
    clearChart('chart-intraday-master');
    clearChart('chart-intraday-vol');
    return;
  }

  renderBiasCard(data.bias);
  renderHybridChart(data);
  renderIntradayMasterChart(data);
  renderIntradayVolChart(data);
  renderOIWallsChart(data.oi_walls);
  renderNetOIChart(data.net_oi);
  renderGEXChart(data.gex_profile);
  renderVannaChart(data.vanna);
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
    ['metric-iv','metric-pcr','metric-skew','metric-activity','metric-gex','metric-walls']
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
function renderOIWallsChart(oiData) {
  if (!oiData || !oiData.strikes) {
    clearChart('chart-oi-walls');
    return;
  }

  destroyChart('chart-oi-walls');

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
  };

  const chart = new ApexCharts(document.getElementById('chart-oi-walls'), options);
  chart.render();
  state.charts['chart-oi-walls'] = chart;
}

// ── Chart: Net OI ────────────────────────────────────────────
function renderNetOIChart(netData) {
  if (!netData || !netData.strikes) {
    clearChart('chart-net-oi');
    return;
  }

  destroyChart('chart-net-oi');

  const colors = (netData.net || []).map(v => v >= 0 ? '#00FF66' : '#FF0055');

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
    },
  };

  const chart = new ApexCharts(document.getElementById('chart-net-oi'), options);
  chart.render();
  state.charts['chart-net-oi'] = chart;
}

// ── Chart: GEX Profile ───────────────────────────────────────
function renderGEXChart(gexData) {
  if (!gexData || !gexData.strikes) {
    clearChart('chart-gex');
    return;
  }

  destroyChart('chart-gex');

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
      xaxis: gexData.flip_price ? [{
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
          },
        },
      }] : [],
    },
  };

  const chart = new ApexCharts(document.getElementById('chart-gex'), options);
  chart.render();
  state.charts['chart-gex'] = chart;
}

// ── Chart: Vanna ─────────────────────────────────────────────
function renderVannaChart(vannaData) {
  if (!vannaData || !vannaData.strikes) {
    clearChart('chart-vanna');
    return;
  }

  destroyChart('chart-vanna');

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
    },
  };

  const chart = new ApexCharts(document.getElementById('chart-vanna'), options);
  chart.render();
  state.charts['chart-vanna'] = chart;
}


// ── Chart Utilities ──────────────────────────────────────────
function destroyChart(id) {
  if (state.charts[id]) {
    try { state.charts[id].destroy(); } catch (e) { /* ignore */ }
    delete state.charts[id];
  }
}

function clearChart(id) {
  destroyChart(id);
  const el = document.getElementById(id);
  if (el) {
    el.innerHTML = '<div class="no-data">NO DATA AVAILABLE</div>';
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
function createCandleChartOptions(id, ohlcvData, vwapData, annotations) {
  const series = [{
    name: 'Candle',
    type: 'candlestick',
    data: ohlcvData ? ohlcvData.map(d => ({ x: d[0], y: [d[1], d[2], d[3], d[4]] })) : []
  }];
  
  // Calculate Today's Highlight
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  
  const xaxisAnns = annotations.xaxis || [];
  // Only highlight if today exists within or after the data range
  xaxisAnns.push({
    x: todayStart,
    x2: Date.now() + 86400000, // Extend to tomorrow to cover future padding
    fillColor: '#FEB019',
    opacity: 0.05,
    label: {
      text: 'TODAY',
      style: { color: '#FEB019', background: 'transparent', fontSize: '10px', fontWeight: 'bold' },
      offsetY: 10
    }
  });
  
  if (vwapData && vwapData.length > 0) {
    series.push({
      name: 'VWAP',
      type: 'line',
      data: vwapData.map(d => ({ x: d[0], y: d[1] }))
    });
  }

  return {
    series: series,
    chart: {
      type: 'candlestick',
      height: '100%',
      background: 'transparent',
      toolbar: { show: true },
      animations: { enabled: false },
      id: id
    },
    title: { align: 'left', style: { color: 'var(--text-dim)', fontSize: '11px', fontFamily: 'var(--font-mono)' } },
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: 'var(--text-muted)' }, datetimeUTC: false },
      axisBorder: { color: 'var(--border-color)' },
      axisTicks: { color: 'var(--border-color)' }
    },
    yaxis: {
      tooltip: { enabled: true },
      labels: { style: { colors: 'var(--text-dim)' }, formatter: val => formatNumber(val) }
    },
    plotOptions: {
      candlestick: {
        colors: { upward: '#00E396', downward: '#FF4560' },
        wick: { useFillColor: true }
      }
    },
    stroke: { width: [1, 2], curve: 'straight' },
    annotations: {
      yaxis: annotations.yaxis || [],
      xaxis: xaxisAnns
    },
    grid: { borderColor: 'var(--border-color)', strokeDashArray: 2, padding: { top: 0, bottom: 0, left: 100, right: 10 } },
    theme: { mode: 'dark' },
    tooltip: { theme: 'dark', x: { format: 'dd MMM yyyy HH:mm' } },
    legend: { show: true, position: 'top', labels: { colors: 'var(--text-dim)' } }
  };
}

function renderHybridChart(data) {
  if (!data || !data.candlesticks) {
    clearChart('chart-hybrid');
    document.getElementById('hybrid-nodata').style.display = 'flex';
    return;
  }
  document.getElementById('hybrid-nodata').style.display = 'none';

  const tabKey = state.activeTabs['hybrid'] || 'hybrid_1d';
  const tf = tabKey.split('_')[1]; // 1d, 1h, 15m
  const candleData = data.candlesticks[tf];
  
  if (!candleData || !candleData.ohlcv || candleData.ohlcv.length === 0) {
    clearChart('chart-hybrid');
    document.getElementById('hybrid-nodata').style.display = 'flex';
    return;
  }

  // Create Annotations for OI
  const yaxisAnns = [];
  if (data.intraday_levels) {
    const allOI = [...data.intraday_levels.oi_resistances, ...data.intraday_levels.oi_supports].map(x => x[1]);
    const maxOI = allOI.length > 0 ? Math.max(...allOI) : 1;

    data.intraday_levels.oi_resistances.forEach(r => {
      const isHigh = r[1] >= maxOI * 0.7;
      const isLow = r[1] <= maxOI * 0.3;
      yaxisAnns.push({
        y: r[0], 
        borderColor: isHigh ? 'rgba(255, 69, 96, 0.9)' : (isLow ? 'rgba(255, 69, 96, 0.3)' : 'rgba(255, 69, 96, 0.6)'), 
        strokeDashArray: isLow ? 4 : 0,
        borderWidth: isHigh ? 3 : 1,
        label: { text: `OI Res: ${r[0]} (${formatCompact(r[1])})`, position: 'left', offsetX: 10, style: { color: '#ffffff', background: 'rgba(255, 69, 96, 1)', fontSize: '10px', fontWeight: 'bold' } }
      });
    });
    data.intraday_levels.oi_supports.forEach(s => {
      const isHigh = s[1] >= maxOI * 0.7;
      const isLow = s[1] <= maxOI * 0.3;
      yaxisAnns.push({
        y: s[0], 
        borderColor: isHigh ? 'rgba(0, 227, 150, 0.9)' : (isLow ? 'rgba(0, 227, 150, 0.3)' : 'rgba(0, 227, 150, 0.6)'), 
        strokeDashArray: isLow ? 4 : 0,
        borderWidth: isHigh ? 3 : 1,
        label: { text: `OI Sup: ${s[0]} (${formatCompact(s[1])})`, position: 'left', offsetX: 10, style: { color: '#ffffff', background: 'rgba(0, 227, 150, 1)', fontSize: '10px', fontWeight: 'bold' } }
      });
    });
  }

  const options = createCandleChartOptions('chart-hybrid', candleData.ohlcv, candleData.vwap, { yaxis: yaxisAnns });
  
  destroyChart('chart-hybrid'); // Kill old instance before new render
  state.charts['chart-hybrid'] = new ApexCharts(document.querySelector('#chart-hybrid'), options);
  state.charts['chart-hybrid'].render();
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

  const yaxisAnns = [];
  
  // SD Bands
  const price = data.bias?.price;
  const step = data.sd_step;
  if (price && step && step > 0) {
    for (let i = 1; i <= 3; i++) {
      yaxisAnns.push({ y: price + (step*i), y2: price + (step*(i-0.05)), fillColor: 'rgba(255, 152, 0, 0.1)', opacity: 0.2 });
      yaxisAnns.push({ y: price - (step*i), y2: price - (step*(i-0.05)), fillColor: 'rgba(0, 143, 251, 0.1)', opacity: 0.2 });
    }
  }

  // OI and Vol levels
  if (data.intraday_levels) {
    const allVol = [...data.intraday_levels.vol_resistances, ...data.intraday_levels.vol_supports].map(x => x[1]);
    const maxVol = allVol.length > 0 ? Math.max(...allVol) : 1;

    data.intraday_levels.vol_resistances.forEach(r => {
      const isHigh = r[1] >= maxVol * 0.7;
      const isLow = r[1] <= maxVol * 0.3;
      yaxisAnns.push({ 
        y: r[0], 
        borderColor: isHigh ? 'rgba(255, 69, 96, 0.7)' : (isLow ? 'rgba(255, 69, 96, 0.2)' : 'rgba(255, 69, 96, 0.4)'), 
        strokeDashArray: isLow ? 8 : 4,
        borderWidth: isHigh ? 3 : 1,
        label: { text: `Vol Res: ${r[0]} (${formatCompact(r[1])})`, position: 'left', offsetX: 10, style: { color: '#ffffff', background: 'rgba(255, 69, 96, 1)', fontSize: '10px', fontWeight: 'bold' } } 
      });
    });
    data.intraday_levels.vol_supports.forEach(s => {
      const isHigh = s[1] >= maxVol * 0.7;
      const isLow = s[1] <= maxVol * 0.3;
      yaxisAnns.push({ 
        y: s[0], 
        borderColor: isHigh ? 'rgba(0, 227, 150, 0.7)' : (isLow ? 'rgba(0, 227, 150, 0.2)' : 'rgba(0, 227, 150, 0.4)'), 
        strokeDashArray: isLow ? 8 : 4,
        borderWidth: isHigh ? 3 : 1,
        label: { text: `Vol Sup: ${s[0]} (${formatCompact(s[1])})`, position: 'left', offsetX: 10, style: { color: '#ffffff', background: 'rgba(0, 227, 150, 1)', fontSize: '10px', fontWeight: 'bold' } } 
      });
    });
  }

  const options = createCandleChartOptions('chart-intraday-master', candleData.ohlcv, candleData.vwap, { yaxis: yaxisAnns });
  
  if (candleData.ohlcv && candleData.ohlcv.length > 0) {
    const latestTimestamp = candleData.ohlcv[candleData.ohlcv.length - 1][0];
    const latestDateStr = new Date(latestTimestamp).toLocaleDateString();
    let prevDateStr = null;
    let minTs = candleData.ohlcv[0][0];
    
    for (let i = candleData.ohlcv.length - 1; i >= 0; i--) {
      const ts = candleData.ohlcv[i][0];
      const dStr = new Date(ts).toLocaleDateString();
      if (dStr !== latestDateStr) {
        if (!prevDateStr) prevDateStr = dStr;
        if (dStr !== prevDateStr) {
          minTs = candleData.ohlcv[i+1][0];
          break;
        }
      }
    }
    
    options.xaxis.min = minTs;
    options.xaxis.max = latestTimestamp + (2 * 60 * 60 * 1000); // 2 hours padding
  }
  
  destroyChart('chart-intraday-master');
  state.charts['chart-intraday-master'] = new ApexCharts(document.querySelector('#chart-intraday-master'), options);
  state.charts['chart-intraday-master'].render();
}

function renderIntradayVolChart(data) {
  if (!data || !data.intraday_volume_profile) {
    clearChart('chart-intraday-vol');
    document.getElementById('intraday-vol-nodata').style.display = 'flex';
    return;
  }
  document.getElementById('intraday-vol-nodata').style.display = 'none';

  const profile = data.intraday_volume_profile;
  const strikes = profile.map(p => p.strike);
  const callVol = profile.map(p => p.call_vol);
  const putVol = profile.map(p => p.put_vol);

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
    legend: { position: 'top', labels: { colors: 'var(--text-dim)' } }
  };

  destroyChart('chart-intraday-vol');
  state.charts['chart-intraday-vol'] = new ApexCharts(document.querySelector('#chart-intraday-vol'), options);
  state.charts['chart-intraday-vol'].render();
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

