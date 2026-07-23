import time

rows = []
for s in range(1000, 5000, 1):
    rows.append({'Strike': s, 'Type': 'Call', 'Volume': 20, 'OI': 10})
    rows.append({'Strike': s, 'Type': 'Put', 'Volume': 20, 'OI': 10})

def original_method():
    profile = []
    all_strikes = sorted(set(r['Strike'] for r in rows))
    for s in all_strikes:
        c_v = sum(r['Volume'] for r in rows if r['Strike'] == s and r['Type'] in ['Call', 'C'])
        p_v = sum(r['Volume'] for r in rows if r['Strike'] == s and r['Type'] in ['Put', 'P'])
        if c_v > 0 or p_v > 0:
            profile.append({"strike": float(s), "call_vol": float(c_v), "put_vol": float(p_v)})
    return profile

def optimized_method():
    # Aggregate volume once per strike to avoid rescanning every option row for each output strike.
    call_vol = {}
    put_vol = {}
    for r in rows:
        s = r['Strike']
        v = r['Volume']
        if r['Type'] in ['Call', 'C']:
            call_vol[s] = call_vol.get(s, 0) + v
        else:
            put_vol[s] = put_vol.get(s, 0) + v

    profile = []
    all_strikes = sorted(set(list(call_vol.keys()) + list(put_vol.keys())))
    for s in all_strikes:
        c_v = call_vol.get(s, 0)
        p_v = put_vol.get(s, 0)
        if c_v > 0 or p_v > 0:
            profile.append({"strike": float(s), "call_vol": float(c_v), "put_vol": float(p_v)})
    return profile

start = time.perf_counter()
res1 = original_method()
t1 = time.perf_counter() - start

start = time.perf_counter()
res2 = optimized_method()
t2 = time.perf_counter() - start

print(f"Original: {t1:.4f}s")
print(f"Optimized: {t2:.4f}s")
print(f"Results match: {res1 == res2}")
