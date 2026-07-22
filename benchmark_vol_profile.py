import time
from update_dashboard import parse_option_data_csv
import random
import os

def create_dummy_csv():
    with open("dummy_data.csv", "w") as f:
        f.write("Strike,Type,OI,Volume,GEX,Vanna,DEX,Charm,IV\n")
        strikes = list(range(1000, 5000, 1))
        for s in strikes:
            f.write(f"{s},Call,10,20,0.1,0.2,0.3,0.4,0.5\n")
            f.write(f"{s},Put,10,20,0.1,0.2,0.3,0.4,0.5\n")

create_dummy_csv()

def run_benchmark():
    start = time.perf_counter()
    parse_option_data_csv("dummy_data.csv")
    return time.perf_counter() - start

# Warmup
run_benchmark()

times = [run_benchmark() for _ in range(5)]
print(f"Median time: {sorted(times)[len(times)//2]:.4f} seconds")
