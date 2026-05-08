"""
Database Migration Engine

Handles bidirectional data migration between SQLite and PostgreSQL databases
with validation, progress tracking, and rollback capabilities.
"""
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import create_engine, MetaData, Table, select, insert, text, inspect, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)


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
                    # Convert row to dictionary, handling special types
                    record = {}
                    for key, value in row._mapping.items():
                        if isinstance(value, datetime):
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
            'import_errors': []
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
                    
                    # Convert datetime strings back to datetime objects
                    processed_records = []
                    for record in records:
                        processed_record = {}
                        for key, value in record.items():
                            if key.endswith('_at') or key.endswith('date') and isinstance(value, str):
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
                
                trans.commit()
                logger.info("Database import completed successfully")
                
            except Exception as e:
                trans.rollback()
                logger.error(f"Import failed, rolling back: {str(e)}")
                import_result['import_errors'].append(str(e))
                raise
        
        return import_result
    
    def _get_table_export_order(self, metadata) -> List[str]:
        """Get table names in export order (dependencies first)."""
        # For ArmillaryLab, the dependency order is:
        # 1. Independent tables (no foreign keys)
        # 2. Tables with foreign keys to independent tables
        # 3. Tables with foreign keys to dependent tables
        
        # Level 1: No foreign key dependencies
        independent_tables = ['target_types', 'palettes', 'global_config', 'filters', 'filter_wheels']
        
        # Level 2: Depend on independent tables
        level2_tables = ['targets', 'object_mappings', 'filter_wheel_slots', 'palette_filters']
        
        # Level 3: Depend on level 2 tables
        level3_tables = ['target_plans', 'imaging_sessions']
        
        # Filter to only existing tables
        all_tables = set(metadata.tables.keys())
        export_order = []
        
        for table in independent_tables:
            if table in all_tables:
                export_order.append(table)
        
        for table in level2_tables:
            if table in all_tables:
                export_order.append(table)
                
        for table in level3_tables:
            if table in all_tables:
                export_order.append(table)
        
        # Add any remaining tables
        remaining_tables = all_tables - set(export_order)
        export_order.extend(sorted(remaining_tables))
        
        return export_order
    
    def _get_table_import_order(self, metadata) -> List[str]:
        """Get table names in import order (same as export for this app)."""
        return self._get_table_export_order(metadata)
    
    def prepare_target_schema(self):
        """Ensure target database has the correct schema."""
        # Check if tables exist in target
        inspector = inspect(self.target_engine)
        existing_tables = inspector.get_table_names()
        
        required_tables = ['targets', 'target_plans', 'imaging_sessions', 'filters', 
                          'palettes', 'target_types', 'global_config', 'filter_wheels',
                          'filter_wheel_slots', 'object_mappings', 'palette_filters']
        
        missing_tables = [t for t in required_tables if t not in existing_tables]
        
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
                
                # Check if main tables exist
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                
                required_tables = ['targets', 'target_plans', 'imaging_sessions']
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
        """Create backup of database before migration."""
        if db_config.db_type == 'sqlite':
            # For SQLite, copy the database file
            source_path = db_config.connection_string.replace('sqlite:///', '')
            backup_path = f"{source_path}.backup_{self.migration_id}"
            
            try:
                shutil.copy2(source_path, backup_path)
                logger.info(f"SQLite backup created: {backup_path}")
                return backup_path
            except Exception as e:
                logger.error(f"Failed to create SQLite backup: {str(e)}")
                return None
        
        else:
            # For PostgreSQL, would need pg_dump (not implemented in this version)
            logger.warning("PostgreSQL backup not implemented")
            return None


def migrate_database(source_config, target_config, **kwargs) -> Dict[str, Any]:
    """Convenience function to perform database migration."""
    with DatabaseMigrator(source_config, target_config) as migrator:
        return migrator.migrate_database(**kwargs)