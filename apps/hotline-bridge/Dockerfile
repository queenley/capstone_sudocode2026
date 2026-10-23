FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/hotline-bridge/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/hotline-bridge/bridge.py ./
RUN useradd --create-home app
USER app
CMD ["python", "bridge.py"]
