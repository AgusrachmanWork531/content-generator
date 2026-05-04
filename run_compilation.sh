#!/bin/bash
# Port untuk Compilation Service
PORT=8889
RUN_MODE=compilation
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== YouTube Compilation Service Controller ==="

# 1. Port Cleanup
PID=$(lsof -ti:$PORT)
if [ -n "$PID" ]; then
  echo "[1/4] Killing process $PID on port $PORT..."
  kill -9 $PID
else
  echo "[1/4] No process found on port $PORT."
fi

# 2. Virtual Environment Setup
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "[2/4] Virtual Environment activated."
else
    echo "Error: Could not activate .venv."
    exit 1
fi

# 3. Environment Config
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
export PYTHONPATH="$DIR:$PYTHONPATH"
export YT_CLIP_RUN_MODE=$RUN_MODE

# 4. Start Service
echo "[4/4] Starting Compilation Service on port $PORT..."
uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload
