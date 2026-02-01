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
    click.echo("AstroPlanner Database Configuration")
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


@db_cli.command()
@with_appcontext
@click.option('--to', required=True, type=click.Choice(['sqlite', 'postgresql']), 
              help='Target database type')
@click.option('--target-url', help='Target database connection URL')
@click.option('--backup/--no-backup', default=True, help='Create backup before migration')
@click.option('--validate/--no-validate', default=True, help='Validate data before and after migration')
def migrate(to, target_url, backup, validate):
    """Migrate data to a different database type."""
    
    # Get current database configuration
    source_config = get_database_config()
    
    click.echo(f"Migrating from {source_config.db_type} to {to}")
    
    # Configure target database
    if target_url:
        os.environ['DATABASE_URL'] = target_url
    
    os.environ['DATABASE_TYPE'] = to
    target_config = get_database_config()
    
    # Validate different database types
    if source_config.db_type == target_config.db_type:
        click.echo("✗ Source and target database types are the same")
        return
    
    # Test target connection first
    click.echo(f"Testing connection to target {to} database...")
    is_valid, error = target_config.validate_connection()
    if not is_valid:
        click.echo(f"✗ Cannot connect to target database: {error}")
        click.echo(f"\nPlease ensure the target database exists and is accessible.")
        if to == 'postgresql':
            click.echo("  1. Create the database: CREATE DATABASE astroplanner;")
            click.echo("  2. Create the user and grant permissions")
            click.echo("  3. Verify the connection URL is correct")
        return
    click.echo("✓ Target database connection successful")
    
    # Confirm migration
    if not click.confirm(f"Are you sure you want to migrate from {source_config.db_type} to {to}?"):
        click.echo("Migration cancelled")
        return
    
    try:
        # Perform migration
        with click.progressbar(length=100, label="Migrating database") as bar:
            result = migrate_database(
                source_config, 
                target_config,
                validate_before=validate,
                validate_after=validate,
                backup_target=backup
            )
            bar.update(100)
        
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
        else:
            click.echo(f"\n✗ Migration failed")
            
    except ValueError as e:
        # Schema-related errors with helpful guidance
        click.echo(f"\n✗ Migration error: {str(e)}")
        click.echo("\nTo fix this, you need to initialize the target database schema first:")
        click.echo(f"  1. Set environment: $env:DATABASE_TYPE = '{to}'")
        if target_url:
            click.echo(f"  2. Set URL: $env:DATABASE_URL = '{target_url}'")
        click.echo(f"  3. Initialize schema: flask init-db")
        click.echo(f"  4. Clear default data (see DATABASE_GUIDE.md)")
        click.echo(f"  5. Re-run migration: flask db migrate --to {to}" + (f" --target-url \"{target_url}\"" if target_url else ""))
    except Exception as e:
        click.echo(f"\n✗ Migration error: {str(e)}")


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