# ─── Stage 1: Builder ────────────────────────────────────────────────────────
# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim AS builder
WORKDIR /build

RUN pip install --upgrade pip
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: Production Image ───────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY --from=builder /install /usr/local
COPY backend/app/ ./app/
COPY knowledge/model-cards/ ./knowledge/model-cards/

# Support both `app.*` (uvicorn) and workspace-root `backend.app.*` imports used in source/tests.
RUN mkdir -p /app/backend && ln -sfn /app/app /app/backend/app
ENV PYTHONPATH=/app
ENV MODEL_CARDS_DIR=/app/knowledge/model-cards

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
