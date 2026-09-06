#!/usr/bin/env bash
# GitContainer Cloud — start the local web interface (macOS/Linux).
# Uses .venv (created by setup.sh). Run ./setup.sh first on a fresh machine.
set -u
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "  [XX] Virtual environment not found. Run ./setup.sh first."
  exit 1
fi

echo ""
echo "========================================="
echo " GitContainer Cloud is running"
echo "========================================="
echo ""
echo "  Open:"
echo "  http://localhost:8000"
echo ""
echo "  Press Ctrl+C to stop."
echo ""
echo "========================================="
echo ""

exec .venv/bin/python app.py
