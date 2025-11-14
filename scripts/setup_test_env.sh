#!/bin/bash
# Test Environment Setup Script for Clang Index MCP
# This script sets up the complete test environment

set -e  # Exit on error

echo "=========================================="
echo "Clang Index MCP - Test Environment Setup"
echo "=========================================="
echo ""

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Python version
echo "Checking Python version..."
if ! command_exists python3; then
    echo "ERROR: Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "Found Python $PYTHON_VERSION"
echo ""

# Check pip
echo "Checking pip..."
if ! command_exists pip3; then
    echo "ERROR: pip3 is not installed. Please install pip3."
    exit 1
fi
echo "pip3 is available"
echo ""

# Upgrade pip
echo "Upgrading pip..."
python3 -m pip install --upgrade pip
echo ""

# Install test dependencies
echo "Installing test dependencies from requirements-test.txt..."
pip3 install -r requirements-test.txt
echo ""

# Verify installations
echo "Verifying installations..."
echo ""

echo -n "  pytest: "
if python3 -c "import pytest; print(pytest.__version__)" 2>/dev/null; then
    echo "    ✓ installed"
else
    echo "    ✗ FAILED"
    exit 1
fi

echo -n "  pytest-cov: "
if python3 -c "import pytest_cov; print('OK')" 2>/dev/null; then
    echo " ✓ installed"
else
    echo " ✗ FAILED"
    exit 1
fi

echo -n "  pytest-xdist: "
if python3 -c "import xdist; print('OK')" 2>/dev/null; then
    echo "✓ installed"
else
    echo "✗ FAILED"
    exit 1
fi

echo -n "  pytest-timeout: "
if python3 -c "import pytest_timeout; print('OK')" 2>/dev/null; then
    echo "✓ installed"
else
    echo "✗ FAILED"
    exit 1
fi

echo -n "  pytest-mock: "
if python3 -c "import pytest_mock; print('OK')" 2>/dev/null; then
    echo "✓ installed"
else
    echo "✗ FAILED"
    exit 1
fi

echo -n "  libclang: "
if python3 -c "import clang.cindex; print('OK')" 2>/dev/null; then
    echo "  ✓ installed"
else
    echo "  ✗ FAILED"
    exit 1
fi

echo -n "  mcp: "
if python3 -c "import mcp; print('OK')" 2>/dev/null; then
    echo "      ✓ installed"
else
    echo "      ✗ FAILED"
    exit 1
fi

echo ""
echo "=========================================="
echo "Test Environment Setup Complete!"
echo "=========================================="
echo ""
echo "You can now run tests with:"
echo "  pytest tests/"
echo ""
echo "Run specific test categories:"
echo "  pytest -m base_functionality"
echo "  pytest -m security"
echo "  pytest -m critical"
echo ""
echo "Run with coverage:"
echo "  pytest --cov=mcp_server tests/"
echo ""
echo "Run infrastructure smoke test:"
echo "  pytest tests/test_infrastructure.py -v"
echo ""
