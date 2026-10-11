FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/shared:/app/service
WORKDIR /app
COPY packages/backend-common/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/backend-common/src/ /app/shared/src/
COPY apps/sales-service/src/ /app/service/
COPY scripts/ /app/scripts/
RUN useradd --create-home app && chown -R app:app /app
USER app
EXPOSE 8300
CMD ["uvicorn", "main:app", "--app-dir", "/app/service", "--host", "0.0.0.0", "--port", "8300", "--no-access-log"]
