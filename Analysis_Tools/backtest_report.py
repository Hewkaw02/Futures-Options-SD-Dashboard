import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import yfinance as yf
from analytics.backtest import load_historical_signals, evaluate_signal_performance

def main():
    print("=" * 60)
    print("  QUANT SIGNAL BACKTESTING ENGINE & SCORECARD")
    print("=" * 60)
    
    signals_df = load_historical_signals('trading_results')
    if signals_df.empty:
        print("[WARN] No historical bias signals found in trading_results/.")
        return
        
    print(f"Loaded {len(signals_df)} historical signal records.")
    
    # Fetch historical candles for GC, ES, NQ
    candles = {}
    for asset, yf_sym in [('GC', 'GC=F'), ('ES', 'ES=F'), ('NQ', 'NQ=F')]:
        try:
            df = yf.download(yf_sym, period='3mo', interval='1h', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            candles[asset] = df
        except Exception as e:
            print(f"Failed downloading {yf_sym}: {e}")
            
    perf = evaluate_signal_performance(signals_df, candles, horizons_hours=[1, 3, 6, 24])
    
    print("\n" + "-" * 40)
    print("  OVERALL PERFORMANCE SUMMARY")
    print("-" * 40)
    print(f"  Total Signals Evaluated: {perf.get('evaluated_signals', 0)} / {perf.get('total_signals', 0)}")
    print(f"  Overall Directional Accuracy (3H): {perf.get('overall_accuracy_pct', 0.0)}%")
    print(f"  Bullish Signals Win Rate:          {perf.get('bull_accuracy_pct', 0.0)}%")
    print(f"  Bearish Signals Win Rate:          {perf.get('bear_accuracy_pct', 0.0)}%")
    print(f"  Strategy Profit Factor:            {perf.get('profit_factor', 0.0)}")
    print(f"  Annualized Sharpe Ratio:           {perf.get('sharpe_ratio', 0.0)}")
    print("-" * 40)

if __name__ == '__main__':
    main()
