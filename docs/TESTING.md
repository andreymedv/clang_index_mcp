# Testing Guide for Clang Index MCP

This document describes how to set up the test environment, run tests, and interpret results for the Clang Index MCP project.

## Table of Contents

- [Quick Start](#quick-start)
- [Test Environment Setup](#test-environment-setup)
- [Running Tests](#running-tests)
- [Test Organization](#test-organization)
- [Test Markers](#test-markers)
- [Coverage Reports](#coverage-reports)
- [Mutation Testing](#mutation-testing)
- [HTML Test Reports](#html-test-reports)
- [Writing Tests](#writing-tests)
- [Troubleshooting](#troubleshooting)
- [Continuous Integration](#continuous-integration)

> **Platform-specific notes:** For macOS-specific testing issues, see [TESTING_MACOS.md](TESTING_MACOS.md).

---

## Quick Start

### Automated Setup (Recommended)

```bash
# Run the automated setup script
./scripts/setup_test_env.sh

# Verify installation
pytest tests/test_infrastructure.py -v
```

### Manual Setup

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run infrastructure smoke test
pytest tests/test_infrastructure.py -v
```

---

## Test Environment Setup

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- libclang (installed automatically via requirements)

### Installation Steps

#### Option 1: Automated Script

The easiest way to set up the test environment:

```bash
./scripts/setup_test_env.sh
```

This script will:
1. Check Python and pip versions
2. Upgrade pip to the latest version
3. Install all test dependencies from `requirements-test.txt`
4. Verify all installations
5. Display usage examples

#### Option 2: Manual Installation

If you prefer manual control:

```bash
# Upgrade pip
python3 -m pip install --upgrade pip

# Install test dependencies
pip install -r requirements-test.txt

# Verify pytest installation
pytest --version
```

### Test Dependencies

The following packages are installed (see `requirements-test.txt`):

- **pytest** (≥9.0.0) - Core testing framework
- **pytest-cov** (≥7.0.0) - Coverage reporting
- **pytest-xdist** (≥3.8.0) - Parallel test execution
- **pytest-timeout** (≥2.4.0) - Timeout protection
- **pytest-mock** (≥3.15.0) - Mocking utilities
- **libclang** (≥16.0.0) - C++ parsing (from requirements.txt)
- **mcp** (≥1.0.0) - MCP SDK (from requirements.txt)

---

## Running Tests

### Run All Tests

```bash
# Run all tests with default configuration
pytest

# Run all tests with verbose output
pytest -v

# Run all tests in parallel (faster)
pytest -n auto
```

### Run Specific Test Files

```bash
# Run infrastructure smoke test
pytest tests/test_infrastructure.py -v

# Run base functionality tests
pytest tests/base_functionality/ -v

# Run security tests
pytest tests/security/ -v
```

### Run Tests by Marker

```bash
# Run only critical P0 tests
pytest -m critical -v

# Run security tests
pytest -m security -v

# Run base functionality tests
pytest -m base_functionality -v

# Run all tests except slow ones
pytest -m "not slow" -v

# Run critical security tests
pytest -m "critical and security" -v
```

### Run with Coverage

```bash
# Run tests with coverage report
pytest --cov=mcp_server tests/

# Generate HTML coverage report
pytest --cov=mcp_server --cov-report=html tests/

# Open coverage report in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Run Specific Tests

```bash
# Run a specific test class
pytest tests/test_infrastructure.py::TestInfrastructure -v

# Run a specific test function
pytest tests/test_infrastructure.py::TestInfrastructure::test_temp_dir_fixture -v

# Run tests matching a pattern
pytest -k "test_temp" -v
```

---

## Test Organization

### Directory Structure

```
tests/
├── base_functionality/    # Core MCP server feature tests
├── error_handling/        # Error handling and recovery tests
├── security/              # Security tests (P0 critical)
├── robustness/            # Data integrity tests (P0 critical)
├── edge_cases/            # Boundary and edge case tests
├── platform/              # Platform-specific tests
├── fixtures/              # C++ test fixture files
│   ├── classes/
│   ├── functions/
│   ├── inheritance/
│   ├── templates/
│   ├── namespaces/
│   └── call_graph/
├── utils/                 # Test utilities and helpers
│   ├── __init__.py
│   └── test_helpers.py
├── conftest.py            # Pytest fixtures and configuration
└── test_infrastructure.py # Infrastructure smoke tests
```

### Test Execution Order

Tests should be executed in the following phases:

1. **Phase 0**: Infrastructure validation (`test_infrastructure.py`)
2. **Phase 1**: Base functionality tests
3. **Phase 2**: Error handling tests
4. **Phase 3**: Security tests (P0 critical)
5. **Phase 4**: Robustness tests (P0 critical)
6. **Phase 5**: Edge case tests
7. **Phase 6**: Platform-specific tests

---

## Test Markers

Tests are categorized using pytest markers. Use markers to run specific test categories.

### Category Markers

| Marker | Description | Priority |
|--------|-------------|----------|
| `base_functionality` | Core MCP server features | P1 |
| `error_handling` | Error handling and recovery | P1 |
| `security` | Security tests (path traversal, injection) | P0 |
| `robustness` | Data integrity, atomic operations | P0 |
| `edge_case` | Boundary conditions | P1 |
| `platform` | Platform-specific (Windows, Unix, macOS) | P1 |
| `critical` | P0 critical tests (must pass) | P0 |

### Other Markers

| Marker | Description |
|--------|-------------|
| `slow` | Tests that take significant time |
| `integration` | Integration tests |
| `unit` | Unit tests |
| `requires_libclang` | Requires libclang installation |

### Usage Examples

```bash
# Run only P0 critical tests
pytest -m critical -v

# Run security and robustness tests
pytest -m "security or robustness" -v

# Run all except slow tests
pytest -m "not slow" -v

# Run base functionality tests
pytest -m base_functionality -v
```

---

## Coverage Reports

### Generate Coverage Report

```bash
# Terminal report
pytest --cov=mcp_server --cov-report=term-missing tests/

# HTML report
pytest --cov=mcp_server --cov-report=html tests/
```

### Coverage Goals

- **Overall Coverage**: ≥80%
- **Security Module**: ≥90%
- **Critical Paths**: ≥85%

### View Coverage Report

```bash
# Open HTML coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux

# Or serve with HTTP
python3 -m http.server --directory htmlcov 8000
# Open http://localhost:8000 in browser
```

The HTML report shows:
- Line coverage by file
- Branch coverage
- Uncovered lines highlighted
- Coverage percentage per module

---

## Mutation Testing

Mutation testing helps identify weaknesses in your test suite by introducing small changes (mutations) to the code and verifying that tests catch them.

### Setup

```bash
# Install mutmut
pip install mutmut

# Run mutation tests
mutmut run

# Show results
mutmut results

# Show specific mutation
mutmut show <mutation-id>

# Apply a mutation to see it
mutmut apply <mutation-id>
```

### Configuration

Mutation testing is configured in `pyproject.toml`:

```toml
[tool.mutmut]
paths_to_mutate = "mcp_server/"
backup = false
runner = "pytest -x tests/"
tests_dir = "tests/"
```

### Interpreting Results

- **Killed**: Test suite caught the mutation (good!)
- **Survived**: Mutation wasn't caught (test gap!)
- **Timeout**: Mutation caused infinite loop
- **Suspicious**: Mutation changed test results but didn't fail

Target: >80% mutation score

---

## HTML Test Reports

Generate detailed HTML test reports with execution details:

```bash
# Install pytest-html
pip install pytest-html

# Run tests with HTML report
pytest tests/ --html=test-report.html --self-contained-html
```

The report will be saved to `test-report.html` and includes:
- Test results summary
- Pass/fail statistics
- Execution times
- Failure details with tracebacks

---

## Writing Tests

### Using Test Fixtures

```python
import pytest
from pathlib import Path

def test_example(temp_project_dir, analyzer):
    """Example test using fixtures."""
    # Create a test file
    (temp_project_dir / "src" / "main.cpp").write_text("""
    class TestClass {
    public:
        void method();
    };
    """)

    # Index the project
    analyzer.index_project()

    # Verify results
    classes = analyzer.search_classes("TestClass")
    assert len(classes) == 1
```

### Using Test Helpers

```python
from tests.utils.test_helpers import (
    temp_project,
    temp_compile_commands,
    setup_test_analyzer
)

def test_with_helpers():
    """Example using helper functions."""
    with temp_project() as project_root:
        # Create compile commands
        temp_compile_commands(project_root, [
            {
                "file": "src/main.cpp",
                "arguments": ["-std=c++17"]
            }
        ])

        # Set up analyzer
        analyzer = setup_test_analyzer(project_root)

        # Run test
        assert analyzer is not None
```

### Marking Tests

```python
import pytest

@pytest.mark.security
@pytest.mark.critical
def test_path_traversal():
    """Critical security test for path traversal."""
    # Test implementation
    pass

@pytest.mark.slow
def test_large_project():
    """Slow test for large project indexing."""
    # Test implementation
    pass
```

---

## Troubleshooting

### Common Issues

#### libclang Issues ⚠️ IMPORTANT

**Error**: `[FATAL] clang package not found` or `ImportError: No module named 'clang.cindex'`

**🔧 Comprehensive Solution**: See **[CLANG_TROUBLESHOOTING.md](docs/CLANG_TROUBLESHOOTING.md)** for detailed diagnosis and fixes.

**Quick Diagnosis**:
```bash
# Run automated diagnostic
python3 scripts/diagnose_clang.py

# Attempt automatic fix
python3 scripts/diagnose_clang.py --fix
```

**Quick Fixes**:
```bash
# Try 1: Reinstall
pip install --force-reinstall libclang

# Try 2: Specific version
pip install libclang==18.1.1

# Try 3: Use virtual environment (recommended)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-test.txt
```

#### Tests fail with import errors

**Solution**: Ensure you're in the project root directory:
```bash
cd /path/to/clang_index_mcp
pytest tests/
```

#### Parallel tests cause issues

**Solution**: Run tests sequentially:
```bash
pytest -n 0 tests/
```

#### Coverage report not generated

**Solution**: Install pytest-cov:
```bash
pip install pytest-cov
```

### Getting Help

1. **Check infrastructure**: Run `pytest tests/test_infrastructure.py -v`
2. **Verify dependencies**: Run `./scripts/setup_test_env.sh`
3. **Check pytest version**: Run `pytest --version`
4. **View available markers**: Run `pytest --markers`

### Debug Mode

Run tests with maximum verbosity:

```bash
# Show all output
pytest -vv -s tests/

# Show local variables on failure
pytest --showlocals tests/

# Drop into debugger on failure
pytest --pdb tests/

# Show test collection without running
pytest --collect-only tests/
```

---

## Test Configuration

### pytest.ini

Test configuration is defined in `pytest.ini`:

- **Test discovery**: `tests/` directory
- **Coverage source**: `mcp_server/` directory
- **Default options**: Verbose, short traceback, coverage
- **Markers**: All custom markers registered
- **Timeouts**: Configurable per test
- **Logging**: File and console logging configured

### Configuration Files

- `pytest.ini` - Pytest configuration
- `requirements-test.txt` - Test dependencies
- `tests/conftest.py` - Shared fixtures
- `.gitignore` - Excludes test logs and coverage reports

---

## Continuous Integration

### Running in CI/CD

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run tests with coverage
pytest --cov=mcp_server --cov-report=xml tests/

# Check coverage threshold
pytest --cov=mcp_server --cov-fail-under=80 tests/
```

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements-test.txt

      - name: Run tests
        run: |
          pytest tests/ -v --cov=mcp_server --cov-report=xml --html=test-report.html

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

      - name: Upload test report
        uses: actions/upload-artifact@v3
        with:
          name: test-report
          path: test-report.html
```

---

## Additional Resources

- [Test Coverage](./TEST_COVERAGE.md) - Detailed test coverage analysis
- [Requirements](./REQUIREMENTS.md) - System requirements
- [pytest Documentation](https://docs.pytest.org/) - Official pytest docs

---

**Last Updated**: 2025-11-14
**Version**: 1.0
