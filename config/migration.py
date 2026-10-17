"""
Database Migration Engine

Handles bidirectional data migration between SQLite and PostgreSQL databases
with validation, progress tracking, and rollback capabilities.
"""
import json
import logging
import os
import subprocess
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import create_engine, MetaData, Table, select, insert, text, inspect, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)

REQUIRED_TABLES = [
    'targets', 'target_plans', 'imaging_sessions', 'calibration_captures',
    'calibration_checkpoint_skips', 'filters', 'palettes', 'target_types',
    'global_config', 'filter_wheels', 'filter_wheel_slots', 'object_mappings',
    'palette_filters', 'mosaic_groups', 'resolver_cache',
]


class PgDumpUnavailableError(RuntimeError):
    """pg_dump is not installed, so no PostgreSQL backup can be taken."""


def create_postgresql_backup(db_config, stamp: str) -> str:
    """Dump a PostgreSQL database with pg_dump. Raises rather than skipping."""
    pg_dump = shutil.which('pg_dump')
    if not pg_dump:
        raise PgDumpUnavailableError(
            "pg_dump was not found on PATH, so the PostgreSQL database cannot be "
            "backed up. Install the PostgreSQL client tools, or take a platform-level "
            "snapshot yourself and re-run with --no-backup to acknowledge that."
        )

    url = make_url(db_config.connection_string)
    if not url.database:
        raise RuntimeError(
            "PostgreSQL connection string has no database name, so pg_dump cannot run."
        )
    base_dir = Path(getattr(db_config, 'base_dir', None) or '.')
    backup_path = base_dir / f"{url.database}_backup_{stamp}.dump"

    cmd = [pg_dump, '--format=custom', '--file', str(backup_path)]
    if url.host:
        cmd += ['--host', url.host]
    if url.port:
        cmd += ['--port', str(url.port)]
    if url.username:
        cmd += ['--username', url.username]
    cmd.append(url.database)

    env = os.environ.copy()
    if url.password:
        env['PGPASSWORD'] = url.password  # never passed on the command line

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("pg_dump timed out.") from e

    if result.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}). {result.stderr.strip()}"
        )

    logger.info(f"PostgreSQL backup created: {backup_path}")
    return str(backup_path)


def reset_postgresql_sequences(conn, table_names) -> None:
    """Move each table's id sequence past MAX(id) so new inserts don't collide."""
    if conn.dialect.name != 'postgresql':
        return
    quote = conn.dialect.identifier_preparer.quote
    for table_name in table_names:
        qt = quote(table_name)
        conn.execute(text(
            f"SELECT setval(pg_get_serial_sequence(:t, 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {qt}), 1), "
            f"(SELECT MAX(id) FROM {qt}) IS NOT NULL)"
        ), {"t": table_name})


class DatabaseMigrator:
    """Handles bidirectional database migration between SQLite and PostgreSQL."""
    
    def __init__(self, source_config, target_config):
        self.source_config = source_config
        self.target_config = target_config
        self.source_engine = None
        self.target_engine = None
        self.migration_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
    def __enter__(self):
        """Context manager entry."""
        self.source_engine = create_engine(
            self.source_config.connection_string,
            **self.source_config.get_engine_args()
        )
        self.target_engine = create_engine(
            self.target_config.connection_string,
            **self.target_config.get_engine_args()
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.source_engine:
            self.source_engine.dispose()
        if self.target_engine:
            self.target_engine.dispose()
    
    def migrate_database(self, 
                        validate_before: bool = True,
                        validate_after: bool = True,
                        backup_target: bool = True) -> Dict[str, Any]:
        """
        Perform complete database migration.
        
        Args:
            validate_before: Validate source database before migration
            validate_after: Validate target database after migration
            backup_target: Create backup of target database before migration
            
        Returns:
            Migration result dictionary with status, stats, and any errors
        """
        migration_result = {
            'migration_id': self.migration_id,
            'source_type': self.source_config.db_type,
            'target_type': self.target_config.db_type,
            'started_at': datetime.now().isoformat(),
            'status': 'started',
            'tables_migrated': [],
            'records_migrated': 0,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Step 1: Pre-migration validation
            if validate_before:
                logger.info("Validating source database...")
                source_valid, source_errors = self.validate_database(self.source_engine)
                if not source_valid:
                    migration_result['status'] = 'failed'
                    migration_result['errors'].extend(source_errors)
                    return migration_result
            
            # Step 2: Backup target database if requested
            if backup_target:
                logger.info("Creating backup of target database...")
                backup_path = self.create_backup(self.target_config)
                migration_result['backup_path'] = backup_path
            
            # Step 3: Export data from source database
            logger.info("Exporting data from source database...")
            exported_data = self.export_database(self.source_engine)
            migration_result['tables_exported'] = len(exported_data)
            
            # Step 4: Prepare target database schema
            logger.info("Preparing target database schema...")
            self.prepare_target_schema()
            
            # Step 5: Import data to target database
            logger.info("Importing data to target database...")
            import_result = self.import_database(self.target_engine, exported_data)
            migration_result.update(import_result)
            
            # Step 6: Post-migration validation
            if validate_after:
                logger.info("Validating target database...")
                target_valid, target_errors = self.validate_database(self.target_engine)
                if not target_valid:
                    migration_result['warnings'].extend(target_errors)
                
                # Compare record counts
                count_validation = self.validate_record_counts(exported_data)
                migration_result['count_validation'] = count_validation
            
            migration_result['status'] = 'completed'
            migration_result['completed_at'] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            migration_result['status'] = 'failed'
            migration_result['errors'].append(str(e))
            migration_result['failed_at'] = datetime.now().isoformat()
        
        return migration_result
    
    def export_database(self, engine) -> Dict[str, List[Dict[str, Any]]]:
        """Export all data from database maintaining relationships."""
        exported_data = {}
        
        # Get table metadata
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Define table order for export (respecting foreign keys)
        table_order = self._get_table_export_order(metadata)
        
        with engine.connect() as conn:
            for table_name in table_order:
                table = metadata.tables[table_name]
                logger.info(f"Exporting table: {table_name}")
                
                # Export all records from table
                result = conn.execute(select(table))
                records = []
                
                for row in result:
                    record = {}
                    for key, value in row._mapping.items():
                        if isinstance(value, datetime):
                            record[key] = value.isoformat()
                        elif hasattr(value, 'isoformat'):
                            record[key] = value.isoformat()
                        else:
                            record[key] = value
                    records.append(record)
                
                exported_data[table_name] = records
                logger.info(f"Exported {len(records)} records from {table_name}")
        
        return exported_data
    
    def import_database(self, engine, data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Import data to database maintaining relationships."""
        import_result = {
            'tables_migrated': [],
            'records_migrated': 0,
            'import_errors': [],
            'warnings': [],
        }
        
        # Get table metadata for target
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Define table order for import (respecting foreign keys)
        table_order = self._get_table_import_order(metadata)
        
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                for table_name in table_order:
                    if table_name not in data:
                        continue
                    
                    table = metadata.tables[table_name]
                    records = data[table_name]
                    
                    if not records:
                        continue
                    
                    logger.info(f"Importing {len(records)} records to {table_name}")

                    target_columns = set(table.c.keys())
                    skipped_columns = sorted(set(records[0].keys()) - target_columns)
                    if skipped_columns:
                        msg = (
                            f"{table_name}: source columns not present in target were skipped: "
                            f"{', '.join(skipped_columns)}"
                        )
                        logger.warning(msg)
                        import_result['warnings'].append(msg)

                    processed_records = []
                    for record in records:
                        processed_record = {}
                        for key, value in record.items():
                            if key not in target_columns:
                                continue
                            if isinstance(value, str) and (key.endswith('_at') or key == 'date'):
                                try:
                                    processed_record[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                except (ValueError, AttributeError):
                                    processed_record[key] = value
                            else:
                                processed_record[key] = value
                        processed_records.append(processed_record)
                    
                    # Insert records in batches
                    batch_size = 1000
                    for i in range(0, len(processed_records), batch_size):
                        batch = processed_records[i:i+batch_size]
                        conn.execute(insert(table), batch)
                    
                    import_result['tables_migrated'].append(table_name)
                    import_result['records_migrated'] += len(records)

                reset_postgresql_sequences(
                    conn,
                    [t for t in import_result['tables_migrated'] if 'id' in metadata.tables[t].c],
                )
                trans.commit()
                logger.info("Database import completed successfully")
                
            except Exception as e:
                trans.rollback()
                logger.error(f"Import failed, rolling back: {str(e)}")
                import_result['import_errors'].append(str(e))
                raise
        
        return import_result
    
    def _get_table_export_order(self, metadata) -> List[str]:
        """Get table names in export order (FK dependencies first)."""
        return [t.name for t in metadata.sorted_tables]
    
    def _get_table_import_order(self, metadata) -> List[str]:
        """Get table names in import order (same as export for this app)."""
        return self._get_table_export_order(metadata)
    
    def prepare_target_schema(self):
        """Ensure target database has the correct schema."""
        # Check if tables exist in target
        inspector = inspect(self.target_engine)
        existing_tables = inspector.get_table_names()
        
        missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]
        
        if missing_tables:
            logger.warning(f"Missing tables in target database: {missing_tables}")
            logger.warning("Please run 'flask init-db' on the target database first to create the schema.")
            raise ValueError(
                f"Target database is missing required tables: {missing_tables}. "
                f"Please initialize the target database schema first by running: "
                f"DATABASE_TYPE={self.target_config.db_type} flask init-db"
            )
        
        logger.info("Target schema validation completed - all required tables exist")
    
    def validate_database(self, engine) -> Tuple[bool, List[str]]:
        """Validate database integrity and structure."""
        errors = []
        
        try:
            with engine.connect() as conn:
                # Test basic connectivity
                conn.execute(text('SELECT 1'))
                
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                
                required_tables = [
                    'targets', 'target_plans', 'imaging_sessions',
                    'calibration_captures', 'calibration_checkpoint_skips',
                ]
                missing_tables = [table for table in required_tables if table not in tables]
                
                if missing_tables:
                    errors.append(f"Missing required tables: {missing_tables}")
                
                return len(errors) == 0, errors
                
        except Exception as e:
            errors.append(f"Database validation failed: {str(e)}")
            return False, errors
    
    def validate_record_counts(self, exported_data: Dict[str, List]) -> Dict[str, Dict]:
        """Validate that record counts match between source and target."""
        count_validation = {}
        
        try:
            with self.target_engine.connect() as conn:
                metadata = MetaData()
                metadata.reflect(bind=self.target_engine)
                
                for table_name, exported_records in exported_data.items():
                    if table_name in metadata.tables:
                        table = metadata.tables[table_name]
                        # SQLAlchemy 2.0 syntax for count
                        result = conn.execute(select(func.count()).select_from(table))
                        target_count = result.scalar()
                        
                        count_validation[table_name] = {
                            'source_count': len(exported_records),
                            'target_count': target_count,
                            'match': len(exported_records) == target_count
                        }
        
        except Exception as e:
            logger.error(f"Count validation failed: {str(e)}")
        
        return count_validation
    
    def create_backup(self, db_config) -> Optional[str]:
        """Back up the target database before migration. Raises if it cannot."""
        if db_config.db_type == 'sqlite':
            source_path = db_config.connection_string.replace('sqlite:///', '')
            backup_path = f"{source_path}.backup_{self.migration_id}"

            if not Path(source_path).exists():
                logger.info("SQLite target %s does not exist yet; nothing to back up.", source_path)
                return None
            try:
                shutil.copy2(source_path, backup_path)
                logger.info(f"SQLite backup created: {backup_path}")
                return backup_path
            except Exception as e:
                raise RuntimeError(
                    f"Failed to back up SQLite target {source_path}: {e}. "
                    f"Migration aborted so the target is left untouched."
                ) from e

        return self._create_postgresql_backup(db_config)

    def _create_postgresql_backup(self, db_config) -> str:
        return create_postgresql_backup(db_config, self.migration_id)


def migrate_database(source_config, target_config, **kwargs) -> Dict[str, Any]:
    """Convenience function to perform database migration."""
    with DatabaseMigrator(source_config, target_config) as migrator:
        return migrator.migrate_database(**kwargs)