FROM python:3.12-slim AS base

WORKDIR /app

# Dependencias del sistema para psycopg2 + healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python (capa cacheable)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY scripts/ ./scripts/
COPY tablero/ ./tablero/
COPY datos/ ./datos/
COPY db/ ./db/

# Crear carpeta de integraciones (oauth tokens en runtime)
RUN mkdir -p ./integraciones

ENV PYTHONUNBUFFERED=1
ENV PORT=5050

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Gunicorn — 1 worker porque el scheduler interno NO es multi-process safe
# (jobstore en DB previene duplicados pero igual queremos un solo punto de orquestación)
CMD ["sh", "-c", "cd scripts && gunicorn --bind 0.0.0.0:${PORT:-5050} --workers 1 --threads 8 --timeout 60 --access-logfile - --error-logfile - api:app"]
