.PHONY: help setup clean test test-coverage lint format check install run dev

# Detect operating system
ifeq ($(OS),Windows_NT)
DETECTED_OS := Windows
else
DETECTED_OS := $(shell uname -s)
endif

# Set platform-specific variables
ifeq ($(DETECTED_OS),Windows)
PYTHON := python
VENV_BIN := mcp_env\Scripts
ACTIVATE := $(VENV_BIN)\activate
RM := del /Q
RMDIR := rmdir /S /Q
else
PYTHON := python3
VENV_BIN := mcp_env/bin
ACTIVATE := source $(VENV_BIN)/activate
RM := rm -f
RMDIR := rm -rf
endif

# Colors for output (Unix-like systems)
ifndef NO_COLOR
	GREEN := \033[0;32m
	BLUE := \033[0;34m
	YELLOW := \033[0;33m
	RED := \033[0;31m
	NC := \033[0m # No Color
endif

help: ## Show this help message
	@echo "$(BLUE)Clang Index MCP - Development Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

setup: ## Set up development environment
	@echo "$(BLUE)Setting up development environment...$(NC)"
ifeq ($(OS),Windows_NT)
	server_setup.bat
else
	./server_setup.sh
endif
	@echo "$(GREEN)Setup complete!$(NC)"
	@echo "Activate environment: $(ACTIVATE)"

install: ## Install dependencies in existing environment
	@echo "$(BLUE)Installing dependencies...$(NC)"
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	@echo "$(GREEN)Dependencies installed!$(NC)"

install-dev: ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install pytest pytest-cov pytest-asyncio black flake8 mypy pre-commit
	@echo "$(GREEN)Development dependencies installed!$(NC)"

install-editable: ## Install package in editable mode for development
	@echo "$(BLUE)Installing package in editable mode...$(NC)"
	$(PYTHON) -m pip install -e .
	@echo "$(GREEN)Package installed in editable mode!$(NC)"
	@echo "You can now run: clang-index-mcp"

test: ## Run all tests
	@echo "$(BLUE)Running tests...$(NC)"
	$(PYTHON) -m pytest -v
	@echo "$(GREEN)Tests complete!$(NC)"

test-coverage: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	$(PYTHON) -m pytest --cov=mcp_server --cov-report=html --cov-report=term -v
	@echo "$(GREEN)Coverage report generated in htmlcov/$(NC)"

test-compile-commands: ## Run compile_commands integration tests
	@echo "$(BLUE)Running compile_commands integration tests...$(NC)"
	$(PYTHON) tests/test_runner.py
	@echo "$(GREEN)Compile commands tests complete!$(NC)"

test-installation: ## Test installation and basic functionality
	@echo "$(BLUE)Testing installation...$(NC)"
	$(PYTHON) scripts/test_installation.py
	@echo "$(GREEN)Installation test complete!$(NC)"

lint: ## Run linting checks (flake8)
	@echo "$(BLUE)Running linting checks...$(NC)"
	$(PYTHON) -m flake8 mcp_server/ scripts/ --exclude=scripts/archived/ --max-line-length=100 --ignore=E501,W503,E203
	@echo "$(GREEN)Linting complete!$(NC)"

format: ## Format code with black
	@echo "$(BLUE)Formatting code...$(NC)"
	$(PYTHON) -m black mcp_server/ scripts/ --line-length=100
	@echo "$(GREEN)Code formatted!$(NC)"

format-check: ## Check code formatting without making changes
	@echo "$(BLUE)Checking code format...$(NC)"
	$(PYTHON) -m black mcp_server/ scripts/ --line-length=100 --check
	@echo "$(GREEN)Format check complete!$(NC)"

type-check: ## Run type checking with mypy
	@echo "$(BLUE)Running type checks...$(NC)"
	$(PYTHON) -m mypy mcp_server/ --ignore-missing-imports
	@echo "$(GREEN)Type checking complete!$(NC)"

check: format-check lint type-check ## Run all checks (format, lint, type)
	@echo "$(GREEN)All checks passed!$(NC)"

run: ## Run the MCP server
	@echo "$(BLUE)Starting MCP server...$(NC)"
	$(PYTHON) -m mcp_server.cpp_mcp_server

dev: ## Run in development mode with debug output
	@echo "$(BLUE)Starting MCP server in development mode...$(NC)"
	MCP_DEBUG=1 PYTHONUNBUFFERED=1 $(PYTHON) -m mcp_server.cpp_mcp_server

build: ## Build wheel package
	@echo "$(BLUE)Building wheel package...$(NC)"
	$(PYTHON) -m pip install --upgrade build
	$(PYTHON) -m build
	@echo "$(GREEN)Build complete! Package available in dist/$(NC)"

build-sdist: ## Build source distribution only
	@echo "$(BLUE)Building source distribution...$(NC)"
	$(PYTHON) -m pip install --upgrade build
	$(PYTHON) -m build --sdist
	@echo "$(GREEN)Source distribution built in dist/$(NC)"

build-wheel: ## Build wheel distribution only
	@echo "$(BLUE)Building wheel distribution...$(NC)"
	$(PYTHON) -m pip install --upgrade build
	$(PYTHON) -m build --wheel
	@echo "$(GREEN)Wheel distribution built in dist/$(NC)"

install-wheel: build-wheel ## Build and install the wheel package locally
	@echo "$(BLUE)Installing wheel package...$(NC)"
	$(PYTHON) -m pip install --force-reinstall dist/*.whl
	@echo "$(GREEN)Package installed!$(NC)"

clean: ## Clean cache and build artifacts
	@echo "$(BLUE)Cleaning up...$(NC)"
ifeq ($(DETECTED_OS),Windows)
	@if exist .mcp_cache\* ( \
		for /d %%d in (.mcp_cache\*) do @rmdir /s /q "%%d" 2>nul & \
		for %%f in (.mcp_cache\*) do @if not "%%~nxf"==".gitkeep" del /q "%%f" 2>nul \
	)
else
	@find .mcp_cache -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
endif
	@$(RMDIR) __pycache__ 2>/dev/null || true
	@$(RMDIR) mcp_server/__pycache__ 2>/dev/null || true
	@$(RMDIR) scripts/__pycache__ 2>/dev/null || true
	@$(RMDIR) .pytest_cache 2>/dev/null || true
	@$(RMDIR) htmlcov 2>/dev/null || true
	@$(RMDIR) build 2>/dev/null || true
	@$(RMDIR) dist 2>/dev/null || true
	@$(RMDIR) *.egg-info 2>/dev/null || true
	@$(RMDIR) clang_index_mcp.egg-info 2>/dev/null || true
	@$(RM) .coverage 2>/dev/null || true
ifeq ($(DETECTED_OS),Windows)
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
	@for /d /r . %%d in (*.egg-info) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
	@del /s /q *.pyc 2>nul
	@del /s /q *.pyo 2>nul
else
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
endif
	@echo "$(GREEN)Cleanup complete!$(NC)"

clean-cache: ## Clean only the MCP cache
	@echo "$(BLUE)Cleaning MCP cache...$(NC)"
ifeq ($(DETECTED_OS),Windows)
	@if exist .mcp_cache\* ( \
		for /d %%d in (.mcp_cache\*) do @rmdir /s /q "%%d" 2>nul & \
		for %%f in (.mcp_cache\*) do @if not "%%~nxf"==".gitkeep" del /q "%%f" 2>nul \
	)
else
	@find .mcp_cache -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
endif
	@echo "$(GREEN)Cache cleaned!$(NC)"

clean-all: clean ## Clean everything including virtual environment
	@echo "$(BLUE)Removing virtual environment...$(NC)"
	@$(RMDIR) mcp_env 2>/dev/null || true
	@echo "$(GREEN)Complete cleanup done!$(NC)"

download-libclang: ## Download libclang binary for your platform
	@echo "$(BLUE)Downloading libclang...$(NC)"
	$(PYTHON) scripts/download_libclang.py
	@echo "$(GREEN)libclang downloaded!$(NC)"

setup-hooks: ## Configure git to use project hooks (enables pre-push tests)
	@echo "$(BLUE)Configuring git hooks...$(NC)"
	git config core.hooksPath .githooks
	@echo "$(GREEN)Git hooks configured! Pre-push will now run tests before push.$(NC)"

pre-commit-install: ## Install pre-commit hooks
	@echo "$(BLUE)Installing pre-commit hooks...$(NC)"
	$(PYTHON) -m pre_commit install
	@echo "$(GREEN)Pre-commit hooks installed!$(NC)"

pre-commit-run: ## Run pre-commit on all files
	@echo "$(BLUE)Running pre-commit on all files...$(NC)"
	$(PYTHON) -m pre_commit run --all-files
	@echo "$(GREEN)Pre-commit checks complete!$(NC)"

info: ## Show project information
	@echo "$(BLUE)Project Information$(NC)"
	@echo "$(GREEN)Python:$(NC) $$($(PYTHON) --version)"
	@echo "$(GREEN)Virtual Environment:$(NC) $(VENV_BIN)"
	@echo "$(GREEN)Working Directory:$(NC) $$(pwd)"
	@echo ""
	@echo "$(BLUE)Environment Status:$(NC)"
	@if [ -d "mcp_env" ]; then \
		echo "$(GREEN)✓$(NC) Virtual environment exists"; \
	else \
		echo "$(RED)✗$(NC) Virtual environment not found (run: make setup)"; \
	fi
	@if [ -d "lib" ] && [ -n "$$(ls -A lib 2>/dev/null)" ]; then \
		echo "$(GREEN)✓$(NC) libclang libraries present"; \
	else \
		echo "$(RED)✗$(NC) libclang libraries not found (run: make download-libclang)"; \
	fi
	@if [ -d ".mcp_cache" ]; then \
		echo "$(GREEN)✓$(NC) Cache directory exists"; \
	else \
		echo "$(YELLOW)!$(NC) No cache directory (will be created on first use)"; \
	fi

# Shortcuts
t: test ## Shortcut for test
tc: test-coverage ## Shortcut for test-coverage
tcc: test-compile-commands ## Shortcut for test-compile-commands
l: lint ## Shortcut for lint
f: format ## Shortcut for format
c: clean ## Shortcut for clean
r: run ## Shortcut for run
b: build ## Shortcut for build
ie: install-editable ## Shortcut for install-editable
