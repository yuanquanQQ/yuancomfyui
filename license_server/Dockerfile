FROM python:3.12-slim

ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ARG PIP_FALLBACK_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --retries 8 --timeout 120 \
      --index-url "${PIP_INDEX_URL}" -r requirements.txt \
    || python -m pip install --no-cache-dir --retries 8 --timeout 120 \
      --index-url "${PIP_FALLBACK_INDEX_URL}" -r requirements.txt

COPY app ./app
RUN mkdir -p /app/secrets && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
