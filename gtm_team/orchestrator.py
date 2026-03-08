"""GTM Team Orchestrator -- CLI entry point for running GTM agents.

Usage:
    python -m gtm_team.orchestrator --all               # Run all agents
    python -m gtm_team.orchestrator --agent stratops     # Run single agent
    python -m gtm_team.orchestrator --daily-brief        # Brief from cached reports
    python -m gtm_team.orchestrator --weekly             # Weekly deep dive
    python -m gtm_team.orchestrator --monthly            # Monthly review
    python -m gtm_team.orchestrator --intel              # Intel freshness check
    python -m gtm_team.orchestrator --intel-report       # Full intel summary
    python -m gtm_team.orchestrator --learning-report    # Meta-learning reports
    python -m gtm_team.orchestrator --research-agenda    # Research priorities
    python -m gtm_team.orchestrator --kpi-check          # KPI target status
    python -m gtm_team.orchestrator --consult "What's our go-to-market readiness?"
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

from gtm_team.shared.config import GTM_AGENT_NAMES, KPI_TARGETS, REPORTS_DIR  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

_AGENT_MODULES: dict[str, str] = {
    "stratops": "gtm_team.stratops.scanner",
    "monetization": "gtm_team.monetization.scanner",
    "marketing": "gtm_team.marketing.scanner",
    "partnerships": "gtm_team.partnerships.scanner",
    "gtm_lead": "gtm_team.gtm_lead.scanner",
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
        try:
            from agents.shared.report_store import publish_report

            publish_report("gtm_team", report.agent, report.serialize())
        except Exception:
            pass  # Redis publish is best-effort
        return report
    except Exception as e:
        logger.error("Agent %s failed: %s", name, e)
        print(f"  [FAIL] {name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_all() -> None:
    """Run all GTM agents sequentially, then produce daily brief."""
    print("=" * 60)
    print("GTM TEAM -- Full Scan")
    print("=" * 60)

    start = time.time()
    reports = []

    # Run agents in order: leaf agents first, then lead
    agent_order = ["stratops", "monetization", "marketing", "partnerships", "gtm_lead"]
    for name in agent_order:
        print(f"\n--- {name} ---")
        report = _run_agent(name)
        if report:
            reports.append(report)
            findings_count = len(report.findings)
            print(f"  {findings_count} findings, {report.scan_duration_seconds:.1f}s")
        else:
            print("  [SKIPPED]")

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"Done in {elapsed:.1f}s -- {len(reports)} agents reported")
    print(f"{'=' * 60}\n")

    # Print daily brief
    from gtm_team.gtm_lead.scanner import generate_daily_brief

    brief = generate_daily_brief()
    print(brief)


def cmd_agent(name: str) -> None:
    """Run a single agent and print its report."""
    report = _run_agent(name)
    if report:
        print(report.to_markdown())


def cmd_daily_brief() -> None:
    """Generate brief from cached reports (no scanning)."""
    from gtm_team.gtm_lead.scanner import generate_daily_brief

    print(generate_daily_brief())


def cmd_weekly() -> None:
    """Generate weekly deep dive report."""
    from gtm_team.gtm_lead.scanner import generate_weekly_report

    print(generate_weekly_report())


def cmd_monthly() -> None:
    """Generate monthly strategy review."""
    from gtm_team.gtm_lead.scanner import generate_monthly_review

    print(generate_monthly_review())


def cmd_intel() -> None:
    """Check GTM intelligence freshness."""
    from gtm_team.shared.intelligence import GTMIntelligence

    gi = GTMIntelligence()
    freshness = gi.check_freshness()
    agenda = gi.generate_research_agenda()

    print("Intelligence Freshness:")
    for cat, is_fresh in freshness.items():
        status = "fresh" if is_fresh else "STALE"
        print(f"  {cat}: {status}")

    if agenda:
        print("\nResearch Agenda:")
        for item in agenda:
            print(f"  [{item['priority']}] {item['question']}")


def cmd_intel_report() -> None:
    """Full intelligence summary report."""
    from gtm_team.shared.intelligence import GTMIntelligence

    gi = GTMIntelligence()
    report = gi.generate_intel_report()

    print("=" * 60)
    print("GTM TEAM -- Intelligence Report")
    print("=" * 60)
    print(f"\nTotal items: {report['total_items']}")
    print(f"Urgent: {report['urgent_items']}")
    print(f"Unadopted: {report['unadopted_items']}")
    print(
        f"Categories: {report['categories_fresh']} fresh / "
        f"{report['categories_stale']} stale of {report['categories_total']}"
    )

    if report.get("items_by_category"):
        print("\nBy Category:")
        for cat, count in sorted(report["items_by_category"].items()):
            print(f"  {cat}: {count}")

    freshness = report.get("freshness", {})
    if freshness:
        print("\nFreshness Detail:")
        for cat, is_fresh in freshness.items():
            print(f"  {cat}: {'fresh' if is_fresh else 'STALE'}")


def cmd_learning_report() -> None:
    """Meta-learning reports for all GTM team agents."""
    from gtm_team.shared.learning import GTMLearningState

    print("=" * 60)
    print("GTM TEAM -- Learning Reports")
    print("=" * 60)

    for agent_name in GTM_AGENT_NAMES:
        ls = GTMLearningState(agent_name)
        report = ls.generate_meta_learning_report()

        print(f"\n--- {agent_name} ---")
        print(f"  Total scans: {report['total_scans']}")
        print(f"  Findings tracked: {report['total_findings_tracked']}")
        print(f"  Insights tracked: {report['total_insights_tracked']}")
        print(f"  Health trajectory: {report['health_trajectory']}")
        print(f"  Methodologies adopted: {report['methodologies_adopted']}")

        if report.get("fix_effectiveness_rate") is not None:
            print(
                f"  Fix effectiveness: {report['fix_effectiveness_rate']:.0%} "
                f"({report['fix_records_sampled']} sampled)"
            )

        if report.get("hot_spots"):
            print("  Hot spots:")
            for hs in report["hot_spots"][:3]:
                print(f"    {hs['file']}: weight={hs['weight']:.2f}")

        if report.get("escalated_patterns"):
            print(f"  Escalated patterns: {len(report['escalated_patterns'])}")
            for p in report["escalated_patterns"][:3]:
                print(f"    {p['key']}: count={p['count']}")

        if report.get("systemic_patterns"):
            print(f"  Systemic patterns: {len(report['systemic_patterns'])}")

        if report.get("tool_reliability"):
            print("  Tool reliability:")
            for tool, score in report["tool_reliability"].items():
                print(f"    {tool}: {score:.0%}")

        if report.get("kpi_trends"):
            print("  KPI trends:")
            for kpi, trend in report["kpi_trends"].items():
                print(f"    {kpi}: {trend}")


def cmd_research_agenda() -> None:
    """Show prioritized research agenda."""
    from gtm_team.shared.intelligence import GTMIntelligence

    gi = GTMIntelligence()
    agenda = gi.generate_research_agenda()

    print("=" * 60)
    print("GTM TEAM -- Research Agenda")
    print("=" * 60)

    if not agenda:
        print("\nAll intelligence categories are fresh. No research needed.")
        return

    for i, item in enumerate(agenda, 1):
        print(f"\n{i}. [{item['priority'].upper()}] {item['category']}")
        print(f"   Question: {item['question']}")
        print(f"   Source: {item.get('source', 'unknown')}")
        print(f"   Agents: {', '.join(item.get('relevant_agents', []))}")


def cmd_kpi_check() -> None:
    """Show KPI target status from cached reports."""
    import json

    print("=" * 60)
    print("GTM TEAM -- KPI Check")
    print("=" * 60)

    # Load lead report for aggregated metrics
    lead_path = REPORTS_DIR / "gtm_lead_latest.json"
    metrics: dict = {}
    if lead_path.exists():
        try:
            data = json.loads(lead_path.read_text())
            metrics = data.get("metrics", {})
        except (json.JSONDecodeError, OSError):
            pass

    if not metrics:
        print("\nNo cached GTM lead report. Run --all first.")
        return

    print("\n| KPI | Current | Target | Status |")
    print("|-----|---------|--------|--------|")
    for kpi_name, kpi_meta in KPI_TARGETS.items():
        current = metrics.get(kpi_name, 0)
        target = kpi_meta.get("target", "?")
        unit = kpi_meta.get("unit", "")
        if isinstance(current, (int, float)) and isinstance(target, (int, float)):
            status = "MET" if current >= target else "GAP"
        else:
            status = "N/A"
        print(f"| {kpi_name} | {current} | {target} {unit} | {status} |")

    readiness = metrics.get("gtm_readiness_score", "N/A")
    print(f"\nComposite GTM Readiness: {readiness}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="WarmPath GTM Team Orchestrator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Run all GTM agents")
    group.add_argument("--agent", type=str, help="Run a single agent by name")
    group.add_argument(
        "--daily-brief", action="store_true", help="Brief from cached reports"
    )
    group.add_argument("--weekly", action="store_true", help="Weekly deep dive")
    group.add_argument("--monthly", action="store_true", help="Monthly review")
    group.add_argument("--intel", action="store_true", help="Intel freshness check")
    group.add_argument("--intel-report", action="store_true", help="Full intel summary")
    group.add_argument(
        "--learning-report", action="store_true", help="Meta-learning reports"
    )
    group.add_argument(
        "--research-agenda", action="store_true", help="Research priorities"
    )
    group.add_argument("--kpi-check", action="store_true", help="KPI target status")
    group.add_argument(
        "--consult",
        type=str,
        metavar="QUERY",
        help="Interactive consultation: ask a question",
    )

    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--team",
        type=str,
        default=None,
        help="Override team routing (with --consult)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.all:
        cmd_all()
    elif args.agent:
        cmd_agent(args.agent)
    elif args.daily_brief:
        cmd_daily_brief()
    elif args.weekly:
        cmd_weekly()
    elif args.monthly:
        cmd_monthly()
    elif args.intel:
        cmd_intel()
    elif args.intel_report:
        cmd_intel_report()
    elif args.learning_report:
        cmd_learning_report()
    elif args.research_agenda:
        cmd_research_agenda()
    elif args.kpi_check:
        cmd_kpi_check()
    elif args.consult:
        from agents.shared.consultant import consult

        team = args.team or "gtm"
        print(f"Consulting {team} team...\n")
        response = consult(args.consult, team=team)
        print(response.to_markdown())
    else:
        # Default: run all
        cmd_all()


if __name__ == "__main__":
    main()
