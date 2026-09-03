#!/usr/bin/env bash
# Dual-service Docker manager for Futures Options SD Dashboard on Linux/macOS/WSL.

set -e

CMD="${1:-start}"

case "$CMD" in
  start)
    echo "🚀 Starting Dual Services (Dashboard Web + Auto-Updater Daemon)..."
    docker compose up -d dashboard updater
    echo ""
    echo "============================================================"
    echo "  ✅ 1. Web Dashboard is LIVE : http://localhost:8050"
    echo "  ✅ 2. Auto-Updater Daemon   : ACTIVE (Background Sync)"
    echo "============================================================"
    echo "  💡 View logs:  ./docker-run.sh logs"
    echo "  💡 Stop:       ./docker-run.sh stop"
    echo "  💡 Quant Demo: ./docker-run.sh demo"
    echo "============================================================"
    ;;
  stop)
    echo "🛑 Stopping dashboard and updater containers..."
    docker compose down
    echo "✅ Stopped successfully."
    ;;
  restart)
    echo "🔄 Restarting both services..."
    docker compose restart dashboard updater
    echo "✅ Restarted."
    ;;
  build)
    echo "🔨 Rebuilding Docker image..."
    docker compose build --no-cache dashboard
    echo "✅ Build complete."
    ;;
  update)
    echo "⚙️ Manually triggering update_dashboard.py inside container..."
    docker compose run --rm pipeline python update_dashboard.py
    echo "✅ Dashboard data updated!"
    ;;
  live)
    echo "⚡ Manually triggering live_feed.py inside container..."
    docker compose run --rm pipeline python live_feed.py
    echo "✅ Live snapshot generated!"
    ;;
  demo)
    echo "📊 Running Institutional Terminal Demo inside container..."
    docker compose run --rm pipeline python demo_institutional_terminal.py
    ;;
  test)
    echo "🧪 Running test suite inside container..."
    docker compose run --rm pipeline python -m unittest discover tests
    ;;
  run-all)
    echo "📈 Running run_all.py inside container..."
    docker compose run --rm pipeline python run_all.py
    ;;
  logs)
    docker compose logs -f dashboard updater
    ;;
  status)
    docker compose ps
    ;;
  *)
    echo "Usage: ./docker-run.sh [start|stop|restart|build|update|demo|test|run-all|logs|status]"
    exit 1
    ;;
esac
