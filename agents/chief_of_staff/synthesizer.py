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
from agents.shared.config import SEVERITY_WEIGHTS
from agents.shared.cost_tracker import check_budget_alerts, get_team_cost_summary
from agents.shared.report import AgentReport, Finding, merge_reports

from .cos_config import COS_CONFIG, SEVERITY_WEIGHT
from .cos_learning import get_learning_summary, weekly_reflect
from .schemas import CosFinding, FounderBrief


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
) -> str:
    """Daily cycle: load reports -> classify -> enrich -> render brief."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Merge and enrich
    all_findings = merge_reports(reports) if reports else []
    enriched = [_enrich_finding(f) for f in all_findings]

    # Sort by composite score
    enriched.sort(key=_score_finding, reverse=True)

    # Classify
    decisions_needed = [
        cf for cf in enriched if cf.severity in ("critical", "high")
    ]
    key_updates = [
        cf for cf in enriched if cf.severity == "medium"
    ]
    progress_items = _build_progress(reports)

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
        cost_summary=costs or {},
        kpi_snapshot=kpi_snapshot,
    )

    return _render_daily_brief(brief, alerts or [])


def _build_progress(reports: list[AgentReport]) -> list[dict[str, Any]]:
    """Identify areas that are going well."""
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {"user_researcher", "product_manager", "ux_lead", "design_lead", "product_lead"}
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    progress: list[dict[str, Any]] = []
    for r in reports:
        critical_high = [
            f for f in r.findings if f.severity in ("critical", "high")
        ]
        if not critical_high:
            if r.agent in _data_agents:
                team = "data"
            elif r.agent in _product_agents:
                team = "product"
            elif r.agent in _ops_agents:
                team = "ops"
            else:
                team = "engineering"
            progress.append({
                "team": team,
                "agent": r.agent,
                "note": f"{r.agent}: clean scan ({r.scan_duration_seconds:.1f}s)",
            })
    return progress


def _render_daily_brief(brief: FounderBrief, alerts: list[str]) -> str:
    """Render FounderBrief as markdown in the spec's format."""
    lines: list[str] = []
    lines.append(f"# Founder Daily Brief - {brief.date}\n")

    # Decisions needed
    lines.append("## Decisions Needed")
    if brief.decisions_needed:
        for d in brief.decisions_needed:
            severity_icon = {
                "critical": "!!",
                "high": "!",
            }.get(d["severity"], "")
            lines.append(f"- **[{d['id']}] {severity_icon} {d['summary']}**")
            lines.append(f"  - Impact: {d['business_impact']}")
            if d.get("recommended_action"):
                lines.append(f"  - Action: {d['recommended_action']}")
            if d.get("outcomes"):
                labels = [
                    OUTCOME_LABELS.get(o, o) for o in d["outcomes"]
                ]
                lines.append(f"  - Outcomes: {', '.join(labels)}")
    else:
        lines.append("No decisions needed today.")
    lines.append("")

    # Key updates
    lines.append("## Key Updates")
    if brief.key_updates:
        for u in brief.key_updates:
            lines.append(f"- **[{u['id']}]** {u['summary']}")
            if u.get("business_impact"):
                lines.append(f"  - {u['business_impact']}")
    else:
        lines.append("No notable updates.")
    lines.append("")

    # Progress
    lines.append("## Progress")
    if brief.progress:
        for p in brief.progress:
            lines.append(f"- {p['note']}")
    else:
        lines.append("All teams reporting — see details above.")
    lines.append("")

    # Cost summary
    if brief.cost_summary:
        lines.append("## Cost Summary")
        total = brief.cost_summary.get("total_estimated_cost_usd", 0)
        tokens = brief.cost_summary.get("total_estimated_tokens", 0)
        duration = brief.cost_summary.get("total_duration_seconds", 0)
        lines.append(
            f"- Total: ${total:.4f} | {tokens} tokens | {duration:.1f}s"
        )
        if alerts:
            for alert in alerts:
                lines.append(f"- **ALERT:** {alert}")
        lines.append("")

    # KPI snapshot
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
        critical_count = sum(
            1 for cf in aligned if cf.severity in ("critical", "high")
        )
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
        lines.append(
            f"{i}. **[{cf.id}]** {cf.summary} ({cf.severity})"
        )
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
        top_categories = sorted(
            category_counts.items(), key=lambda x: -x[1]
        )[:3]
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


def synthesize_status(reports: list[AgentReport]) -> str:
    """Quick cross-team status snapshot."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_findings = merge_reports(reports) if reports else []

    lines: list[str] = []
    lines.append(f"# Status Snapshot - {today}\n")

    # Summary counts
    sev_counts: dict[str, int] = {}
    for f in all_findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    critical = sev_counts.get("critical", 0)
    high = sev_counts.get("high", 0)
    medium = sev_counts.get("medium", 0)
    low = sev_counts.get("low", 0) + sev_counts.get("info", 0)

    # Split reports by team
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {"user_researcher", "product_manager", "ux_lead", "design_lead", "product_lead"}
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    eng_reports = [r for r in reports if r.agent not in _data_agents and r.agent not in _product_agents and r.agent not in _ops_agents]
    data_reports = [r for r in reports if r.agent in _data_agents]
    product_reports = [r for r in reports if r.agent in _product_agents]
    ops_reports = [r for r in reports if r.agent in _ops_agents]

    lines.append("## Engineering")
    eng_findings = [f for r in eng_reports for f in r.findings]
    eng_crit = sum(1 for f in eng_findings if f.severity == "critical")
    eng_high = sum(1 for f in eng_findings if f.severity == "high")
    lines.append(f"- Agents: {len(eng_reports)} reporting")
    lines.append(
        f"- Findings: {eng_crit} critical, {eng_high} high, "
        f"{sum(1 for f in eng_findings if f.severity == 'medium')} medium, "
        f"{sum(1 for f in eng_findings if f.severity in ('low', 'info'))} low"
    )

    for r in eng_reports:
        count = len(r.findings)
        worst = "clean"
        for sev in ("critical", "high", "medium", "low", "info"):
            if any(f.severity == sev for f in r.findings):
                worst = sev
                break
        lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
    lines.append("")

    if data_reports:
        lines.append("## Data Team")
        data_findings_all = [f for r in data_reports for f in r.findings]
        data_crit = sum(1 for f in data_findings_all if f.severity == "critical")
        data_high = sum(1 for f in data_findings_all if f.severity == "high")
        lines.append(f"- Agents: {len(data_reports)} reporting")
        lines.append(
            f"- Findings: {data_crit} critical, {data_high} high, "
            f"{sum(1 for f in data_findings_all if f.severity == 'medium')} medium, "
            f"{sum(1 for f in data_findings_all if f.severity in ('low', 'info'))} low"
        )
        for r in data_reports:
            count = len(r.findings)
            worst = "clean"
            for sev in ("critical", "high", "medium", "low", "info"):
                if any(f.severity == sev for f in r.findings):
                    worst = sev
                    break
            lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
        lines.append("")

    if product_reports:
        lines.append("## Product Team")
        product_findings_all = [f for r in product_reports for f in r.findings]
        product_crit = sum(1 for f in product_findings_all if f.severity == "critical")
        product_high = sum(1 for f in product_findings_all if f.severity == "high")
        lines.append(f"- Agents: {len(product_reports)} reporting")
        lines.append(
            f"- Findings: {product_crit} critical, {product_high} high, "
            f"{sum(1 for f in product_findings_all if f.severity == 'medium')} medium, "
            f"{sum(1 for f in product_findings_all if f.severity in ('low', 'info'))} low"
        )
        for r in product_reports:
            count = len(r.findings)
            worst = "clean"
            for sev in ("critical", "high", "medium", "low", "info"):
                if any(f.severity == sev for f in r.findings):
                    worst = sev
                    break
            lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
        lines.append("")

    if ops_reports:
        lines.append("## Operations Team")
        ops_findings_all = [f for r in ops_reports for f in r.findings]
        ops_crit = sum(1 for f in ops_findings_all if f.severity == "critical")
        ops_high = sum(1 for f in ops_findings_all if f.severity == "high")
        lines.append(f"- Agents: {len(ops_reports)} reporting")
        lines.append(
            f"- Findings: {ops_crit} critical, {ops_high} high, "
            f"{sum(1 for f in ops_findings_all if f.severity == 'medium')} medium, "
            f"{sum(1 for f in ops_findings_all if f.severity in ('low', 'info'))} low"
        )
        for r in ops_reports:
            count = len(r.findings)
            worst = "clean"
            for sev in ("critical", "high", "medium", "low", "info"):
                if any(f.severity == sev for f in r.findings):
                    worst = sev
                    break
            lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
        lines.append("")

    # Active teams
    active = [
        name for name, cfg in COS_CONFIG["teams"].items() if cfg.get("active")
    ]
    inactive = [
        name for name, cfg in COS_CONFIG["teams"].items() if not cfg.get("active")
    ]
    lines.append("## Teams")
    lines.append(f"- Active: {', '.join(active)}")
    if inactive:
        lines.append(f"- Planned: {', '.join(inactive)}")

    return "\n".join(lines)
