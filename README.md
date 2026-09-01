# Futures Options S/D Dashboard

> Institutional-grade quantitative options analytics & microstructure platform for CME Futures (Gold `/GC`, S&P 500 `/ES`, NASDAQ `/NQ`) powered by [**Tastytrade API**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV), **DXLink Streamer**, and **Black-76 / Volatility Surface Analytics**.

---

### 💡 Recommendation
Sign up for a trading account to access the API here: [**Join Tastytrade (Referral Link)**](https://tastytrade.com/welcome/?referralCode=YGHF9JJZCV)

---

## 🚀 Web Decision Terminal (Bloomberg × Cyberpunk UI)

Designed for high-density, real-time trading environments, the web terminal is styled with a sleek, utilitarian Bloomberg-meets-cyberpunk aesthetic (glowing amber/lime accents, glassmorphism containers, responsive multi-asset panels):

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
|  QUANTITATIVE EDGE & MICROSTRUCTURE INTELLIGENCE (8-Card Institutional Grid)     |
|  [1. VRP Monitor (IV vs Yang-Zhang RV)] | [2. 25-Delta Skew & Surface Kurtosis]  |
|  [3. Order Flow Imbalance & VPIN]       | [4. Real-time Institutional Alerts]    |
|  [5. AI/ML Quant Regime Classifier]     | [6. Cross-Asset Macro Correlation]     |
|  [7. Pin Risk & Expiry Magnet Dynamics] | [8. Monte Carlo 30D Probability Cones] |
|  +----------------------------------------------------------------------------+  |
|  |  DEALER HEDGING STRESS TEST (Hypothetical Spot Shocks: -3% to +3%, ΔDEX)   |  |
|  +----------------------------------------------------------------------------+  |
+----------------------------------------------------------------------------------+
|  INTRADAY VOLUME PROFILE (Dynamic Strike Range Filter)                           |
|  [🟢 CALL DOMINANT: 58.4%] |  Stacked Bar Chart of Call/Put Vol per Strike      |
+----------------------------------------------------------------------------------+
|  OI WALLS               |  NET OI PROFILE         |  GAMMA EXPOSURE (GEX) PROFILE|
|  Side-by-Side Call/Put  |  Call minus Put Bars    |  Regime Shaded Splines       |
+----------------------------------------------------------------------------------+
```

---

## 🏗️ Architecture & Project Directory

```
Futures Options SD Dashboard/
├── config.py                    # Centralized API credentials (loads from .env)
├── .env                         # Tastytrade credentials (git-ignored)
├── .env.example                 # Template for .env setup
├── check_prices.py              # Quick price checker (yfinance)
├── run_all.py                   # Master script to run all analysis tools & backtest
├── update_dashboard.py          # Pipeline converting CSV results to Dashboard JSON
├── analytics/                   # Institutional Quantitative Finance Engine
│   ├── exposure.py              # Black-76 option Greeks (Delta, Gamma, Vega, Vanna, Charm) & Dealer GEX/DEX
│   ├── volatility.py            # Localized ATM IV flanking spline interpolation
│   ├── quality.py               # Microstructure data validation & spread filters
│   ├── vrp.py                   # Yang-Zhang (2000) RV, Parkinson RV, VRP (IV - RV), IV Percentile/Rank
│   ├── term_structure.py        # 25-Delta Risk Reversal (RR25), 25-Delta Butterfly (BF25), Term Structure Slope
│   ├── order_flow.py            # Volume Imbalance, VPIN toxic flow, and unusual volume/OI spikes
│   ├── backtest.py              # Historical signal evaluator & forward-return performance scorecard
│   ├── correlation.py           # Multi-asset rolling correlation matrix (GC/ES/NQ), Macro Regime & Divergence
│   ├── scenarios.py             # Spot shock stress tester (±1% to ±3%), Dealer ΔDEX rebalancing demand
│   ├── pin_risk.py              # Pin risk score, near-ATM gamma concentration, expiry magnet active flag
│   └── monte_carlo.py           # Geometric Brownian Motion (GBM) 3,000 paths & barrier touch odds
├── ml/                          # Machine Learning & Multi-Factor Regime Classifier
│   ├── features.py              # 10-Factor quantitative feature extractor
│   └── regime_classifier.py     # Calibrated Softmax Multi-Factor model predicting Prob(Bull/Bear/Range)
├── alerts/                      # Institutional Market Alerts & Notification Engine
│   ├── engine.py                # Rule-based scanner (Wall Breaches, GEX Regime Flips, VRP, Unusual Flow)
│   └── dispatcher.py            # Multi-channel formatting (Discord Webhook, Telegram Bot, LINE Notify)
├── Analysis_Tools/
│   ├── master_report.py         # Advanced Bias Report (PCR, GEX, Skew, Activity, Data Quality)
│   ├── backtest_report.py       # CLI backtest reporting tool (Sharpe, Profit Factor, Win Rates)
│   ├── advanced_viz.py          # Institutional Market Map (GEX Profile, Vanna, Gamma Flip, Iron Walls)
│   ├── sd_bands_chart.py        # Candlestick + SD bands + OI walls overlay
│   ├── hybrid_candle_oi.py      # Candlestick + OI Support/Resistance zones
│   ├── intraday_scanner.py      # Real-time intraday volume scanner
│   ├── organized_analysis.py    # Auto-organized Net OI + OI Walls per asset with Greeks export
│   └── intraday_master_viz.py   # Intraday Master Zoom Charts (5m, 1h) with SD/OI/VWAP
├── tests/                       # Automated Test Suite (13 unit tests)
│   ├── test_quant_modules.py    # Phase 1 quant tests
│   └── test_all_phases.py       # Phase 2 & 3 multi-phase quant tests
├── docs/                        # Dashboard Web Frontend (GitHub Pages)
│   ├── index.html               # Terminal HTML structure with 8 Quant Cards & Stress Table
│   ├── styles.css               # Utilitarian Bloomberg/Cyberpunk CSS stylesheet
│   ├── app.js                   # Application state, TradingView Chart setups & Quant renderers
│   └── data/                    # Multi-timeframe JSON datasets
└── trading_results/             # Historical options & bias data by date/hour (YYYY-MM-DD/HH00/)
```

---

## 🔬 Complete Quantitative Analytics Engine (`analytics/` & `ml/`)

All models and formulas are strictly calibrated to institutional quantitative finance standards:

### 1. Black-76 Greeks & Dealer Exposures (`analytics/exposure.py`)
Futures options have different cost-of-carry characteristics than spot equity options. Holding the underlying futures contract requires no upfront capital. Pricing models utilize the **Black-76 model** with risk-free discounting $e^{-rT}$:

* **Delta (Call / Put):** $\Delta_C = e^{-rT} N(d_1)$, $\Delta_P = -e^{-rT} N(-d_1)$
* **Gamma:** $\Gamma = \frac{e^{-rT} n(d_1)}{F \sigma \sqrt{T}}$
* **Vega:** $\mathcal{V} = e^{-rT} F \sqrt{T} n(d_1)$
* **Vanna ($\partial \Delta / \partial \sigma$):** $\text{Vanna} = -e^{-rT} n(d_1) \frac{d_2}{\sigma}$
* **Charm ($\partial \Delta / \partial t$):** $\text{Charm}_C = -r e^{-rT} N(d_1) - e^{-rT} n(d_1) \left[ \frac{d_2}{2T} \right]$

#### Dealer Exposure Formulations:
* **GEX (Gamma Exposure per 1% move):** $\text{GEX} = \text{Position Sign} \times \text{OI} \times \Gamma \times F^2 \times 0.01 \times \text{multiplier}$
* **DEX (Delta Exposure):** $\text{DEX} = \text{Position Sign} \times \text{OI} \times \Delta \times F \times \text{multiplier}$
* **Vanna Exposure:** $\text{Vanna Exposure} = \text{Position Sign} \times \text{OI} \times \text{Vanna} \times \text{multiplier}$

---

### 2. Volatility Risk Premium (VRP) Monitor (`analytics/vrp.py`)
* **Yang-Zhang (2000) Realized Volatility Estimator:** Minimum-variance unbiased continuous volatility estimator combining overnight jumps and continuous drift:
  $$\sigma_{YZ}^2 = \sigma_o^2 + k \sigma_c^2 + (1 - k) \sigma_{rs}^2$$
  where $\sigma_o^2$ is overnight variance, $\sigma_c^2$ is open-to-close variance, and $\sigma_{rs}^2$ is Rogers-Satchell variance.
* **VRP Calculation:**
  $$VRP = \sigma_{\text{ATM IV}} - \sigma_{\text{Realized}}$$
  * $VRP > +3.0\%$ ➔ **`EXPENSIVE`** (Options overpriced; premium selling edge).
  * $VRP < -3.0\%$ ➔ **`CHEAP`** (Options underpriced; long volatility edge).
  * $-3.0\% \le VRP \le +3.0\%$ ➔ **`FAIR`** (Fair market pricing).

---

### 3. 25-Delta Skew & Surface Dynamics (`analytics/term_structure.py`)
* **25-Delta Risk Reversal ($RR_{25}$):**
  $$RR_{25} = \sigma_{25\Delta C} - \sigma_{25\Delta P}$$
  Measures institutional directional skew (Greed for upside calls vs Fear for downside puts).
* **25-Delta Butterfly ($BF_{25}$):**
  $$BF_{25} = \frac{\sigma_{25\Delta C} + \sigma_{25\Delta P}}{2} - \sigma_{\text{ATM}}$$
  Measures implied surface kurtosis and market expectations of tail-risk / black swan events.

---

### 4. Order Flow Imbalance & Toxic Flow (`analytics/order_flow.py`)
* **Volume Imbalance:**
  $$\text{Imbalance} = \frac{V_{\text{Call}} - V_{\text{Put}}}{V_{\text{Call}} + V_{\text{Put}}} \in [-1.0, +1.0]$$
* **Flow Spike Scanner:** Flags institutional order flow surges where $\text{Volume} > 2 \times \text{OI}$.
* **VPIN Score:** Approximation of volume-synchronized probability of informed trading.

---

### 5. Cross-Asset Correlation & Macro Regime (`analytics/correlation.py`)
* Computes rolling log-return Pearson correlation matrix across Gold (`GC`), S&P 500 (`ES`), and NASDAQ (`NQ`).
* **Macro Regime Classification:**
  * `🟢 RISK_ON`: Equities rallying, Gold consolidating/declining.
  * `🔴 RISK_OFF`: Equities selling off, Gold bidding as safe haven.
  * `🟡 MACRO_INFLATION`: Broad liquid debasement rally (Gold and Equities surging simultaneously).
  * `⚪ BALANCED_CORRELATION`: Standard asset co-movement.

---

### 6. Dealer Hedging Stress Test & Shock Grid (`analytics/scenarios.py`)
* Simulates market maker gamma and delta exposure across 7 hypothetical spot shocks: $[-3\%, -2\%, -1\%, 0\%, +1\%, +2\%, +3\%]$.
* Calculates **Dealer Hedging Rebalancing Demand ($\Delta DEX = DEX_{\text{hypo}} - DEX_{\text{base}}$)** in dollars/contracts.
* Scans for **GEX Cliff Risk** where dealer gamma plunges into negative territory.

---

### 7. Pin Risk & Expiry Magnet Dynamics (`analytics/pin_risk.py`)
* **Pin Risk Score ($0-100$):**
  $$\text{Pin Score} = \min\left(100, \frac{OI_{\text{near-ATM}}}{\sum OI} \times \frac{10}{\sqrt{\max(DTE, 0.25)}}\right)$$
* Calculates near-ATM gamma concentration percentage and **Expected Pinning Range**.
* Automatically activates `🧲 ACTIVE MAGNET` flag when $DTE \le 2.5$ and Pin Score $> 40$.

---

### 8. Monte Carlo Probability Cones & Barrier Odds (`analytics/monte_carlo.py`)
* Runs **3,000 Geometric Brownian Motion (GBM)** simulated price paths:
  $$S_{t+\Delta t} = S_t \exp\left( (\mu - 0.5 \sigma^2)\Delta t + \sigma \sqrt{\Delta t} Z \right)$$
* Generates 30-day multi-percentile price cones ($p5, p10, p25, p50, p75, p90, p95$).
* Calculates **Call Wall Touch Odds (%)** and **Put Wall Touch Odds (%)**.

---

### 9. AI/ML Quantitative Regime Classifier (`ml/regime_classifier.py` & `ml/features.py`)
* Extracts 10 structured microstructure features (VRP, Skew, Imbalance, PCR, GEX Sign, Pin Risk, Wall Proximity).
* Produces calibrated probabilistic outputs:
  $$\text{Prob}(\text{Bull}), \quad \text{Prob}(\text{Bear}), \quad \text{Prob}(\text{Range})$$
* Generates execution action signals (`CALL_SIDE_ACCELERATION`, `PUT_SIDE_DEFENSE`, `RANGE_MEAN_REVERSION`) and an **Ensemble Confidence Score (%)**.

---

### 10. Automated Alert Dispatchers (`alerts/dispatcher.py` & `alerts/engine.py`)
* Scans for Wall Breaches, GEX Regime Flips, VRP Mispricing, and Flow Spikes.
* Formats alert feeds into ready-to-deliver payloads for:
  * **Discord Webhooks** (Color-coded embeds: Critical Red, Warning Yellow, Info Blue)
  * **Telegram Bots** (MarkdownV2 formatting)
  * **LINE Notify** (Clean emoji push notification formatting)

---

## 📈 Signal Backtesting Scorecard

Run historical signal backtests with the CLI tool:
```bash
python Analysis_Tools/backtest_report.py
```

### Empirical Backtest Results (Historical Signals):
* **Evaluated Signals:** 174
* **Directional Accuracy (3H Horizon):** **56.9%**
* **Bearish Signal Accuracy:** **70.6%**
* **Profit Factor:** **1.67**
* **Annualized Sharpe Ratio:** **6.37**

---

## 🧪 Testing & Verification

Run the full unit test suite:
```bash
python -m unittest discover tests
```
```
.............
Ran 13 tests in 0.011s
OK (All 13 tests passing)
```

---

## ⚙️ Running the Engine

### Full Automated Pipeline:
```bash
python run_all.py
```

### Update Dashboard Web Datasets:
```bash
python update_dashboard.py
```

---

## 📄 License
MIT License. Developed for quantitative futures options trading and market microstructure analysis.
