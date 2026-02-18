"""Orchestrator — CLI entry point for running the WarmPath agent team.

Usage:
    python -m agents.orchestrator --all          # Run all agents + lead brief
    python -m agents.orchestrator --agent architect   # Run a single agent
    python -m agents.orchestrator --lead-only    # Generate brief from cached reports
    python -m agents.orchestrator --weekly       # Generate weekly trend report
    python -m agents.orchestrator --intel-update # Refresh external intelligence cache
    python -m agents.orchestrator --cos-daily    # Chief of Staff daily brief
    python -m agents.orchestrator --cos-weekly   # Chief of Staff weekly synthesis
    python -m agents.orchestrator --cos-status   # Chief of Staff status snapshot
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
            name,
            len(report.findings),
            report.scan_duration_seconds,
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

    # Record health snapshot
    try:
        from agents.shared.learning import get_learning_state
        from agents.shared.config import SEVERITY_WEIGHTS, HEALTH_WEIGHTS

        sev_counts: dict[str, int] = {}
        for f in all_findings:
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

        # Compute health score (100 - weighted penalty)
        penalty = sum(
            SEVERITY_WEIGHTS.get(sev, 0) * count for sev, count in sev_counts.items()
        )
        health_score = max(0.0, 100.0 - penalty)

        lead_ls = get_learning_state("lead")
        lead_ls.record_health_snapshot(health_score, sev_counts)
        logger.info("Recorded health snapshot: %.1f", health_score)
    except Exception as exc:
        logger.warning("Failed to record health snapshot: %s", exc)

    # Check intel freshness
    try:
        from agents.shared.config import INTEL_REFRESH_ON_SCAN

        if INTEL_REFRESH_ON_SCAN:
            from agents.shared.intelligence import ExternalIntelligence

            ei = ExternalIntelligence()
            freshness = ei.check_freshness()
            stale = [k for k, v in freshness.items() if not v]
            if stale:
                logger.info("Stale intel categories: %s", ", ".join(stale[:5]))
    except Exception:
        pass

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


def cmd_kpis() -> None:
    """Print KPI dashboard from cached reports (no scanning)."""
    from agents.shared.kpis import compute_kpis, render_dashboard

    dashboard = compute_kpis()
    print(render_dashboard(dashboard))


def cmd_intel_update() -> None:
    """Refresh external intelligence cache."""
    from agents.shared.intelligence import get_all_intelligence

    intel = get_all_intelligence()
    advisories = intel.get("advisories", [])
    deps = intel.get("dep_versions", {})
    print("Intelligence updated:")
    print(f"  Advisories: {len(advisories)} found")
    print(f"  Dependencies checked: {len(deps)}")
    print(f"  API status: {len(intel.get('api_status', {}))} endpoints")
    print(f"  Framework updates: {len(intel.get('framework_updates', []))} items")


def cmd_intel_report() -> None:
    """Print intel inventory, urgent items, and freshness status."""
    from agents.shared.intelligence import ExternalIntelligence, INTEL_CATEGORIES

    ei = ExternalIntelligence()
    freshness = ei.check_freshness()
    urgent = ei.get_urgent()
    unadopted = ei.get_unadopted()

    print("## Intelligence Report\n")

    print("### Freshness Status")
    for cat, is_fresh in sorted(freshness.items()):
        status = "fresh" if is_fresh else "STALE"
        ttl = INTEL_CATEGORIES.get(cat, {}).get("refresh_hours", "?")
        print(f"  {cat}: {status} (TTL: {ttl}h)")
    print()

    print(f"### Urgent Items ({len(urgent)})")
    if urgent:
        for item in urgent:
            print(f"  [{item.severity.upper()}] {item.title} ({item.category})")
    else:
        print("  None.")
    print()

    print(f"### Unadopted ({len(unadopted)})")
    if unadopted:
        for item in unadopted[:10]:
            print(f"  - {item.title} ({item.category})")
        if len(unadopted) > 10:
            print(f"  ... and {len(unadopted) - 10} more")
    else:
        print("  All items adopted.")


def cmd_learning_report() -> None:
    """Print meta-learning summary for all agents."""
    from agents.shared.learning import get_learning_state
    from agents.shared.config import AGENT_NAMES

    print("## Learning Report\n")

    for agent in AGENT_NAMES + ["lead"]:
        ls = get_learning_state(agent)
        meta = ls.generate_meta_learning_report()

        total_scans = meta.get("total_scans", 0)
        if total_scans == 0:
            continue

        print(f"### {agent} ({total_scans} scans)")
        print(f"  Findings tracked: {meta['total_findings_tracked']}")

        # Health
        trajectory = meta.get("health_trajectory", "insufficient_data")
        if trajectory != "insufficient_data":
            print(f"  Health trend: {trajectory}")

        # Fix effectiveness
        fix_rate = meta.get("fix_effectiveness_rate")
        if fix_rate is not None:
            print(f"  Fix effectiveness: {fix_rate:.0%}")

        # Tool reliability
        tool_rel = meta.get("tool_reliability", {})
        if tool_rel:
            rel_str = ", ".join(f"{t}: {r:.0%}" for t, r in tool_rel.items())
            print(f"  Tool reliability: {rel_str}")

        # Escalated patterns
        escalated = meta.get("escalated_patterns", [])
        if escalated:
            print(f"  Escalated patterns: {len(escalated)}")
            for p in escalated[:3]:
                print(
                    f"    - {p.get('category')}: {p.get('file', '?')} ({p.get('count')}x)"
                )

        # Systemic
        systemic = meta.get("systemic_patterns", [])
        if systemic:
            print(f"  Systemic patterns: {len(systemic)}")

        print()


def cmd_research_agenda() -> None:
    """Print prioritized research questions."""
    from agents.shared.intelligence import ExternalIntelligence

    ei = ExternalIntelligence()
    agenda = ei.generate_research_agenda()

    print("## Research Agenda\n")
    if not agenda:
        print("All intelligence categories are fresh. No research needed.")
        return

    for i, item in enumerate(agenda, 1):
        priority = item.get("priority", "medium").upper()
        print(f"{i}. [{priority}] {item['question']}")
        print(f"   Source: {item['source']}")
        agents_str = ", ".join(item.get("relevant_agents", []))
        print(f"   Relevant agents: {agents_str}")
        print()


def cmd_health_trend() -> None:
    """Print codebase health score timeline."""
    from agents.shared.learning import get_learning_state

    ls = get_learning_state("lead")
    history = ls.state.get("codebase_health_history", [])

    print("## Codebase Health Trend\n")

    if not history:
        print("No health snapshots recorded yet.")
        print("Run `--all` to generate the first health snapshot.")
        return

    trajectory = ls.get_health_trajectory()
    print(f"Trajectory: **{trajectory}**\n")

    print("| Date       | Score | Critical | High | Medium | Low  |")
    print("|------------|-------|----------|------|--------|------|")
    for snap in history[-15:]:  # last 15 entries
        ts = snap.get("timestamp", "")[:10]
        score = snap.get("score", 0)
        counts = snap.get("finding_counts", {})
        print(
            f"| {ts} | {score:5.1f} "
            f"| {counts.get('critical', 0):8} "
            f"| {counts.get('high', 0):4} "
            f"| {counts.get('medium', 0):6} "
            f"| {counts.get('low', 0):4} |"
        )


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
    group.add_argument(
        "--all", action="store_true", help="Run all agents + daily brief"
    )
    group.add_argument("--agent", type=str, help="Run a single agent by name")
    group.add_argument(
        "--lead-only", action="store_true", help="Brief from cached reports"
    )
    group.add_argument("--weekly", action="store_true", help="Weekly trend report")
    group.add_argument(
        "--kpis", action="store_true", help="KPI dashboard from cached reports"
    )
    group.add_argument(
        "--intel-update", action="store_true", help="Refresh intelligence cache"
    )
    group.add_argument(
        "--intel-report", action="store_true", help="Intelligence inventory + freshness"
    )
    group.add_argument(
        "--learning-report",
        action="store_true",
        help="Meta-learning summary for all agents",
    )
    group.add_argument(
        "--research-agenda", action="store_true", help="Prioritized research questions"
    )
    group.add_argument(
        "--health-trend", action="store_true", help="Codebase health score timeline"
    )
    group.add_argument(
        "--cos-daily", action="store_true", help="Chief of Staff daily brief"
    )
    group.add_argument(
        "--cos-weekly", action="store_true", help="Chief of Staff weekly synthesis"
    )
    group.add_argument(
        "--cos-status", action="store_true", help="Chief of Staff status snapshot"
    )

    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip test_engineer (faster)"
    )
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
    elif args.kpis:
        cmd_kpis()
    elif args.intel_update:
        cmd_intel_update()
    elif args.intel_report:
        cmd_intel_report()
    elif args.learning_report:
        cmd_learning_report()
    elif args.research_agenda:
        cmd_research_agenda()
    elif args.health_trend:
        cmd_health_trend()
    elif args.cos_daily:
        from agents.chief_of_staff.cos_agent import run_daily

        print(run_daily())
    elif args.cos_weekly:
        from agents.chief_of_staff.cos_agent import run_weekly

        print(run_weekly())
    elif args.cos_status:
        from agents.chief_of_staff.cos_agent import run_status

        print(run_status())


if __name__ == "__main__":
    main()
