#!/usr/bin/env bash
# Launch the DebugAI web app (home + dashboard + diagnosis/fix API).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# Load secrets from a local .env if present (gitignored — keys never get committed).
if [ -f .env ]; then
  set -a; . ./.env; set +a
  echo "Loaded .env"
fi

# Use already-downloaded models; no network model checks.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
# Optional hardening (see README "Security & robustness"):
#   ANTHROPIC_API_KEY   enable the live LLM explainer + fix re-run
#   DEBUGAI_API_KEY     require X-API-Key on /api/*  (lock down a hosted instance)
#   DEBUGAI_RATE_LIMIT  /api/* requests/min/client (default 240)
#   DEBUGAI_TRUST_PROXY=1 honour X-Forwarded-For when behind a reverse proxy
#   DEBUGAI_SSL_CERT / DEBUGAI_SSL_KEY  serve HTTPS directly

HOST="${HOST:-127.0.0.1}"

# Build the frontend bundles if missing (vendored React + esbuild output).
if [ ! -f server/static/dist/dashboard.js ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building frontend (npm install && npm run build)…"
    npm install --silent && npm run build
  else
    echo "WARN: server/static/dist is missing and npm is unavailable — run 'npm install && npm run build'." >&2
  fi
fi

SSL_ARGS=()
if [ -n "${DEBUGAI_SSL_CERT:-}" ] && [ -n "${DEBUGAI_SSL_KEY:-}" ]; then
  SSL_ARGS=(--ssl-certfile "$DEBUGAI_SSL_CERT" --ssl-keyfile "$DEBUGAI_SSL_KEY")
  echo "Starting DebugAI on https://${HOST}:${PORT}  (Ctrl-C to stop)"
else
  echo "Starting DebugAI on http://${HOST}:${PORT}  (Ctrl-C to stop)"
fi
exec "$PY" -m uvicorn server.app:app --host "$HOST" --port "${PORT}" --reload "${SSL_ARGS[@]}"
