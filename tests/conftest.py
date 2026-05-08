"""
Test Configuration for Database Testing

Provides test database configurations and utilities for testing
both SQLite and PostgreSQL implementations.
"""
import os
import tempfile
from pathlib import Path

import pytest
from config.database import DatabaseConfig


class TestDatabaseConfig:
    """Test database configuration utility."""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sqlite_path = os.path.join(self.temp_dir, "test.db")
    
    def get_sqlite_config(self):
        """Get SQLite test configuration."""
        config = DatabaseConfig()
        config.db_type = 'sqlite'
        config.connection_string = f'sqlite:///{self.sqlite_path}'
        config.pool_config = {
            'connect_args': {
                'timeout': 30,
                'check_same_thread': False
            }
        }
        return config
    
    def get_postgresql_config(self):
        """Get PostgreSQL test configuration."""
        # Use environment variable or default test database
        test_db_url = os.getenv(
            'TEST_DATABASE_URL',
            'postgresql://test:test@localhost:5432/test_armillarylab'
        )
        
        config = DatabaseConfig()
        config.db_type = 'postgresql'
        config.connection_string = test_db_url
        config.pool_config = {
            'pool_size': 5,
            'pool_timeout': 30,
            'pool_recycle': 3600
        }
        return config
    
    def cleanup(self):
        """Clean up test resources."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


@pytest.fixture
def test_db_config():
    """Pytest fixture for test database configuration."""
    config = TestDatabaseConfig()
    yield config
    config.cleanup()


@pytest.fixture
def sqlite_config(test_db_config):
    """Pytest fixture for SQLite test configuration."""
    return test_db_config.get_sqlite_config()


@pytest.fixture
def postgresql_config(test_db_config):
    """Pytest fixture for PostgreSQL test configuration."""
    return test_db_config.get_postgresql_config()


@pytest.fixture(params=['sqlite', 'postgresql'])
def db_config(request, test_db_config):
    """Pytest fixture that provides both database types for parametrized tests."""
    if request.param == 'sqlite':
        return test_db_config.get_sqlite_config()
    elif request.param == 'postgresql':
        # Skip PostgreSQL tests if not available
        try:
            config = test_db_config.get_postgresql_config()
            is_valid, _ = config.validate_connection()
            if not is_valid:
                pytest.skip("PostgreSQL test database not available")
            return config
        except Exception:
            pytest.skip("PostgreSQL test database not available")


def requires_postgresql(func):
    """Decorator to skip tests that require PostgreSQL."""
    return pytest.mark.skipif(
        not os.getenv('TEST_DATABASE_URL'),
        reason="PostgreSQL test database not configured"
    )(func)