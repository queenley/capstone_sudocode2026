FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/shared
WORKDIR /app
COPY packages/backend-common/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/backend-common/src/ /app/shared/src/
COPY packages/backend-common/migrations/ /app/shared/migrations/
COPY scripts/ /app/scripts/
COPY data/seed/ /app/data/
# The organisers' catalogue and mock: the storefront is seeded from them (scripts/seed/btc_catalog.py).
COPY apps/ai-agent-service/data/btc/catalog/ /app/btc/catalog/
COPY apps/ai-agent-service/data/btc/eval/mock_tools.py /app/btc/eval/mock_tools.py
RUN useradd --create-home app && chown -R app:app /app
USER app
