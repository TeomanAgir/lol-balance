# Tek container: backend + webui statik dosyaları (api_contract §7).
# Build context REPO KÖKÜ olmalıdır (webui/ da imaja girer):
#   docker build -f backend/Dockerfile -t lol-balance .
FROM python:3.12-slim

WORKDIR /app

COPY backend/rating/ ./rating/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/
COPY webui/ ./webui/

ENV DB_PATH=/data/lol_balance.db \
    WEBUI_DIR=/app/webui

# SQLite dosyası volume'da yaşar: docker run -v lol-balance-data:/data ...
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
