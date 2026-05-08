"""
Test Runner Script for ArmillaryLab

Provides convenient test execution with proper environment setup
for both SQLite and PostgreSQL database testing.
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path


def run_tests(test_type='all', database='all', verbose=False, coverage=False):
    """Run tests with specified configuration."""
    
    # Base directory
    base_dir = Path(__file__).parent
    
    # Set up test environment
    test_env = os.environ.copy()
    test_env['PYTHONPATH'] = str(base_dir)
    test_env['FLASK_ENV'] = 'testing'
    test_env['DATABASE_TYPE'] = 'sqlite'  # Default to SQLite for tests
    
    # Build pytest command
    cmd = ['python', '-m', 'pytest']
    
    if verbose:
        cmd.append('-v')
    
    if coverage:
        cmd.extend(['--cov=.', '--cov-report=html', '--cov-report=term'])
    
    # Select test files based on type
    if test_type == 'config':
        cmd.append('tests/test_database_config.py')
    elif test_type == 'migration':
        cmd.append('tests/test_migration.py')
    elif test_type == 'all':
        cmd.append('tests/')
    else:
        cmd.append(f'tests/test_{test_type}.py')
    
    # Database-specific configuration
    if database == 'postgresql':
        if not os.getenv('TEST_DATABASE_URL'):
            print("Warning: TEST_DATABASE_URL not set. PostgreSQL tests will be skipped.")
            print("Set TEST_DATABASE_URL to enable PostgreSQL tests:")
            print("export TEST_DATABASE_URL=postgresql://user:pass@localhost/test_db")
        test_env['DATABASE_TYPE'] = 'postgresql'
    elif database == 'sqlite':
        test_env['DATABASE_TYPE'] = 'sqlite'
    # 'all' runs with default configuration
    
    print(f"Running {test_type} tests with {database} database configuration...")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 60)
    
    # Run tests
    try:
        result = subprocess.run(cmd, env=test_env, cwd=base_dir)
        return result.returncode
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
        return 130
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description='Run ArmillaryLab tests')
    
    parser.add_argument(
        '--type', '-t',
        choices=['all', 'config', 'migration'],
        default='all',
        help='Type of tests to run (default: all)'
    )
    
    parser.add_argument(
        '--database', '-d',
        choices=['all', 'sqlite', 'postgresql'],
        default='all',
        help='Database type to test (default: all)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    
    parser.add_argument(
        '--coverage', '-c',
        action='store_true',
        help='Generate coverage report'
    )
    
    parser.add_argument(
        '--setup-env',
        action='store_true',
        help='Display environment setup instructions'
    )
    
    args = parser.parse_args()
    
    if args.setup_env:
        print_setup_instructions()
        return 0
    
    # Run tests
    exit_code = run_tests(
        test_type=args.type,
        database=args.database,
        verbose=args.verbose,
        coverage=args.coverage
    )
    
    if exit_code == 0:
        print("\n✓ All tests passed!")
    else:
        print(f"\n✗ Tests failed with exit code {exit_code}")
    
    return exit_code


def print_setup_instructions():
    """Print test environment setup instructions."""
    print("ArmillaryLab Test Environment Setup")
    print("=" * 40)
    print()
    print("1. Install test dependencies:")
    print("   pip install pytest pytest-flask pytest-cov")
    print()
    print("2. SQLite Testing (default):")
    print("   No additional setup required")
    print()
    print("3. PostgreSQL Testing (optional):")
    print("   - Set up PostgreSQL test database")
    print("   - Export TEST_DATABASE_URL environment variable:")
    print("   export TEST_DATABASE_URL=postgresql://user:pass@localhost/test_db")
    print()
    print("4. Run tests:")
    print("   python run_tests.py                    # All tests, all databases")
    print("   python run_tests.py -t config          # Database config tests only")
    print("   python run_tests.py -d sqlite          # SQLite tests only")
    print("   python run_tests.py -d postgresql      # PostgreSQL tests only")
    print("   python run_tests.py -c                 # With coverage report")
    print("   python run_tests.py -v                 # Verbose output")
    print()
    print("5. Check coverage report:")
    print("   # HTML report will be in htmlcov/ directory")
    print("   open htmlcov/index.html")


if __name__ == '__main__':
    sys.exit(main())