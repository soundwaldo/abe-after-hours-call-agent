FROM python:3.12-slim

WORKDIR /app

# Silero VAD downloads its model on first run; keep a cache dir.
ENV XDG_CACHE_HOME=/app/.cache

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/

ENV PORT=7860
EXPOSE 7860

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "7860"]
