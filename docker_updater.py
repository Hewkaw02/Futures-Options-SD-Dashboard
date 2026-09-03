"""
Background Dual-Speed Auto-Updater Daemon for Futures Options SD Dashboard
1. High-frequency (every 5s): Runs live_feed.py to fetch real-time CME futures quotes,
   tick intraday candles, and refresh docs/data/live/{ASSET}_data.json.
2. Low-frequency (every 300s): Runs update_dashboard.py to process new historical snapshots,
   recompute Greeks/Flow matrices, and update docs/data/manifest.json.
"""

import os
import sys
import time
import signal
import subprocess
from datetime import datetime

running = True

def sig_handler(signum, frame):
    global running
    print(f"\n[Updater Daemon] Received shutdown signal ({signum}). Exiting gracefully...")
    running = False

signal.signal(signal.SIGTERM, sig_handler)
signal.signal(signal.SIGINT, sig_handler)

def run_live_feed():
    try:
        cmd = [sys.executable, "live_feed.py"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[LiveSync] Error running live feed: {e}")

def run_snapshot_update():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[SnapshotSync] [{now_str}] Running update_dashboard.py across all snapshot batches...")
    sys.stdout.flush()
    try:
        cmd = [sys.executable, "update_dashboard.py"]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print(f"[SnapshotSync] [{now_str}] Update completed successfully.")
        else:
            print(f"[SnapshotSync] [{now_str}] Returned code {result.returncode}")
    except Exception as e:
        print(f"[SnapshotSync] [{now_str}] Error: {e}")
    sys.stdout.flush()

def main():
    live_interval = int(os.environ.get("LIVE_SYNC_INTERVAL", "5"))
    snapshot_interval = int(os.environ.get("UPDATE_INTERVAL_SECONDS", "300"))

    print("================================================================")
    print("  FUTURES OPTIONS DASHBOARD -- DUAL-SPEED AUTO-UPDATER DAEMON   ")
    print(f"  Live Real-time Feed : Every {live_interval}s")
    print(f"  Historical Snapshot : Every {snapshot_interval}s")
    print("================================================================")
    sys.stdout.flush()

    # Initial sync
    run_live_feed()
    run_snapshot_update()

    last_live = time.time()
    last_snapshot = time.time()

    while running:
        time.sleep(1)
        now = time.time()

        if now - last_live >= live_interval:
            run_live_feed()
            last_live = now

        if now - last_snapshot >= snapshot_interval:
            run_snapshot_update()
            last_snapshot = now

if __name__ == "__main__":
    main()
