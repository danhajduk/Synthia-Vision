FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY tools /app/tools
COPY config /app/config
COPY Documents/schema.sql /app/Documents/schema.sql

RUN addgroup --system synthia && adduser --system --ingroup synthia synthia \
    && mkdir -p /app/state /app/logs \
    && chown -R synthia:synthia /app \
    && chmod -R 0777 /app/state /app/logs

USER synthia

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "from pathlib import Path; p=Path('/app/config/config.yaml'); raise SystemExit(0 if p.exists() else 1)"

CMD ["python", "-m", "src.main"]
