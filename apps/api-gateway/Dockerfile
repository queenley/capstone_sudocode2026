FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api-gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api-gateway/src/ ./src/
RUN useradd --create-home app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
