# syntax=docker/dockerfile:1.7
# Carina Compass AI API image. Multi stage: dependencies are built once in a
# builder layer, the runtime image runs as an unprivileged user.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY ingestion ./ingestion
COPY evaluation ./evaluation
ARG EXTRAS="llm,stores"
RUN pip wheel --wheel-dir /wheels ".[${EXTRAS}]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CC_DATA_DIR=/app/data CC_INDEX_DIR=/app/data/index \
    CC_AUDIT_PATH=/app/data/audit/audit.jsonl CC_FEEDBACK_PATH=/app/data/audit/feedback.jsonl
RUN useradd --create-home --uid 10001 carina
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
COPY ingestion/data/seed ./ingestion/data/seed
RUN mkdir -p /app/data/audit /app/data/index && chown -R carina:carina /app
USER carina
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready').status == 200 else 1)"
CMD ["uvicorn", "carina.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
