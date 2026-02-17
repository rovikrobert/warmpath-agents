"""Orchestrator — CLI entry point for running the WarmPath agent team.

Usage:
    python -m agents.orchestrator --all          # Run all agents + lead brief
    python -m agents.orchestrator --agent architect   # Run a single agent
    python -m agents.orchestrator --lead-only    # Generate brief from cached reports
    python -m agents.orchestrator --weekly       # Generate weekly trend report
    python -m agents.orchestrator --intel-update # Refresh external intelligence cache
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so the orchestrator works when invoked
# directly (python agents/orchestrator.py) as well as via -m flag.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.shared.config import AGENT_NAMES, REPORTS_DIR
from agents.shared.report import AgentReport, merge_reports
from agents.lead.lead import (
    generate_daily_brief,
    generate_weekly_report,
    record_brief_metrics,
    save_report,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent registry — maps agent name to its module's scan() function
# ---------------------------------------------------------------------------

_AGENT_MODULES = {
    "architect": "agents.architect.architect",
    "test_engineer": "agents.test_engineer.test_engineer",
    "perf_monitor": "agents.perf_monitor.perf_monitor",
    "deps_manager": "agents.deps_manager.deps_manager",
    "doc_keeper": "agents.doc_keeper.doc_keeper",
    "security": "agents.security.security",
    "privy": "agents.privy.privy",
}


def _run_agent(name: str) -> AgentReport | None:
    """Import and run a single agent's scan(), save its report."""
    module_path = _AGENT_MODULES.get(name)
    if not module_path:
        logger.error("Unknown agent: %s (known: %s)", name, ", ".join(_AGENT_MODULES))
        return None

    try:
        module = importlib.import_module(module_path)
        scan_fn = getattr(module, "scan", None)
        if scan_fn is None:
            logger.error("Agent %s has no scan() function", name)
            return None

        logger.info("Running %s ...", name)
        report = scan_fn()
        save_report(report)
        logger.info(
            "  %s: %d findings in %.1fs",
            name, len(report.findings), report.scan_duration_seconds,
        )
        return report
    except Exception as exc:
        logger.error("Agent %s failed: %s", name, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_all(skip_tests: bool = False) -> None:
    """Run all agents, then generate the daily brief."""
    start = time.time()
    reports: list[AgentReport] = []

    agents_to_run = list(_AGENT_MODULES.keys())
    if skip_tests:
        agents_to_run = [a for a in agents_to_run if a != "test_engineer"]

    for name in agents_to_run:
        report = _run_agent(name)
        if report:
            reports.append(report)

    if not reports:
        print("No agents produced reports.")
        return

    # Merge and record metrics
    all_findings = merge_reports(reports)
    record_brief_metrics(all_findings)

    # Generate and print brief
    brief = generate_daily_brief(reports)
    print("\n" + brief)

    elapsed = time.time() - start
    print(f"\n---\nTotal orchestration time: {elapsed:.1f}s ({len(reports)} agents)")


def cmd_agent(name: str) -> None:
    """Run a single agent and print its report."""
    report = _run_agent(name)
    if report:
        print(report.to_markdown())
    else:
        print(f"Agent '{name}' failed to produce a report.", file=sys.stderr)
        sys.exit(1)


def cmd_lead_only() -> None:
    """Generate brief from cached reports (no scanning)."""
    brief = generate_daily_brief()
    print(brief)


def cmd_weekly() -> None:
    """Generate weekly trend report."""
    report = generate_weekly_report()
    print(report)


def cmd_intel_update() -> None:
    """Refresh external intelligence cache."""
    from agents.shared.intelligence import get_all_intelligence
    intel = get_all_intelligence()
    advisories = intel.get("advisories", [])
    deps = intel.get("dep_versions", {})
    print(f"Intelligence updated:")
    print(f"  Advisories: {len(advisories)} found")
    print(f"  Dependencies checked: {len(deps)}")
    print(f"  API status: {len(intel.get('api_status', {}))} endpoints")
    print(f"  Framework updates: {len(intel.get('framework_updates', []))} items")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WarmPath Engineering Agent Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all agents + daily brief")
    group.add_argument("--agent", type=str, help="Run a single agent by name")
    group.add_argument("--lead-only", action="store_true", help="Brief from cached reports")
    group.add_argument("--weekly", action="store_true", help="Weekly trend report")
    group.add_argument("--intel-update", action="store_true", help="Refresh intelligence cache")

    parser.add_argument("--skip-tests", action="store_true", help="Skip test_engineer (faster)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.all:
        cmd_all(skip_tests=args.skip_tests)
    elif args.agent:
        cmd_agent(args.agent)
    elif args.lead_only:
        cmd_lead_only()
    elif args.weekly:
        cmd_weekly()
    elif args.intel_update:
        cmd_intel_update()


if __name__ == "__main__":
    main()
