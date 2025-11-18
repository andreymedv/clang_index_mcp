# Testing Guide

This guide covers all testing features for the Clang Index MCP project.

## Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=mcp_server --cov-report=html

# Run specific test categories
pytest tests/ -m security
pytest tests/ -m "not slow"
```

## Test Categories

### By Priority
- `critical` - P0 tests that must pass before release
- `slow` - Long-running tests (excluded by default)

### By Type
- `base_functionality` - Core features (indexing, search, hierarchy)
- `error_handling` - Error recovery and resilience
- `security` - Security vulnerabilities (ReDoS, path traversal, injection)
- `robustness` - Data integrity and atomic operations
- `edge_case` - Boundary conditions and extreme inputs
- `integration` - Integration tests with MCP protocol
- `benchmark` - Performance benchmarks

## Running Tests

### Basic Usage

```bash
# All tests
pytest tests/

# Verbose output
pytest tests/ -v

# With coverage
pytest tests/ --cov=mcp_server --cov-report=html --cov-report=term

# Specific marker
pytest tests/ -m security

# Exclude slow tests
pytest tests/ -m "not slow"

# Run tests in parallel
pytest tests/ -n auto
```

### HTML Test Reports

Generate HTML test reports:

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

### Performance Benchmarks

Run performance benchmarks:

```bash
# Run all benchmarks
pytest tests/performance/ -v

# Run specific benchmark category
pytest tests/performance/test_benchmarks.py::TestPerformanceBenchmarks -v

# Run benchmarks with detailed output
pytest tests/performance/ -v -s
```

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

## Coverage Reports

### Generate Coverage

```bash
# Terminal report
pytest tests/ --cov=mcp_server --cov-report=term-missing

# HTML report
pytest tests/ --cov=mcp_server --cov-report=html

# Both
pytest tests/ --cov=mcp_server --cov-report=html --cov-report=term
```

### View HTML Coverage

```bash
# Generate and open
pytest tests/ --cov=mcp_server --cov-report=html
python3 -m http.server --directory htmlcov 8000
# Open http://localhost:8000 in browser
```

## Continuous Integration

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

## Test Structure

```
tests/
├── base_functionality/     # Core feature tests
│   ├── test_core_features.py
│   ├── test_cache.py
│   ├── test_compile_commands.py
│   └── test_vcpkg.py
├── security/               # Security tests
│   ├── test_regex_security.py
│   ├── test_path_security.py
│   └── test_command_security.py
├── integration/            # Integration tests
│   ├── test_mcp_protocol.py
│   └── test_mcp_tools.py
├── performance/            # Performance benchmarks
│   └── test_benchmarks.py
├── error_handling/         # Error handling tests
├── robustness/            # Data integrity tests
├── edge_cases/            # Edge case tests
├── platform/              # Platform-specific tests
└── conftest.py            # Shared fixtures
```

## Writing Tests

### Test Structure

```python
import pytest
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.security
@pytest.mark.critical
class TestSecurity:
    """Test security features"""

    def test_redos_prevention(self, temp_project_dir):
        """Test ReDoS attack prevention"""
        # Setup
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Test
        with pytest.raises(RegexValidationError):
            analyzer.search_classes("(a+)+b")
```

### Using Fixtures

```python
def test_with_fixtures(temp_project_dir, analyzer):
    """Use pre-configured fixtures"""
    # temp_project_dir: Temporary C++ project
    # analyzer: Pre-configured CppAnalyzer
    count = analyzer.index_project()
    assert count > 0
```

## Troubleshooting

### Tests Failing

```bash
# Run with verbose output
pytest tests/ -vv

# Show local variables in failures
pytest tests/ --showlocals

# Drop into debugger on failure
pytest tests/ --pdb
```

### Slow Tests

```bash
# Profile test execution
pytest tests/ --durations=10

# Run only fast tests
pytest tests/ -m "not slow"
```

### Import Errors

```bash
# Ensure you're in project root
cd /path/to/clang_index_mcp
python3 -m pytest tests/
```

## Test Metrics

Target metrics for this project:

- **Coverage**: >85%
- **Pass Rate**: 100%
- **Mutation Score**: >80%
- **Critical Tests**: 100% passing
- **Performance**: All benchmarks meet targets

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [mutmut Documentation](https://mutmut.readthedocs.io/)
- [pytest-html Documentation](https://pytest-html.readthedocs.io/)
