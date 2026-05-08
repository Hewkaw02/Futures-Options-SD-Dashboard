import asyncio
import subprocess
import sys
from pathlib import Path
from datetime import datetime

async def run_script(script_path, description):
    print(f"\n{'='*20} RUNNING: {description} {'='*20}")
    try:
        # Using sys.executable to ensure we use the same virtual environment
        process = subprocess.Popen([sys.executable, script_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        
        rc = process.poll()
        if rc == 0:
            print(f"[OK] {description} completed successfully.")
        else:
            print(f"[FAIL] {description} failed with exit code {rc}.")
        return rc
    except Exception as e:
        print(f"[WARN] Error running {description}: {e}")
        return 1

async def main():
    start_time = datetime.now()
    print(f"[START] Starting All-in-One Trading Analysis Suite (Complete Version)")
    print(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    # Full list of analysis scripts from README.md
    tasks = [
        # 1. Core Logic & Snapshots
        ("Trading_Core/Main.py", "Core Asset Snapshots & SD Ranges"),
        
        # 2. Advanced Reports & Bias
        ("Analysis_Tools/master_report.py", "Master Trading Bias Report"),
        
        # 3. Real-time Scanners
        ("Analysis_Tools/intraday_scanner.py", "Intraday Volume & OI Scanner"),
        ("Analysis_Tools/advanced_viz.py", "Institutional Market Map Dashboard"),
        ("Analysis_Tools/intraday_master_viz.py", "Intraday Master Combined Viz"),
        
        # 4. Master Charts (SD Bands & OI Zones)
        ("Analysis_Tools/sd_bands_chart.py", "SD Bands & OI Master Chart"),
        ("Analysis_Tools/hybrid_candle_oi.py", "Hybrid Candle & OI Zones"),
        
        # 5. Specialized Visualizations
        ("Analysis_Tools/organized_analysis.py", "Auto-organized Net OI & Walls"),
        ("Analysis_Tools/multi_asset_net_oi.py", "Multi-asset Net OI Comparison"),
        
        # 6. Focused Asset Analysis (Gold)
        ("Analysis_Tools/gc_oi_focused.py", "Gold OI Walls (Focused)"),
        ("Analysis_Tools/gc_option_viz.py", "Gold Volume & OI Visualization"),
    ]

    success_count = 0
    total_tasks = len(tasks)

    for script, desc in tasks:
        if Path(script).exists():
            rc = await run_script(script, desc)
            if rc == 0:
                success_count += 1
        else:
            print(f"[WARN] Skipping {desc}: File not found at {script}")

    end_time = datetime.now()
    duration = end_time - start_time
    print("-" * 60)
    print(f"[DONE] Finished! {success_count}/{total_tasks} tasks completed in {duration.total_seconds():.1f} seconds.")
    print(f"Check 'trading_results' and 'intraday_results' folders for updated charts and reports.")

if __name__ == "__main__":
    asyncio.run(main())
