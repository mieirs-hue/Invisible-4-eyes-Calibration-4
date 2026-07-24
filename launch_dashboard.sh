#!/bin/bash
set -euo pipefail

PROJECT_DIR="/home/unclejesse/Desktop/Invisble 4=eyes"
JETSON_DIR="$PROJECT_DIR/jetson"
DASHBOARD_DIR="$PROJECT_DIR/dashboard"
DASHBOARD_PORT=8780
DASHBOARD_URL="http://127.0.0.1:${DASHBOARD_PORT}/index.html"
JETSON_LOG="$JETSON_DIR/invisible_4eyes.log"

mkdir -p "$JETSON_DIR"

PYTHON_BIN="python3"
if [[ -x "$JETSON_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$JETSON_DIR/.venv/bin/python"
fi

# Keep a single backend instance to avoid websocket bind conflicts.
mapfile -t JETSON_PIDS < <(pgrep -f "$JETSON_DIR/main.py" || true)
if [[ ${#JETSON_PIDS[@]} -gt 1 ]]; then
  for ((i=1; i<${#JETSON_PIDS[@]}; i++)); do
    kill "${JETSON_PIDS[$i]}" >/dev/null 2>&1 || true
  done
fi

# Start live telemetry backend if it is not already running.
if ! pgrep -f "$JETSON_DIR/main.py" >/dev/null 2>&1; then
  (
    cd "$JETSON_DIR"
    nohup "$PYTHON_BIN" "$JETSON_DIR/main.py" >> "$JETSON_LOG" 2>&1 &
  )
fi

# Serve dashboard over HTTP so browsers reliably load current content.
if ! pgrep -f "http.server ${DASHBOARD_PORT}" >/dev/null 2>&1; then
  (
    cd "$DASHBOARD_DIR"
    nohup python3 -m http.server "$DASHBOARD_PORT" >/tmp/invisible4eyes_dashboard_http.log 2>&1 &
  )
fi

# Open this project in VS Code so the workspace is immediately available.
if command -v code >/dev/null 2>&1; then
  code "$PROJECT_DIR" >/dev/null 2>&1 &
fi

# Open the dashboard UI in Chromium first (Jetson requirement), then fallback.
if command -v chromium-browser >/dev/null 2>&1; then
  chromium-browser --new-window "$DASHBOARD_URL" >/dev/null 2>&1 &
elif command -v chromium >/dev/null 2>&1; then
  chromium --new-window "$DASHBOARD_URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 || sensible-browser "$DASHBOARD_URL"
else
  sensible-browser "$DASHBOARD_URL"
fi
