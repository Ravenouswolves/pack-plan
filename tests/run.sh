#!/usr/bin/env bash
# Serve the staging site with `python -m http.server` and run Wilson's checks
# plus the prep-branch Playwright tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${WB_PORT:-8765}"
PY="${PYTHON:-/workspace/.venv/bin/python}"

# Free the port if a leftover server is sitting on it.
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
fi

cd "$ROOT"
python3 -m http.server "$PORT" --bind 127.0.0.1 >/tmp/wb-http.log 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" >/dev/null 2>&1 || true; }
trap cleanup EXIT

for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/index.html"; then
    break
  fi
  sleep 0.2
done
curl -sf -o /dev/null "http://127.0.0.1:${PORT}/index.html"

export WB_NO_SERVER=1
export WB_PORT="$PORT"
export WB_URL="http://127.0.0.1:${PORT}/index.html"

echo "==== Wilson's 39 checks ===="
"$PY" "$ROOT/tests/test_app.py"
echo
echo "==== Prep / wrap / SW checks ===="
"$PY" "$ROOT/tests/test_prep.py"
echo
echo "All tests passed."
