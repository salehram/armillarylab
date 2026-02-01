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

> **Migration Note:** The migrate command automatically handles schema creation, data clearing, data migration, and `.env` file updates. Just run the command and confirm!

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

The migration tool handles everything automatically:
- ✅ Tests connection to target database
- ✅ Creates schema (tables) on target
- ✅ Clears any existing data on target
- ✅ Migrates all data from source
- ✅ Updates your `.env` file to use the new database

No manual steps required!

---

### SQLite → PostgreSQL Migration

Use this when moving from local development to production or cloud deployment.

#### Prerequisites

Before migrating, ensure:

- [ ] PostgreSQL is installed and running
- [ ] PostgreSQL database and user created (see [Option B: PostgreSQL](#option-b-postgresql))
- [ ] You have the PostgreSQL connection URL ready

#### Migration Command

```powershell
flask db migrate --to postgresql --target-url "postgresql://user:password@localhost:5432/astroplanner"
```

When prompted, type `y` to confirm the migration.

#### Example Output

```
============================================================
Migrating from SQLite to PostgreSQL
============================================================
Source: sqlite:///c:\...\astroplanner.db
Target: postgresql://user:***@localhost:5432/astroplanner

Step 1/5: Testing target connection...
✓ Target database connection successful

Step 2/5: Initializing target schema...
✓ Schema initialized (10 tables created)

Step 3/5: Clearing target database...
⚠ Target database has existing data (86 records)
Clear target database and proceed with migration? [y/N]: y
✓ Target database cleared

Step 4/5: Migrating data...
✓ Data migration complete

Step 5/5: Updating .env file...
✓ .env file updated to use postgresql

Migration Results
============================================================
Status: completed
Tables migrated: 10
Records migrated: 86
.env file updated: yes

🎉 Migration complete! Your app will now use PostgreSQL.
   Restart your Flask server to apply the changes.
```

#### Verify Migration

```powershell
flask db info
flask run
```

Open http://127.0.0.1:5000 and verify all your targets, sessions, and settings are intact.

> **Note:** Your original SQLite database file remains unchanged as a backup.

---

### PostgreSQL → SQLite Migration

Use this when moving from production back to local development or creating a portable backup.

#### Prerequisites

- [ ] You're currently using PostgreSQL (check with `flask db info`)
- [ ] You have write permissions to the project directory

#### Migration Command

```powershell
flask db migrate --to sqlite
```

When prompted, type `y` to confirm the migration.

#### Example Output

```
============================================================
Migrating from PostgreSQL to SQLite
============================================================
Source: postgresql://user:***@localhost:5432/astroplanner
Target: sqlite:///c:\...\astroplanner.db

Step 1/5: Testing target connection...
✓ Target database connection successful

Step 2/5: Initializing target schema...
✓ Schema initialized (10 tables created)

Step 3/5: Clearing target database...
✓ Target database is empty, proceeding

Step 4/5: Migrating data...
✓ Data migration complete

Step 5/5: Updating .env file...
✓ .env file updated to use sqlite

Migration Results
============================================================
Status: completed
Tables migrated: 10
Records migrated: 86
.env file updated: yes

🎉 Migration complete! Your app will now use SQLite.
   Restart your Flask server to apply the changes.
```

#### Verify Migration

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
