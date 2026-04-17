# ──────────────────────────────────────────────────────────────
# Stage 1: Build Frontend
# ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

COPY apipool_server/frontend/package*.json ./
RUN npm ci

COPY apipool_server/frontend/ .
RUN npx vite build

# ──────────────────────────────────────────────────────────────
# Stage 2: Runtime (Python slim)
# ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="apipool-team"
LABEL description="apipool-server — API Key pool management with transparent proxy calls"

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy source code
COPY apipool/ ./apipool/
COPY apipool_server/ ./apipool_server/

# Copy built frontend assets
COPY --from=frontend-build /app/frontend/dist/ ./apipool_server/static/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash apipool \
    && chown -R apipool:apipool /app
USER apipool

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "apipool_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
