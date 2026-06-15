# syntax=docker/dockerfile:1

# ── Stage 1: build the frontend bundles (esbuild) ──────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
# sources the build reads (JSX + the design-system landing templates)
COPY frontend ./frontend
COPY server/static ./server/static
COPY Debug_AI ./Debug_AI
RUN npm run build   # → server/static/dist/* and server/static/vendor/*

# ── Stage 2: python runtime ────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    DEBUGAI_DATA_DIR=/data
WORKDIR /app

# CPU-only torch first (avoids the multi-GB CUDA wheel), then the rest.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.12,<2.13"
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m spacy download en_core_web_sm

# Bake the small signal models into the image so the container runs offline.
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python - <<'PY'
from sentence_transformers import SentenceTransformer, CrossEncoder
SentenceTransformer("all-MiniLM-L6-v2")
CrossEncoder("cross-encoder/nli-deberta-v3-base")
print("models baked")
PY

COPY . .
COPY --from=frontend /app/server/static/dist ./server/static/dist
COPY --from=frontend /app/server/static/vendor ./server/static/vendor

RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4).status==200 else 1)"
# Set OPENAI_API_KEY / ANTHROPIC_API_KEY / DEBUGAI_* at runtime (see README).
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
