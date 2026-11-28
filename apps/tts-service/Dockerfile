FROM python:3.12-slim

# VieNeu-TTS as its own service, on CPU. Build from the repo root:
#   docker build -f apps/tts-service/Dockerfile -t telesales-tts:cpu .
# The weights (about 1.4 GB) download into HF_HOME on the first start; mount /models to keep them.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY apps/tts-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/tts-service/src/ /app/src/

RUN useradd --create-home --uid 1000 app && mkdir -p /models && chown -R app:app /app /models
USER app
VOLUME ["/models"]
EXPOSE 8600
HEALTHCHECK --interval=10s --timeout=3s --start-period=600s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8600/health/ready')"
CMD ["uvicorn", "tts_service.main:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8600", "--no-access-log"]
