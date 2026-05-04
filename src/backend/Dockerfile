# Build arg: set ENABLE_CONFIDENCE=true to produce the v2 image (canary demo).
# The v2 image appends a 'confidence: float' field to the LogAnalysis JSON output,
# making the canary visibly different from v1 replicas during the Argo Rollouts demo.
ARG ENABLE_CONFIDENCE=false

FROM python:3.12-slim AS builder

ENV TIKTOKEN_CACHE_DIR=/install/tiktoken_cache

WORKDIR /build
COPY src/backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    PYTHONPATH=/install/lib/python3.12/site-packages \
    python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"


FROM python:3.12-slim

ARG ENABLE_CONFIDENCE=false
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/app/src:/install/lib/python3.12/site-packages" \
    TIKTOKEN_CACHE_DIR=/install/tiktoken_cache \
    ENABLE_CONFIDENCE=${ENABLE_CONFIDENCE}

COPY --from=builder /install /install

RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app
COPY src/backend /app/src/backend
COPY datasets /app/datasets
COPY tests/eval/judge /app/tests/eval/judge

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
