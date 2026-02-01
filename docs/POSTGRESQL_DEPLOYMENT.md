# PostgreSQL Deployment Guide

This guide covers deploying AstroPlanner with PostgreSQL support across different environments.

## Quick Start

### Local Development with PostgreSQL

1. **Install PostgreSQL**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install postgresql postgresql-contrib
   
   # macOS with Homebrew
   brew install postgresql
   
   # Windows - Download from postgresql.org
   ```

2. **Create Database**
   ```bash
   sudo -u postgres createdb astroplanner
   sudo -u postgres createuser astroplanner_user
   sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE astroplanner TO astroplanner_user;"
   ```

3. **Configure Environment**
   ```bash
   export DATABASE_TYPE=postgresql
   export DATABASE_URL=postgresql://astroplanner_user:password@localhost:5432/astroplanner
   ```

4. **Initialize Database**
   ```bash
   flask db init
   python -m flask run
   ```

### Migration from SQLite

```bash
# Backup current SQLite database
flask db backup

# Migrate to PostgreSQL
flask db migrate --to postgresql --target-url postgresql://user:pass@localhost/dbname

# Verify migration
flask db info
```

## Production Deployment

### Heroku

1. **Add PostgreSQL Add-on**
   ```bash
   heroku addons:create heroku-postgresql:hobby-dev
   ```

2. **Configure Environment**
   ```bash
   heroku config:set DATABASE_TYPE=postgresql
   heroku config:set SECRET_KEY=your-production-secret
   ```

3. **Deploy**
   ```bash
   git push heroku main
   heroku run flask db init
   ```

### Railway

1. **Add PostgreSQL Database**
   - In Railway dashboard, add PostgreSQL service
   - Note the connection details

2. **Configure Environment Variables**
   ```
   DATABASE_TYPE=postgresql
   DATABASE_URL=postgresql://user:pass@host:port/dbname
   SECRET_KEY=your-production-secret
   ```

3. **Deploy**
   - Railway automatically deploys on git push
   - Database initialization happens on first run

### Render

1. **Create PostgreSQL Database**
   - In Render dashboard, create new PostgreSQL database
   - Note the connection string

2. **Configure Web Service**
   ```
   DATABASE_TYPE=postgresql
   DATABASE_URL=your-postgres-connection-string
   SECRET_KEY=your-production-secret
   ```

3. **Deploy**
   - Connect GitHub repository
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `gunicorn app:app`

### Docker with PostgreSQL

1. **Use Docker Compose**
   ```yaml
   version: '3.8'
   services:
     app:
       build: .
       ports:
         - "5000:5000"
       environment:
         - DATABASE_TYPE=postgresql
         - DATABASE_URL=postgresql://postgres:password@db:5432/astroplanner
       depends_on:
         - db
     
     db:
       image: postgres:15
       environment:
         - POSTGRES_DB=astroplanner
         - POSTGRES_PASSWORD=password
       volumes:
         - postgres_data:/var/lib/postgresql/data
   
   volumes:
     postgres_data:
   ```

2. **Run**
   ```bash
   docker-compose up -d
   docker-compose exec app flask db init
   ```

## Environment Configuration

### Required Variables

- `DATABASE_TYPE=postgresql`
- `DATABASE_URL=postgresql://user:pass@host:port/dbname`
- `SECRET_KEY=your-secret-key`

### Optional Variables

```bash
# PostgreSQL Pool Configuration
POSTGRES_POOL_SIZE=20
POSTGRES_POOL_TIMEOUT=30
POSTGRES_POOL_RECYCLE=3600

# Security (Production)
SECURE_SSL_REDIRECT=true
SESSION_COOKIE_SECURE=true

# Application Features
NINA_INTEGRATION=true
BACKUP_RETENTION_DAYS=7
```

## Database Management

### CLI Commands

```bash
# Database information
flask db info

# Initialize new database
flask db init

# Migrate from SQLite
flask db migrate --to postgresql

# Create backup
flask db backup

# Reset database (development only)
flask db reset
```

### Connection Testing

```bash
# Test current configuration
flask db info

# Validate connection
python -c "from config.database import get_database_config; print(get_database_config().validate_connection())"
```

## Performance Tuning

### Connection Pool Settings

For production deployments, tune connection pool settings based on your needs:

```bash
# High-traffic sites
export POSTGRES_POOL_SIZE=50
export POSTGRES_POOL_TIMEOUT=60
export POSTGRES_POOL_RECYCLE=7200

# Low-traffic sites
export POSTGRES_POOL_SIZE=10
export POSTGRES_POOL_TIMEOUT=30
export POSTGRES_POOL_RECYCLE=3600
```

### Database Optimization

```sql
-- Create indexes for better performance
CREATE INDEX idx_targets_name ON targets(name);
CREATE INDEX idx_imaging_sessions_target_id ON imaging_sessions(target_id);
CREATE INDEX idx_imaging_sessions_date ON imaging_sessions(session_date);
```

## Monitoring and Maintenance

### Health Checks

```bash
# Application health
curl http://your-app.com/health

# Database connection
flask db info
```

### Backup Strategies

```bash
# Automated backup (add to cron)
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
psql $DATABASE_URL < backup_file.sql
```

### Log Monitoring

Monitor application logs for database-related issues:

```bash
# Heroku
heroku logs --tail

# Docker
docker-compose logs -f app

# Direct server
tail -f /var/log/astroplanner.log
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Check PostgreSQL is running
   - Verify connection string
   - Check firewall settings

2. **Authentication Failed**
   - Verify username/password
   - Check database permissions
   - Ensure user exists

3. **Database Not Found**
   - Create database: `createdb dbname`
   - Check database name in URL

4. **Migration Issues**
   - Check source database accessibility
   - Verify target database permissions
   - Review migration logs

### Debug Commands

```bash
# Test connection
flask db info

# Check configuration
python -c "from config.database import get_database_config; config = get_database_config(); print(f'Type: {config.db_type}, URL: {config.connection_string}')"

# Validate environment
python -c "import os; print('DATABASE_TYPE:', os.getenv('DATABASE_TYPE')); print('DATABASE_URL:', os.getenv('DATABASE_URL'))"
```

## Security Considerations

1. **Use SSL in Production**
   ```bash
   export DATABASE_URL="postgresql://user:pass@host:port/db?sslmode=require"
   ```

2. **Secure Connection Strings**
   - Never commit connection strings to version control
   - Use environment variables
   - Rotate passwords regularly

3. **Database Permissions**
   - Create dedicated application user
   - Grant minimal required permissions
   - Avoid using superuser accounts

4. **Network Security**
   - Restrict database access to application servers
   - Use VPC/private networks when possible
   - Enable connection logging