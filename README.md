# Futures Options S/D Dashboard

> Real-time options analytics platform for CME Futures (Gold `/GC`, S&P 500 `/ES`, NASDAQ `/NQ`) powered by [**Tastytrade API**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV) and **DXLink Streamer**.

---

### 💡 Recommendation
Sign up for a trading account to access the API here: [**Join Tastytrade (Referral Link)**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV)

---

## 🚀 Web Decision Terminal (Bloomberg × Cyberpunk UI)

Designed for high-density, real-time trading environments, the web terminal is styled with a sleek, utilitarian Bloomberg-meets-cyberpunk aesthetic (glowing amber/lime accents, glassmorphism containers, compact spacing, responsive panels):

```
+----------------------------------------------------------------------------------+
|                    FUTURES OPTIONS S/D TERMINAL [GC] [ES] [NQ] (Time Travel)    |
+----------------------------------------------------------------------------------+
|  MASTER TRADING BIAS (Hero Card)                                                 |
|  [Direction: BULLISH]     [Confidence: 85%]     [Price: 2,342.50]  [IV: 15.2%]   |
+----------------------------------------------------------------------------------+
|  HYBRID CANDLE & OI S/R ZONES (TradingView Lightweight Chart - Left-Aligned Axis)|
|  <- [Price Scale Left]  |  Candlesticks (1D/1H/15M), SD Bands, Session Levels   |
+----------------------------------------------------------------------------------+
|  INTRADAY MASTER CHART (Decision Terminal - Left-Aligned Axis)                   |
|  <- [Price Scale Left]  |  5M/1H Candlesticks, VWAP, Active Option Walls        |
|  +----------------------------------------------------------------------------+  |
|  |  [ Freshness Badge: ⚡ LIVE ]  [ TACTICAL SETUP ]  [ DISTANCE ]  [ HEDGING ]|  |
|  +----------------------------------------------------------------------------+  |
+----------------------------------------------------------------------------------+
|  INTRADAY VOLUME PROFILE (Dynamic Strike Range Filter)                           |
|  [🟢 CALL DOMINANT: 58.4%] |  Stacked Bar Chart of Call/Put Vol per Strike      |
+----------------------------------------------------------------------------------+
|  OI WALLS               |  NET OI PROFILE         |  GAMMA EXPOSURE (GEX) PROFILE|
|  Side-by-Side Call/Put  |  Call minus Put Bars    |  Regime Shaded Splines       |
+----------------------------------------------------------------------------------+
```

### 1. 📈 Interactive Charting Engines
* **TradingView Lightweight Charts Integration**: Interactive candlestick rendering replaces static engines for Master and Hybrid charts, featuring:
  * **Left-Aligned Price Axes**: Moves the Y-axis price scale to the left on both the **Hybrid Chart** and **Intraday Master Chart**, giving candlestick patterns, wicks, and profiles maximum breathing room on the right.
  * **Custom HTML Floating Tooltips**: Renders smooth, crosshair-tracked overlays for OHLC, volume, VWAP, and active option walls.
  * **Intraday Session Highlight**: Highlights **Today's Active Intraday Session** dynamically with a shaded yellow area bounded strictly to the day's hours.
  * **Multi-Layer Toggles**: Integrated checkbox panels directly in the card headers allow instant toggling of SD Bands, Session Levels, Option Walls, VWAP, and Trade Setup zones.

### 2. 🎛️ Flex Widget Container (Side-by-Side Execution Cards)
* **TACTICAL TRADE SETUP**: Renders preferred sentiment bias (BULLISH, BEARISH, NEUTRAL), execution action (BUY, SELL, HOLD), entry zone, stop-loss invalidation level, target milestones, and risk/reward ratios. Toggles automatically to `SETUP FAILED` if the spot price breaches the invalidation level.
* **DISTANCE TO KEY WALLS**: Displays real-time points/percent distances from the active spot price to the major Call and Put walls.
* **WALL INTERACTION & HEDGING STATUS**: Scans spot price proximity to the top option walls in real-time, displaying structural states (`STABLE`, `TESTING`, or `BROKEN`). Connects to a rule-based hedging flow engine indicating dealer risk reactions:
  * `GAMMA SQUEEZE` (Spot testing Call Wall under positive/negative gamma regimes).
  * `DELTA CASCADE` (Spot breaking Put Wall prompting aggressive dealer shorting).
  * `BUYER/SELLER DEFENSE` (Spot bouncing clean from wall boundaries).
  * `VOLATILITY TRIGGER` (Unstable spot movements near key GEX levels).
  * `STABLE NEUTRAL FLOW` (Standard range-bound dealer hedging).
* **`⚡ LIVE TODAY` Badge**: A glowing, pulsing indicator confirming that active live intraday data is feeding into the scanning engine.

### 3. 📊 Smart Volume Profile & Mismatch Correction
* **Strike-for-Strike Synchrony**: Re-calculates top 3 Call (resistance) and Put (support) volume levels directly within the frontend `renderAll` function inside `docs/app.js` to establish 100% data congruence. The horizontal lines plotted on the **Intraday Master Chart** align flawlessly with the columns of the **Intraday Volume Profile Bar Chart**.
* **Smart Strike Range Filtering**: Filters option strikes shown in the Volume Profile dynamically based on the current zoom viewport of the candlestick chart (plus a standard 30% padding margin). This removes cluttered deep OTM bars and ensures clean, readable columns.
* **Put/Call Volume Dominance Badge**: Real-time volume ratio tracker displaying total Call/Put percentages and ratios inside the profile panel with dynamic, color-coded alert banners (e.g., `🟢 CALL DOMINANT: 58.4% (Ratio: 0.71)` vs `🔴 PUT DOMINANT: 62.1% (Ratio: 1.64)`).
* **Top 3 Walls Always Visible**: The "Strongest Only" filtering system is deprecated. The dashboard always renders the top 3 Call and Put walls to provide full market transparency.

### 4. ⚡ Pipeline Performance Acceleration
* **YF_CACHE In-Memory Engine**: The core python pipeline (`update_dashboard.py`) features a module-level `YF_CACHE` dictionary caching `yfinance` candlestick downloads across multi-timeframe configurations (1d, 1h, 15m, 5m). This avoids hundreds of redundant API calls during batch compilations, slashing full dashboard export times from minutes to **under 20 seconds** (a 50x acceleration!).

---

## 🏗️ Architecture & Project Directory

```
Futures Options SD Dashboard/
├── config.py                    # Centralized API credentials (loads from .env)
├── .env                         # Tastytrade credentials (git-ignored)
├── .env.example                 # Template for .env setup
├── .gitignore                   # Ignores .env, __pycache__, outputs
├── check_prices.py              # Quick price checker (yfinance)
├── run_all.py                   # Master script to run all analysis tools
├── update_dashboard.py          # Converts CSV results to Dashboard JSON (with YF_CACHE)
├── analytics/                   # Shared Quantitative Library (v3.0)
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
│   ├── index.html               # Main Terminal HTML structure
│   ├── styles.css               # Utilitarian Bloomberg-style CSS stylesheet
│   ├── app.js                   # Application state, TradingView Chart setups & UI bindings
│   └── data/                    # Processed JSON data for the dashboard
├── trading_results/             # Output: charts & reports by date/hour (YYYY-MM-DD/HH00/)
└── intraday_results/            # Output: intraday scans by date/hour (YYYY-MM-DD/HH00/)
```

---

## 🆕 Quantitative Analytics Module (`analytics/`)

In version 1.0.0, all calculations are standardized to modern quantitative finance best practices:

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
  $$\text{GEX} = \text{Position Sign} \times \text{OI} \times \Gamma \times F^2 \times 0.01 \times \text{multiplier}$$
* **DEX (Delta Exposure):**
  $$\text{DEX} = \text{Position Sign} \times \text{OI} \times \Delta \times F \times \text{multiplier}$$
* **Vanna Exposure:**
  $$\text{Vanna Exposure} = \text{Position Sign} \times \text{OI} \times \text{Vanna} \times \text{multiplier}$$
* **Charm Exposure:**
  $$\text{Charm Exposure} = \text{Position Sign} \times \text{OI} \times \left( \frac{\text{Charm}}{365.0} \right) \times F \times \text{multiplier}$$

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

## 📘 How to Read the Metrics & Use Cases

> [!NOTE]
> **Real-Time Data Notice:** If you want this dashboard to update in real-time, you can connect the Tastytrade API credentials in your own environment (see the configuration steps below). Although there might be minor connection delays or streaming lag, the processed options structures remain highly valuable for structural and positional analysis.

This dashboard is designed to translate complex options microstructure data into actionable trading levels. Here is a guide on how to interpret each value and apply them to your trading strategies.

---

### 1. Master Trading Bias

Located at the top **Hero Card** of the terminal, this card provides a multi-factor directional score based on option walls, PCR (Put/Call Ratio), GEX, Skew, and Price momentum.

*   **Bias Direction:**
    *   `Strong BULL` / `Mild BULL`: The options market structure is positioning for an upward move. Call walls, Positive GEX, low Put-to-Call ratio, or bullish skew confirm high probability of upward movement.
    *   `NEUTRAL`: Range-bound environment. No clear directional dominance.
    *   `Strong BEAR` / `Mild BEAR`: The options market structure is positioning for a downward move. Put walls broken, Negative GEX, high Put-to-Call ratio, or bearish skew confirm high probability of downward movement.
*   **Confidence %:** Ranging from `0%` to `100%`. It reflects the alignment of all 6 scoring factors (Price vs. Walls, PCR OI, PCR Vol, GEX sum, and Skew). Higher confidence means a stronger consensus among options metrics.
*   **ATM IV (Implied Volatility):** The true implied volatility interpolated exactly at-the-money. A rising IV indicates expected larger swings (implied volatility expansion), while a falling IV suggests range-bound consolidation.
*   **PCR Vol (Put/Call Volume Ratio):** The ratio of traded put options to call options volume. A ratio `< 0.8` signifies bullish volume momentum; a ratio `> 1.2` suggests bearish volume momentum.
*   **Skew:** Measures the premium of OTM Puts relative to OTM Calls. High positive skew indicates traders are paying more for downside protection (bearish sentiment), while negative skew suggests call-buying demand (bullish sentiment).
*   **GEX (Net Gamma Exposure):** The aggregate Gamma Exposure. Positive values indicate a stabilizing environment (mean reversion), whereas negative values indicate a volatile environment (momentum).

---

### 2. Price Levels & Chart Overlays

Both the **Hybrid Chart** and **Intraday Master Chart** display key support/resistance zones derived from option positioning:

*   **Standard Deviation (SD) Bands:**
    *   `±1SD (Standard Deviation)`: Statistically contains ~68% of price outcomes.
    *   `±2SD (Standard Deviation)`: Statistically contains ~95% of price outcomes.
    *   *How to trade:* When the price tests `±2SD` under positive GEX, it is highly likely to reject and revert. If the price breaks out of `±2SD` under negative GEX, a massive breakout trend is likely starting.
*   **Option Walls:**
    *   `Call Wall (Resistance)`: The strike price with the largest concentration of Call Open Interest. Serves as a major overhead ceiling.
    *   `Put Wall (Support)`: The strike price with the largest concentration of Put Open Interest. Serves as a major floor.
*   **VWAP (Volume Weighted Average Price):** The average price weighted by volume. Used as an intraday anchor. Trading above VWAP favors long setups; trading below VWAP favors short setups.
*   **Gamma Flip Price:** The boundary where GEX transitions between positive and negative.
    *   **Above Flip Price (Positive Gamma Regime):** High liquidity, tight ranges, mean-reversion behavior. Fades and range plays are favored.
    *   **Below Flip Price (Negative Gamma Regime):** Low liquidity, rapid trend acceleration, heavy volatility. Breakout and momentum plays are favored.

---

### 3. Tactical Widgets & Hedging Flows

*   **Tactical Trade Setup Card:**
    *   Dynamically calculates entry zones, stop losses, and target milestones based on option walls and SD bands.
    *   `Status: ACTIVE`: The trade plan is valid.
    *   `Status: SETUP FAILED`: The price has breached the stop-loss level, invalidating the current bias setup.
*   **Distance to Key Walls:** Displays how many points/percentages the current spot price is away from the Call Wall and Put Wall, helping you gauge remaining upside/downside room.
*   **Wall Interaction & Hedging Status:**
    *   `🔴 GAMMA SQUEEZE` (Negative GEX regime): Spot breaches the Call Wall. Market makers are forced to buy underlying futures to maintain delta-neutrality, creating a rapid buying loop.
    *   `🔴 DELTA CASCADE` (Negative GEX regime): Spot breaches the Put Wall. Market makers are forced to sell underlying futures to hedge, triggering a rapid selling cascade.
    *   `🟢 BUYER / SELLER DEFENSE` (Positive GEX regime): Price tests Put/Call walls and gets rejected. Market makers buy/sell futures to stabilize the boundaries, resulting in a bounce.
    *   `🟡 VOLATILITY TRIGGER`: Price is currently testing key walls; expect volatile whipsaws as dealer hedges adjust.
    *   `⚪ Stable Neutral Flow`: Normal range-bound conditions with balanced dealer flows.

---

### 4. Practical Trading Use Cases

#### 📉 Case 1: Mean Reversion / Range Trading
*   **Condition:** Price is **above** the Gamma Flip Price (Positive Gamma) + Master Bias is `NEUTRAL` or `Mild BULL/BEAR`.
*   **Strategy:**
    1.  Wait for the price to drop to the **Put Wall** or the **-1SD / -2SD** band.
    2.  Check if the **Put Wall Interaction** displays `🟢 BUYER DEFENSE` or `REJECTED (UP)`.
    3.  Enter a **LONG** position targeting the **VWAP** or **+1SD**.
    4.  Place a stop loss just below the **Put Wall** (or use the Tactical Trade Setup stop-loss level).
    5.  *(Inverse for Short setups at the Call Wall / +2SD)*

#### 🚀 Case 2: Breakout / Momentum Trading
*   **Condition:** Price crosses **below** the Gamma Flip Price (entering Negative Gamma) + Master Bias is `Strong BEAR` (or crosses above with `Strong BULL` bias).
*   **Strategy:**
    1.  Wait for the price to breach a major Option Wall.
    2.  Confirm that the **Hedging Status** changes to `🔴 DELTA CASCADE` (for shorts) or `🔴 GAMMA SQUEEZE` (for longs).
    3.  Enter in the direction of the breakout (e.g., Short when Put Wall breaks).
    4.  Hold the position for a fast momentum run toward the **-2SD / -3SD** bands.
    5.  Set your stop loss at the breached Wall level (now acting as new resistance/support).

#### 🛡️ Case 3: Risk Avoidance / Volatility Hedging
*   **Condition:** Price is trading very close to the **Gamma Flip Price** or **Hedging Status** is `🟡 VOLATILITY TRIGGER`.
*   **Strategy:**
    1.  Expect high intraday noise and whipsaws.
    2.  Avoid placing tight stop losses in this zone as they are highly likely to get swept.
    3.  Reduce position size or stay on the sidelines until the price establishes a direction away from the Flip level.

#### 📊 Case 4: Smart Strike Range Selection
*   **Condition:** Selling Options (Credit Spreads, Iron Condors) to collect premium.
*   **Strategy:**
    1.  Use the **±2SD Bands** and the **Call/Put Walls** to identify low-probability boundary zones.
    2.  Sell Call Spreads above the **Call Wall** / **+2SD** and Put Spreads below the **Put Wall** / **-2SD**.
    3.  Monitor the **Data Quality Score**; only write options when the score is `> 80%` to ensure tight bid-ask spreads and fair pricing.

---


## ⚙️ Function Reference

### `Analysis_Tools/master_report.py` — Advanced Trading Bias Report
Generates a consolidated console table + saves CSV/TXT reports to `trading_results/{date}/{hour}/`.
* Upgraded to incorporate **`pcr_vol`** (intraday volume momentum) in `get_bias()` multi-factor scoring (expanding maximum score range from $[-4, +4]$ to $[-6, +6]$ with calibrated confidence).
* Runs the data quality filter and includes a quality score and microstructure warnings inside the reports.

### `Analysis_Tools/advanced_viz.py` — Institutional Market Map
Generates high-resolution **"Institutional Dashboards"** focused on dealer positioning.
Uses canonical Black-76 formulas, exact Vanna and Charm mathematical derivatives, and proper contract multipliers to map out Positive vs Negative Gamma regimes.
* Output: `trading_results/{date}/{hour}/{ASSET}/{asset}_institutional_dashboard_{ts}.png`

### `Analysis_Tools/organized_analysis.py` — Auto-organized OI Analysis
Subscribes to live `Summary` and `Greeks` channels, calculates exact Black-76 exposures (`GEX`, `Vanna`, `DEX`, `Charm`), and saves them in CSV formats, while logging data quality.
* Output: `trading_results/{date}/{hour}/{ASSET}/{asset}_data_{ts}.csv`

### `update_dashboard.py` — CSV -> Dashboard JSON
* Reads advanced Greeks and exposures directly from CSV datasets.
* Integrates a **linear interpolation** formula to identify the exact **Gamma Flip Price** (the strike where GEX crosses zero).
* Features **`YF_CACHE`** to avoid redundant API downloads and speed up dashboard exports by 50x.
* Maintains backwards-compatible fallbacks to calculate proxy exposures for historical data without Greeks.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
Ensure you have Python 3.10+ installed. Install required dependencies:
```bash
pip install tastytrade yfinance pandas matplotlib mplfinance httpx scipy
```

### 2. Configuration
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` with your Tastytrade OAuth credentials:
   * `TASTYTRADE_CLIENT_SECRET` — OAuth client secret
   * `TASTYTRADE_REFRESH_TOKEN` — OAuth refresh token

`config.py` loads credentials automatically via `python-dotenv`. No hard-coded secrets.

---

## 🚀 Execution & Usage

### 1. Data Collection & Analysis Pipeline
Run individual tools or execute the master pipeline:

```bash
# Run the core quantitative engine (standard deviation bands & asset snapshots)
python Trading_Core/Main.py

# Generate institutional market map GEX/Vanna dashboards
python Analysis_Tools/advanced_viz.py

# Generate advanced trading bias reports with microstructure checks
python Analysis_Tools/master_report.py

# Collect and organize open interest data with exact Greeks
python Analysis_Tools/organized_analysis.py

# Compile and export CSV results to frontend docs/data/ JSON format (Super-charged with YF_CACHE)
python update_dashboard.py
```

To run the full suite at once:
```bash
python run_all.py
```

### 2. Running the Local Web Terminal
Launch a high-performance local web server inside the `docs` folder to view the interactive dashboard:

```bash
# Using Python's built-in HTTP server
python -m http.server 8000 --directory docs
```

Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## 🛡️ Core Quality & Quantitative Compliance (v1.0.0)

| # | Category | Core Feature | Implementation |
|---|----------|---|---|
| 1 | 🔴 Mathematics | GEX Pricing | Built on canonical **Black-76** GEX equations with $e^{-rT}$ discounting. |
| 2 | 🔴 Mathematics | Vanna & Charm | Utilizes exact mathematical partial derivatives ($\frac{\partial \Delta}{\partial \sigma}$ and $\frac{\partial \Delta}{\partial T}$). |
| 3 | 🟠 Finance | ATM Volatility | Implemented a **localized flanking strikes spline** to find true ATM IV. |
| 4 | 🟠 Microstructure | Liquidity Validation | Built a microstructure **Data Quality Filter** (spread checks, volume/OI confluences). |
| 5 | 🟠 Pricing | Multipliers | Fully integrated contract multipliers across all GEX, DEX, Vanna, and Charm calculators. |
| 6 | 🟡 UX | Gamma Flip | Uses **exact linear interpolation** to calculate the accurate zero-gamma flip price. |
| 7 | 🟡 Optimization | Caching Engine | Built a local memory **`YF_CACHE`** in `update_dashboard.py` to prevent API rate limits. |
