.PHONY: install lint check help

help:
	@echo "warmpath-agents (archived) — available targets:"
	@echo "  make install   Install direct dependencies"
	@echo "  make lint      Run ruff over the tracked packages"
	@echo "  make check     Import orchestrator module (smoke test)"

install:
	python3 -m pip install -e ".[dev]"

lint:
	python3 -m ruff check agents data_team finance_team gtm_team mcp_server ops_team product_team

# Smoke test: resolve the CLI surface without invoking any agent.
# Confirms the import graph is coherent. A full run also needs the
# WarmPath product repo — see README.
check:
	python3 -m agents.orchestrator --help >/dev/null
	@echo "orchestrator --help OK"
