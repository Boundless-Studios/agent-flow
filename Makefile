SHELL := /bin/bash

PYTHON ?= python3.11
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python
PIP := $(BIN)/pip
RUN_DIR := .run
PID_FILE := $(RUN_DIR)/sessionbus-hub.pid
LOG_FILE := $(RUN_DIR)/sessionbus-hub.log

.PHONY: help setup setup-core setup-dev setup-desktop setup-mcp setup-all readme test launch launch-ui mcp shutdown status logs clean

help:
	@echo "SessionBus developer commands"
	@echo "  make setup         - Create .venv and install all extras (recommended)"
	@echo "  make setup-core    - Install core runtime only"
	@echo "  make setup-dev     - Install core + test dependencies"
	@echo "  make setup-desktop - Install desktop UI dependencies"
	@echo "  make setup-mcp     - Install MCP dependencies"
	@echo "  make setup-all     - Alias for setup"
	@echo "  make readme        - Print README"
	@echo "  make test          - Run pytest"
	@echo "  make launch        - Start headless hub in background"
	@echo "  make launch-ui     - Launch desktop UI"
	@echo "  make mcp           - Run MCP server over stdio"
	@echo "  make status        - Show process/runtime status"
	@echo "  make logs          - Tail hub logs"
	@echo "  make shutdown      - Stop background hub"
	@echo "  make clean         - Remove local runtime/caches"

$(VENV):
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

setup-core: $(VENV)
	$(PIP) install -e .

setup-dev: $(VENV)
	$(PIP) install -e ".[dev]"

setup-desktop: $(VENV)
	$(PIP) install -e ".[desktop]"

setup-mcp: $(VENV)
	$(PIP) install -e ".[mcp]"

setup-all setup: $(VENV)
	$(PIP) install -e ".[all]"

readme:
	@cat README.md

test:
	$(PY) -m pytest -q

launch:
	@mkdir -p $(RUN_DIR)
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "SessionBus hub already running with PID $$(cat "$(PID_FILE)")"; \
		exit 0; \
	fi
	@nohup $(BIN)/sessionbus-hub > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@sleep 1
	@echo "Started SessionBus hub (PID $$(cat "$(PID_FILE)"))"
	@$(MAKE) status

launch-ui:
	$(BIN)/agent-flow

mcp:
	$(BIN)/sessionbus-mcp

shutdown:
	@if [ ! -f "$(PID_FILE)" ]; then \
		echo "No PID file found ($(PID_FILE)). Nothing to stop."; \
		exit 0; \
	fi
	@if kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		kill $$(cat "$(PID_FILE)"); \
		echo "Stopped SessionBus hub PID $$(cat "$(PID_FILE)")"; \
	else \
		echo "Process in PID file is not running."; \
	fi
	@rm -f "$(PID_FILE)"

status:
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "Hub process: running (PID $$(cat "$(PID_FILE)"))"; \
	else \
		echo "Hub process: not running"; \
	fi
	@if [ -f "$$HOME/.sessionbus/runtime.json" ]; then \
		echo "Runtime file: $$HOME/.sessionbus/runtime.json"; \
		cat "$$HOME/.sessionbus/runtime.json"; \
	else \
		echo "Runtime file not found: $$HOME/.sessionbus/runtime.json"; \
	fi

logs:
	@mkdir -p $(RUN_DIR)
	@touch $(LOG_FILE)
	tail -n 100 -f "$(LOG_FILE)"

clean:
	rm -rf $(RUN_DIR) .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
