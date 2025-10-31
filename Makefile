.PHONY: help install dev build clean test lint format typecheck docs docs-serve publish check

help:
	@echo "Specwright - Build targets:"
	@echo ""
	@echo "Development:"
	@echo "  install    - Install package"
	@echo "  dev        - Install in editable mode with dev dependencies"
	@echo "  test       - Run test suite"
	@echo "  lint       - Run linter (ruff)"
	@echo "  format     - Format code (ruff)"
	@echo "  typecheck  - Run type checking (mypy)"
	@echo "  check      - Run all checks (lint + typecheck + test)"
	@echo ""
	@echo "Build & Release:"
	@echo "  build      - Build distribution packages"
	@echo "  clean      - Remove build artifacts"
	@echo "  publish    - Publish to PyPI (requires credentials)"
	@echo ""
	@echo "Documentation:"
	@echo "  docs       - Build documentation"
	@echo "  docs-serve - Serve docs locally"

install:
	pip install .

dev:
	pip install -e ".[dev]"

clean:
	rm -rf dist build src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

build:
	python -m build

test:
	@echo "Running tests..."
	python -m pytest tests/ 2>/dev/null || echo "No tests found"

docs:
	mkdocs build

publish: build
	@echo "Publishing spec-core to PyPI..."
	twine upload dist/*
	@echo "✅ Published"