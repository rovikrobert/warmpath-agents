"""Data team orchestrator — CLI entry point for running data agents.

Usage:
    python -m data_team.orchestrator --all              # Run all agents
    python -m data_team.orchestrator --agent pipeline   # Run single agent
    python -m data_team.orchestrator --lead-only        # Brief from cached reports
    python -m data_team.orchestrator --weekly           # Weekly deep dive
    python -m data_team.orchestrator --monthly          # Monthly review
    python -m data_team.orchestrator --intel            # Intel freshness check
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from data_team.shared.config import DATA_AGENT_NAMES, REPORTS_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

_AGENT_MODULES: dict[str, str] = {
    "pipeline": "data_team.pipeline.pipeline",
    "analyst": "data_team.analyst.analyst",
    "model_engineer": "data_team.model_engineer.model_engineer",
    "data_lead": "data_team.data_lead.data_lead",
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_agent(name: str) -> object | None:
    """Dynamically import and run an agent's scan(), save report."""
    mod_path = _AGENT_MODULES.get(name)
    if not mod_path:
        print(f"Unknown agent: {name}")
        return None

    try:
        mod = importlib.import_module(mod_path)
        report = mod.scan()
        mod.save_report(report)
        return report
    except Exception as e:
        logger.error("Agent %s failed: %s", name, e)
        print(f"  [FAIL] {name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_all() -> None:
    """Run all data agents sequentially, then produce daily brief."""
    print("=" * 60)
    print("DATA TEAM — Full Scan")
    print("=" * 60)

    start = time.time()
    reports = []

    # Run agents in order: pipeline, analyst, model_engineer, then data_lead
    agent_order = ["pipeline", "analyst", "model_engineer", "data_lead"]
    for name in agent_order:
        print(f"\n--- {name} ---")
        report = _run_agent(name)
        if report:
            reports.append(report)
            findings_count = len(report.findings)
            print(f"  {findings_count} findings, {report.scan_duration_seconds:.1f}s")
        else:
            print(f"  [SKIPPED]")

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"Done in {elapsed:.1f}s — {len(reports)} agents reported")
    print(f"{'=' * 60}\n")

    # Print daily brief
    from data_team.data_lead.data_lead import generate_daily_brief
    brief = generate_daily_brief()
    print(brief)


def cmd_agent(name: str) -> None:
    """Run a single agent and print its report."""
    report = _run_agent(name)
    if report:
        print(report.to_markdown())


def cmd_lead_only() -> None:
    """Generate brief from cached reports (no scanning)."""
    from data_team.data_lead.data_lead import generate_daily_brief
    print(generate_daily_brief())


def cmd_weekly() -> None:
    """Generate weekly deep dive report."""
    from data_team.data_lead.data_lead import generate_weekly_report
    print(generate_weekly_report())


def cmd_monthly() -> None:
    """Generate monthly strategy review."""
    from data_team.data_lead.data_lead import generate_monthly_review
    print(generate_monthly_review())


def cmd_intel() -> None:
    """Check data intelligence freshness."""
    from data_team.shared.intelligence import DataIntelligence
    di = DataIntelligence()
    freshness = di.check_freshness()
    agenda = di.generate_research_agenda()

    print("Intelligence Freshness:")
    for cat, is_fresh in freshness.items():
        status = "fresh" if is_fresh else "STALE"
        print(f"  {cat}: {status}")

    if agenda:
        print("\nResearch Agenda:")
        for item in agenda:
            print(f"  [{item['priority']}] {item['question']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="WarmPath Data Team Orchestrator"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Run all data agents")
    group.add_argument("--agent", type=str, help="Run a single agent by name")
    group.add_argument("--lead-only", action="store_true", help="Brief from cached reports")
    group.add_argument("--weekly", action="store_true", help="Weekly deep dive")
    group.add_argument("--monthly", action="store_true", help="Monthly review")
    group.add_argument("--intel", action="store_true", help="Intel freshness check")

    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.all:
        cmd_all()
    elif args.agent:
        cmd_agent(args.agent)
    elif args.lead_only:
        cmd_lead_only()
    elif args.weekly:
        cmd_weekly()
    elif args.monthly:
        cmd_monthly()
    elif args.intel:
        cmd_intel()
    else:
        # Default: run all
        cmd_all()


if __name__ == "__main__":
    main()
