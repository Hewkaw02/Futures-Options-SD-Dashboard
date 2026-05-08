import yfinance as yf
assets = {'Gold': 'GC=F', 'ES': 'ES=F', 'NQ': 'NQ=F'}
for name, sym in assets.items():
    try:
        data = yf.Ticker(sym).history(period='1d')
        if not data.empty:
            print(f"{name} ({sym}) Real Price: {data['Close'].iloc[-1]:.2f}")
        else:
            print(f"{name} ({sym}) No data found.")
    except Exception as e:
        print(f"Error fetching {name}: {e}")
