FROM python:3.12-slim

# Build arguments for flexibility
ARG PYTHON_VERSION=3.12

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies for astropy, PostgreSQL, and general build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcfitsio-dev \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Flask configuration
ENV FLASK_APP=app.py \
    FLASK_RUN_HOST=0.0.0.0

# Default port (can be overridden)
ENV PORT=5000

# Database configuration defaults (SQLite for simple deployments)
ENV DATABASE_TYPE=sqlite

# Default observer location (Riyadh, Saudi Arabia)
ENV OBSERVER_LAT=24.7136 \
    OBSERVER_LON=46.6753 \
    OBSERVER_ELEV_M=600 \
    OBSERVER_TZ=Asia/Riyadh

# Create directories for data persistence
RUN mkdir -p /app/uploads /app/instance

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ || exit 1

# Production server (gunicorn) - use flask run for development
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "app:app"]
