#!/bin/bash

# Configuration
PORT=8888
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== YouTube Clip Downloader Service Controller ==="

# 1. Port Cleanup
PID=$(lsof -ti:$PORT)
if [ -n "$PID" ]; then
  echo "[1/5] Killing process $PID on port $PORT..."
  kill -9 $PID
else
  echo "[1/5] No process found on port $PORT."
fi

# 2. Virtual Environment Setup
echo "[2/5] Setting up Virtual Environment..."
if [ ! -d ".venv" ]; then
    echo "Creating new .venv..."
    python3 -m venv .venv
fi

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "Virtual Environment activated."
else
    echo "Error: Could not activate .venv."
    exit 1
fi

# 3. Environment Config
echo "[3/5] Configuring paths..."
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
export PYTHONPATH="$DIR:$PYTHONPATH"
export PYTHONWARNINGS="ignore"

# 4. Dependency Check & Install
echo "[4/5] Checking and installing dependencies..."
if [ -f "requirements.txt" ]; then
    # In venv, 'pip' and 'python' point to the venv versions
    pip install -r requirements.txt --quiet
    if [ $? -eq 0 ]; then
        echo "Dependencies verified/installed successfully."
    else
        # Try with --break-system-packages if somehow still blocked, 
        # but in venv it should never happen.
        echo "Warning: pip had issues, trying one last fallback..."
        pip install -r requirements.txt --quiet --break-system-packages 2>/dev/null
    fi
else
    echo "Warning: requirements.txt not found."
fi

# 5. Start Service
echo "[5/5] Starting Service on port $PORT..."
python -m app.main
