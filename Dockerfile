FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 ENV=production
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY static static
COPY seed.py .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8080
# Cloud Run injects $PORT. --proxy-headers because Cloud Run terminates TLS in front of the container.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --proxy-headers --forwarded-allow-ips='*'
