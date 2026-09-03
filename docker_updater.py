"""
Background Dual-Speed Auto-Updater Daemon for Futures Options SD Dashboard
1. High-frequency (every 5s): Runs live_feed.py to stream real-time CME futures quotes,
   tick intraday candle bars, and refresh docs/data/live/{ASSET}_data.json.
2. Hourly Analysis Pipeline (every 1 hour / 3600s, identical to GitHub Actions workflow):
   - Step 1: Runs run_all.py (All-in-one quant analysis suite, generating trading_results/)
   - Step 2: Runs update_dashboard.py (Converts trading_results/ to docs/data/ snapshots and updates manifest.json)
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

def run_hourly_pipeline():
    """
    Executes the identical 2-step analysis pipeline as GitHub Actions (.github/workflows/hourly_update.yml):
    1. python run_all.py (Full quant & broker options analysis suite)
    2. python update_dashboard.py (Convert trading_results to docs/data/ snapshots and update manifest)
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*65}")
    print(f"  [HourlyPipeline] [{now_str}] STARTING HOURLY UPDATE (GitHub Action Local Equivalent)")
    print(f"{'='*65}")
    sys.stdout.flush()

    # Step 1: Run full analysis suite (run_all.py)
    print(f"[HourlyPipeline] [Step 1/2] Executing run_all.py...")
    sys.stdout.flush()
    try:
        result_run_all = subprocess.run([sys.executable, "run_all.py"])
        if result_run_all.returncode == 0:
            print(f"[HourlyPipeline] [Step 1/2] [OK] run_all.py completed successfully.")
        else:
            print(f"[HourlyPipeline] [Step 1/2] [WARN] run_all.py returned exit code {result_run_all.returncode}. Proceeding to dashboard update...")
    except Exception as e:
        print(f"[HourlyPipeline] [Step 1/2] [ERROR] Failed to run run_all.py: {e}")
    sys.stdout.flush()

    # Step 2: Update dashboard JSON and manifest (update_dashboard.py)
    print(f"[HourlyPipeline] [Step 2/2] Executing update_dashboard.py...")
    sys.stdout.flush()
    try:
        result_update = subprocess.run([sys.executable, "update_dashboard.py"])
        if result_update.returncode == 0:
            print(f"[HourlyPipeline] [Step 2/2] [OK] update_dashboard.py completed successfully.")
        else:
            print(f"[HourlyPipeline] [Step 2/2] [WARN] update_dashboard.py returned exit code {result_update.returncode}")
    except Exception as e:
        print(f"[HourlyPipeline] [Step 2/2] [ERROR] Failed to run update_dashboard.py: {e}")
    sys.stdout.flush()

    print(f"{'='*65}")
    print(f"  [HourlyPipeline] [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] HOURLY UPDATE COMPLETED")
    print(f"{'='*65}\n")
    sys.stdout.flush()

def main():
    live_interval = int(os.environ.get("LIVE_SYNC_INTERVAL", "5"))
    # Default to 3600s (1 hour) matching GitHub Actions schedule: 0 * * * 1-5
    hourly_interval = int(os.environ.get("HOURLY_PIPELINE_INTERVAL_SECONDS", os.environ.get("UPDATE_INTERVAL_SECONDS", "3600")))

    print("================================================================")
    print("  FUTURES OPTIONS DASHBOARD -- DUAL-SPEED AUTO-UPDATER DAEMON   ")
    print(f"  Live Real-time Feed    : Every {live_interval}s")
    print(f"  Hourly Pipeline Action : Every {hourly_interval}s ({hourly_interval//60} mins, 1 hour default)")
    print("  Pipeline Sequence      : 1) run_all.py -> 2) update_dashboard.py")
    print("================================================================")
    sys.stdout.flush()

    # Initial live tick
    run_live_feed()

    # Initial quick dashboard JSON sync on startup to ensure existing data is mapped
    try:
        subprocess.run([sys.executable, "update_dashboard.py"])
    except Exception as e:
        print(f"[StartupSync] Error: {e}")

    last_live = time.time()
    last_hourly = time.time()

    while running:
        time.sleep(1)
        now = time.time()

        # High-frequency real-time feed tick
        if now - last_live >= live_interval:
            run_live_feed()
            last_live = now

        # Hourly Analysis Pipeline (GitHub Action local equivalent)
        if now - last_hourly >= hourly_interval:
            run_hourly_pipeline()
            last_hourly = now

if __name__ == "__main__":
    main()
