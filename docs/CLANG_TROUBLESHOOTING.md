# Clang Installation Troubleshooting Guide

## Overview

The Clang Index MCP project uses `libclang` - Python bindings to the LLVM Clang compiler's C API. This guide helps diagnose and fix common installation issues.

## Quick Diagnosis

Run our diagnostic script:
```bash
python3 scripts/diagnose_clang.py
```

To automatically fix issues:
```bash
python3 scripts/diagnose_clang.py --fix
```

---

## Understanding libclang

**Two components are required:**

1. **Python package** (`libclang`): Python bindings installed via pip
2. **Shared library** (libclang.so/.dll/.dylib): The actual C/C++ library

**Common confusion**: The pip package bundles the library, but sometimes the library isn't found due to path/environment issues.

---

## Common Issues and Solutions

### Issue 1: "clang package not found" after pip install

**Symptoms:**
```
[FATAL] clang package not found. Install with: pip install libclang
ImportError: No module named 'clang.cindex'
```

**Diagnosis:**
```bash
# Check if package is installed
pip show libclang

# Try importing directly
python3 -c "import clang.cindex; print('Success!')"
```

**Solutions:**

#### Solution A: Reinstall libclang
```bash
pip install --force-reinstall libclang
```

#### Solution B: Install specific version
```bash
pip install libclang==18.1.1
```

#### Solution C: Use virtual environment (recommended)
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install libclang
```

#### Solution D: Check Python path
```bash
# Ensure you're using the right Python
which python3
python3 -m pip install libclang
```

---

### Issue 2: Library not found / Can't load shared library

**Symptoms:**
```
OSError: libclang.so: cannot open shared object file
OSError: [WinError 126] The specified module could not be found
dyld: Library not loaded: libclang.dylib
```

**Diagnosis:**
```bash
python3 scripts/diagnose_clang.py
```

**Solutions:**

#### Linux:
```bash
# Option 1: Install system libclang
sudo apt-get update
sudo apt-get install libclang-dev

# Option 2: Install LLVM
sudo apt-get install llvm

# Option 3: Set library path
export LD_LIBRARY_PATH=/usr/lib/llvm-16/lib:$LD_LIBRARY_PATH
```

#### macOS:
```bash
# Install LLVM via Homebrew
brew install llvm

# Set library path
export LIBCLANG_PATH=/opt/homebrew/opt/llvm/lib/libclang.dylib

# For Intel Macs:
export LIBCLANG_PATH=/usr/local/opt/llvm/lib/libclang.dylib
```

#### Windows:
```powershell
# Download LLVM from: https://github.com/llvm/llvm-project/releases

# Set environment variable
setx LIBCLANG_PATH "C:\Program Files\LLVM\bin\libclang.dll"

# Or add to PATH
setx PATH "%PATH%;C:\Program Files\LLVM\bin"
```

---

### Issue 3: Version conflicts / Multiple Python installations

**Symptoms:**
- Works in terminal but not in tests
- Works with `python` but not `python3`
- Works globally but not in virtual environment

**Diagnosis:**
```bash
# Check all Python installations
which -a python python3

# Check where libclang is installed
python3 -m pip show libclang
python -m pip show libclang

# Check sys.path
python3 -c "import sys; print('\n'.join(sys.path))"
```

**Solutions:**

#### Solution A: Use specific Python everywhere
```bash
# Always use the same Python executable
/usr/local/bin/python3 -m pip install libclang
/usr/local/bin/python3 -m pytest tests/
```

#### Solution B: Create fresh virtual environment
```bash
# Remove old venv
rm -rf venv

# Create new with specific Python
/usr/bin/python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
```

#### Solution C: Fix IDE Python interpreter
- In PyCharm/VSCode: Select correct interpreter
- Point to venv/bin/python if using virtual environment
- Restart IDE after changing interpreter

---

### Issue 4: Architecture mismatch (32-bit vs 64-bit)

**Symptoms:**
```
OSError: wrong ELF class: ELFCLASS32
OSError: [WinError 193] %1 is not a valid Win32 application
```

**Diagnosis:**
```bash
# Check Python architecture
python3 -c "import struct; print(struct.calcsize('P') * 8, 'bit')"

# Check libclang architecture (Linux)
file $(python3 -c "import clang.cindex; print(clang.cindex.conf.lib._name)")
```

**Solution:**
- Install matching architecture Python and libclang
- Most systems use 64-bit - ensure you're using 64-bit Python
```bash
# Install 64-bit Python (if needed)
# Then reinstall libclang
pip install --force-reinstall libclang
```

---

### Issue 5: Works in CLI but fails in pytest

**Symptoms:**
- `python3 -c "import clang.cindex"` works
- `pytest tests/` fails with import error

**Diagnosis:**
```bash
# Check pytest Python
pytest --version

# Run pytest with verbose Python info
python3 -m pytest --version
```

**Solutions:**

#### Solution A: Use Python module invocation
```bash
# Instead of:
pytest tests/

# Use:
python3 -m pytest tests/
```

#### Solution B: Check pytest installation
```bash
# Ensure pytest uses same Python
which pytest
python3 -m pip show pytest

# Reinstall pytest
python3 -m pip install --force-reinstall pytest
```

#### Solution C: Set PYTHONPATH
```bash
# Ensure project root in path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python3 -m pytest tests/
```

---

### Issue 6: Permission errors

**Symptoms:**
```
PermissionError: [Errno 13] Permission denied
Could not find write access to cache directory
```

**Solution:**
```bash
# Don't use sudo with pip (creates permission issues)
# Instead use --user flag or virtual environment

# Fix existing permission issues
sudo chown -R $USER:$USER ~/.local
sudo chown -R $USER:$USER venv/

# Or use virtual environment (preferred)
python3 -m venv venv
source venv/bin/activate
pip install libclang
```

---

## Environment-Specific Setup

### Docker/Container Environments

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libclang-dev \
    llvm \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install -r requirements.txt
```

### CI/CD (GitHub Actions)

```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    pip install libclang>=16.0.0
    pip install -r requirements.txt
    pip install -r requirements-test.txt

- name: Verify libclang
  run: |
    python -c "import clang.cindex; print('libclang OK')"
    python scripts/diagnose_clang.py
```

### Shared Hosting / Limited Access

If you can't install system packages:
```bash
# Use bundled library from pip package
pip install --user libclang

# Or download pre-built LLVM binaries
wget https://github.com/llvm/llvm-project/releases/download/llvmorg-16.0.0/clang+llvm-16.0.0-x86_64-linux-gnu-ubuntu-22.04.tar.xz
tar xf clang+llvm-*.tar.xz
export LD_LIBRARY_PATH=$(pwd)/clang+llvm-*/lib:$LD_LIBRARY_PATH
```

---

## Best Practices

### 1. Always Use Virtual Environments
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Pin Versions
```
# In requirements.txt
libclang==18.1.1
```

### 3. Document System Dependencies
```bash
# Create install_deps.sh
#!/bin/bash
# For Ubuntu/Debian
sudo apt-get install libclang-dev llvm

# For macOS
brew install llvm
```

### 4. Test After Installation
```bash
# Quick test
python3 -c "from clang.cindex import Index; Index.create(); print('OK')"

# Comprehensive test
python3 scripts/diagnose_clang.py
```

---

## Debugging Checklist

When libclang issues occur, check:

- [ ] Python version is 3.8+ (`python3 --version`)
- [ ] libclang package installed (`pip show libclang`)
- [ ] Can import clang.cindex (`python3 -c "import clang.cindex"`)
- [ ] Can create Index (`python3 -c "from clang.cindex import Index; Index.create()"`)
- [ ] Using same Python everywhere (terminal, IDE, pytest)
- [ ] Virtual environment activated if using one
- [ ] No permission issues on packages directory
- [ ] System libclang installed (Linux/macOS) or LLVM (Windows)

---

## Getting Help

If issues persist after trying these solutions:

1. Run diagnostic script and save output:
```bash
python3 scripts/diagnose_clang.py > clang_diagnosis.txt 2>&1
```

2. Include in bug report:
   - Operating system and version
   - Python version (`python3 --version`)
   - libclang version (`pip show libclang`)
   - Full diagnostic output
   - Full error message and stack trace

3. Check existing issues: https://github.com/llvm/llvm-project/issues

---

## Advanced: Manual Library Configuration

If automatic detection fails, manually configure:

```python
# In your code before importing
import clang.cindex

# Set library path manually
clang.cindex.Config.set_library_path('/usr/lib/llvm-16/lib')

# Or set library file directly
clang.cindex.Config.set_library_file('/usr/lib/x86_64-linux-gnu/libclang-16.so.1')

# Then use normally
from clang.cindex import Index
index = Index.create()
```

---

**Last Updated**: 2025-11-14
**Maintainer**: Clang Index MCP Team
