"""
Database Configuration Module

Handles database type detection, connection string building, and configuration
for both SQLite and PostgreSQL databases with environment-based selection.
"""
import os
from urllib.parse import urlparse
from pathlib import Path


class DatabaseConfig:
    """Database configuration manager with support for SQLite and PostgreSQL."""
    
    SUPPORTED_DATABASES = ['sqlite', 'postgresql']
    DEFAULT_DATABASE_TYPE = 'sqlite'
    
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or Path(__file__).parent.parent
        self.db_type = self._detect_database_type()
        self.connection_string = self._build_connection_string()
        self.pool_config = self._get_pool_config()
    
    def _detect_database_type(self):
        """Detect database type from environment variables or URL."""
        # 1. Explicit DATABASE_TYPE environment variable
        db_type = os.getenv('DATABASE_TYPE', '').lower()
        if db_type in self.SUPPORTED_DATABASES:
            return db_type
        
        # 2. Parse DATABASE_URL to detect type
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            parsed = urlparse(database_url)
            if parsed.scheme in ['postgresql', 'postgres']:
                return 'postgresql'
            elif parsed.scheme == 'sqlite':
                return 'sqlite'
        
        # 3. Cloud platform detection
        if self._is_cloud_environment():
            return 'postgresql'
        
        # 4. Default fallback
        return self.DEFAULT_DATABASE_TYPE
    
    def _is_cloud_environment(self):
        """Detect if running in cloud environment where PostgreSQL is preferred."""
        cloud_indicators = [
            'PORT',  # Heroku
            'KUBERNETES_SERVICE_HOST',  # Kubernetes
            'GAE_APPLICATION',  # Google App Engine
            'AWS_EXECUTION_ENV',  # AWS Lambda/ECS
            'WEBSITE_INSTANCE_ID',  # Azure
        ]
        return any(os.getenv(indicator) for indicator in cloud_indicators)
    
    def _build_connection_string(self):
        """Build appropriate connection string based on database type."""
        if self.db_type == 'postgresql':
            return self._build_postgresql_url()
        else:
            return self._build_sqlite_url()
    
    def _build_postgresql_url(self):
        """Build PostgreSQL connection URL."""
        # Use DATABASE_URL if provided
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            return database_url
        
        # Build from individual components
        host = os.getenv('DB_HOST', 'localhost')
        port = os.getenv('DB_PORT', '5432')
        database = os.getenv('DB_NAME', 'armillarylab')
        username = os.getenv('DB_USER', 'armillarylab')
        password = os.getenv('DB_PASSWORD', '')
        
        # Handle SSL mode
        ssl_mode = os.getenv('DB_SSL_MODE', 'prefer')
        ssl_param = f'?sslmode={ssl_mode}' if ssl_mode else ''
        
        if password:
            return f'postgresql://{username}:{password}@{host}:{port}/{database}{ssl_param}'
        else:
            return f'postgresql://{username}@{host}:{port}/{database}{ssl_param}'
    
    def _build_sqlite_url(self):
        """Build SQLite connection URL."""
        # Use DATABASE_URL if it's SQLite
        database_url = os.getenv('DATABASE_URL')
        if database_url and database_url.startswith('sqlite://'):
            return database_url
        
        # Use SQLITE_PATH if provided
        sqlite_path = os.getenv('SQLITE_PATH')
        if sqlite_path:
            if os.path.isabs(sqlite_path):
                return f'sqlite:///{sqlite_path}'
            else:
                from pathlib import Path
                base_path = Path(self.base_dir) if isinstance(self.base_dir, str) else self.base_dir
                full_path = base_path / sqlite_path
                return f'sqlite:///{full_path}'
        
        # Default SQLite path
        if self.base_dir:
            from pathlib import Path
            base_path = Path(self.base_dir) if isinstance(self.base_dir, str) else self.base_dir
            db_path = base_path / 'armillarylab.db'
        else:
            db_path = 'armillarylab.db'
        
        return f'sqlite:///{db_path}'
    
    def _get_pool_config(self):
        """Get database connection pool configuration."""
        if self.db_type == 'postgresql':
            return {
                'pool_size': int(os.getenv('DB_POOL_SIZE', '10')),
                'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '30')),
                'pool_recycle': int(os.getenv('DB_POOL_RECYCLE', '3600')),
                'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '20')),
                'pool_pre_ping': True,  # Verify connections before use
            }
        else:
            # SQLite connection pool config
            return {
                'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '20')),
                'pool_recycle': int(os.getenv('DB_POOL_RECYCLE', '-1')),
                'connect_args': {
                    'check_same_thread': False,
                    'timeout': int(os.getenv('SQLITE_TIMEOUT', '20')),
                }
            }
    
    def get_engine_args(self):
        """Get SQLAlchemy engine arguments for the configured database type."""
        base_args = {
            'echo': os.getenv('DB_ECHO', 'false').lower() == 'true',
        }
        
        if self.db_type == 'postgresql':
            base_args.update(self.pool_config)
        else:
            # SQLite specific arguments
            base_args['connect_args'] = self.pool_config['connect_args']
            
            # Enable WAL mode for better concurrency
            if os.getenv('SQLITE_WAL_MODE', 'true').lower() == 'true':
                base_args['connect_args']['isolation_level'] = None
        
        return base_args
    
    def validate_connection(self):
        """Validate that database connection can be established."""
        from sqlalchemy import create_engine, text
        
        try:
            engine = create_engine(self.connection_string, **self.get_engine_args())
            with engine.connect() as conn:
                if self.db_type == 'postgresql':
                    conn.execute(text('SELECT 1'))
                else:
                    conn.execute(text('SELECT 1'))
            engine.dispose()
            return True, None
        except Exception as e:
            return False, str(e)
    
    def get_info(self):
        """Get database configuration information."""
        return {
            'type': self.db_type,
            'connection_string': self.connection_string,
            'pool_config': self.pool_config,
            'base_dir': str(self.base_dir),
        }


def get_database_config(base_dir=None):
    """Factory function to get database configuration."""
    return DatabaseConfig(base_dir)


def get_flask_config(base_dir=None):
    """Get Flask-compatible database configuration."""
    db_config = get_database_config(base_dir)
    
    flask_config = {
        'SQLALCHEMY_DATABASE_URI': db_config.connection_string,
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_ENGINE_OPTIONS': db_config.get_engine_args(),
    }
    
    return flask_config, db_config