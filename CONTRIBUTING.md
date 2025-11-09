# Contributing to Clang Index MCP

Thank you for your interest in contributing to Clang Index MCP! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Process](#development-process)
- [Submitting Changes](#submitting-changes)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)

## Code of Conduct

This project follows the standard open-source code of conduct. Please be respectful and constructive in all interactions.

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Git
- Basic understanding of C++ and libclang

### Setting Up Your Development Environment

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/clang_index_mcp.git
   cd clang_index_mcp
   ```

3. Set up the development environment:
   ```bash
   # Linux/macOS
   ./server_setup.sh

   # Windows
   server_setup.bat
   ```

4. Activate the virtual environment:
   ```bash
   # Linux/macOS
   source mcp_env/bin/activate

   # Windows
   mcp_env\Scripts\activate
   ```

5. Install development dependencies:
   ```bash
   pip install -r requirements.txt
   ```

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed development setup instructions.

## Development Process

### Branching Strategy

- `main` - Stable production code
- `claude/*` - Feature branches created by Claude Code
- `feature/*` - Feature branches
- `bugfix/*` - Bug fix branches

### Creating a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### Making Changes

1. Make your changes in your feature branch
2. Write or update tests as needed
3. Update documentation if necessary
4. Run tests to ensure everything works
5. Commit your changes with clear, descriptive messages

## Submitting Changes

### Before Submitting

- [ ] Code follows project coding standards
- [ ] All tests pass
- [ ] New tests added for new functionality
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive

### Pull Request Process

1. Push your changes to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. Open a Pull Request on GitHub
3. Fill out the PR template completely
4. Link any related issues
5. Wait for review and address feedback

### PR Guidelines

- **Title**: Clear, concise description of changes
- **Description**:
  - What changes were made and why
  - How to test the changes
  - Any breaking changes or migration notes
- **Tests**: Include test results or describe testing performed
- **Documentation**: Note any documentation updates

## Coding Standards

### Python Style

- Follow PEP 8 style guide
- Use meaningful variable and function names
- Maximum line length: 100 characters (flexible for readability)
- Use type hints where appropriate
- Write docstrings for public functions and classes

### Code Organization

```python
"""Module docstring describing purpose."""

# Standard library imports
import os
import sys

# Third-party imports
from mcp.server import Server
import clang.cindex

# Local imports
from .cache_manager import CacheManager


class YourClass:
    """Class docstring."""

    def your_method(self, param: str) -> bool:
        """
        Method docstring.

        Args:
            param: Description of parameter

        Returns:
            Description of return value
        """
        pass
```

### Error Handling

- Use specific exception types
- Provide helpful error messages
- Clean up resources properly
- Log errors appropriately

### Comments

- Write self-documenting code
- Use comments to explain "why", not "what"
- Keep comments up-to-date with code changes

## Testing

### Running Tests

```bash
# Run all tests
make test

# Or directly with pytest
pytest

# Run specific test file
pytest tests/test_specific.py

# Run with coverage
make test-coverage
```

### Writing Tests

- Write tests for all new functionality
- Test edge cases and error conditions
- Use descriptive test names
- Keep tests simple and focused

### Test Structure

```python
def test_feature_name_scenario():
    """Test that feature handles specific scenario correctly."""
    # Arrange
    analyzer = CppAnalyzer("/path/to/project")

    # Act
    result = analyzer.some_method()

    # Assert
    assert result.is_valid()
```

## Documentation

### Code Documentation

- All public classes, methods, and functions should have docstrings
- Use Google-style or NumPy-style docstrings
- Include parameter types and return types
- Provide usage examples for complex functions

### README and Guides

- Update README.md if adding new features
- Update DEVELOPMENT.md for development process changes
- Add examples for new functionality
- Keep documentation clear and concise

### Changelog

When making significant changes, update the CHANGELOG.md following [Keep a Changelog](https://keepachangelog.com/) format:

- **Added** - New features
- **Changed** - Changes in existing functionality
- **Deprecated** - Soon-to-be removed features
- **Removed** - Removed features
- **Fixed** - Bug fixes
- **Security** - Vulnerability fixes

## Questions?

If you have questions or need help:

1. Check existing issues and discussions
2. Review the documentation in the `docs/` folder
3. Open a new issue with the "question" label

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
