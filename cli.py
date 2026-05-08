"""
Database CLI Commands

Provides CLI commands for database management including initialization,
migration, and information display for both SQLite and PostgreSQL.
"""
import click
import os
from datetime import datetime
from pathlib import Path

from flask import current_app
from flask.cli import with_appcontext
from config.database import get_database_config, DatabaseConfig
from config.migration import migrate_database


@click.group()
def db_cli():
    """Database management commands."""
    pass


@db_cli.command()
@with_appcontext
def info():
    """Display current database configuration information."""
    db_config = get_database_config()
    
    click.echo("=" * 60)
    click.echo("ArmillaryLab Database Configuration")
    click.echo("=" * 60)
    click.echo(f"Database Type: {db_config.db_type}")
    click.echo(f"Connection String: {db_config.connection_string}")
    
    if db_config.db_type == 'postgresql':
        click.echo("\nPostgreSQL Configuration:")
        click.echo(f"  Pool Size: {db_config.pool_config['pool_size']}")
        click.echo(f"  Pool Timeout: {db_config.pool_config['pool_timeout']}")
        click.echo(f"  Pool Recycle: {db_config.pool_config['pool_recycle']}")
    else:
        click.echo("\nSQLite Configuration:")
        click.echo(f"  Timeout: {db_config.pool_config['connect_args']['timeout']}")
        click.echo(f"  WAL Mode: {os.getenv('SQLITE_WAL_MODE', 'true')}")
    
    # Test connection
    click.echo("\nConnection Test:")
    is_valid, error = db_config.validate_connection()
    if is_valid:
        click.echo("✓ Connection successful")
    else:
        click.echo(f"✗ Connection failed: {error}")


@db_cli.command()
@with_appcontext
def init():
    """Initialize database schema."""
    from app import db
    
    click.echo("Initializing database schema...")
    
    try:
        # Create all tables
        db.create_all()
        
        # Import and initialize default data
        from app import GlobalConfig, TargetType, Palette
        import json
        
        # Create global config if it doesn't exist
        if not GlobalConfig.query.first():
            global_config = GlobalConfig(
                observer_latitude=32.0,
                observer_longitude=35.0,
                observer_elevation=500,
                timezone_name="Asia/Jerusalem",
                default_packup_time="01:00",
                default_min_altitude=30.0
            )
            db.session.add(global_config)
        
        # Create default target types if they don't exist
        default_types = [
            {"name": "Galaxy", "description": "Galaxies and galaxy clusters"},
            {"name": "Nebula", "description": "Emission, reflection, and planetary nebulae"},
            {"name": "Star Cluster", "description": "Open and globular star clusters"},
            {"name": "Star", "description": "Individual stars and binary systems"},
            {"name": "Solar System", "description": "Planets, moons, and other solar system objects"},
            {"name": "Other", "description": "Other astronomical objects"}
        ]
        
        for type_data in default_types:
            if not TargetType.query.filter_by(name=type_data["name"]).first():
                target_type = TargetType(
                    name=type_data["name"],
                    description=type_data["description"]
                )
                db.session.add(target_type)
        
        # Create default palettes if they don't exist
        default_palettes = [
            {
                "name": "SHO",
                "description": "Sulfur II, Hydrogen Alpha, Oxygen III",
                "is_system": True,
                "filters_json": json.dumps({
                    "S": {"label": "SII", "rgb_channel": "R", "default_exposure": 300, "default_weight": 1.0},
                    "H": {"label": "Ha", "rgb_channel": "G", "default_exposure": 300, "default_weight": 1.0},
                    "O": {"label": "OIII", "rgb_channel": "B", "default_exposure": 300, "default_weight": 1.0}
                })
            },
            {
                "name": "HOO",
                "description": "Hydrogen Alpha, Oxygen III, Oxygen III",
                "is_system": True,
                "filters_json": json.dumps({
                    "H": {"label": "Ha", "rgb_channel": "R", "default_exposure": 300, "default_weight": 1.0},
                    "O": {"label": "OIII", "rgb_channel": "GB", "default_exposure": 300, "default_weight": 1.0}
                })
            },
            {
                "name": "LRGB",
                "description": "Luminance, Red, Green, Blue",
                "is_system": True,
                "filters_json": json.dumps({
                    "L": {"label": "Lum", "rgb_channel": "L", "default_exposure": 300, "default_weight": 1.0},
                    "R": {"label": "Red", "rgb_channel": "R", "default_exposure": 300, "default_weight": 0.3},
                    "G": {"label": "Green", "rgb_channel": "G", "default_exposure": 300, "default_weight": 0.3},
                    "B": {"label": "Blue", "rgb_channel": "B", "default_exposure": 300, "default_weight": 0.4}
                })
            }
        ]
        
        for palette_data in default_palettes:
            if not Palette.query.filter_by(name=palette_data["name"]).first():
                palette = Palette(
                    name=palette_data["name"],
                    description=palette_data["description"],
                    is_system=palette_data["is_system"],
                    filters_json=palette_data["filters_json"]
                )
                db.session.add(palette)
        
        db.session.commit()
        
        click.echo("✓ Database initialized successfully")
        
    except Exception as e:
        db.session.rollback()
        click.echo(f"✗ Database initialization failed: {str(e)}")
        raise


def update_env_file(db_type, db_url=None):
    """Update .env file with new database configuration."""
    env_path = Path(current_app.root_path) / '.env'
    
    if not env_path.exists():
        # Create new .env file
        lines = [
            "# ArmillaryLab Environment Configuration\n",
            f"DATABASE_TYPE={db_type}\n",
        ]
        if db_url:
            lines.append(f"DATABASE_URL={db_url}\n")
        env_path.write_text(''.join(lines))
        return True
    
    # Read existing .env file
    content = env_path.read_text()
    lines = content.splitlines(keepends=True)
    
    new_lines = []
    found_db_type = False
    found_db_url = False
    
    for line in lines:
        stripped = line.strip()
        
        # Handle DATABASE_TYPE
        if stripped.startswith('DATABASE_TYPE=') or stripped.startswith('#DATABASE_TYPE='):
            if not found_db_type:
                new_lines.append(f"DATABASE_TYPE={db_type}\n")
                found_db_type = True
            # Skip any additional DATABASE_TYPE lines (commented or not)
            continue
        
        # Handle DATABASE_URL
        if stripped.startswith('DATABASE_URL=') or stripped.startswith('#DATABASE_URL='):
            if not found_db_url:
                if db_url:
                    new_lines.append(f"DATABASE_URL={db_url}\n")
                elif db_type == 'sqlite':
                    # Comment out DATABASE_URL for SQLite
                    new_lines.append(f"#DATABASE_URL=\n")
                found_db_url = True
            continue
        
        new_lines.append(line)
    
    # Add if not found
    if not found_db_type:
        new_lines.append(f"DATABASE_TYPE={db_type}\n")
    if not found_db_url and db_url:
        new_lines.append(f"DATABASE_URL={db_url}\n")
    
    env_path.write_text(''.join(new_lines))
    return True


@db_cli.command()
@with_appcontext
@click.option('--to', required=True, type=click.Choice(['sqlite', 'postgresql']), 
              help='Target database type')
@click.option('--target-url', help='Target database connection URL (required for PostgreSQL)')
@click.option('--backup/--no-backup', default=True, help='Create backup before migration')
@click.option('--validate/--no-validate', default=True, help='Validate data before and after migration')
@click.option('--update-env/--no-update-env', default=True, help='Update .env file after successful migration')
def migrate(to, target_url, backup, validate, update_env):
    """Migrate data to a different database type.
    
    This command handles the complete migration workflow:
    1. Validates source and target connections
    2. Initializes target database schema if needed
    3. Clears any default data from target
    4. Migrates all data from source to target
    5. Updates .env file to use the new database
    """
    from app import db
    
    # Get current database configuration
    source_config = get_database_config()
    
    click.echo(f"Migrating from {source_config.db_type} to {to}")
    
    # For PostgreSQL, require target-url
    if to == 'postgresql' and not target_url:
        click.echo("✗ PostgreSQL migration requires --target-url")
        click.echo("  Example: flask db migrate --to postgresql --target-url \"postgresql://user:pass@localhost:5432/dbname\"")
        return
    
    # Validate different database types
    if source_config.db_type == to:
        click.echo("✗ Source and target database types are the same")
        return
    
    # Configure target database temporarily
    original_db_type = os.environ.get('DATABASE_TYPE')
    original_db_url = os.environ.get('DATABASE_URL')
    
    if target_url:
        os.environ['DATABASE_URL'] = target_url
    elif to == 'sqlite':
        os.environ.pop('DATABASE_URL', None)
    
    os.environ['DATABASE_TYPE'] = to
    target_config = get_database_config()
    
    # Test target connection
    click.echo(f"\nStep 1: Testing connection to target {to} database...")
    is_valid, error = target_config.validate_connection()
    if not is_valid:
        click.echo(f"✗ Cannot connect to target database: {error}")
        if to == 'postgresql':
            click.echo("\nPlease ensure:")
            click.echo("  1. PostgreSQL server is running")
            click.echo("  2. Database exists: CREATE DATABASE armillarylab;")
            click.echo("  3. User has permissions: GRANT ALL PRIVILEGES...")
            click.echo("  4. Connection URL is correct")
        # Restore original env
        if original_db_type:
            os.environ['DATABASE_TYPE'] = original_db_type
        if original_db_url:
            os.environ['DATABASE_URL'] = original_db_url
        return
    click.echo("✓ Target database connection successful")
    
    # Confirm migration
    click.echo(f"\nThis will migrate all data from {source_config.db_type} to {to}.")
    if update_env:
        click.echo("The .env file will be updated to use the new database after migration.")
    if not click.confirm("Proceed with migration?"):
        click.echo("Migration cancelled")
        # Restore original env
        if original_db_type:
            os.environ['DATABASE_TYPE'] = original_db_type
        if original_db_url:
            os.environ['DATABASE_URL'] = original_db_url
        return
    
    try:
        # Step 2: Initialize target database schema
        click.echo(f"\nStep 2: Initializing {to} database schema...")
        from sqlalchemy import create_engine, inspect
        
        target_engine = create_engine(target_config.connection_string, **target_config.get_engine_args())
        inspector = inspect(target_engine)
        existing_tables = inspector.get_table_names()
        target_engine.dispose()
        
        required_tables = ['targets', 'target_plans', 'imaging_sessions']
        missing_tables = [t for t in required_tables if t not in existing_tables]
        
        if missing_tables:
            click.echo(f"  Creating schema in {to} database...")
            # Temporarily switch app to target database to create schema
            from sqlalchemy import create_engine
            target_engine = create_engine(target_config.connection_string, **target_config.get_engine_args())
            db.metadata.create_all(target_engine)
            target_engine.dispose()
            click.echo("  ✓ Schema created")
        else:
            click.echo("  ✓ Schema already exists")
        
        # Step 3: Clear target database data
        click.echo(f"\nStep 3: Clearing existing data in {to} database...")
        target_engine = create_engine(target_config.connection_string, **target_config.get_engine_args())
        
        from sqlalchemy.orm import Session
        with Session(target_engine) as session:
            # Delete in reverse dependency order using raw SQL for reliability
            tables_to_clear = [
                'imaging_sessions', 'target_plans', 'targets',
                'filter_wheel_slots', 'filter_wheels', 
                'palette_filters', 'object_mappings',
                'filters', 'palettes', 'target_types', 'global_config'
            ]
            for table_name in tables_to_clear:
                try:
                    session.execute(db.text(f'DELETE FROM {table_name}'))
                except Exception:
                    pass  # Table might not exist
            session.commit()
        target_engine.dispose()
        click.echo("  ✓ Target database cleared")
        
        # Step 4: Perform migration
        click.echo(f"\nStep 4: Migrating data from {source_config.db_type} to {to}...")
        result = migrate_database(
            source_config, 
            target_config,
            validate_before=validate,
            validate_after=validate,
            backup_target=backup
        )
        
        # Display results
        click.echo("\n" + "=" * 60)
        click.echo("Migration Results")
        click.echo("=" * 60)
        click.echo(f"Status: {result['status']}")
        click.echo(f"Tables migrated: {len(result['tables_migrated'])}")
        click.echo(f"Records migrated: {result['records_migrated']}")
        
        if result.get('backup_path'):
            click.echo(f"Backup created: {result['backup_path']}")
        
        if result['errors']:
            click.echo("\nErrors:")
            for error in result['errors']:
                click.echo(f"  ✗ {error}")
        
        if result['warnings']:
            click.echo("\nWarnings:")
            for warning in result['warnings']:
                click.echo(f"  ⚠ {warning}")
        
        if result['status'] == 'completed':
            click.echo("\n✓ Migration completed successfully")
            
            # Step 5: Update .env file
            if update_env:
                click.echo(f"\nStep 5: Updating .env file to use {to}...")
                try:
                    update_env_file(to, target_url)
                    click.echo(f"  ✓ .env file updated")
                    click.echo(f"\n🎉 Migration complete! Your app is now configured to use {to}.")
                    click.echo("   Restart your Flask server to use the new database.")
                except Exception as e:
                    click.echo(f"  ⚠ Could not update .env file: {e}")
                    click.echo(f"\n  Please manually update your .env file:")
                    click.echo(f"    DATABASE_TYPE={to}")
                    if target_url:
                        click.echo(f"    DATABASE_URL={target_url}")
        else:
            click.echo(f"\n✗ Migration failed")
            # Restore original env
            if original_db_type:
                os.environ['DATABASE_TYPE'] = original_db_type
            if original_db_url:
                os.environ['DATABASE_URL'] = original_db_url
            
    except Exception as e:
        click.echo(f"\n✗ Migration error: {str(e)}")
        # Restore original env
        if original_db_type:
            os.environ['DATABASE_TYPE'] = original_db_type
        if original_db_url:
            os.environ['DATABASE_URL'] = original_db_url


@db_cli.command()
@with_appcontext
def backup():
    """Create a backup of the current database."""
    db_config = get_database_config()
    
    if db_config.db_type == 'sqlite':
        source_path = db_config.connection_string.replace('sqlite:///', '')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{source_path}.backup_{timestamp}"
        
        try:
            import shutil
            shutil.copy2(source_path, backup_path)
            click.echo(f"✓ SQLite backup created: {backup_path}")
        except Exception as e:
            click.echo(f"✗ Backup failed: {str(e)}")
    
    elif db_config.db_type == 'postgresql':
        click.echo("PostgreSQL backup requires pg_dump. Please use:")
        click.echo("pg_dump DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql")
    
    else:
        click.echo(f"Backup not supported for database type: {db_config.db_type}")


@db_cli.command()
@with_appcontext
def reset():
    """Reset database (drop all tables and reinitialize)."""
    if not click.confirm("Are you sure you want to reset the database? This will delete ALL data!"):
        click.echo("Reset cancelled")
        return
    
    from app import db
    
    try:
        click.echo("Dropping all tables...")
        db.drop_all()
        
        click.echo("Reinitializing database...")
        db.create_all()
        
        click.echo("✓ Database reset completed")
        
    except Exception as e:
        click.echo(f"✗ Reset failed: {str(e)}")


def register_cli_commands(app):
    """Register CLI commands with Flask app."""
    app.cli.add_command(db_cli, 'db')