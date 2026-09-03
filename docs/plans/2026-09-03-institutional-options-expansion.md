# Institutional Options Analytics Expansion Implementation Plan

> **For Gemini / Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Futures Options SD Dashboard with institutional quantitative desk mechanics: Asymmetric Dealer GEX/DEX Positioning, 4-Quadrant Volume vs $\Delta$OI Flow Decomposition, Event IV Crush & Vanna Rally Simulation, Charm Overnight Flow, and Delta-Weighted Strike Pinning.

**Architecture:** 
- Mathematical layer in `analytics/` (Black-76 Greeks, Dealer Exposure, Order Flow, Scenario Shocks, Pinning Distribution).
- Pipeline serialization in `update_dashboard.py` (transforming raw options CSVs and Greeks into `{ASSET}_data.json`).
- High-density frontend in `docs/index.html` and `docs/app.js` (Bloomberg × Cyberpunk Terminal with ApexCharts and TradingView Lightweight Charts).

**Tech Stack:** Python 3.12, NumPy, Pandas, Black-76 Pricing Model, ApexCharts 3.x, HTML5/CSS3, JavaScript (ES6+).

---

## Roadmap & Phase Overview

| Phase | Scope | Core Modules & Outputs | Effort |
| :--- | :--- | :--- | :---: |
| **Phase 1: Quick Wins** | Quant Analytics Core | Asymmetric Dealer Positioning, 4-Quadrant Vol/$\Delta$OI, IV Crush Vanna Simulator, Charm Flow | Low (Ready Data) |
| **Phase 2: Terminal UI** | Web Terminal Integration | 4-Quadrant Flow Cards, Charm Chart & Overnight Gauge, IV Stress Shock Grid | Low-Medium |
| **Phase 3: Advanced Models** | Deep Institutional Quant | Delta-Weighted Pinning Probability Distribution, Multi-Expiry Calendar Roll Tracker | Medium |

---

## Phase 1: Quant Analytics Core (Quick Wins)

### Task 1: Asymmetric Dealer Positioning Model (GEX / DEX Refinement)

**Files:**
- Modify: `analytics/exposure.py:78-136`
- Test: `tests/test_exposure_positioning.py`

**Step 1: Write the failing test**

Create `tests/test_exposure_positioning.py`:
```python
import unittest
from analytics.exposure import calculate_dealer_exposures

class TestAsymmetricDealerExposure(unittest.TestCase):
    def test_asymmetric_dealer_positioning(self):
        # OTM Call (Strike 2500 vs Spot 2400): Customers sell covered calls -> Dealer is LONG call (+1)
        # Therefore dealer gamma should be POSITIVE
        exp_otm_call = calculate_dealer_exposures(
            oi=100.0, delta=0.30, gamma=0.002, vega=10.0, vanna=0.05, charm=-0.01,
            spot=2400.0, multiplier=100.0, option_type="C",
            strike=2500.0, dealer_model="asymmetric"
        )
        self.assertGreater(exp_otm_call['gex'], 0, "Dealer should be Long Gamma on OTM Calls")

        # ATM/ITM Call (Strike 2300 vs Spot 2400): Customers buy calls -> Dealer is SHORT call (-1)
        exp_itm_call = calculate_dealer_exposures(
            oi=100.0, delta=0.70, gamma=0.002, vega=10.0, vanna=0.05, charm=-0.01,
            spot=2400.0, multiplier=100.0, option_type="C",
            strike=2300.0, dealer_model="asymmetric"
        )
        self.assertLess(exp_itm_call['gex'], 0, "Dealer should be Short Gamma on ITM Calls")

        # Put Option (Strike 2300 vs Spot 2400): Customers buy put hedges -> Dealer is SHORT put (-1)
        exp_put = calculate_dealer_exposures(
            oi=100.0, delta=-0.30, gamma=0.002, vega=10.0, vanna=0.05, charm=0.01,
            spot=2400.0, multiplier=100.0, option_type="P",
            strike=2300.0, dealer_model="asymmetric"
        )
        self.assertLess(exp_put['gex'], 0, "Dealer should be Short Gamma on Puts")

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_exposure_positioning.py`
Expected: FAIL (argument `strike` or `dealer_model` not accepted).

**Step 3: Implement minimal code in `analytics/exposure.py`**

Update `calculate_dealer_exposures`:
```python
def calculate_dealer_exposures(
    oi: float,
    delta: float,
    gamma: float,
    vega: float,
    vanna: float,
    charm: float,
    spot: float,
    multiplier: float,
    option_type: str,
    dealer_assumed_side: str = "short",
    strike: float = 0.0,
    dealer_model: str = "symmetric"
) -> dict:
    opt_type_upper = option_type.upper()
    is_call = ('C' in opt_type_upper)

    if dealer_model == "asymmetric" and strike > 0 and spot > 0:
        if is_call:
            # Customers sell OTM calls (covered calls) -> Dealer is LONG (+1)
            # Customers buy ATM/ITM calls -> Dealer is SHORT (-1)
            position_sign = 1.0 if strike > spot else -1.0
        else:
            # Customers buy puts for portfolio insurance -> Dealer is SHORT (-1)
            position_sign = -1.0
    else:
        position_sign = -1.0 if dealer_assumed_side == "short" else 1.0

    gex = position_sign * oi * gamma * (spot**2) * 0.01 * multiplier
    dex = position_sign * oi * delta * spot * multiplier
    vanna_exp = position_sign * oi * vanna * multiplier
    charm_exp = position_sign * oi * (charm / 365.0) * spot * multiplier

    return {
        "gex": gex,
        "dex": dex,
        "vanna_exp": vanna_exp,
        "charm_exp": charm_exp
    }
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_exposure_positioning.py`
Expected: PASS (All tests pass).

---

### Task 2: 4-Quadrant Volume vs $\Delta$OI Flow Decomposition

**Files:**
- Modify: `analytics/order_flow.py`
- Test: `tests/test_order_flow_quadrant.py`

**Step 1: Write the failing test**

Create `tests/test_order_flow_quadrant.py`:
```python
import unittest
from analytics.order_flow import classify_oi_volume_quadrant, decompose_strike_flow

class TestOrderFlowQuadrant(unittest.TestCase):
    def test_quadrant_classification(self):
        # High vol + Positive Delta OI = Accumulation
        res1 = classify_oi_volume_quadrant(volume=500, delta_oi=300, min_vol=50)
        self.assertEqual(res1['quadrant'], 'ACCUMULATION')
        self.assertEqual(res1['badge'], '🟢 ACCUMULATING')

        # High vol + Negative Delta OI = Liquidation
        res2 = classify_oi_volume_quadrant(volume=500, delta_oi=-300, min_vol=50)
        self.assertEqual(res2['quadrant'], 'LIQUIDATION')
        self.assertEqual(res2['badge'], '🔴 DE-RISKING')

        # High vol + Flat Delta OI = Day Trading
        res3 = classify_oi_volume_quadrant(volume=500, delta_oi=5, min_vol=50)
        self.assertEqual(res3['quadrant'], 'DAY_TRADING')
        self.assertEqual(res3['badge'], '⚪ CHURN/SCALP')

    def test_decompose_strike_flow(self):
        records = [
            {'strike': 2400.0, 'call_vol': 800, 'call_doi': 600, 'put_vol': 100, 'put_doi': -50},
            {'strike': 2350.0, 'call_vol': 50, 'call_doi': 0, 'put_vol': 900, 'put_doi': 700},
        ]
        res = decompose_strike_flow(records)
        self.assertIn('dominant_regime', res)
        self.assertIn('accumulation_strikes', res)
        self.assertEqual(len(res['accumulation_strikes']), 2)

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_order_flow_quadrant.py`
Expected: FAIL with `ImportError: cannot import name 'classify_oi_volume_quadrant'`.

**Step 3: Implement minimal code in `analytics/order_flow.py`**

Add to `analytics/order_flow.py`:
```python
def classify_oi_volume_quadrant(
    volume: float,
    delta_oi: float,
    min_vol: float = 50.0,
    churn_threshold_pct: float = 0.15
) -> Dict[str, Any]:
    if volume < min_vol:
        return {'quadrant': 'INACTIVE', 'badge': '—', 'desc': 'Low volume'}

    abs_doi = abs(delta_oi)
    if abs_doi < (volume * churn_threshold_pct):
        return {
            'quadrant': 'DAY_TRADING',
            'badge': '⚪ CHURN/SCALP',
            'desc': f'High turnover ({int(volume)} contracts) with flat OI change ({int(delta_oi)}). Speculative day trading.'
        }
    elif delta_oi > 0:
        return {
            'quadrant': 'ACCUMULATION',
            'badge': '🟢 ACCUMULATING',
            'desc': f'Volume ({int(volume)}) confirmed by positive ΔOI (+{int(delta_oi)}). Institutional position building.'
        }
    else:
        return {
            'quadrant': 'LIQUIDATION',
            'badge': '🔴 DE-RISKING',
            'desc': f'Volume ({int(volume)}) accompanied by OI contraction ({int(delta_oi)}). Position unwinding / profit taking.'
        }

def decompose_strike_flow(
    strike_records: List[Dict[str, Any]],
    min_vol: float = 50.0
) -> Dict[str, Any]:
    accumulations = []
    liquidations = []
    day_trades = []

    for r in strike_records:
        strike = r.get('strike', 0.0)
        # Calls
        c_v = r.get('call_vol', 0.0)
        c_doi = r.get('call_doi', 0.0)
        c_res = classify_oi_volume_quadrant(c_v, c_doi, min_vol=min_vol)
        if c_res['quadrant'] == 'ACCUMULATION':
            accumulations.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi})
        elif c_res['quadrant'] == 'LIQUIDATION':
            liquidations.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi})
        elif c_res['quadrant'] == 'DAY_TRADING':
            day_trades.append({'strike': strike, 'type': 'CALL', 'volume': c_v, 'delta_oi': c_doi})

        # Puts
        p_v = r.get('put_vol', 0.0)
        p_doi = r.get('put_doi', 0.0)
        p_res = classify_oi_volume_quadrant(p_v, p_doi, min_vol=min_vol)
        if p_res['quadrant'] == 'ACCUMULATION':
            accumulations.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi})
        elif p_res['quadrant'] == 'LIQUIDATION':
            liquidations.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi})
        elif p_res['quadrant'] == 'DAY_TRADING':
            day_trades.append({'strike': strike, 'type': 'PUT', 'volume': p_v, 'delta_oi': p_doi})

    dominant = 'ACCUMULATION' if len(accumulations) > len(liquidations) else (
        'LIQUIDATION' if len(liquidations) > len(accumulations) else 'DAY_TRADING'
    )

    return {
        'dominant_regime': dominant,
        'accumulation_strikes': sorted(accumulations, key=lambda x: -x['delta_oi']),
        'liquidation_strikes': sorted(liquidations, key=lambda x: x['delta_oi']),
        'day_trading_strikes': sorted(day_trades, key=lambda x: -x['volume']),
        'summary': f"{len(accumulations)} strikes accumulating, {len(liquidations)} de-risking, {len(day_trades)} day-traded."
    }
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_order_flow_quadrant.py`
Expected: PASS.

---

### Task 3: Dual Shock Stress Grid: Spot & Event IV Shocks (Vanna Rally Simulator)

**Files:**
- Modify: `analytics/scenarios.py`
- Test: `tests/test_vanna_rally_scenario.py`

**Step 1: Write the failing test**

Create `tests/test_vanna_rally_scenario.py`:
```python
import unittest
from analytics.scenarios import run_stress_scenarios

class TestVannaRallyScenario(unittest.TestCase):
    def test_iv_shock_simulation(self):
        rows = [
            {'Strike': 2400.0, 'Type': 'C', 'Open_Interest': 500, 'IV': 0.20},
            {'Strike': 2350.0, 'Type': 'P', 'Open_Interest': 800, 'IV': 0.25}
        ]
        # Test with IV shock scenarios (-5% IV crush, e.g. post-FOMC)
        res = run_stress_scenarios(
            options_rows=rows, spot=2400.0, dte=5.0, multiplier=100.0,
            iv_shifts=[-0.05, 0.0, +0.05]
        )
        self.assertIn('vanna_rally_scenarios', res)
        iv_crush = [s for s in res['vanna_rally_scenarios'] if s['iv_shift_pct'] == -5.0]
        self.assertEqual(len(iv_crush), 1)
        self.assertIn('dealer_rebalance_usd', iv_crush[0])
        self.assertIn('vanna_rally_direction', iv_crush[0])

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_vanna_rally_scenario.py`
Expected: FAIL with `TypeError: unexpected keyword argument 'iv_shifts'`.

**Step 3: Implement minimal code in `analytics/scenarios.py`**

Update `run_stress_scenarios` signature and logic:
```python
def run_stress_scenarios(
    options_rows: List[Dict[str, Any]],
    spot: float,
    dte: float,
    multiplier: float = 100.0,
    shifts: List[float] = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03],
    iv_shifts: Optional[List[float]] = None
) -> Dict[str, Any]:
    ...
    # (Existing spot shocks logic) ...

    # Add Event IV Shock Grid (Vanna Rally Simulator)
    if iv_shifts is None:
        iv_shifts = [-0.05, -0.025, 0.0, 0.025, 0.05]

    vanna_scenarios = []
    base_dex_at_zero = base_dex

    for iv_s in iv_shifts:
        shock_dex = 0.0
        shock_vanna = 0.0
        for r_opt in options_rows:
            strike = float(r_opt.get('Strike', 0) or 0)
            oi = float(r_opt.get('Open_Interest', 0) or 0)
            iv = float(r_opt.get('IV', 0) or 0)
            opt_type = str(r_opt.get('Type', '')).upper()
            type_char = 'C' if 'C' in opt_type else 'P'
            if strike <= 0 or oi <= 0 or iv <= 0:
                continue

            hypo_iv = max(0.01, iv + iv_s)
            greeks = black76_greeks(F=spot, K=strike, T=T, sigma=hypo_iv, r=r, option_type=type_char)
            exp = calculate_dealer_exposures(
                oi=oi, delta=greeks['delta'], gamma=greeks['gamma'], vega=greeks['vega'],
                vanna=greeks['vanna'], charm=greeks['charm'], spot=spot, multiplier=multiplier,
                option_type=type_char, strike=strike, dealer_model="asymmetric"
            )
            shock_dex += exp['dex']
            shock_vanna += exp['vanna_exp']

        rebalance_demand = shock_dex - base_dex_at_zero
        direction = 'BUY_UNDERLYING (Vanna Rally)' if rebalance_demand > 0 else (
            'SELL_UNDERLYING' if rebalance_demand < 0 else 'NEUTRAL'
        )

        vanna_scenarios.append({
            'iv_shift_pct': round(iv_s * 100.0, 1),
            'dealer_rebalance_usd': round(rebalance_demand, 2),
            'dealer_rebalance_contracts': round(rebalance_demand / (spot * multiplier), 1) if spot > 0 else 0,
            'vanna_rally_direction': direction
        })

    result_dict['vanna_rally_scenarios'] = vanna_scenarios
    return result_dict
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_vanna_rally_scenario.py`
Expected: PASS.

---

### Task 4: Charm Exposure Pipeline & Overnight Charm Flow Metric

**Files:**
- Modify: `update_dashboard.py:230-278` & `update_dashboard.py:700-740`
- Test: `tests/test_charm_pipeline.py`

**Step 1: Write the failing test**

Create `tests/test_charm_pipeline.py`:
```python
import unittest
from update_dashboard import parse_option_data_csv
import tempfile
import os

class TestCharmPipeline(unittest.TestCase):
    def test_charm_parsed_and_aggregated(self):
        csv_content = """Strike,Type,OI,Volume,GEX,Vanna,DEX,Charm,IV
2400.0,Call,100,50,150.0,25.0,-20000.0,12.5,0.20
2400.0,Put,80,40,-120.0,-20.0,18000.0,-8.0,0.20
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            res = parse_option_data_csv(temp_path)
            self.assertIn('charm', res)
            self.assertIn('charm_exp', res['charm'])
            self.assertIn('total_overnight_flow_usd', res['charm'])
            self.assertAlmostEqual(res['charm']['total_overnight_flow_usd'], 4.5, delta=0.1)
        finally:
            os.remove(temp_path)

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_charm_pipeline.py`
Expected: FAIL with `KeyError: 'charm'`.

**Step 3: Implement minimal code in `update_dashboard.py`**

In `parse_option_data_csv`:
```python
    # After gex_map and vanna_map aggregation:
    charm_map = {}
    for r in rows:
        s = r['Strike']
        charm_map[s] = charm_map.get(s, 0.0) + r.get('Charm', 0.0)

    charm_values = []
    for s in active_strikes:
        charm_values.append(round(charm_map.get(s, 0.0), 2))

    total_overnight_flow = sum(charm_values)
    charm_data = {
        "strikes": active_strikes,
        "charm_exp": charm_values,
        "total_overnight_flow_usd": round(total_overnight_flow, 2),
        "bias": "BUY_PRESSURE" if total_overnight_flow > 0 else ("SELL_PRESSURE" if total_overnight_flow < 0 else "NEUTRAL")
    }

    # Add to return dictionary
    return {
        ...
        "charm": charm_data,
        ...
    }
```
And ensure in `process_timestamp`:
```python
    data["charm"] = opt_data.get("charm")
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_charm_pipeline.py`
Expected: PASS.

---

## Phase 2: Web Decision Terminal UI Integration

### Task 5: Web UI Card: 4-Quadrant Flow & Institutional Positioning Table

**Files:**
- Modify: `docs/index.html:444-460`
- Modify: `docs/app.js:1280-1370`
- Modify: `docs/styles.css`

**Step 1: Add HTML Card in `docs/index.html`**

Directly beneath `#card-oi-change`, add:
```html
<!-- ══════ 4-QUADRANT FLOW & ACCUMULATION TABLE ══════ -->
<div class="card full-width" id="card-flow-quadrant">
  <div class="card-header">
    <span class="card-title">Institutional Position Flow Decomposition (4-Quadrant Matrix)</span>
    <span class="card-badge" id="flow-quadrant-badge">ANALYZING...</span>
  </div>
  <div class="card-body">
    <div class="quadrant-summary-row" id="quadrant-summary-text">
      Loading flow decomposition...
    </div>
    <div class="table-responsive">
      <table class="data-table" id="table-flow-quadrant">
        <thead>
          <tr>
            <th>Strike</th>
            <th>Type</th>
            <th>Volume</th>
            <th>ΔOI</th>
            <th>Classification</th>
            <th>Institutional Action</th>
          </tr>
        </thead>
        <tbody id="flow-quadrant-tbody">
          <tr><td colspan="6" class="text-center">No flow anomalies detected.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
```

**Step 2: Add Render Logic in `docs/app.js`**

Add `renderFlowQuadrantTable(flowData, oiChangeData, volumeProfileData)`:
- Cross-references `volume_profile` with `oi_change` per strike.
- Displays Top 5 Accumulating strikes with green badge `🟢 ACCUMULATION` and Top 5 De-risking strikes with red badge `🔴 LIQUIDATION`.
- Updates `#flow-quadrant-badge` with dominant regime.

**Step 3: Verification**

- Run: `python update_dashboard.py`
- Open `docs/index.html` in browser.
- Verify that table displays real accumulated strikes with clear institutional interpretation.

---

### Task 6: Web UI Card: Charm Exposure & Overnight Hedging Gauge

**Files:**
- Modify: `docs/index.html:425-435`
- Modify: `docs/app.js:1070-1145`

**Step 1: Add Charm Chart Card in `docs/index.html`**

Update the Vanna / Charm section to split side-by-side or add Charm card:
```html
<div class="card" id="card-charm">
  <div class="card-header">
    <span class="card-title">Charm Flow (Time Decay Exposure)</span>
    <span class="card-badge" id="charm-flow-badge">DECAY FLOW</span>
  </div>
  <div class="card-body">
    <div class="metric-row">
      <span class="metric-label">Overnight Dealer Re-hedge:</span>
      <span class="metric-value text-accent" id="metric-charm-flow">$0.0M</span>
    </div>
    <div class="chart-container" id="chart-charm"></div>
  </div>
</div>
```

**Step 2: Add Render Logic in `docs/app.js`**

Implement `renderCharmChart(charmData, data)`:
- ApexCharts bar chart colored in cyan/teal `#00E5FF`.
- Labels positive Charm bars as dealer buying on decay and negative as dealer selling.
- Updates `#metric-charm-flow` with dollar value.

---

### Task 7: Web UI Stress Test Update: IV Crush / Vanna Rally Simulator

**Files:**
- Modify: `docs/index.html:365-388`
- Modify: `docs/app.js:1600-1680`

**Step 1: Add Event IV Shock Sub-table in `docs/index.html`**

Beneath the spot shock table, add:
```html
<div class="stress-vanna-container mt-2">
  <div class="card-subheading">⚡ Event IV Shock Stress Test (Vanna Rally Predictor)</div>
  <table class="data-table" id="table-vanna-stress">
    <thead>
      <tr>
        <th>IV Shock</th>
        <th>Implied Condition</th>
        <th>Dealer Hedge Demand ($)</th>
        <th>Dealer Contracts</th>
        <th>Predicted Flow</th>
      </tr>
    </thead>
    <tbody id="vanna-stress-tbody">
      <tr><td colspan="5" class="text-center">Loading IV shock grid...</td></tr>
    </tbody>
  </table>
</div>
```

**Step 2: Add Render Logic in `docs/app.js`**

Populate rows from `data.scenarios.vanna_rally_scenarios`. Highlight the `-5.0%` row (typical post-CPI/FOMC IV crush) in lime green if Dealer is forced to buy.

---

## Phase 3: Advanced Models (Probability & Multi-Expiry Roll)

### Task 8: Delta-Weighted Strike Pinning Probability Distribution Model

**Files:**
- Modify: `analytics/pin_risk.py`
- Test: `tests/test_pin_distribution.py`

**Step 1: Write the failing test**

Create `tests/test_pin_distribution.py`:
```python
import unittest
from analytics.pin_risk import calc_pinning_probability_distribution

class TestPinDistribution(unittest.TestCase):
    def test_pin_distribution_probabilities(self):
        rows = [
            {'Strike': 2380.0, 'Type': 'C', 'Open_Interest': 100, 'IV': 0.18},
            {'Strike': 2400.0, 'Type': 'C', 'Open_Interest': 1500, 'IV': 0.18},
            {'Strike': 2400.0, 'Type': 'P', 'Open_Interest': 1200, 'IV': 0.18},
            {'Strike': 2420.0, 'Type': 'P', 'Open_Interest': 200, 'IV': 0.18},
        ]
        res = calc_pinning_probability_distribution(rows, spot=2395.0, dte=1.0)
        self.assertIn('pin_probabilities', res)
        self.assertIn('most_likely_pin_strike', res)
        self.assertEqual(res['most_likely_pin_strike'], 2400.0)

        # Sum of probabilities across strikes should equal 1.0 (100%)
        total_p = sum(p['probability'] for p in res['pin_probabilities'])
        self.assertAlmostEqual(total_p, 1.0, places=2)

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Implement minimal code in `analytics/pin_risk.py`**

Formula:
$$W(K) = (\text{Call\_OI}_K + \text{Put\_OI}_K) \times \Gamma_K \times \exp\left(-\frac{(K - F)^2}{2 (F \sigma \sqrt{T})^2}\right)$$
Normalize:
$$P(\text{Pin}_K) = \frac{W(K)}{\sum_j W(K_j)}$$

Export `most_likely_pin_strike`, `top_3_pin_strikes`, and `pin_probabilities`.

---

### Task 9: Multi-Expiry Roll Activity Detector (Front-Month vs Back-Month)

**Files:**
- Modify: `adapters/base.py` & `adapters/tastytrade_adapter.py` / `adapters/databento_adapter.py`
- Modify: `Analysis_Tools/master_report.py`
- Modify: `update_dashboard.py`
- Test: `tests/test_roll_detector.py`

**Step 1: Write the failing test**

Create `tests/test_roll_detector.py`:
```python
import unittest
from analytics.order_flow import detect_calendar_roll_activity

class TestRollDetector(unittest.TestCase):
    def test_calendar_roll_detection(self):
        # Front month losing 500 contracts, Back month gaining 480 contracts at 2400 strike
        front_changes = {2400.0: -500, 2450.0: -50}
        back_changes = {2400.0: +480, 2450.0: +20}

        rolls = detect_calendar_roll_activity(front_changes, back_changes, min_roll_contracts=100)
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0]['strike'], 2400.0)
        self.assertEqual(rolls[0]['roll_status'], 'ACTIVE_CALENDAR_ROLL')

if __name__ == '__main__':
    unittest.main()
```

**Step 2: Implement minimal code in `analytics/order_flow.py`**

Detect when front month experiences large negative $\Delta\text{OI}$ and back month experiences positive $\Delta\text{OI}$ at identical or adjacent strikes.

---

## Verification & Execution Checklists

### Comprehensive Test Suite Run:
```bash
python -m unittest discover tests
```
*Verification criteria:* All existing 13 tests plus all newly introduced tests pass with 0 errors.

### Dashboard Generation Verification:
```bash
python update_dashboard.py
```
*Verification criteria:* Output JSON files in `docs/data/*/*/*_data.json` contain the new `charm`, `flow_quadrant`, `vanna_rally_scenarios`, and `pin_distribution` fields without syntax or schema errors.
