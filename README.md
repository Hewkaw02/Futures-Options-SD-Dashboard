# Futures Options S/D Dashboard

> Real-time options analytics platform for CME Futures (Gold `/GC`, S&P 500 `/ES`, NASDAQ `/NQ`) powered by [**Tastytrade API**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV) and **DXLink Streamer**.

---

### 💡 Recommendation
Sign up for a trading account to access the API here: [**Join Tastytrade (Referral Link)**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV)

## 🚀 What's New in v3.0 (Interactive TradingView Engine & Performance Boost)

The latest **v3.0 update** introduces institutional-grade interactive charting and massive pipeline performance optimizations:

* **TradingView Lightweight Charts Integration**: Interactive candlestick rendering replaces ApexCharts for Master and Hybrid charts, featuring:
  * **Left-Aligned Price Axes**: Leaves plenty of wicks breathing room on the right side of the canvas.
  * **Custom HTML Floating Tooltips**: Smooth crosshair tracking displays OHLC, VWAP, and active levels cleanly.
  * **Intraday Session Highlight**: Shaded yellow background highlights **Today's Active Intraday Session** dynamically.
* **Wall Interaction & Hedging Status**: Dynamic scanning of spot interactions with major walls:
  * Detects `STABLE`, `TESTING`, or `BROKEN` states for both Call and Put walls.
  * Live dealer hedging status flow rules (e.g., `GAMMA SQUEEZE`, `DELTA CASCADE`, `BUYER/SELLER DEFENSE`, `VOLATILITY TRIGGER`).
* **Put/Call Volume Dominance Badge**: Displays total Call vs Put volume ratios across profiles with color-coded alerts (e.g., `🟢 CALL DOMINANT`, `🔴 PUT DOMINANT`).
* **Smart Volume Profile Filter**: Filters strikes in the volume profile based on the active zoom viewport (plus 30% margin) to prevent unreadable, cluttered bars.
* **50x Pipeline Acceleration**: Implemented in-memory yfinance caching (`YF_CACHE`) in `update_dashboard.py`, bringing down full-history generation runtime from minutes to **under 20 seconds**!
* **Exact Greeks & Gamma Flip Price**: Added support for standard Greek CSV headers (`GEX`, `Vanna`, `DEX`, `Charm`) and shorthand types (`C`/`P`), using linear interpolation to locate the exact price where dealer gamma exposure crosses zero.

## Architecture

```
Futures Options SD Dashboard/
├── config.py                    # Centralized API credentials (loads from .env)
├── .env                         # Tastytrade credentials (git-ignored)
├── .env.example                 # Template for .env setup
├── .gitignore                   # Ignores .env, __pycache__, outputs
├── check_prices.py              # Quick price checker (yfinance)
├── run_all.py                   # Master script to run all analysis tools
├── update_dashboard.py          # Converts CSV results to Dashboard JSON (with YF cache)
├── analytics/                   # 🆕 Shared Quantitative Library (v3.0)
│   ├── exposure.py              # Canonical Black-76 option Greeks & dealer exposures
│   ├── volatility.py            # Localized ATM IV flanking spline interpolation
│   └── quality.py               # Microstructure data validation & quality scoring
├── Trading_Core/
│   ├── Main.py                  # Core engine: IV, SD ranges, asset snapshots
│   └── CheckValue.py            # Real-time trade data viewer
├── Analysis_Tools/
│   ├── master_report.py         # Advanced Bias Report (PCR, GEX, Skew, Activity, Data Quality)
│   ├── advanced_viz.py          # Institutional Market Map (GEX Profile, Vanna, Gamma Flip, Iron Walls)
│   ├── sd_bands_chart.py        # Candlestick + SD bands + OI walls overlay
│   ├── hybrid_candle_oi.py      # Candlestick + OI Support/Resistance zones
│   ├── intraday_scanner.py      # Real-time intraday volume scanner
│   ├── organized_analysis.py    # Auto-organized Net OI + OI Walls per asset with Greeks export
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

```bash
pip install tastytrade yfinance pandas matplotlib mplfinance httpx scipy
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

## 🆕 Quantitative Analytics Module (`analytics/`)

In version 3.0, all calculations are standardized to modern quantitative finance best practices:

### 1. Black-76 Math & Exposures (`analytics/exposure.py`)
Futures options have different cost-of-carry characteristics than spot equity options. Holding the underlying futures contract requires no upfront capital, meaning the cost of carry is fully priced in. Pricing models utilize the **Black-76 model** with risk-free rate discounting factor $e^{-rT}$:

* **Delta (Call):** $\Delta_C = e^{-rT} N(d_1)$
* **Delta (Put):** $\Delta_P = -e^{-rT} N(-d_1)$
* **Gamma:** $\Gamma = \frac{e^{-rT} n(d_1)}{F \sigma \sqrt{T}}$
* **Vega:** $\mathcal{V} = e^{-rT} F \sqrt{T} n(d_1)$
* **Vanna (Sensitivity to Implied Volatility):** $\text{Vanna} = \frac{\partial \Delta}{\partial \sigma} = -e^{-rT} n(d_1) \frac{d_2}{\sigma}$
* **Charm (Daily Delta Decay Rate):**
  $$\text{Charm}_C = -r e^{-rT} N(d_1) - e^{-rT} n(d_1) \left[ \frac{d_2}{2T} \right]$$
  $$\text{Charm}_P = r e^{-rT} N(-d_1) - e^{-rT} n(d_1) \left[ \frac{d_2}{2T} \right]$$

#### Dealer Exposure Formulations:
* **GEX (Gamma Exposure per 1% underlying move):**
  $$\text{GEX} = \text{Position\_Sign} \times \text{OI} \times \Gamma \times F^2 \times 0.01 \times \text{multiplier}$$
* **DEX (Delta Exposure):**
  $$\text{DEX} = \text{Position\_Sign} \times \text{OI} \times \Delta \times F \times \text{multiplier}$$
* **Vanna Exposure:**
  $$\text{Vanna Exposure} = \text{Position\_Sign} \times \text{OI} \times \text{Vanna} \times \text{multiplier}$$
* **Charm Exposure:**
  $$\text{Charm Exposure} = \text{Position\_Sign} \times \text{OI} \times \left( \frac{\text{Charm}}{365.0} \right) \times F \times \text{multiplier}$$

### 2. Flanking Strike ATM IV Spline (`analytics/volatility.py`)
Replaces the highly biased `min(IV)` search (which selects deep OTM strikes experiencing significant skew) with a **localized flanking strike spline**:
1. Finds the two nearest strikes bounding the current mark price ($K_{\text{lower}} \le F < K_{\text{upper}}$).
2. Performs a linear interpolation of the implied volatilities to obtain the exact ATM IV at the futures spot mark:
   $$\sigma_{\text{ATM}} = \sigma_{\text{lower}} + \frac{F - K_{\text{lower}}}{K_{\text{upper}} - K_{\text{lower}}} (\sigma_{\text{upper}} - \sigma_{\text{lower}})$$
3. Shaded standard deviation bands are constructed using the true interpolated $\sigma_{\text{ATM}}$.

### 3. Data Freshness & Microstructure Quality Filter (`analytics/quality.py`)
Validates option data in real-time during overnight Globex trading hours to eliminate low-liquidity noise:
* **Bid-Ask Spread Filter:** Excludes options where the relative spread is greater than $50\%$ of the mid-price ($\frac{\text{Ask} - \text{Bid}}{\text{Mid}} > 0.50$).
* **Zero Bid Rule:** Correctly accounts for illiquid, deep OTM options that do not have active quotes.
* **Volume vs. OI Check (High Flow Instability):** Generates warnings when daily volume exceeds $200\%$ of opening open interest ($\text{Volume} > 2 \times \text{OI}$), indicating active dealer delta re-hedging.
* Outputs a **Data Quality Score (0-100%)** and granular warnings to console and JSON reports.

---

## Function Reference

### `Analysis_Tools/master_report.py` — Advanced Trading Bias Report
Generates a consolidated console table + saves CSV/TXT reports to `trading_results/{date}/{hour}/`.
* Upgraded to incorporate **`pcr_vol`** (intraday volume momentum) in `get_bias()` multi-factor scoring (expanding maximum score range from $[-4, +4]$ to $[-6, +6]$ with calibrated confidence).
* Runs the data quality filter and includes a quality score and microstructure warnings inside the reports.

### `Analysis_Tools/advanced_viz.py` — Institutional Market Map
Generates high-resolution **"Institutional Dashboards"** focused on dealer positioning.
Uses canonical Black-76 formulas, exact Vanna and Charm mathematical derivatives, and proper contract multipliers to map out Positive vs Negative Gamma regimes.
Output: `trading_results/{date}/{hour}/{ASSET}/{asset}_institutional_dashboard_{ts}.png`

### `Analysis_Tools/organized_analysis.py` — Auto-organized OI Analysis
Subscribes to live `Summary` and `Greeks` channels, calculates exact Black-76 exposures (`GEX`, `Vanna`, `DEX`, `Charm`), and saves them in CSV formats, while logging data quality.
Output: `trading_results/{date}/{hour}/{ASSET}/{asset}_data_{ts}.csv`

### `update_dashboard.py` — CSV -> Dashboard JSON
* Reads advanced Greeks and exposures directly from CSV datasets.
* Integrates a **linear interpolation** formula to identify the exact **Gamma Flip Price** (the strike where GEX crosses zero).
* Features **`YF_CACHE`** to avoid redundant API downloads and speed up dashboard exports.
* Maintains backwards-compatible fallbacks to calculate proxy exposures for historical data without Greeks.

---

## ✅ Issues Resolved (v3.0 Quantitative Refactoring)

| # | Category | Issue | Fix Applied (v3.0) |
|---|----------|-------|--------------------|
| 1 | 🔴 Mathematics | Approximate GEX proxy formula | Standardized to canonical **Black-76** GEX equations with $e^{-rT}$ discounting. |
| 2 | 🔴 Mathematics | Static Theta and Vega proxies for Vanna/Charm | Replaced with exact mathematical partial derivatives ($\frac{\partial \Delta}{\partial \sigma}$ and $\frac{\partial \Delta}{\partial T}$). |
| 3 | 🟠 Finance | Highly biased `min(IV)` ATM proxy | Implemented a **localized flanking strikes spline** to find true ATM IV. |
| 4 | 🟠 Microstructure | Low Globex overnight liquidity noise | Built a microstructure **Data Quality Filter** (spread checks, volume/OI confluences). |
| 5 | 🟠 Pricing | Missing contract multipliers | Fully integrated multipliers across all GEX, DEX, Vanna, and Charm dashboard calculators. |
| 6 | 🟡 UX | Inaccurate Gamma Flip Price | Replaced simple binary search with **exact linear interpolation** of the flip price. |
| 7 | 🟡 Optimization | Duplicate yfinance HTTP hits | Built a local memory **`YF_CACHE`** in `update_dashboard.py` to prevent API rate limits. |

---

## Usage

```bash
# Core engine — IV, SD ranges for GC/ES/NQ
python Trading_Core/Main.py

# Advanced institutional market map (Dashboard charts)
python Analysis_Tools/advanced_viz.py

# Master bias report with data quality metrics
python Analysis_Tools/master_report.py

# organized OI analysis (auto-dated folders with exact Greeks)
python Analysis_Tools/organized_analysis.py

# Converts CSV results to Dashboard JSON for docs/
python update_dashboard.py
```
