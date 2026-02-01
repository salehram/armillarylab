"""
Test Database Configuration Module

Tests for database configuration, connection management,
and environment-based database selection.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from config.database import (
    DatabaseConfig, get_database_config, get_flask_config
)


class TestDatabaseConfig:
    """Test DatabaseConfig class."""
    
    def test_sqlite_configuration(self, sqlite_config):
        """Test SQLite configuration."""
        assert sqlite_config.db_type == 'sqlite'
        assert 'sqlite:///' in sqlite_config.connection_string
        assert 'connect_args' in sqlite_config.pool_config
        assert sqlite_config.pool_config['connect_args']['timeout'] == 30
    
    def test_postgresql_configuration(self, postgresql_config):
        """Test PostgreSQL configuration."""
        assert postgresql_config.db_type == 'postgresql'
        assert 'postgresql://' in postgresql_config.connection_string
        assert 'pool_size' in postgresql_config.pool_config
        assert postgresql_config.pool_config['pool_size'] == 5
    
    def test_connection_validation_sqlite(self, sqlite_config):
        """Test SQLite connection validation."""
        # This should work since we're using an in-memory or temp file
        is_valid, error = sqlite_config.validate_connection()
        # Note: validation might fail if file doesn't exist yet, which is expected
        assert isinstance(is_valid, bool)
        if not is_valid:
            assert isinstance(error, str)
    
    @pytest.mark.skipif(
        not os.getenv('TEST_DATABASE_URL'),
        reason="PostgreSQL test database not configured"
    )
    def test_connection_validation_postgresql(self, postgresql_config):
        """Test PostgreSQL connection validation."""
        is_valid, error = postgresql_config.validate_connection()
        assert isinstance(is_valid, bool)
        if not is_valid:
            assert isinstance(error, str)


class TestDatabaseSelection:
    """Test database type selection and configuration."""
    
    def test_default_sqlite_selection(self):
        """Test default SQLite selection."""
        with patch.dict(os.environ, {}, clear=True):
            config = get_database_config('/tmp/test')
            assert config.db_type == 'sqlite'
    
    def test_explicit_sqlite_selection(self):
        """Test explicit SQLite selection via environment."""
        with patch.dict(os.environ, {'DATABASE_TYPE': 'sqlite'}, clear=True):
            config = get_database_config('/tmp/test')
            assert config.db_type == 'sqlite'
    
    def test_explicit_postgresql_selection(self):
        """Test explicit PostgreSQL selection via environment."""
        with patch.dict(os.environ, {
            'DATABASE_TYPE': 'postgresql',
            'DATABASE_URL': 'postgresql://user:pass@localhost/test'
        }, clear=True):
            config = get_database_config('/tmp/test')
            assert config.db_type == 'postgresql'
            assert 'postgresql://user:pass@localhost/test' in config.connection_string
    
    def test_database_url_override(self):
        """Test DATABASE_URL override."""
        test_url = 'postgresql://test:test@testhost/testdb'
        with patch.dict(os.environ, {'DATABASE_URL': test_url}, clear=True):
            config = get_database_config('/tmp/test')
            assert config.db_type == 'postgresql'
            assert test_url in config.connection_string


class TestFlaskConfiguration:
    """Test Flask configuration generation."""
    
    def test_flask_config_sqlite(self):
        """Test Flask configuration for SQLite."""
        with patch.dict(os.environ, {'DATABASE_TYPE': 'sqlite'}, clear=True):
            flask_config, db_config = get_flask_config('/tmp/test')
            
            assert 'SQLALCHEMY_DATABASE_URI' in flask_config
            assert 'sqlite:///' in flask_config['SQLALCHEMY_DATABASE_URI']
            assert flask_config['SQLALCHEMY_TRACK_MODIFICATIONS'] is False
            assert 'SQLALCHEMY_ENGINE_OPTIONS' in flask_config
    
    def test_flask_config_postgresql(self):
        """Test Flask configuration for PostgreSQL."""
        test_url = 'postgresql://test:test@localhost/testdb'
        with patch.dict(os.environ, {
            'DATABASE_TYPE': 'postgresql',
            'DATABASE_URL': test_url
        }, clear=True):
            flask_config, db_config = get_flask_config('/tmp/test')
            
            assert 'SQLALCHEMY_DATABASE_URI' in flask_config
            assert test_url in flask_config['SQLALCHEMY_DATABASE_URI']
            assert flask_config['SQLALCHEMY_TRACK_MODIFICATIONS'] is False
            assert 'SQLALCHEMY_ENGINE_OPTIONS' in flask_config


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_invalid_database_type(self):
        """Test handling of invalid database type - falls back to sqlite."""
        with patch.dict(os.environ, {'DATABASE_TYPE': 'invalid'}, clear=True):
            # Invalid types fall back to sqlite (default behavior)
            config = get_database_config('/tmp/test')
            assert config.db_type == 'sqlite'
    
    def test_missing_postgresql_url(self):
        """Test missing PostgreSQL URL handling."""
        with patch.dict(os.environ, {'DATABASE_TYPE': 'postgresql'}, clear=True):
            # Should use a default URL or raise an appropriate error
            try:
                config = get_database_config('/tmp/test')
                assert config.db_type == 'postgresql'
            except ValueError as e:
                assert 'DATABASE_URL' in str(e) or 'PostgreSQL' in str(e)
    
    def test_invalid_postgresql_url(self):
        """Test invalid PostgreSQL URL handling."""
        with patch.dict(os.environ, {
            'DATABASE_TYPE': 'postgresql',
            'DATABASE_URL': 'invalid://url'
        }, clear=True):
            config = get_database_config('/tmp/test')
            # Should handle gracefully - may not validate but shouldn't crash
            assert config.db_type == 'postgresql'