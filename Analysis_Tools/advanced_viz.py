import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import date, datetime
from pathlib import Path
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import get_future_option_chain
from tastytrade.dxfeed import Summary, Greeks, Trade
import math
import yfinance as yf
from matplotlib.patches import Ellipse

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN, CONTRACT_MULTIPLIERS

from analytics.exposure import black76_greeks, calculate_dealer_exposures

def get_yf_price(symbol_root):
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
    """Calculate 1 Standard Deviation move."""
    return price * iv * math.sqrt(dte / 365)

async def analyze_advanced_exposure(session, symbol, title, output_base):
    print(f"Generating Focused Dashboard for {title}...")
    try:
        chain = await get_future_option_chain(session, symbol)
        today = date.today()
        expiry_dates = sorted([d for d in chain.keys() if d >= today])
        if not expiry_dates: return
        expiry = expiry_dates[0]
        is_0dte = (expiry == today)
        
        options = chain[expiry]
        mark = get_yf_price(symbol)
        if not mark:
            mark = infer_mark_price(chain, expiry)
        
        # 1. ATM IV for Auto-Range
        atm_opt = min(options, key=lambda o: abs(float(o.strike_price) - mark))
        
        summary_cache = {}
        greek_cache = {}

        # Initial quick sub for ATM IV to determine range
        async with DXLinkStreamer(session) as streamer:
            await streamer.subscribe(Greeks, [atm_opt.streamer_symbol])
            try:
                g_atm = await asyncio.wait_for(streamer.get_event(Greeks), timeout=5.0)
                atm_iv = float(g_atm.volatility or 0.2) # Fallback to 20%
            except (asyncio.TimeoutError, Exception):
                atm_iv = 0.2
            
            # 2. Dynamic Focus Range (2.5 Standard Deviations)
            sd1 = calc_sd(mark, atm_iv)
            range_width = sd1 * 2.5
            limit_min, limit_max = mark - range_width, mark + range_width
            
            relevant_options = [o for o in options if limit_min <= float(o.strike_price) <= limit_max]
            # Ensure we don't have too few strikes (min 40)
            if len(relevant_options) < 40:
                relevant_options = sorted(options, key=lambda o: abs(float(o.strike_price) - mark))[:60]
            
            symbols = [o.streamer_symbol for o in relevant_options]
            print(f"  Auto-Range: {limit_min:,.0f} - {limit_max:,.0f} ({len(relevant_options)} strikes)")

            trade_cache = {}

            await streamer.subscribe(Summary, symbols)
            await streamer.subscribe(Greeks, symbols)
            await streamer.subscribe(Trade, symbols)
            
            end_time = asyncio.get_event_loop().time() + 12
            while asyncio.get_event_loop().time() < end_time:
                try:
                    # Use sequence pattern for stability
                    try:
                        s = await asyncio.wait_for(streamer.get_event(Summary), timeout=0.2)
                        summary_cache[s.event_symbol] = s
                    except (asyncio.TimeoutError, Exception):
                        pass
                    try:
                        g = await asyncio.wait_for(streamer.get_event(Greeks), timeout=0.2)
                        greek_cache[g.event_symbol] = g
                    except (asyncio.TimeoutError, Exception):
                        pass
                    try:
                        t = await asyncio.wait_for(streamer.get_event(Trade), timeout=0.2)
                        trade_cache[t.event_symbol] = t
                    except (asyncio.TimeoutError, Exception):
                        pass
                except Exception:
                    pass

        # Process Data
        records = []
        dte_days = max(1.0, float((expiry - today).days))
        T_years = dte_days / 365.0
        
        for o in relevant_options:
            s = summary_cache.get(o.streamer_symbol)
            g = greek_cache.get(o.streamer_symbol)
            t = trade_cache.get(o.streamer_symbol)
            if s and g:
                oi = float(s.open_interest or 0)
                vol = float(t.day_volume or 0) if t else 0.0
                opt_iv = float(g.volatility or 0.2)
                
                product_code = symbol.lstrip('/')
                multiplier = CONTRACT_MULTIPLIERS.get(product_code, 1)
                
                # Exact Black-76 Greeks & Exposures
                greeks = black76_greeks(F=mark, K=float(o.strike_price), T=T_years, sigma=opt_iv, option_type=o.option_type.value)
                exposures = calculate_dealer_exposures(
                    oi=oi,
                    delta=greeks["delta"],
                    gamma=greeks["gamma"],
                    vega=greeks["vega"],
                    vanna=greeks["vanna"],
                    charm=greeks["charm"],
                    spot=mark,
                    multiplier=multiplier,
                    option_type=o.option_type.value,
                    dealer_assumed_side="short"
                )
                
                records.append({
                    'Strike': float(o.strike_price),
                    'Type': o.option_type.value,
                    'GEX': exposures["gex"],
                    'VannaExp': exposures["vanna_exp"],
                    'DEX': exposures["dex"],
                    'Charm': exposures["charm_exp"],
                    'Vol': vol,
                    'OI': oi
                })

        df = pd.DataFrame(records)
        if df.empty: 
            print(f"  ⚠ No data captured for {title}")
            return

        df_profile = df.groupby('Strike').agg({
            'GEX': 'sum', 'VannaExp': 'sum', 'DEX': 'sum', 'Charm': 'sum', 'Vol': 'sum', 'OI': 'sum'
        }).sort_index()
        
        # 1. Gamma Flip
        flip_price = None
        for i in range(len(df_profile)-1):
            if df_profile['GEX'].iloc[i] * df_profile['GEX'].iloc[i+1] <= 0:
                flip_price = df_profile.index[i]
                break
        
        # 2. Iron Walls (Confluence)
        max_oi_strike = df_profile['OI'].idxmax()
        max_vol_strike = df_profile['Vol'].idxmax()
        iron_wall = max_oi_strike if abs(max_oi_strike - max_vol_strike) / mark < 0.005 else None

        # 3. Market Regime
        regime = "RANGE BOUND (Mean Reversion)" if (flip_price and mark > flip_price) else "TRENDING (High Momentum)"
        vol_trigger = "STABLE / MUZZLED" if (df_profile['GEX'].sum() > 0) else "EXPLOSIVE / ACCELERATING"
        
        # Dealer Positioning
        total_dex = df_profile['DEX'].sum()
        dealer_pos = "LONG DELTA (Suppressing)" if total_dex > 0 else "SHORT DELTA (Amplifying)"
        
        # ─── Plotting ──────────────────────────────────────────
        now = datetime.now()
        date_str, hour_str, ts = now.strftime("%Y-%m-%d"), now.strftime("%H00"), now.strftime("%H%M")
        asset_dir = output_base / date_str / hour_str / symbol.replace('/', '')
        asset_dir.mkdir(parents=True, exist_ok=True)

        fig, (ax1, ax2, ax4) = plt.subplots(3, 1, figsize=(12, 18), sharex=True, gridspec_kw={'height_ratios': [1.5, 1, 0.8]})
        plt.subplots_adjust(hspace=0.3)

        # 1. GEX Profile
        ax1.plot(df_profile.index, df_profile['GEX'], color='blue', lw=2.5, label='Total Gamma Exposure', zorder=3)
        ax1.fill_between(df_profile.index, df_profile['GEX'], 0, where=(df_profile['GEX'] >= 0), color='green', alpha=0.25)
        ax1.fill_between(df_profile.index, df_profile['GEX'], 0, where=(df_profile['GEX'] < 0), color='red', alpha=0.25)
        ax1.axvline(mark, color='black', ls='--', lw=2, label=f'Spot: {mark:,.2f}', zorder=4)
        if flip_price:
            ax1.axvline(flip_price, color='darkorange', ls=':', lw=2.5, label=f'Gamma Flip: {flip_price:,.0f}')
        
        if iron_wall:
            # Draw Stylized Ellipse around IRON WALL
            gex_val = df_profile.loc[iron_wall, 'GEX']
            x_range = df_profile.index.max() - df_profile.index.min()
            y_range = df_profile['GEX'].max() - df_profile['GEX'].min()
            
            ellipse = Ellipse(xy=(iron_wall, gex_val), width=x_range*0.06, height=y_range*0.15,
                              edgecolor='red', fc='none', lw=2, ls='-', alpha=0.8, zorder=5)
            ax1.add_patch(ellipse)
            
            for i in range(1, 4):
                glow = Ellipse(xy=(iron_wall, gex_val), width=x_range*0.06 + i*x_range*0.01, 
                               height=y_range*0.15 + i*y_range*0.02,
                               edgecolor='red', fc='none', lw=1, alpha=0.2 - i*0.05, zorder=4)
                ax1.add_patch(glow)

            ax1.annotate('IRON WALL', xy=(iron_wall, gex_val), xytext=(0, 35), 
                         textcoords='offset points', ha='center', fontweight='bold', color='darkred',
                         fontsize=10, arrowprops=dict(arrowstyle='->', color='black'))

        # Dashboard Text
        summary_text = (
            f"MARKET REGIME : {regime}\n"
            f"DEALER POS    : {dealer_pos}\n"
            f"VOL TRIGGER   : {vol_trigger}\n"
            f"EXPIRATION    : {expiry} ({'0DTE' if is_0dte else 'Standard'})\n"
            f"NET DELTA     : ${total_dex/1e6:.1f}M\n"
            f"GEX TOTAL     : ${df_profile['GEX'].sum()/1e6:.1f}M / 1% move"
        )
        ax1.text(0.02, 0.96, summary_text, transform=ax1.transAxes, fontsize=10, verticalalignment='top',
                 fontfamily='monospace', fontweight='bold', bbox=dict(facecolor='white', alpha=0.9, edgecolor='gray', pad=10))

        ax1.set_title(f"Institutional Market Map - {title} | {ts}", fontsize=16, fontweight='bold', pad=20)
        ax1.set_ylabel("Dealer Gamma Sensitivity ($)", fontsize=12)
        ax1.grid(alpha=0.2)
        ax1.legend(loc='upper right')

        # 2. Vanna & Volume
        ax2.bar(df_profile.index, df_profile['VannaExp'], width=(df_profile.index[1]-df_profile.index[0])*0.7 if len(df_profile)>1 else 5, 
                color='purple', alpha=0.5, label='Vanna (IV Risk)')
        ax2.axvline(mark, color='black', ls='--')
        
        ax3 = ax2.twinx()
        ax3.step(df_profile.index, df_profile['Vol'], where='mid', color='gray', alpha=0.3, label='Intraday Vol')
        ax3.set_ylabel("Volume (Contracts)", color='gray')
        
        ax2.set_title("Vanna Flow & Liquidity Squeeze Zones", fontsize=14, fontweight='bold')
        ax2.set_ylabel("Vanna Exposure", fontsize=12)
        ax2.grid(alpha=0.2)
        
        # 3. Charm Flow (Time Decay Risk)
        ax4.bar(df_profile.index, df_profile['Charm'], width=(df_profile.index[1]-df_profile.index[0])*0.7 if len(df_profile)>1 else 5, 
                color='teal', alpha=0.5, label='Charm (Time Decay Risk)')
        ax4.axvline(mark, color='black', ls='--')
        ax4.set_title("Charm Flow (Dealer Hedging Pressure over Time)", fontsize=14, fontweight='bold')
        ax4.set_xlabel("Strike Price", fontsize=12)
        ax4.set_ylabel("Charm Exp", fontsize=12)
        ax4.grid(alpha=0.2)

        save_path = asset_dir / f"{symbol.replace('/', '').lower()}_institutional_dashboard_{ts}.png"
        plt.savefig(save_path, bbox_inches='tight', dpi=120)
        plt.close()
        print(f"✓ Dashboard saved to {save_path}")

    except Exception as e:
        print(f"  ✗ Dashboard Error: {e}")

async def main():
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    output_base = Path("trading_results")
    assets = [('/GC', 'Gold'), ('/ES', 'S&P 500'), ('/NQ', 'NASDAQ')]
    for symbol, title in assets:
        await analyze_advanced_exposure(session, symbol, title, output_base)

if __name__ == "__main__":
    asyncio.run(main())
