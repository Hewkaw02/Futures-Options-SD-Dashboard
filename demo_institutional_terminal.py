"""
demo_institutional_terminal.py — Institutional Options Microstructure Showcase
Runs and displays all 4 pillars from the quantitative desk article:
1. GEX & Asymmetric Dealer Positioning (Flip Point & Market Regime)
2. Vanna Rally Predictor & Event IV Shock Grid (FOMC/CPI IV Crush)
3. Charm Exposure & Overnight Hedging Flow (Time Decay Clock)
4. 4-Quadrant Volume vs ΔOI Matrix (Accumulation vs Liquidation vs Day Trading)
5. Delta-Weighted Strike Pinning Probability Distribution
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = Path("docs/data/2026-06-24/0200")
ASSETS = [("GC", "Gold Futures (/GC)"), ("ES", "S&P 500 E-mini (/ES)"), ("NQ", "NASDAQ 100 E-mini (/NQ)")]

def format_compact(val):
    if abs(val) >= 1e9: return f"${val/1e9:.2f}B"
    if abs(val) >= 1e6: return f"${val/1e6:.2f}M"
    if abs(val) >= 1e3: return f"${val/1e3:.1f}K"
    return f"${val:.1f}"

def run_demo():
    print("\n" + "=" * 115)
    print(f"{'INSTITUTIONAL OPTIONS QUANT DESK — LIVE MICROSTRUCTURE TERMINAL':^115}")
    print(f"{'Snapshot: 2026-06-24 02:00 UTC | Model: Asymmetric Black-76 GEX & Flow Decomposition':^115}")
    print("=" * 115)

    for symbol, title in ASSETS:
        file_path = DATA_DIR / f"{symbol}_data.json"
        if not file_path.exists():
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        bias = data.get("bias", {})
        price = bias.get("price", 0.0)
        gex_prof = data.get("gex_profile", {})
        flip = gex_prof.get("flip_price", "N/A")
        vanna_scen = data.get("scenarios", {}).get("vanna_rally_scenarios", [])
        charm = data.get("charm", {})
        flow = data.get("flow_decomposition", {})
        pin = data.get("pin_risk", {})

        print(f"\n┌─ [ {title.upper()} ] ────────────────────────────────────────────────────────────────────────")
        print(f"│ Spot Price: {price:,.2f} | Bias: {bias.get('label', '—')} (Conf: {bias.get('confidence', '—')}) | ATM IV: {bias.get('iv', '—')}")
        print(f"│ 1. GEX & REGIME: {bias.get('gex', '—')} | Gamma Flip Point: {flip} | Asymmetric Dealer Positioning Active")
        
        # 2. Vanna Rally
        print("│")
        print("│ 2. ⚡ EVENT IV SHOCK STRESS TEST (VANNA RALLY PREDICTOR):")
        if vanna_scen:
            for s in vanna_scen:
                shift = f"{s['iv_shift_pct']:+.1f}% IV"
                usd = format_compact(s['dealer_rebalance_usd'])
                contracts = f"{s['dealer_rebalance_contracts']:+,.1f} contracts"
                action = s['vanna_rally_direction']
                highlight = "🔥 [RALLY TRIGGER]" if s['iv_shift_pct'] == -5.0 and s['dealer_rebalance_usd'] > 0 else ""
                print(f"│    • {shift:<10} ➔ Dealer Re-hedge: {usd:<10} ({contracts:<18}) ➔ Action: {action} {highlight}")
        else:
            print("│    • No IV shock scenarios recorded.")

        # 3. Charm Flow
        print("│")
        print("│ 3. ⏳ CHARM EXPOSURE & OVERNIGHT TIME DECAY FLOW:")
        if charm:
            total_flow = charm.get("total_overnight_flow_usd", 0.0)
            bias_charm = charm.get("bias", "NEUTRAL")
            print(f"│    • Total Overnight Dealer Flow: {format_compact(total_flow)} ({bias_charm})")
            print(f"│    • Net dealer futures buying/selling required by market open due to Delta decay (Charm).")
        else:
            print("│    • No charm data.")

        # 4. 4-Quadrant Flow Matrix
        print("│")
        print("│ 4. 🔍 4-QUADRANT FLOW DECOMPOSITION (VOLUME vs ΔOI):")
        if flow:
            print(f"│    • Dominant Regime: {flow.get('dominant_regime', '—')} | {flow.get('summary', '')}")
            acc = flow.get("accumulation_strikes", [])[:3]
            liq = flow.get("liquidation_strikes", [])[:2]
            day = flow.get("day_trading_strikes", [])[:2]
            if acc:
                print("│      🟢 ACCUMULATION (สถาบันเปิดสถานะสะสมของจริง):")
                for item in acc:
                    print(f"│         Strike {item['strike']:,.1f} {item['type']:<4} | Vol: {int(item['volume']):<6} | ΔOI: +{int(item['delta_oi']):<6} ➔ {item['badge']}")
            if liq:
                print("│      🔴 LIQUIDATION (การปิดสัญญา / ลดความเสี่ยง):")
                for item in liq:
                    print(f"│         Strike {item['strike']:,.1f} {item['type']:<4} | Vol: {int(item['volume']):<6} | ΔOI: {int(item['delta_oi']):<6} ➔ {item['badge']}")
            if day:
                print("│      ⚪ DAY TRADING (หมุนรอบเก็งกำไรในวัน):")
                for item in day:
                    print(f"│         Strike {item['strike']:,.1f} {item['type']:<4} | Vol: {int(item['volume']):<6} | ΔOI: {int(item['delta_oi']):<6} ➔ {item['badge']}")
        else:
            print("│    • No flow decomposition available.")

        # 5. Delta-Weighted Pinning
        print("│")
        print("│ 5. 🧲 DELTA & GAMMA-WEIGHTED STRIKE PINNING ODDS:")
        if pin and pin.get("top_3_pin_strikes"):
            top_strikes = pin.get("top_3_pin_strikes", [])
            print(f"│    • Most Likely Expiry Pin Target: Strike {pin.get('most_likely_pin_strike', 0):,.1f}")
            for rank, t in enumerate(top_strikes, 1):
                bar = "█" * int(t['probability_pct'] / 3)
                print(f"│      #{rank} Strike {t['strike']:,.1f} ➔ Probability: {t['probability_pct']:.1f}%  {bar}")
        else:
            print(f"│    • Pin Score: {pin.get('pin_score', 0):.1f}/100 | Zone: {pin.get('pinning_zone', [])}")

        print("└" + "─" * 90)

    print("\n" + "=" * 115)

if __name__ == "__main__":
    run_demo()
