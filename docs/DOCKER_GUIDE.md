# Docker Deployment Guide

This guide explains how to deploy AstroPlanner using Docker containers, with support for both SQLite (simple) and PostgreSQL (production) databases.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Deployment Options](#deployment-options)
3. [Configuration](#configuration)
4. [SQLite Deployment](#sqlite-deployment)
5. [PostgreSQL Deployment](#postgresql-deployment)
6. [Production Considerations](#production-considerations)
7. [Maintenance](#maintenance)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+

### Fastest Setup (SQLite)

```bash
# Clone the repository
git clone https://github.com/yourusername/astroplanner.git
cd astroplanner

# Start with default settings
docker-compose up -d

# Initialize the database
docker-compose exec astroplanner flask init-db

# Access at http://localhost:5000
```

---

## Deployment Options

| Option | Database | Best For | Compose File |
|--------|----------|----------|--------------|
| Simple | SQLite | Single user, local use | `docker-compose.yml` |
| Production | PostgreSQL | Multi-user, cloud deployment | `docker-compose.postgres.yml` |

---

## Configuration

### Environment Variables

All configuration is done via environment variables. Create a `.env` file or set them in your docker-compose override.

#### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Flask secret key (change in production!) |
| `FLASK_ENV` | `production` | Environment mode |
| `FLASK_DEBUG` | `False` | Enable debug mode |
| `PORT` | `5000` | Application port |

#### Database Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_TYPE` | `sqlite` | Database type: `sqlite` or `postgresql` |
| `DATABASE_URL` | - | Full database connection URL |
| `POSTGRES_POOL_SIZE` | `10` | Connection pool size |
| `POSTGRES_POOL_TIMEOUT` | `30` | Pool timeout in seconds |
| `POSTGRES_POOL_RECYCLE` | `3600` | Connection recycle time |

#### Observer Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVER_LAT` | `24.7136` | Observer latitude |
| `OBSERVER_LON` | `46.6753` | Observer longitude |
| `OBSERVER_ELEV_M` | `600` | Observer elevation in meters |
| `OBSERVER_TZ` | `Asia/Riyadh` | Observer timezone |

#### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `NINA_INTEGRATION` | `true` | Enable NINA export features |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backups |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_TO_STDOUT` | `true` | Log to stdout |

---

## SQLite Deployment

Best for single-user setups or local development.

### docker-compose.yml (Default)

```yaml
version: "3.9"

services:
  astroplanner:
    build: .
    ports:
      - "5000:5000"
    environment:
      - SECRET_KEY=your-secret-key
      - DATABASE_TYPE=sqlite
      - OBSERVER_LAT=your-latitude
      - OBSERVER_LON=your-longitude
    volumes:
      - ./uploads:/app/uploads
      - ./instance:/app/instance  # SQLite database
    restart: unless-stopped
```

### Commands

```bash
# Start
docker-compose up -d

# Initialize database
docker-compose exec astroplanner flask init-db

# View logs
docker-compose logs -f astroplanner

# Stop
docker-compose down
```

### Data Persistence

SQLite data is stored in `./instance/astroplanner.db` on the host.

---

## PostgreSQL Deployment

Recommended for production and multi-user scenarios.

### Using docker-compose.postgres.yml

```bash
# Start with PostgreSQL
docker-compose -f docker-compose.postgres.yml up -d

# Initialize database
docker-compose -f docker-compose.postgres.yml exec astroplanner flask init-db

# Check status
docker-compose -f docker-compose.postgres.yml ps
```

### Custom Configuration

Create a `.env` file:

```dotenv
# Security
SECRET_KEY=your-very-secure-random-key

# PostgreSQL password
POSTGRES_PASSWORD=your-secure-password

# Observer location (example: London)
OBSERVER_LAT=51.5074
OBSERVER_LON=-0.1278
OBSERVER_ELEV_M=11
OBSERVER_TZ=Europe/London

# Optional: Expose PostgreSQL externally
POSTGRES_PORT=5432
```

Then run:

```bash
docker-compose -f docker-compose.postgres.yml up -d
```

### Connecting to External PostgreSQL

If using an external database (RDS, Cloud SQL, etc.):

```yaml
services:
  astroplanner:
    environment:
      - DATABASE_TYPE=postgresql
      - DATABASE_URL=postgresql://user:pass@your-host:5432/astroplanner
```

---

## Production Considerations

### 1. Secret Key

Generate a secure secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Reverse Proxy (Nginx)

Example nginx configuration:

```nginx
server {
    listen 80;
    server_name astroplanner.yourdomain.com;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. HTTPS/SSL

With a reverse proxy handling SSL:

```yaml
environment:
  - SECURE_SSL_REDIRECT=true
  - SESSION_COOKIE_SECURE=true
  - SESSION_COOKIE_HTTPONLY=true
  - SESSION_COOKIE_SAMESITE=strict
```

### 4. Resource Limits

```yaml
services:
  astroplanner:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### 5. Logging

View logs:

```bash
# All logs
docker-compose logs -f

# App only
docker-compose logs -f astroplanner

# Last 100 lines
docker-compose logs --tail=100 astroplanner
```

---

## Maintenance

### Backup

#### SQLite Backup

```bash
# Copy the database file
docker-compose exec astroplanner cp /app/instance/astroplanner.db /app/uploads/backup.db

# Or from host
cp ./instance/astroplanner.db ./backups/astroplanner_$(date +%Y%m%d).db
```

#### PostgreSQL Backup

```bash
# Using pg_dump
docker-compose -f docker-compose.postgres.yml exec postgres \
  pg_dump -U astroplanner astroplanner > backup_$(date +%Y%m%d).sql

# Using Flask CLI
docker-compose -f docker-compose.postgres.yml exec astroplanner \
  flask db backup
```

### Restore

#### SQLite Restore

```bash
# Stop the app
docker-compose down

# Replace database
cp ./backups/astroplanner_backup.db ./instance/astroplanner.db

# Start again
docker-compose up -d
```

#### PostgreSQL Restore

```bash
# Restore from SQL dump
docker-compose -f docker-compose.postgres.yml exec -T postgres \
  psql -U astroplanner astroplanner < backup.sql
```

### Updates

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose build
docker-compose up -d

# Run any migrations if needed
docker-compose exec astroplanner flask db upgrade
```

### Database Migration (SQLite → PostgreSQL)

```bash
# 1. Start PostgreSQL stack
docker-compose -f docker-compose.postgres.yml up -d postgres

# 2. Export from SQLite
docker-compose exec astroplanner flask db migrate --to postgresql \
  --target-url postgresql://astroplanner:password@postgres:5432/astroplanner

# 3. Switch to PostgreSQL compose file
docker-compose down
docker-compose -f docker-compose.postgres.yml up -d
```

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs astroplanner

# Check container status
docker-compose ps

# Verify build
docker-compose build --no-cache
```

### Database connection errors

```bash
# PostgreSQL: Check if database is ready
docker-compose -f docker-compose.postgres.yml exec postgres pg_isready

# Check database logs
docker-compose -f docker-compose.postgres.yml logs postgres
```

### Permission denied on volumes

```bash
# Fix ownership (Linux)
sudo chown -R 1000:1000 ./uploads ./instance

# Or run with current user
docker-compose run --user $(id -u):$(id -g) astroplanner flask init-db
```

### Out of memory

Increase Docker memory limits or reduce workers:

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "2", "app:app"]
```

### Health check failing

```bash
# Test manually
docker-compose exec astroplanner curl -f http://localhost:5000/

# Check app logs
docker-compose logs --tail=50 astroplanner
```

### Port already in use

```bash
# Use different port
PORT=8080 docker-compose up -d

# Or edit docker-compose.yml
ports:
  - "8080:5000"
```

---

## File Structure

```
astroplanner/
├── Dockerfile                    # Container build instructions
├── docker-compose.yml            # SQLite deployment (default)
├── docker-compose.postgres.yml   # PostgreSQL deployment
├── .dockerignore                 # Files excluded from build
├── .env                          # Local environment (not committed)
├── .env.example                  # Environment template
├── instance/                     # SQLite database (volume mount)
├── uploads/                      # User uploads (volume mount)
└── config/presets/               # Custom presets (volume mount)
```

---

## Related Documentation

- [Database Guide](DATABASE_GUIDE.md) - Database configuration details
- [PostgreSQL Deployment](POSTGRESQL_DEPLOYMENT.md) - Advanced PostgreSQL setup
- [Equipment Presets Guide](PRESETS_GUIDE.md) - Configure filter presets
