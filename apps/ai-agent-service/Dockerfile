FROM python:3.12-slim

# WITH_VOICE=1 installs ASR/TTS/turn-detection (several hundred MB); the text
# channels work without it and /health reports voice as "missing packages".
ARG WITH_VOICE=0
# The voice calls are spoken with: "openai:<voice>" (cloud, nothing more to
# install) or "vieneu:" (local, installs VieNeu-TTS). Empty: config/models.yaml's
# voice.tts, which is vieneu.
ARG VOICE_TTS=""

# AGENT_HOME is where config/ (models, lanes, situations) and data/btc live;
# PYTHONPATH reaches backend-common (`src.*`) and the agent package, and is
# inherited by the MCP servers the agent starts as subprocesses.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AGENT_HOME=/app/agent \
    PYTHONPATH=/app/shared:/app/service \
    VOICE_MODELS_DIR=/app/models \
    EMBEDDING_MODELS_DIR=/app/models/embedding \
    HF_HOME=/app/models/huggingface

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY packages/backend-common/requirements.txt ./requirements-common.txt
RUN pip install --no-cache-dir -r requirements-common.txt
COPY apps/ai-agent-service/requirements.txt apps/ai-agent-service/requirements-voice.txt \
     apps/ai-agent-service/requirements-voice-local-tts.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_VOICE" = "1" ]; then pip install --no-cache-dir -r requirements-voice.txt; fi \
    && if [ "$WITH_VOICE" = "1" ] && { [ -z "$VOICE_TTS" ] || [ "${VOICE_TTS%%:*}" = "vieneu" ]; }; then \
         pip install --no-cache-dir -r requirements-voice-local-tts.txt; fi

COPY packages/backend-common/src/ /app/shared/src/
COPY apps/ai-agent-service/src/ /app/service/
COPY apps/ai-agent-service/config/ /app/agent/config/
# The agent's voices by region for VOICE_TTS=elevenlabs: (one file, shared with create_data).
COPY scripts/create_data/config/voices.yaml /app/agent/config/voices.yaml
COPY apps/ai-agent-service/data/btc/ /app/agent/data/btc/
COPY apps/ai-agent-service/data/kb/ /app/agent/data/kb/

RUN useradd --create-home app && mkdir -p /app/models /app/agent/runs \
    && chown -R app:app /app
USER app
VOLUME ["/app/models"]
EXPOSE 8400
CMD ["uvicorn", "ai_agent_service.main:app", "--app-dir", "/app/service", "--host", "0.0.0.0", "--port", "8400", "--no-access-log"]
