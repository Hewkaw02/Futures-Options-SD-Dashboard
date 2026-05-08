import asyncio
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain, Future
from tastytrade.dxfeed import Summary, Greeks, Trade
import math
import yfinance as yf

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN, CONTRACT_MULTIPLIERS

# --- Helper Functions -----------------------------------------
def get_yf_price(symbol_root):
    """Fetch current price from yfinance."""
    mapping = {'/GC': 'GC=F', '/ES': 'ES=F', '/NQ': 'NQ=F'}
    yf_sym = mapping.get(symbol_root)
    if not yf_sym: return None
    try:
        data = yf.Ticker(yf_sym).history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception:
        pass
    return None

def infer_mark_price(chain, expiry):
    options = chain[expiry]
    strikes = sorted([float(o.strike_price) for o in options])
    return strikes[len(strikes) // 2] if strikes else 0

def calc_sd(price, iv, dte=1.0):
    # Standardize to 365 calendar days — CME futures trade ~23hrs/day
    sd1 = price * iv * math.sqrt(dte / 365)
    return sd1

def get_bias(price, call_wall, put_wall, pcr_oi, pcr_vol, gex_sum, skew):
    score = 0
    # Price vs Walls
    if put_wall > 0 and price > put_wall: score += 1
    if call_wall > 0 and price < call_wall: score -= 1
    # PCR Sentiment
    if pcr_oi < 0.8: score += 1
    elif pcr_oi > 1.2: score -= 1
    # GEX Sentiment
    if gex_sum > 0: score += 1
    else: score -= 1
    # Skew Sentiment
    if skew > 0.05: score -= 1
    elif skew < -0.05: score += 1

    conf = min(abs(score) * 20, 100) # Confidence %
    
    label = "NEUTRAL"
    if score >= 3: label = "Strong BULL"
    elif score >= 1: label = "Mild BULL"
    elif score <= -3: label = "Strong BEAR"
    elif score <= -1: label = "Mild BEAR"
    
    return label, f"{conf}%"

async def analyze_asset(session, symbol, title):
    print(f"Analyzing {title} ({symbol})...")
    try:
        chain = await get_future_option_chain(session, symbol)
        today = date.today()
        expiry_dates = sorted([d for d in chain.keys() if d >= today])
        if not expiry_dates: return None
        expiry = expiry_dates[0]
        
        options = chain[expiry]
        
        # 1. Price Detection (yfinance primary, chain inference fallback)
        mark = get_yf_price(symbol)
        if not mark:
            print(f"  [INFO] Using option chain inference for {title}")
            mark = infer_mark_price(chain, expiry)
        
        sorted_options = sorted(options, key=lambda o: abs(float(o.strike_price) - mark))
        relevant_options = sorted_options[:50] # Compact range for stability
        greek_subset = sorted_options[:10]
        
        call_skew_opt = min([o for o in options if o.option_type.value == 'C'], key=lambda o: abs(float(o.strike_price) - mark * 1.02))
        put_skew_opt = min([o for o in options if o.option_type.value == 'P'], key=lambda o: abs(float(o.strike_price) - mark * 0.98))
        
        target_greeks = list(set([o.streamer_symbol for o in greek_subset] + [call_skew_opt.streamer_symbol, put_skew_opt.streamer_symbol]))
        target_summaries = [o.streamer_symbol for o in relevant_options]
        
        greek_cache = {}
        summary_cache = {}
        trade_cache = {}
        
        try:
            async with DXLinkStreamer(session) as streamer:
                await streamer.subscribe(Greeks, target_greeks)
                await streamer.subscribe(Summary, target_summaries)
                await streamer.subscribe(Trade, target_summaries)
                
                # Use the pattern that worked in organized_analysis.py
                end_time = asyncio.get_event_loop().time() + 10
                while asyncio.get_event_loop().time() < end_time:
                    try:
                        # Try to get a Summary event
                        s_event = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.2)
                        summary_cache[s_event.event_symbol] = s_event
                    except (asyncio.TimeoutError, Exception):
                        pass
                    
                    try:
                        # Try to get a Greeks event
                        g_event = await asyncio.wait_for(streamer.get_event(Greeks), timeout=0.2)
                        greek_cache[g_event.event_symbol] = g_event
                    except (asyncio.TimeoutError, Exception):
                        pass

                    try:
                        # Try to get a Trade event
                        t_event = await asyncio.wait_for(streamer.get_event(Trade), timeout=0.2)
                        trade_cache[t_event.event_symbol] = t_event
                    except (asyncio.TimeoutError, Exception):
                        pass
        except Exception as e:
            print(f"  [WARN] Streamer error for {title}: {e}")

        if not summary_cache:
            print(f"  [WARN] No data captured for {title}")
            return None

        # 3. Calculations
        records = []
        gex_total = 0
        for o in relevant_options:
            s = summary_cache.get(o.streamer_symbol)
            t = trade_cache.get(o.streamer_symbol)
            if s:
                oi = float(s.open_interest or 0)
                vol = float(t.day_volume or 0) if t else 0.0
                records.append({'Type': o.option_type.value, 'OI': oi, 'Vol': vol, 'Strike': float(o.strike_price)})
                if o.streamer_symbol in greek_cache:
                    g = greek_cache[o.streamer_symbol]
                    product_code = symbol.lstrip('/')
                    multiplier = CONTRACT_MULTIPLIERS.get(product_code, 1)
                    direction = 1 if o.option_type.value == 'C' else -1
                    gex_total += oi * float(g.gamma or 0) * direction * multiplier

        df = pd.DataFrame(records)
        c_oi = df[df['Type'] == 'C']['OI'].sum()
        p_oi = df[df['Type'] == 'P']['OI'].sum()
        pcr_oi = p_oi / c_oi if c_oi > 0 else 0
        
        c_vol = df[df['Type'] == 'C']['Vol'].sum()
        p_vol = df[df['Type'] == 'P']['Vol'].sum()
        pcr_vol = p_vol / c_vol if c_vol > 0 else 0
        
        total_oi = df['OI'].sum()
        total_vol = df['Vol'].sum()
        activity = (total_vol / total_oi * 100) if total_oi > 0 else 0
        
        call_wall = df[df['Type'] == 'C'].sort_values('OI', ascending=False).iloc[0]['Strike'] if not df[df['Type'] == 'C'].empty else 0
        put_wall = df[df['Type'] == 'P'].sort_values('OI', ascending=False).iloc[0]['Strike'] if not df[df['Type'] == 'P'].empty else 0
        
        # Skew
        iv_p = float(greek_cache[put_skew_opt.streamer_symbol].volatility or 0) if put_skew_opt.streamer_symbol in greek_cache else 0
        iv_c = float(greek_cache[call_skew_opt.streamer_symbol].volatility or 0) if call_skew_opt.streamer_symbol in greek_cache else 0
        skew = iv_p - iv_c

        # Calculate atm_iv from the minimum of all captured Greeks
        iv_values = [float(g.volatility) for g in greek_cache.values() if g.volatility and float(g.volatility) > 0]
        atm_iv = min(iv_values) if iv_values else 0.0
        
        bias_label, conf_str = get_bias(mark, call_wall, put_wall, pcr_oi, pcr_vol, gex_total, skew)

        return {
            'Asset': title, 'Price': round(mark, 2),
            'Bias': bias_label, 'Conf%': conf_str,
            'IV%': f"{atm_iv*100:.1f}%",
            'PCR(V)': round(pcr_vol, 2),
            'Skew%': f"{skew*100:+.1f}%",
            'Act%': f"{activity:.1f}%",
            'GEX': "STABLE" if gex_total > 0 else "VOLTL",
            'Wall(R/S)': f"{call_wall}/{put_wall}"
        }
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return None

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    assets_config = [
        ('/GC', 'Gold'),
        ('/ES', 'S&P 500'),
        ('/NQ', 'NASDAQ')
    ]
    
    results = []
    for symbol, title in assets_config:
        res = await analyze_asset(session, symbol, title)
        if res:
            results.append(res)

    # 4. Final Report Preparation
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%H00")
    timestamp = now.strftime("%H%M")
    
    report_header = "="*110 + "\n"
    report_header += f"{'MASTER TRADING BIAS REPORT (ADVANCED v3.5)':^110}\n"
    report_header += f"{'Date: ' + date_str + ' | Time: ' + timestamp:^110}\n"
    report_header += "="*110 + "\n"
    
    df_report = pd.DataFrame(results)
    
    # 5. Output to Console
    print("\n" + report_header)
    if not df_report.empty:
        print(df_report.to_string(index=False))
    else:
        print("No data processed.")
    print("="*110)
    
    # 6. Save to Hourly Folder Structure
    output_base = Path("trading_results") / date_str / hour_str
    output_base.mkdir(parents=True, exist_ok=True)
    
    if not df_report.empty:
        # Save CSV
        csv_path = output_base / f"master_bias_report_{timestamp}.csv"
        df_report.to_csv(csv_path, index=False)
        
        # Save Text Report
        txt_path = output_base / f"master_bias_report_{timestamp}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report_header)
            f.write(df_report.to_string(index=False))
            f.write("\n" + "="*110 + "\n")
            f.write("Definitions:\n")
            f.write("- Conf%: Signal alignment strength\n")
            f.write("- Act%: Volume/OI Ratio (Participation)\n")
            f.write("- GEX: Market Stability Regime\n")
            f.write("="*110 + "\n")
            
        print(f"\n[OK] Master Report saved to: {output_base}")
    else:
        print("\n[WARN] Skipping file save due to empty report.")

if __name__ == "__main__":
    asyncio.run(main())
