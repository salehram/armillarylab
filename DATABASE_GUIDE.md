# AstroPlanner Database Configuration Guide

This guide provides clear, step-by-step instructions for configuring and migrating databases in AstroPlanner. The application supports both **SQLite** (default, for development/local use) and **PostgreSQL** (recommended for production/cloud deployment).

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Part 1: Initial Setup](#part-1-initial-setup)
   - [Option A: SQLite (Default)](#option-a-sqlite-default)
   - [Option B: PostgreSQL](#option-b-postgresql)
3. [Part 2: Migrating Between Databases](#part-2-migrating-between-databases)
   - [SQLite → PostgreSQL Migration](#sqlite--postgresql-migration)
   - [PostgreSQL → SQLite Migration](#postgresql--sqlite-migration)
4. [Environment Variables Reference](#environment-variables-reference)
5. [Troubleshooting](#troubleshooting)

---

## Quick Reference

| Scenario | Command |
|----------|---------|
| Check current database | `flask db info` |
| Initialize SQLite | `flask init-db` |
| Initialize PostgreSQL | Set env vars + `flask init-db` |
| Migrate SQLite → PostgreSQL | `flask db migrate --to postgresql --target-url <URL>` |
| Migrate PostgreSQL → SQLite | `flask db migrate --to sqlite` |
| Create backup | `flask db backup` |

---

## Using .env Files for Configuration

Instead of setting environment variables manually each time, you can use `.env` files for persistent configuration.

### Available Configuration Files

| File | Purpose |
|------|--------|
| `.env.example` | Template with all available options (copy to `.env`) |
| `.env.production` | Template optimized for production deployment |
| `.flaskenv` | Flask server settings (auto-loaded) |

### Setup for Development (SQLite)

1. **Copy the example file:**
   ```powershell
   # Windows
   copy .env.example .env
   
   # Linux/macOS
   cp .env.example .env
   ```

2. **Edit `.env`** - No changes needed for SQLite (default):
   ```dotenv
   SECRET_KEY=your-secret-key-here
   FLASK_ENV=development
   FLASK_DEBUG=True
   DATABASE_TYPE=sqlite
   ```

3. **Run the app** - Settings are automatically loaded:
   ```powershell
   flask run
   ```

### Setup for Production (PostgreSQL)

1. **Copy the production template:**
   ```powershell
   copy .env.production .env
   ```

2. **Edit `.env` with your PostgreSQL credentials:**
   ```dotenv
   SECRET_KEY=your-secure-production-key
   FLASK_ENV=production
   FLASK_DEBUG=False
   
   DATABASE_TYPE=postgresql
   DATABASE_URL=postgresql://username:password@hostname:5432/astroplanner
   
   # Connection pool (adjust based on your needs)
   POSTGRES_POOL_SIZE=20
   POSTGRES_POOL_TIMEOUT=30
   ```

3. **Initialize and run:**
   ```powershell
   flask init-db
   flask run
   ```

### Important Notes

- **`.env` is gitignored** - Your credentials won't be committed
- **`.flaskenv` is safe to commit** - Contains only server settings, no secrets
- **Restart required** - After changing `.env`, restart the Flask server
- **Environment variables override `.env`** - Manual `$env:VAR` takes precedence

---

## Part 1: Initial Setup

Choose ONE of the following options based on your use case:

### Option A: SQLite (Default)

SQLite is the default database and requires **zero configuration**. Perfect for:
- Local development
- Single-user installations
- Quick testing
- Portable setups (database is a single file)

#### Steps

1. **Ensure virtual environment is activated**
   ```powershell
   # Windows
   .\dev\Scripts\activate
   
   # Linux/macOS
   source dev/bin/activate
   ```

2. **Initialize the database**
   ```powershell
   flask init-db
   ```
   
   With options:
   ```powershell
   # Use ZWO filter preset with AstroBin IDs
   flask init-db --filter-preset zwo
   
   # Force re-initialization (CAUTION: deletes existing data)
   flask init-db --force
   ```

3. **Start the application**
   ```powershell
   flask run
   ```

4. **Verify database**
   ```powershell
   flask db info
   ```
   
   Expected output:
   ```
   Database Type: sqlite
   Connection String: sqlite:///c:\...\astroplanner\astroplanner.db
   ✓ Connection successful
   ```

**Database location:** `astroplanner.db` in the project root directory.

---

### Option B: PostgreSQL

PostgreSQL is recommended for:
- Production deployments
- Cloud platforms (Heroku, Railway, Render)
- Multi-user scenarios
- Better concurrency and performance

#### Prerequisites

Before you begin, ensure you have:

1. **PostgreSQL installed and running**
   
   Windows (download from postgresql.org):
   ```powershell
   # Verify installation
   psql --version
   ```
   
   Linux/macOS:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install postgresql postgresql-contrib
   
   # macOS with Homebrew
   brew install postgresql
   brew services start postgresql
   ```

2. **psycopg2-binary installed** (already in requirements.txt)
   ```powershell
   pip install psycopg2-binary
   ```

3. **A PostgreSQL database created**
   ```powershell
   # Connect to PostgreSQL as admin
   psql -U postgres
   
   # Create database and user
   CREATE DATABASE astroplanner;
   CREATE USER astroplanner_user WITH PASSWORD 'your_secure_password';
   GRANT ALL PRIVILEGES ON DATABASE astroplanner TO astroplanner_user;
   
   # Exit
   \q
   ```

#### Steps

1. **Set environment variables**

   **Windows PowerShell:**
   ```powershell
   $env:DATABASE_TYPE = "postgresql"
   $env:DATABASE_URL = "postgresql://astroplanner_user:your_secure_password@localhost:5432/astroplanner"
   ```

   **Windows CMD:**
   ```cmd
   set DATABASE_TYPE=postgresql
   set DATABASE_URL=postgresql://astroplanner_user:your_secure_password@localhost:5432/astroplanner
   ```

   **Linux/macOS:**
   ```bash
   export DATABASE_TYPE=postgresql
   export DATABASE_URL=postgresql://astroplanner_user:your_secure_password@localhost:5432/astroplanner
   ```

   **Or using individual components (alternative):**
   ```powershell
   $env:DATABASE_TYPE = "postgresql"
   $env:DB_HOST = "localhost"
   $env:DB_PORT = "5432"
   $env:DB_NAME = "astroplanner"
   $env:DB_USER = "astroplanner_user"
   $env:DB_PASSWORD = "your_secure_password"
   ```

2. **Verify environment configuration**
   ```powershell
   flask db info
   ```
   
   Expected output:
   ```
   Database Type: postgresql
   Connection String: postgresql://astroplanner_user:***@localhost:5432/astroplanner
   
   PostgreSQL Configuration:
     Pool Size: 10
     Pool Timeout: 30
     Pool Recycle: 3600
   
   Connection Test:
   ✓ Connection successful
   ```

3. **Initialize the database**
   ```powershell
   flask init-db
   ```

4. **Start the application**
   ```powershell
   flask run
   ```

#### Making Environment Variables Persistent

**Windows (System Environment Variables):**
1. Press `Win + X` → System → Advanced system settings
2. Click "Environment Variables"
3. Add new User variables:
   - `DATABASE_TYPE` = `postgresql`
   - `DATABASE_URL` = `postgresql://user:pass@localhost:5432/astroplanner`

**Linux/macOS (.bashrc or .zshrc):**
```bash
echo 'export DATABASE_TYPE=postgresql' >> ~/.bashrc
echo 'export DATABASE_URL=postgresql://user:pass@localhost:5432/astroplanner' >> ~/.bashrc
source ~/.bashrc
```

**Using .env file (requires python-dotenv):**
Create a `.env` file in the project root:
```env
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://astroplanner_user:your_password@localhost:5432/astroplanner
SECRET_KEY=your-secret-key
```

---

## Part 2: Migrating Between Databases

### SQLite → PostgreSQL Migration

Use this when moving from local development to production or cloud deployment.

#### Prerequisites Checklist

Before migrating, ensure:

- [ ] PostgreSQL is installed and running
- [ ] Target database exists and is empty
- [ ] You have the PostgreSQL connection URL ready
- [ ] Current SQLite database has data you want to preserve
- [ ] You've created a backup of your SQLite database

#### Step-by-Step Migration

1. **Create a backup of your current SQLite database**
   ```powershell
   flask db backup
   ```
   This creates: `astroplanner.db.backup_YYYYMMDD_HHMMSS`

2. **Verify current database status**
   ```powershell
   flask db info
   ```
   Confirm you're currently on SQLite with data.

3. **Prepare the PostgreSQL database**
   ```powershell
   # Connect to PostgreSQL
   psql -U postgres
   
   # Create fresh database (if not done already)
   DROP DATABASE IF EXISTS astroplanner;
   CREATE DATABASE astroplanner;
   GRANT ALL PRIVILEGES ON DATABASE astroplanner TO astroplanner_user;
   \q
   ```

4. **Run the migration**
   ```powershell
   flask db migrate --to postgresql --target-url "postgresql://astroplanner_user:password@localhost:5432/astroplanner"
   ```
   
   Options:
   - `--backup` / `--no-backup`: Create backup before migration (default: yes)
   - `--validate` / `--no-validate`: Validate data before/after migration (default: yes)

5. **Review migration results**
   ```
   Migration Results
   ============================================================
   Status: completed
   Tables migrated: 10
   Records migrated: 156
   Backup created: astroplanner.db.backup_20260201_143052
   
   ✓ Migration completed successfully
   ```

6. **Switch to PostgreSQL for future sessions**
   ```powershell
   $env:DATABASE_TYPE = "postgresql"
   $env:DATABASE_URL = "postgresql://astroplanner_user:password@localhost:5432/astroplanner"
   ```

7. **Verify the migration**
   ```powershell
   flask db info
   flask run
   ```
   Check the application to ensure all data is intact.

---

### PostgreSQL → SQLite Migration

Use this when moving from production back to local development or creating a portable backup.

#### Prerequisites Checklist

- [ ] Current PostgreSQL database has data you want to preserve
- [ ] You have write permissions to the project directory
- [ ] (Optional) Backup your PostgreSQL database first

#### Step-by-Step Migration

1. **Backup PostgreSQL database (recommended)**
   ```powershell
   # Using pg_dump
   pg_dump $env:DATABASE_URL > backup_postgresql_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql
   ```

2. **Verify current database status**
   ```powershell
   flask db info
   ```

3. **Remove existing SQLite file (if any)**
   ```powershell
   Remove-Item astroplanner.db -ErrorAction SilentlyContinue
   ```

4. **Run the migration**
   ```powershell
   flask db migrate --to sqlite
   ```

5. **Switch to SQLite for future sessions**
   ```powershell
   # Remove PostgreSQL environment variables
   Remove-Item Env:DATABASE_TYPE -ErrorAction SilentlyContinue
   Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
   ```

6. **Verify the migration**
   ```powershell
   flask db info
   flask run
   ```

---

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_TYPE` | Database engine to use | `sqlite` or `postgresql` |
| `DATABASE_URL` | Full connection string | `postgresql://user:pass@host:port/db` |

### PostgreSQL-Specific Variables

If not using `DATABASE_URL`, you can specify components individually:

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL server hostname | `localhost` |
| `DB_PORT` | PostgreSQL server port | `5432` |
| `DB_NAME` | Database name | `astroplanner` |
| `DB_USER` | Database username | `astroplanner` |
| `DB_PASSWORD` | Database password | (none) |
| `DB_SSL_MODE` | SSL connection mode | `prefer` |

### Connection Pool Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_POOL_SIZE` | PostgreSQL connection pool size | `10` |
| `DB_POOL_TIMEOUT` | Connection timeout (seconds) | `30` |
| `DB_POOL_RECYCLE` | Connection recycle time (seconds) | `3600` |
| `DB_MAX_OVERFLOW` | Max overflow connections | `20` |

### SQLite-Specific Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SQLITE_PATH` | Custom path to SQLite file | `astroplanner.db` |
| `SQLITE_TIMEOUT` | Connection timeout (seconds) | `20` |
| `SQLITE_WAL_MODE` | Enable WAL mode | `true` |

---

## Troubleshooting

### Common Issues

#### "Connection Refused" (PostgreSQL)

**Symptoms:** `flask db info` shows connection failed

**Solutions:**
1. Verify PostgreSQL is running:
   ```powershell
   # Windows (check services)
   Get-Service postgresql*
   
   # Linux
   sudo systemctl status postgresql
   ```

2. Check connection details:
   ```powershell
   # Test direct connection
   psql -U astroplanner_user -h localhost -d astroplanner
   ```

3. Verify firewall allows port 5432

#### "Database does not exist"

**Solution:**
```powershell
psql -U postgres -c "CREATE DATABASE astroplanner;"
```

#### "Authentication Failed"

**Solutions:**
1. Verify password in connection string
2. Check PostgreSQL authentication settings (`pg_hba.conf`)
3. Ensure user has proper permissions:
   ```sql
   GRANT ALL PRIVILEGES ON DATABASE astroplanner TO astroplanner_user;
   ```

#### Migration Shows "0 records migrated"

**Possible causes:**
1. Source database is empty - check with `flask db info`
2. Source database path is wrong
3. Tables exist but are empty

#### Environment Variables Not Working

**Windows PowerShell:**
```powershell
# Check current values
$env:DATABASE_TYPE
$env:DATABASE_URL

# Set for current session
$env:DATABASE_TYPE = "postgresql"

# Verify
echo $env:DATABASE_TYPE
```

**Persistent issues:**
- Restart terminal after setting system environment variables
- Use `.env` file with python-dotenv for consistent configuration

### Debug Commands

```powershell
# Full database info
flask db info

# Test configuration loading
python -c "from config.database import get_database_config; c = get_database_config(); print(f'Type: {c.db_type}'); print(f'URL: {c.connection_string}')"

# Check environment
python -c "import os; print('DATABASE_TYPE:', os.getenv('DATABASE_TYPE')); print('DATABASE_URL:', os.getenv('DATABASE_URL'))"

# Test PostgreSQL connection directly
psql "postgresql://user:pass@localhost:5432/astroplanner" -c "SELECT 1;"
```

### Getting Help

If you encounter issues not covered here:

1. Check application logs for detailed error messages
2. Run `flask db info` to verify configuration
3. Ensure all prerequisites are met for your chosen database
4. Verify network connectivity for remote PostgreSQL servers

---

## Summary

| Task | SQLite | PostgreSQL |
|------|--------|------------|
| **Setup complexity** | None | Moderate |
| **Performance** | Good for single user | Excellent for multiple users |
| **Portability** | Single file, easy to backup | Requires server |
| **Cloud deployment** | Not recommended | Recommended |
| **Best for** | Development, testing | Production |

**Remember:**
- SQLite is the default - no configuration needed
- PostgreSQL requires environment variables to be set
- Always backup before migrating
- Verify data integrity after migration with `flask db info`
