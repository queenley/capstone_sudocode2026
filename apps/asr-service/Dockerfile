FROM python:3.12-slim

# The ASR service on CPU. For a GPU, Dockerfile.gpu. Build from the repo root:
#   docker build -f apps/asr-service/Dockerfile -t telesales-asr:cpu .
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ASR_MODELS_DIR=/models \
    HF_HOME=/models/huggingface \
    ASR_DEVICE=cpu

WORKDIR /app
COPY apps/asr-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG INSTALL_DENOISER=0
COPY apps/asr-service/requirements-denoise.txt ./
RUN if [ "$INSTALL_DENOISER" = "1" ]; then pip install --no-cache-dir --no-deps -r requirements-denoise.txt; fi
COPY THIRD_PARTY_NOTICES/RNNoise.txt /app/THIRD_PARTY_NOTICES/RNNoise.txt
COPY apps/asr-service/src/ /app/src/

RUN useradd --create-home app && mkdir -p /models && chown -R app:app /app /models
USER app
VOLUME ["/models"]
EXPOSE 8500
HEALTHCHECK --interval=10s --timeout=3s --start-period=600s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/health/ready')"
CMD ["uvicorn", "asr_service.main:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8500", "--no-access-log"]
