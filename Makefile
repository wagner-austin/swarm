# Makefile for Discord Bot project

.PHONY: install lint format test clean run docs build backup

# Python command (use python or py depending on your system)
PYTHON := python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy

# Install dependencies
install:
	$(PIP) install -e .

# Run linting checks (ruff check --fix, ruff format, black, mypy strict)
lint:
	$(PIP) install types-requests
	$(RUFF) check --fix .
	$(RUFF) format .
	$(MYPY) --strict .

# Format code
format:
	$(RUFF) format .
	$(PYTHON) -m black .

# Run tests
test:
	$(PYTEST)

# Clean up temporary files and caches
clean:
	-del /s /q *.pyc *.pyo *.pyd 2>nul
	-if exist __pycache__ rd /s /q __pycache__ 2>nul
	-if exist .pytest_cache rd /s /q .pytest_cache 2>nul
	-if exist .ruff_cache rd /s /q .ruff_cache 2>nul
	-if exist .mypy_cache rd /s /q .mypy_cache 2>nul
	-if exist *.egg-info rd /s /q *.egg-info 2>nul

# Run the bot
run:
	$(PYTHON) -m bot.core

# Generate documentation (update this if you use a specific doc generator)
docs:
	@echo Documentation generation command goes here

# Build the project package
build:
	$(PYTHON) -m build

# Use savecode to save files
savecode:
	savecode . --skip tests --ext toml py

# Use savecode to save files
savecode-test:
	savecode . --ext toml py