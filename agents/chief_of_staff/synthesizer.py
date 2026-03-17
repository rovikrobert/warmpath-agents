"""Report synthesizer — transforms engineering reports into founder-facing briefs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.shared.business_outcomes import (
    OUTCOME_LABELS,
    OUTCOME_PRIORITY,
    get_aligned_outcomes,
    get_business_impact,
    score_alignment,
)
from agents.shared.decision_registry import PendingDecision, save_pending_decisions
from agents.shared.learning import filter_resolved_findings
from agents.shared.report import AgentReport, Finding, merge_reports

from .cos_config import COS_CONFIG, SEVERITY_WEIGHT, TEAM_REGISTRY
from .cos_learning import weekly_reflect
from .schemas import CosFinding, FounderBrief


# ---------------------------------------------------------------------------
# Category-level noise suppression
# ---------------------------------------------------------------------------

# Categories that generate recurring false positives from broad regex scanners.
# Findings in these categories are dropped unless critical severity.
_NOISE_CATEGORIES = {
    "dependency-update",
    "dependency-dead",
    "dependency-missing",
}
_SUPPRESSED_CATEGORIES = {
    "auth_coverage",  # Clerk handles auth; scanner can't detect non-JWT auth
    "sql_injection",  # Scanner matches safe parameterized queries
    "pii_leak",  # Scanner matches hashed/anonymized value logging
    "validation",  # Input validation noise on internal fields
    "info_leak",  # Pre-launch, no real users to enumerate
    "debug_print",  # Low-value debug print detection
}


def _filter_noisy_findings(findings: list[Finding]) -> list[Finding]:
    """Remove known false-positive-heavy categories and low-confidence findings.

    Low-confidence findings (< 0.5) are suppressed unless critical severity,
    preventing statistically unreliable data from reaching the daily brief.
    """
    return [
        f
        for f in findings
        if (f.category not in _NOISE_CATEGORIES or f.severity in ("critical", "high"))
        and (f.category not in _SUPPRESSED_CATEGORIES or f.severity == "critical")
        and (f.confidence >= 0.5 or f.severity == "critical")
    ]


# ---------------------------------------------------------------------------
# Finding enrichment
# ---------------------------------------------------------------------------


def _enrich_finding(f: Finding) -> CosFinding:
    """Transform a raw Finding into a CosFinding with business context."""
    outcomes = get_aligned_outcomes(f.category)
    impact = get_business_impact(f.category, f.severity)

    return CosFinding(
        id=f.id,
        severity=f.severity,
        category=f.category,
        summary=f.title,
        evidence=f.detail,
        business_impact=impact,
        recommended_action=f.recommendation,
        effort_estimate=f"{f.effort_hours}h" if f.effort_hours else "TBD",
        outcome_alignment=outcomes,
    )


def _score_finding(cf: CosFinding) -> float:
    """Score a CosFinding for prioritization.

    Higher score = needs more attention.
    """
    sev_weight = SEVERITY_WEIGHT.get(cf.severity, 0)
    alignment = score_alignment(cf.outcome_alignment)
    return sev_weight * (1.0 + alignment)


# ---------------------------------------------------------------------------
# Daily synthesis
# ---------------------------------------------------------------------------


def synthesize_daily(
    reports: list[AgentReport],
    kpi_snapshot: str = "",
    costs: dict[str, Any] | None = None,
    alerts: list[str] | None = None,
    cross_team_requests: list[dict[str, Any]] | None = None,
    founder_requests: list[dict[str, Any]] | None = None,
    resolutions: list[dict[str, Any]] | None = None,
    repairs: dict[str, Any] | None = None,
    recommendations: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Daily cycle: load reports -> classify -> enrich -> render brief."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Merge, filter resolved, and suppress noisy categories
    all_findings = merge_reports(reports) if reports else []
    all_findings = filter_resolved_findings(all_findings)
    all_findings = _filter_noisy_findings(all_findings)
    # Preserve original Findings before enrichment (CosFinding drops file/auto_fixable)
    _original_findings = {f.id: f for f in all_findings}
    enriched = [_enrich_finding(f) for f in all_findings]

    # Sort by composite score
    enriched.sort(key=_score_finding, reverse=True)

    # Classify
    decisions_needed = [cf for cf in enriched if cf.severity in ("critical", "high")]
    key_updates = [cf for cf in enriched if cf.severity == "medium"]
    # Use the same per-team filtered reports for progress detection so that
    # resolved / noisy findings don't prevent "clean scan" labels.
    _filtered_reports = [
        AgentReport(
            agent=r.agent,
            timestamp=r.timestamp,
            scan_duration_seconds=r.scan_duration_seconds,
            findings=_filter_noisy_findings(filter_resolved_findings(r.findings)),
            metrics=r.metrics,
            intelligence_applied=r.intelligence_applied,
            learning_updates=r.learning_updates,
        )
        for r in reports
    ]
    progress_items = _build_progress(_filtered_reports)

    # Operational health checks (use filtered reports so noise doesn't
    # inflate finding-volume warnings that surface in Telegram)
    operational_health = _check_operational_health(
        _filtered_reports, cross_team_requests or []
    )

    # Compute per-team summaries (with resolved findings filtered out)
    team_report_groups = _group_reports_by_team(_filtered_reports)

    team_summaries_list = [
        summarize_team(team, team_reports)
        for team, team_reports in sorted(team_report_groups.items())
    ]

    # Build the brief model
    brief = FounderBrief(
        date=today,
        decisions_needed=[
            {
                "id": cf.id,
                "summary": cf.summary,
                "severity": cf.severity,
                "business_impact": cf.business_impact,
                "recommended_action": cf.recommended_action,
                "outcomes": cf.outcome_alignment,
            }
            for cf in decisions_needed[:5]
        ],
        key_updates=[
            {
                "id": cf.id,
                "summary": cf.summary,
                "business_impact": cf.business_impact,
            }
            for cf in key_updates[:5]
        ],
        progress=progress_items,
        team_summaries=team_summaries_list,
        cross_team_requests=cross_team_requests or [],
        operational_health=operational_health,
        founder_requests=founder_requests or [],
        resolutions=resolutions or [],
        cost_summary=costs or {},
        kpi_snapshot=kpi_snapshot,
    )

    rendered = _render_daily_brief(brief, alerts or [])
    # Return both markdown and structured data for Telegram/Notion consumers
    data = brief.model_dump()
    # Attach repair + recommendation data for Telegram (not part of FounderBrief model)
    if repairs:
        data["repairs"] = repairs
    if recommendations:
        data["recommendations"] = recommendations
    # Persist pending decisions for Telegram approval execution
    from dataclasses import asdict as _asdict

    from agents.shared.execution_engine import ExecutionEngine

    _engine = ExecutionEngine()
    _pending = []
    for i, cf in enumerate(decisions_needed[:3], 1):
        _orig = _original_findings.get(cf.id)
        if _orig:
            _tier = _engine.triage(_orig)
            _pending.append(
                PendingDecision(
                    number=i,
                    finding_id=cf.id,
                    finding=_asdict(_orig),
                    brief_date=today,
                    tier=_tier.value,
                    action_plan=cf.recommended_action or f"Review: {cf.summary}",
                )
            )
    save_pending_decisions(_pending)
    return rendered, data


def _team_agent_sets() -> dict[str, set[str]]:
    """Derive team→agent set mapping from TEAM_REGISTRY (single source of truth)."""
    return {team: set(agents) for team, agents in TEAM_REGISTRY.items()}


def _check_operational_health(
    reports: list[AgentReport],
    cross_team_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Check CoS operational health indicators for the daily brief."""
    items: list[dict[str, Any]] = []

    # 1. Cross-team request backlog
    pending = [
        r for r in cross_team_requests if r.get("urgency") in ("critical", "high")
    ]
    if pending:
        items.append(
            {
                "indicator": "Cross-Team Request Backlog",
                "status": "warning" if len(pending) > 3 else "ok",
                "detail": f"{len(pending)} high/critical cross-team requests pending",
            }
        )
    else:
        items.append(
            {
                "indicator": "Cross-Team Request Backlog",
                "status": "ok",
                "detail": "No high-urgency cross-team requests",
            }
        )

    # 2. Scan freshness (check timestamps)
    team_agents = _team_agent_sets()
    reporting_agents = {r.agent for r in reports}
    teams_reporting = set()
    teams_silent = set()
    for team_name, agents in team_agents.items():
        if reporting_agents & agents:
            teams_reporting.add(team_name)
        else:
            teams_silent.add(team_name)

    if teams_silent:
        items.append(
            {
                "indicator": "Scan Coverage",
                "status": "warning",
                "detail": f"{len(teams_reporting)}/6 teams reporting. Silent: {', '.join(sorted(teams_silent))}",
            }
        )
    else:
        items.append(
            {
                "indicator": "Scan Coverage",
                "status": "ok",
                "detail": f"All 6 teams reporting ({len(reports)} agents total)",
            }
        )

    # 3. Report format compatibility
    agents_with_metrics = sum(1 for r in reports if r.metrics)
    agents_without = len(reports) - agents_with_metrics
    if agents_without > 0:
        items.append(
            {
                "indicator": "Report Completeness",
                "status": "info",
                "detail": f"{agents_without}/{len(reports)} agents reported without metrics",
            }
        )

    # 4. Finding volume — signal overload check
    total_findings = sum(len(r.findings) for r in reports)
    if total_findings > 100:
        items.append(
            {
                "indicator": "Signal Volume",
                "status": "warning",
                "detail": f"{total_findings} total findings — consider reviewing resolved registry for noise reduction",
            }
        )

    # 5. Shared intelligence activity
    try:
        from agents.shared.shared_intelligence import get_insight_summary

        intel_summary = get_insight_summary()
        teams_sharing = len(intel_summary.get("teams_contributing", []))
        total_shared = intel_summary.get("total_shared_insights", 0)
        if teams_sharing < 3 and total_shared == 0:
            items.append(
                {
                    "indicator": "Cross-Team Intelligence",
                    "status": "info",
                    "detail": "No shared intelligence yet — teams are operating in silos",
                }
            )
        else:
            items.append(
                {
                    "indicator": "Cross-Team Intelligence",
                    "status": "ok",
                    "detail": f"{total_shared} shared insights from {teams_sharing} teams",
                }
            )
    except Exception:
        pass

    return items


def _agent_to_team(agent_name: str) -> str:
    """Look up which team an agent belongs to via TEAM_REGISTRY."""
    for team, agents in TEAM_REGISTRY.items():
        if agent_name in agents:
            return team
    return "engineering"


def _build_progress(reports: list[AgentReport]) -> list[dict[str, Any]]:
    """Identify areas that are going well."""
    progress: list[dict[str, Any]] = []
    for r in reports:
        critical_high = [f for f in r.findings if f.severity in ("critical", "high")]
        if not critical_high:
            progress.append(
                {
                    "team": _agent_to_team(r.agent),
                    "agent": r.agent,
                    "note": f"{r.agent}: clean scan ({r.scan_duration_seconds:.1f}s)",
                }
            )
    return progress


def summarize_team(team: str, reports: list[AgentReport]) -> dict[str, Any]:
    """Produce a structured per-team summary for the FounderBrief.

    Returns dict with keys: team, health, summary, agent_count, finding_count.
    """
    if not reports:
        return {
            "team": team,
            "health": "green",
            "summary": f"{team.title()} team silent — no reports this cycle.",
            "agent_count": 0,
            "finding_count": 0,
        }

    all_findings = [f for r in reports for f in r.findings]
    crit = sum(1 for f in all_findings if f.severity == "critical")
    high = sum(1 for f in all_findings if f.severity == "high")
    medium = sum(1 for f in all_findings if f.severity == "medium")

    if crit > 0 or high > 0:
        health = "red"
    elif medium > 0:
        health = "yellow"
    else:
        health = "green"

    if health == "red":
        top = next(
            (f for f in all_findings if f.severity in ("critical", "high")), None
        )
        if top:
            summary = f"Needs attention — {top.title}."
        else:
            summary = f"Has {crit + high} issues that need fixing."
    elif health == "yellow":
        summary = f"{medium} items being tracked, nothing blocking."
    else:
        summary = f"All clear across {len(reports)} agents."

    return {
        "team": team,
        "health": health,
        "summary": summary,
        "agent_count": len(reports),
        "finding_count": len(all_findings),
    }


def _render_daily_brief(brief: FounderBrief, alerts: list[str]) -> str:
    """Render FounderBrief as natural-language markdown for Notion."""
    lines: list[str] = []
    lines.append(f"# Daily Brief — {brief.date}\n")

    # Lead with decisions — the only section that requires founder action
    if brief.decisions_needed:
        lines.append("## Your call needed\n")
        for d in brief.decisions_needed:
            lines.append(
                f"**{d['summary']}** — {d['business_impact']} "
                f"{d.get('recommended_action', '')}".rstrip()
            )
            lines.append("")
    else:
        lines.append("Nothing needs your decision today.\n")

    # Founder requests
    if brief.founder_requests:
        lines.append("## Open requests from you\n")
        for fr in brief.founder_requests:
            lines.append(f"- {fr.get('title', 'Untitled')}")
        lines.append("")

    # Conflict resolutions
    if brief.resolutions:
        lines.append("## Resolved conflicts\n")
        for res in brief.resolutions:
            escalated = " (escalated to you)" if res.get("escalated") else ""
            lines.append(f"- {res.get('outcome', '')}{escalated}")
        lines.append("")

    # Team summaries — prose, not tables
    lines.append("## What each team is doing\n")
    for ts in brief.team_summaries:
        lines.append(f"**{ts['team'].title()}** — {ts['summary']}")
        lines.append("")

    # Key updates — only if there's something worth reading
    if brief.key_updates:
        lines.append("## Other updates\n")
        for u in brief.key_updates:
            impact = f" ({u['business_impact']})" if u.get("business_impact") else ""
            lines.append(f"- {u['summary']}{impact}")
        lines.append("")

    # Cross-team handoffs — only urgent ones
    if brief.cross_team_requests:
        urgent = [
            r
            for r in brief.cross_team_requests
            if r.get("urgency") in ("critical", "high")
        ]
        if urgent:
            lines.append("## Cross-team handoffs needing attention\n")
            for req in urgent:
                source = req.get("source_agent", req.get("team", "unknown"))
                lines.append(f"- {req.get('request', 'N/A')} (from {source})")
            lines.append("")

    # Operational health — only show warnings, skip "all clear" noise
    if brief.operational_health:
        warnings = [
            item for item in brief.operational_health if item.get("status") == "warning"
        ]
        if warnings:
            lines.append("## Heads up\n")
            for item in warnings:
                lines.append(f"- {item['indicator']}: {item['detail']}")
            lines.append("")

    # Cost — one line, not a section
    if brief.cost_summary:
        total = brief.cost_summary.get("total_estimated_cost_usd", 0)
        if total > 0:
            lines.append(f"**Agent cost yesterday:** ${total:.2f}")
        if alerts:
            for alert in alerts:
                lines.append(f"**Cost alert:** {alert}")
        lines.append("")

    # Top risks — only if KPI snapshot provided
    if brief.kpi_snapshot:
        lines.append(brief.kpi_snapshot)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Weekly synthesis
# ---------------------------------------------------------------------------


def synthesize_weekly(
    reports: list[AgentReport],
    kpi_snapshot: str = "",
    costs: dict[str, Any] | None = None,
) -> str:
    """Weekly synthesis: outcome scorecard + priorities + self-learning."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_findings = merge_reports(reports) if reports else []
    all_findings = filter_resolved_findings(all_findings)
    all_findings = _filter_noisy_findings(all_findings)
    enriched = [_enrich_finding(f) for f in all_findings]
    enriched.sort(key=_score_finding, reverse=True)

    lines: list[str] = []
    lines.append(f"# Weekly Synthesis - {today}\n")

    # Business outcome scorecard
    lines.append("## Business Outcome Scorecard")
    lines.append("| Outcome | Status | Key Signal |")
    lines.append("|---------|--------|------------|")
    for outcome in OUTCOME_PRIORITY:
        label = OUTCOME_LABELS[outcome]
        aligned = [cf for cf in enriched if outcome in cf.outcome_alignment]
        critical_count = sum(1 for cf in aligned if cf.severity in ("critical", "high"))
        if critical_count > 0:
            status = "At Risk"
            signal = f"{critical_count} critical/high findings"
        elif aligned:
            status = "Monitoring"
            signal = f"{len(aligned)} findings (medium/low)"
        else:
            status = "Healthy"
            signal = "No issues detected"
        lines.append(f"| {label} | {status} | {signal} |")
    lines.append("")

    # Top 3 priorities
    lines.append("## Top 3 Priorities")
    for i, cf in enumerate(enriched[:3], 1):
        lines.append(f"{i}. **[{cf.id}]** {cf.summary} ({cf.severity})")
        lines.append(f"   - {cf.business_impact}")
    if not enriched:
        lines.append("No priorities — all clear.")
    lines.append("")

    # Cross-team patterns (placeholder for future teams)
    lines.append("## Cross-Team Patterns")
    category_counts: dict[str, int] = {}
    for cf in enriched:
        category_counts[cf.category] = category_counts.get(cf.category, 0) + 1
    if category_counts:
        top_categories = sorted(category_counts.items(), key=lambda x: -x[1])[:3]
        for cat, count in top_categories:
            lines.append(f"- **{cat}**: {count} findings")
    else:
        lines.append("No cross-team patterns yet (single team).")
    lines.append("")

    # Self-learning notes
    lines.append("## Self-Learning")
    reflections = weekly_reflect()
    if reflections:
        for note in reflections:
            lines.append(f"- {note}")
    else:
        lines.append("- No learning updates this week.")
    lines.append("")

    # Cost summary
    if costs:
        lines.append("## Cost Summary")
        total = costs.get("total_estimated_cost_usd", 0)
        tokens = costs.get("total_estimated_tokens", 0)
        lines.append(f"- Weekly total: ${total:.4f} | {tokens} tokens")
        lines.append("")

    # KPI snapshot
    if kpi_snapshot:
        lines.append(kpi_snapshot)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick status
# ---------------------------------------------------------------------------


def _group_reports_by_team(
    reports: list[AgentReport],
) -> dict[str, list[AgentReport]]:
    """Group reports by team using TEAM_REGISTRY."""
    team_agents = _team_agent_sets()
    groups: dict[str, list[AgentReport]] = {team: [] for team in TEAM_REGISTRY}
    for r in reports:
        placed = False
        for team, agents in team_agents.items():
            if r.agent in agents:
                groups[team].append(r)
                placed = True
                break
        if not placed:
            groups.setdefault("engineering", []).append(r)
    return groups


def _worst_severity(findings: list[Finding]) -> str:
    """Return the worst severity across findings, or 'clean'."""
    for sev in ("critical", "high", "medium", "low", "info"):
        if any(f.severity == sev for f in findings):
            return sev
    return "clean"


_TEAM_DISPLAY_NAMES: dict[str, str] = {
    "engineering": "Engineering",
    "data": "Data Team",
    "product": "Product Team",
    "ops": "Operations Team",
    "finance": "Finance Team",
    "gtm": "GTM Team",
}

_HEALTH_PENALTY: dict[str, int] = {
    "critical": 20,
    "high": 10,
    "medium": 3,
    "low": 1,
    "info": 0,
}


def _render_team_status(
    lines: list[str], team: str, team_reports: list[AgentReport]
) -> None:
    """Render a single team's status section. Mutates `lines` in place."""
    display = _TEAM_DISPLAY_NAMES.get(team, team.title())
    lines.append(f"## {display}")
    findings = [f for r in team_reports for f in r.findings]
    crit = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    med = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity in ("low", "info"))
    lines.append(f"- Agents: {len(team_reports)} reporting")
    lines.append(f"- Findings: {crit} critical, {high} high, {med} medium, {low} low")

    for r in team_reports:
        worst = _worst_severity(r.findings)
        lines.append(f"  - {r.agent}: {len(r.findings)} findings (worst: {worst})")
    lines.append("")


def synthesize_status(reports: list[AgentReport]) -> str:
    """Quick cross-team status snapshot."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Pre-filter all reports so resolved/noisy findings are excluded everywhere
    reports = [
        AgentReport(
            agent=r.agent,
            timestamp=r.timestamp,
            scan_duration_seconds=r.scan_duration_seconds,
            findings=_filter_noisy_findings(filter_resolved_findings(r.findings)),
            metrics=r.metrics,
            intelligence_applied=r.intelligence_applied,
            learning_updates=r.learning_updates,
        )
        for r in reports
    ]

    lines: list[str] = []
    lines.append(f"# Status Snapshot - {today}\n")

    # Render each team
    grouped = _group_reports_by_team(reports)
    team_order = ["engineering", "data", "product", "ops", "finance", "gtm"]
    for team in team_order:
        team_reports = grouped.get(team, [])
        if not team_reports and team != "engineering":
            continue
        _render_team_status(lines, team, team_reports)

    # Normalized metrics comparison across teams
    lines.append("## Team Metrics Summary")
    lines.append("| Team | Agents | Findings | Critical | High | Health |")
    lines.append("|------|--------|----------|----------|------|--------|")
    for team in team_order:
        team_reports = grouped.get(team, [])
        if not team_reports:
            continue
        t_findings = [f for r in team_reports for f in r.findings]
        t_crit = sum(1 for f in t_findings if f.severity == "critical")
        t_high = sum(1 for f in t_findings if f.severity == "high")
        t_penalty = sum(_HEALTH_PENALTY.get(f.severity, 0) for f in t_findings)
        t_health = max(0.0, 100.0 - t_penalty)
        lines.append(
            f"| {team} | {len(team_reports)} | {len(t_findings)} | "
            f"{t_crit} | {t_high} | {t_health:.0f}/100 |"
        )
    lines.append("")

    # Active teams
    active = [name for name, cfg in COS_CONFIG["teams"].items() if cfg.get("active")]
    inactive = [
        name for name, cfg in COS_CONFIG["teams"].items() if not cfg.get("active")
    ]
    lines.append("## Teams")
    lines.append(f"- Active: {', '.join(active)}")
    if inactive:
        lines.append(f"- Planned: {', '.join(inactive)}")

    return "\n".join(lines)
