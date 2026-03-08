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
    python -m agents.orchestrator --consult "How should we improve onboarding?"
    python -m agents.orchestrator --consult "What's our biggest security risk?" --team engineering
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Ensure project root is on sys.path so the orchestrator works when invoked
# directly (python agents/orchestrator.py) as well as via -m flag.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.shared.report import AgentReport, merge_reports  # noqa: E402
from agents.lead.lead import (  # noqa: E402
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
        try:
            from agents.shared.report_store import publish_report

            publish_report("agents", report.agent, report.serialize())
        except Exception:
            pass  # Redis publish is best-effort
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
    """Run all agents in parallel batches, then generate the daily brief.

    Batch 1 (parallel): all agents except architect
    Batch 2 (solo):     architect — runs after batch 1 so mutation testing
                        can't corrupt files other agents are reading
    """
    start = time.time()
    reports: list[AgentReport] = []

    agents_to_run = list(_AGENT_MODULES.keys())
    if skip_tests:
        agents_to_run = [a for a in agents_to_run if a != "test_engineer"]

    # Split into two batches: batch1 (safe to parallelize) and architect (solo)
    batch1 = [a for a in agents_to_run if a != "architect"]
    run_architect = "architect" in agents_to_run

    # Batch 1: run in parallel via ThreadPoolExecutor
    if batch1:
        with ThreadPoolExecutor(max_workers=len(batch1)) as pool:
            futures = {pool.submit(_run_agent, name): name for name in batch1}
            for future in as_completed(futures):
                report = future.result()
                if report:
                    reports.append(report)

    # Batch 2: architect runs solo (mutation testing modifies source files)
    if run_architect:
        report = _run_agent("architect")
        if report:
            reports.append(report)

    if not reports:
        print("No agents produced reports.")
        return

    # Merge and record metrics
    all_findings = merge_reports(reports)
    record_brief_metrics(all_findings)

    # Auto-repair phase: fix auto_fixable findings (ruff lint + format)
    repair_result = None
    try:
        from agents.shared.repair import repair_auto_fixable

        repair_result = repair_auto_fixable(all_findings)
        if repair_result.fixed_count > 0:
            logger.info(
                "Auto-repair: fixed %d findings, PR: %s",
                repair_result.fixed_count,
                repair_result.pr_url,
            )
        if repair_result.errors:
            logger.warning("Auto-repair errors: %s", repair_result.errors)
    except Exception as exc:
        logger.warning("Auto-repair phase failed: %s", exc)

    # Record health snapshot
    try:
        from agents.shared.learning import get_learning_state
        from agents.shared.config import SEVERITY_WEIGHTS

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


def cmd_resolve(finding_id: str, resolution_type: str, reason: str) -> None:
    """Mark a finding as resolved in the global registry."""
    from agents.shared.learning import resolve_issue

    valid_types = ("fixed", "false_positive", "wont_fix", "deferred")
    if resolution_type not in valid_types:
        print(f"Invalid resolution type: {resolution_type}")
        print(f"Valid types: {', '.join(valid_types)}")
        sys.exit(1)

    skip_days = None if resolution_type in ("wont_fix", "false_positive") else 30
    resolve_issue(finding_id, resolution_type, reason, skip_days=skip_days)
    print(f"Resolved [{finding_id}] as {resolution_type}: {reason}")
    if skip_days:
        print(f"  Will re-check after {skip_days} days")
    else:
        print("  Permanently suppressed (unresolve with --unresolve)")


def cmd_unresolve(finding_id: str) -> None:
    """Remove a finding from the resolved registry."""
    from agents.shared.learning import unresolve_issue

    if unresolve_issue(finding_id):
        print(f"Unresolved [{finding_id}] — agents will report it again")
    else:
        print(f"[{finding_id}] was not in the resolved registry")


def cmd_resolved() -> None:
    """List all resolved findings."""
    from agents.shared.learning import list_resolved

    registry = list_resolved()
    if not registry:
        print("No resolved findings.")
        return

    print("## Resolved Findings\n")
    print(f"| {'ID':<25} | {'Type':<15} | {'Resolved':<12} | Reason |")
    print(f"|{'-' * 27}|{'-' * 17}|{'-' * 14}|--------|")
    for fid, entry in sorted(registry.items()):
        res_type = entry.get("resolution_type", "?")
        resolved_at = entry.get("resolved_at", "")[:10]
        reason = entry.get("reason", "")
        print(f"| {fid:<25} | {res_type:<15} | {resolved_at:<12} | {reason} |")


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
    group.add_argument(
        "--resolve",
        nargs=3,
        metavar=("FINDING_ID", "TYPE", "REASON"),
        help="Mark finding as resolved (types: fixed, false_positive, wont_fix, deferred)",
    )
    group.add_argument(
        "--unresolve",
        type=str,
        metavar="FINDING_ID",
        help="Remove a finding from the resolved registry",
    )
    group.add_argument(
        "--resolved", action="store_true", help="List all resolved findings"
    )
    group.add_argument(
        "--consult",
        type=str,
        metavar="QUERY",
        help="Interactive consultation: ask a question to any team",
    )

    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip test_engineer (faster)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument(
        "--team",
        type=str,
        default=None,
        help="Team to consult (with --consult). Options: engineering, data, product, ops, gtm, finance, cos",
    )

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
    elif args.resolve:
        cmd_resolve(*args.resolve)
    elif args.unresolve:
        cmd_unresolve(args.unresolve)
    elif args.resolved:
        cmd_resolved()
    elif args.consult:
        cmd_consult(args.consult, team=args.team)


def cmd_consult(query: str, team: str | None = None) -> None:
    """Interactive consultation with an agent team."""
    import os
    from pathlib import Path

    from agents.shared.consultant import consult
    from agents.chief_of_staff.router import route_query

    # Consult is useless in mock mode — force AI mode and load .env for API key
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    os.environ["AI_MOCK_MODE"] = "false"

    if team:
        # Direct team consultation
        print(f"Consulting {team} team...\n")
        response = consult(query, team=team)
        print(response.to_markdown())
    else:
        # Auto-route via CoS router
        route = route_query(query)
        print(f"Routing: {route.reasoning}\n")
        print(f"Consulting {route.primary_team} team...\n")
        response = consult(query, team=route.primary_team)
        print(response.to_markdown())

        # Consult secondary teams if confidence is low
        if route.secondary_teams and route.confidence < 0.6:
            for sec_team in route.secondary_teams[:1]:
                print(f"\nAlso consulting {sec_team} team...\n")
                sec_response = consult(query, team=sec_team)
                print(sec_response.to_markdown())


if __name__ == "__main__":
    main()
