# Futures Options S/D Dashboard

> Real-time options analytics platform for CME Futures (Gold `/GC`, S&P 500 `/ES`, NASDAQ `/NQ`) powered by **Tastytrade API** and **DXLink Streamer**.

## Architecture

```
Futures Options SD Dashboard/
├── config.py                    # Centralized API credentials (loads from .env)
├── .env                         # Tastytrade credentials (git-ignored)
├── .env.example                 # Template for .env setup
├── .gitignore                   # Ignores .env, __pycache__, outputs
├── check_prices.py              # Quick price checker (yfinance)
├── run_all.py                   # Master script to run all analysis tools
├── update_dashboard.py          # Converts CSV results to Dashboard JSON
├── Trading_Core/
│   ├── Main.py                  # Core engine: IV, SD ranges, asset snapshots
│   └── CheckValue.py            # Real-time trade data viewer
├── Analysis_Tools/
│   ├── master_report.py         # Advanced Bias Report (PCR, GEX, Skew, Activity)
│   ├── advanced_viz.py          # Institutional Market Map (GEX Profile, Vanna, Gamma Flip, Iron Walls)
│   ├── sd_bands_chart.py        # Candlestick + SD bands + OI walls overlay
│   ├── hybrid_candle_oi.py      # Candlestick + OI Support/Resistance zones
│   ├── intraday_scanner.py      # Real-time intraday volume scanner
│   ├── organized_analysis.py    # Auto-organized Net OI + OI Walls per asset
│   ├── gc_oi_focused.py         # Gold-only OI wall analysis
│   ├── gc_option_viz.py         # Gold Volume & OI bar charts
│   ├── gc_option_volume.py      # Gold option volume/OI table output
│   ├── intraday_master_viz.py   # Intraday Master Zoom Charts (5m, 1h) with SD/OI/VWAP
│   └── multi_asset_net_oi.py    # Multi-asset Net OI comparison chart
├── docs/                        # Dashboard frontend (GitHub Pages)
│   └── data/                    # Processed JSON data for the dashboard
├── trading_results/             # Output: charts & reports by date/hour (YYYY-MM-DD/HH00/)
└── intraday_results/            # Output: intraday scans by date/hour (YYYY-MM-DD/HH00/)
```

## Prerequisites

```
pip install tastytrade yfinance pandas matplotlib mplfinance httpx
```

## Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your Tastytrade OAuth credentials:
   - `TASTYTRADE_CLIENT_SECRET` — OAuth client secret
   - `TASTYTRADE_REFRESH_TOKEN` — OAuth refresh token

`config.py` loads credentials automatically via `python-dotenv`. No hard-coded secrets.

---

## Function Reference

### `config.py`

| Variable | Description |
|----------|-------------|
| `CLIENT_SECRET` | Tastytrade OAuth client secret (loaded from `.env`) |
| `REFRESH_TOKEN` | Long-lived refresh token (loaded from `.env`) |
| `CONTRACT_MULTIPLIERS` | Dict mapping product → contract multiplier (GC=100, ES=50, NQ=20) |

---

### `check_prices.py`

Simple utility — no functions defined. Uses `yfinance` to fetch and print the latest close prices for Gold (`GC=F`), S&P 500 (`ES=F`), and NASDAQ (`NQ=F`).

---

### `Trading_Core/Main.py` — Core Engine

#### `_patched_validate_response(response)`
**Monkeypatch** for Tastytrade SDK error handling. Handles cases where the API returns `"error"` as a string instead of a dict, preventing `AttributeError`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `response` | `httpx.Response` | Raw HTTP response object |

- **Raises**: `TastytradeError` with parsed error message

---

#### `infer_mark_price_from_chain(chain, expiry_date, debug=False) → float`
Infers the futures mark price from the option chain by using the **median strike price** as a proxy for ATM price.

| Parameter | Type | Description |
|-----------|------|-------------|
| `chain` | `dict` | Option chain keyed by expiry date |
| `expiry_date` | `date` | Target expiration date |
| `debug` | `bool` | Enable verbose logging |

- **Returns**: Median strike price (float), or `0.0` if no data
- **⚠ Financial Note**: Median strike ≠ true ATM. A put-call parity approach would be more accurate.

---

#### `calc_sd_ranges(price, iv, dte) → dict`
Calculates **1σ and 2σ price ranges** using the Black-Scholes implied volatility framework.

**Formula**: `SD₁ = Price × IV × √(DTE / 365)` — **365 calendar days** (CME futures trade ~23hrs/day)

| Parameter | Type | Description |
|-----------|------|-------------|
| `price` | `float` | Current futures price |
| `iv` | `float` | Implied volatility (decimal, e.g. 0.25 = 25%) |
| `dte` | `float` | Days to expiration |

**Returns dict:**
| Key | Description |
|-----|-------------|
| `1sd_upper` / `1sd_lower` | ±1σ price boundaries |
| `2sd_upper` / `2sd_lower` | ±2σ price boundaries |
| `sd1_move` | Absolute 1σ move in price units |
| `swing_p1_percent` | 1σ move as % of price |
| `swing_p1_prob_percent` | Probability of exceeding ±1σ (~31.73%) |
| `sd_dte_used` | Effective DTE used (min 1.0 day floor) |

- **Uses**: `erfc(1/√2)` for exact normal distribution probability ✅

---

#### `build_asset_values(...) → dict`
Assembles a complete per-asset snapshot for export/inspection.

| Parameter | Type | Description |
|-----------|------|-------------|
| `root_symbol` | `str` | Root symbol (e.g. `/GC`) |
| `front_month_symbol` | `str` | Front-month contract symbol |
| `mark` | `float` | Mark/reference price |
| `best_expiry` | `date` | Selected expiration date |
| `dte` | `int` | Days to expiration |
| `atm_streamer_symbol` | `str` | DXLink streamer symbol for ATM option |
| `atm_strike` | `float` | ATM strike price |
| `iv` | `float` | ATM implied volatility |
| `call_count` / `put_count` | `int` | Number of calls/puts at expiry |
| `sd` | `dict` | Output from `calc_sd_ranges()` |

---

#### `main()` — async
Main execution pipeline:
1. Authenticates via OAuth
2. Finds front-month futures for GC, NQ, ES
3. Fetches option chains → infers mark price
4. Finds ATM call → subscribes to Greeks via DXLink
5. Calculates SD ranges → prints and collects all asset snapshots

---

### `Trading_Core/CheckValue.py`

Subscribes to real-time Trade events for `/GCJ6`, `/NQM6`, `/ESM6` and displays last price, day volume, and day turnover.

#### `main()` — async
Fetches trade data with 10-second timeout per symbol.

---

### `Analysis_Tools/master_report.py` — Advanced Trading Bias Report

#### `get_bias(...)`
**Multi-factor bias scoring model**. Incorporates Price location, PCR, GEX sentiment, and IV Skew.

| Score | Bias Label |
|-------|-----------|
| ≥ +3 | Strong BULLISH |
| +1 to +2 | Mild BULLISH |
| -1 to -2 | Mild BEARISH |
| ≤ -3 | Strong BEARISH |
| 0 | NEUTRAL |

**Calculated Metrics**:
- **PCR (V)**: Intraday Volume Put/Call Ratio (Fear/Greed momentum).
- **PCR (O)**: Open Interest Put/Call Ratio (Structural sentiment).
- **Skew %**: (Put IV - Call IV). High positive = Crash hedging demand.
- **Act %**: (Volume / OI). High % = Unusual institutional participation.
- **GEX**: Net Gamma Exposure (STABLE vs VOLATILE regime).

#### `main()` — async
Generates a consolidated console table + saves CSV/TXT reports to `trading_results/{date}/{hour}/`.

---

### `Analysis_Tools/advanced_viz.py` — Institutional Market Map

#### `analyze_advanced_exposure(session, symbol, title, output_base)`
Generates high-resolution **"Institutional Dashboards"** focused on dealer positioning.

**Features**:
1. **GEX Profile**: Visualizes Positive (stabilizing) vs Negative (accelerating) Gamma across strikes.
2. **Gamma Flip**: Identifies the price level where market volatility regime changes.
3. **Vanna Flow Bar**: Measures price sensitivity to changes in Implied Volatility.
4. **Charm Flow Bar**: Measures Dealer Hedging Pressure over time (Delta decay).
5. **Iron Wall Detection**: Stylized **red ellipse** highlighting price levels where high OI and high Volume converge (Maximum Liquidity Confluence).
6. **Executive Summary**: Dashboard overlay showing Market Regime, Dealer Positioning (Net Delta), Vol Trigger, and 0DTE status.

**Auto-Range**: Dynamically "zooms in" on strikes within ±2.5 Standard Deviations from current price (via yfinance).

Output: `trading_results/{date}/{hour}/{ASSET}/{asset}_institutional_dashboard_{ts}.png`

---

### `Analysis_Tools/sd_bands_chart.py` — SD Bands + OI Master Chart

#### `get_price_and_iv(session, symbol_root) → (float, float)`
Hybrid data fetch: price from **Yahoo Finance** (1m interval), IV from **Tastytrade Greeks** (ATM call).

#### `get_oi_walls(session, symbol, current_price) → (list, list)`
Fetches Open Interest data within ±10% of current price. Returns top 3 resistance strikes (Call OI walls) and top 3 support strikes (Put OI walls).

#### `generate_sd_chart(session, asset, output_base)`
Generates master candlestick charts with overlaid:
- **SD Bands**: 1σ (blue), 2σ (orange), 3σ (dark red) shaded zones
- **OI Walls**: Thick horizontal lines for support (green) / resistance (red)
- **Current Price**: Dashed black line

Timeframes: 4H (resampled from 1h) and 1D.

**SD Formula**: `P × IV × √(1/365)` — standardized to **365 calendar days** (CME futures convention).

**Output**: `trading_results/{ASSET}/{asset}_4h_master_chart.png`, `..._1d_master_chart.png`

---

### `Analysis_Tools/hybrid_candle_oi.py` — Candlestick + OI Zones

#### `get_oi_walls(session, asset) → (list, list, date)`
Fetches OI data within configured strike range → returns top 3 resistances, supports, and expiry date.

#### `generate_hybrid_chart(session, asset, output_base)`
Generates candlestick charts with:
- **VWAP line** (fuchsia) on intraday charts (15m, 1H)
- **OI Support/Resistance zones** as shaded rectangles

**VWAP Formula**: `Σ(Volume × TypicalPrice) / Σ(Volume)` where `TypicalPrice = (H+L+C)/3` ✅

Timeframes: 15m, 1H, 1D. Output: `trading_results/{ASSET}/`.

---

### `Analysis_Tools/intraday_scanner.py` — Real-time Intraday Scanner

#### `get_auto_range(session, symbol_root) → (float, float, float)`
Uses Yahoo Finance to find current price, then calculates strike range:
- Gold: ±3% of current price
- ES/NQ: ±5% of current price

#### `scan_intraday(session, symbol_root, asset_title, output_base)`
Subscribes to both **Trade** and **Summary** events for 20 seconds. Collects real-time intraday volume and open interest. Generates bar chart + CSV.

Output: `intraday_results/{date}/{hour}/{ASSET}/`

---

### `Analysis_Tools/organized_analysis.py` — Auto-organized OI Analysis

#### `process_asset(session, asset, output_base)`
Fetches OI data → generates two charts per asset:
1. **Net OI chart** (Call OI - Put OI) — green = bullish, red = bearish
2. **OI Walls chart** — side-by-side Call/Put OI bars

Also saves raw data as CSV. All files organized by `{date}/{hour}/{ASSET}/`.

---

### `Analysis_Tools/gc_oi_focused.py` — Gold OI Walls (Focused)

Single-asset (Gold only) analysis with **auto-range** strike detection (±5% from current price via yfinance).
Generates a focused bar chart highlighting the largest OI walls with annotations.
Prints top 3 Call Walls (Resistance) and Put Walls (Support).

---

### `Analysis_Tools/gc_option_viz.py` — Gold Volume & OI Visualization

Generates a 2-panel chart for Gold options with **auto-range** strike detection (±4% from current price):
- **Panel 1**: Option Volume by strike (Call vs Put)
- **Panel 2**: Open Interest by strike (Call vs Put)

Also prints Pandas summary statistics grouped by option type.

---

### `Analysis_Tools/gc_option_volume.py` — Gold Option Volume Table

Console-only output displaying a formatted table of Gold option volume and open interest. Uses **auto-range** via yfinance (±5% of current price). No chart generated.

---

### `Analysis_Tools/intraday_master_viz.py` — Intraday Master Zoom Charts

#### `get_trading_data(session, symbol_root) → dict`
Fetches 5-minute and 1-hour candles from Yahoo Finance, plus IV/OI/Volume from Tastytrade streamer.

#### `generate_intraday_master(session, asset, output_base)`
Generates **zoomed** intraday candlestick charts with:
- **VWAP line** (fuchsia)
- **SD Bands**: 1σ (blue), 2σ (orange), 3σ (red) — using 365 calendar days
- **OI Walls**: Solid lines for support (green) / resistance (red)
- **Volume Walls**: Dashed lines for intraday volume confluence

Timeframes: 5m (last 48 candles), 1H (last 72 candles).
Output: `intraday_results/{date}/{hour}/{ASSET}/`

---

### `Analysis_Tools/multi_asset_net_oi.py` — Multi-asset Net OI Comparison

#### `get_net_oi(session, symbol, strike_min, strike_max) → (DataFrame, date)`
Fetches OI → pivots → calculates `Net OI = Call OI - Put OI` per strike.

#### `main()`
Generates a 3-panel chart comparing Net OI across Gold, S&P 500, and NASDAQ. Labels spikes exceeding 60% of maximum. Output: `multi_asset_net_oi.png`.

---

---

## ✅ Issues Resolved (v2.0 Audit)

| # | Category | Issue | Fix Applied |
|---|----------|-------|-------------|
| 1 | 🔴 Security | Hard-coded credentials in `config.py` | Migrated to `.env` + `python-dotenv` |
| 2 | 🔴 Stability | `CheckValue.py` broken (module-level async) | Wrapped in proper `main()` function |
| 3 | 🟠 Code Quality | Bare `except:` clauses swallowing all errors | Replaced with typed exception handling |
| 4 | 🟠 Finance | SD annualization inconsistency (252 vs 365) | **Standardized to 365 calendar days** (CME futures) |
| 5 | 🟠 Finance | GEX missing contract multiplier | Added per-product multiplier (GC=100, ES=50, NQ=20) |
| 6 | 🟠 Stale Data | Hard-coded strike ranges in gc_oi_focused/viz/volume/multi | **Auto-range via yfinance** in all files |
| 7 | 🟡 Imports | Duplicate imports (os, datetime) | Cleaned up |
| 8 | 🟡 Testing | Hard-coded SPY option symbol with expiry date | Dynamic symbol generation |
| 9 | 🟡 Pipeline | `run_all.py` referenced non-existent file | Corrected to actual filenames |

### Remaining Known Limitations
- **`sys.path.append`** pattern — fragile; consider proper packaging for production
- **Median strike as ATM proxy** — put-call parity approach would be more accurate
- **Equal-weight bias scoring** — could benefit from factor weighting calibration

---

## Usage

```bash
# Core engine — IV, SD ranges for GC/ES/NQ
python Trading_Core/Main.py

# Advanced institutional market map (Dashboard)
python Analysis_Tools/advanced_viz.py

# Master bias report
python Analysis_Tools/master_report.py

# SD bands + OI walls master chart
python Analysis_Tools/sd_bands_chart.py

# Hybrid candlestick + OI zones (15m, 1H, 1D)
python Analysis_Tools/hybrid_candle_oi.py

# Intraday volume scanner
python Analysis_Tools/intraday_scanner.py

# Organized OI analysis (auto-dated folders)
python Analysis_Tools/organized_analysis.py

# Multi-asset Net OI comparison
python Analysis_Tools/multi_asset_net_oi.py

# Quick price check
python check_prices.py
```

---

## Financial Concepts Used

| Concept | Formula / Method | Files |
|---------|-----------------|-------|
| **Standard Deviation (σ)** | `P × IV × √(DTE/365)` | Main.py, master_report.py |
| **VWAP** | `Σ(V × TP) / Σ(V)` | hybrid_candle_oi.py |
| **Gamma Flip** | Price where Total GEX crosses Zero | advanced_viz.py |
| **Vanna Flow** | `Σ(OI × Vega × dir)` sensitivity to IV | advanced_viz.py |
| **Charm Flow** | `Σ(OI × Theta × dir)` time decay pressure | advanced_viz.py |
| **Net Delta (DEX)**| `Σ(OI × Delta × P × dir)` dealer positioning | advanced_viz.py |
| **Iron Walls** | Confluence of max OI and max Volume | advanced_viz.py |
| **Put-Call Ratio (PCR)** | `Put OI ÷ Call OI` | master_report.py |
| **Gamma Exposure (GEX)** | `Σ(OI × Γ × dir × multiplier)` | master_report.py, advanced_viz.py |
| **IV Skew** | `IV(OTM Put) - IV(OTM Call)` | master_report.py |
| **OI Walls (S/R)** | Top strikes by Call/Put OI | multiple files |
| **Net OI** | `Call OI - Put OI` per strike | organized_analysis.py |
