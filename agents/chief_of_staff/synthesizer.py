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
from agents.shared.report import AgentReport, Finding, merge_reports

from .cos_config import COS_CONFIG, SEVERITY_WEIGHT, TEAM_REGISTRY
from .cos_learning import weekly_reflect
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
    cross_team_requests: list[dict[str, Any]] | None = None,
    founder_requests: list[dict[str, Any]] | None = None,
    resolutions: list[dict[str, Any]] | None = None,
    repairs: dict[str, Any] | None = None,
    recommendations: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Daily cycle: load reports -> classify -> enrich -> render brief."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Merge and enrich
    all_findings = merge_reports(reports) if reports else []
    # Filter noise: skip low-value categories that clutter briefs
    _NOISE_CATEGORIES = {
        "dependency-update",
        "dependency-dead",
        "dependency-missing",
    }
    all_findings = [
        f
        for f in all_findings
        if f.category not in _NOISE_CATEGORIES or f.severity in ("critical", "high")
    ]
    enriched = [_enrich_finding(f) for f in all_findings]

    # Sort by composite score
    enriched.sort(key=_score_finding, reverse=True)

    # Classify
    decisions_needed = [cf for cf in enriched if cf.severity in ("critical", "high")]
    key_updates = [cf for cf in enriched if cf.severity == "medium"]
    progress_items = _build_progress(reports)

    # Operational health checks
    operational_health = _check_operational_health(reports, cross_team_requests or [])

    # Compute per-team summaries
    _team_agents_sets = {team: set(agents) for team, agents in TEAM_REGISTRY.items()}
    team_report_groups: dict[str, list[AgentReport]] = {}
    for r in reports:
        for team_name, agent_set in _team_agents_sets.items():
            if r.agent in agent_set:
                team_report_groups.setdefault(team_name, []).append(r)
                break
        else:
            team_report_groups.setdefault("engineering", []).append(r)

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
    return rendered, data


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
    _TEAM_AGENTS = {
        "engineering": {
            "architect",
            "test_engineer",
            "perf_monitor",
            "deps_manager",
            "doc_keeper",
        },
        "data": {"pipeline", "analyst", "model_engineer", "data_lead"},
        "product": {
            "user_researcher",
            "product_manager",
            "ux_lead",
            "design_lead",
            "product_lead",
        },
        "ops": {"keevs", "treb", "naiv", "marsh", "ops_lead"},
        "finance": {
            "finance_manager",
            "credits_manager",
            "investor_relations",
            "legal_compliance",
            "finance_lead",
        },
        "gtm": {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"},
    }
    all_agents_set = set()
    for agents in _TEAM_AGENTS.values():
        all_agents_set.update(agents)
    reporting_agents = {r.agent for r in reports}
    teams_reporting = set()
    teams_silent = set()
    for team_name, agents in _TEAM_AGENTS.items():
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


def _build_progress(reports: list[AgentReport]) -> list[dict[str, Any]]:
    """Identify areas that are going well."""
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {
        "user_researcher",
        "product_manager",
        "ux_lead",
        "design_lead",
        "product_lead",
    }
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    _finance_agents = {
        "finance_manager",
        "credits_manager",
        "investor_relations",
        "legal_compliance",
        "finance_lead",
    }
    _gtm_agents = {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"}
    progress: list[dict[str, Any]] = []
    for r in reports:
        critical_high = [f for f in r.findings if f.severity in ("critical", "high")]
        if not critical_high:
            if r.agent in _data_agents:
                team = "data"
            elif r.agent in _product_agents:
                team = "product"
            elif r.agent in _ops_agents:
                team = "ops"
            elif r.agent in _finance_agents:
                team = "finance"
            elif r.agent in _gtm_agents:
                team = "gtm"
            else:
                team = "engineering"
            progress.append(
                {
                    "team": team,
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

    sev_counts.get("critical", 0)
    sev_counts.get("high", 0)
    sev_counts.get("medium", 0)
    sev_counts.get("low", 0) + sev_counts.get("info", 0)

    # Split reports by team
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {
        "user_researcher",
        "product_manager",
        "ux_lead",
        "design_lead",
        "product_lead",
    }
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    _finance_agents = {
        "finance_manager",
        "credits_manager",
        "investor_relations",
        "legal_compliance",
        "finance_lead",
    }
    _gtm_agents = {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"}
    eng_reports = [
        r
        for r in reports
        if r.agent not in _data_agents
        and r.agent not in _product_agents
        and r.agent not in _ops_agents
        and r.agent not in _finance_agents
        and r.agent not in _gtm_agents
    ]
    data_reports = [r for r in reports if r.agent in _data_agents]
    product_reports = [r for r in reports if r.agent in _product_agents]
    ops_reports = [r for r in reports if r.agent in _ops_agents]
    finance_reports = [r for r in reports if r.agent in _finance_agents]
    gtm_reports = [r for r in reports if r.agent in _gtm_agents]

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

    if finance_reports:
        lines.append("## Finance Team")
        finance_findings_all = [f for r in finance_reports for f in r.findings]
        finance_crit = sum(1 for f in finance_findings_all if f.severity == "critical")
        finance_high = sum(1 for f in finance_findings_all if f.severity == "high")
        lines.append(f"- Agents: {len(finance_reports)} reporting")
        lines.append(
            f"- Findings: {finance_crit} critical, {finance_high} high, "
            f"{sum(1 for f in finance_findings_all if f.severity == 'medium')} medium, "
            f"{sum(1 for f in finance_findings_all if f.severity in ('low', 'info'))} low"
        )
        for r in finance_reports:
            count = len(r.findings)
            worst = "clean"
            for sev in ("critical", "high", "medium", "low", "info"):
                if any(f.severity == sev for f in r.findings):
                    worst = sev
                    break
            lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
        lines.append("")

    if gtm_reports:
        lines.append("## GTM Team")
        gtm_findings_all = [f for r in gtm_reports for f in r.findings]
        gtm_crit = sum(1 for f in gtm_findings_all if f.severity == "critical")
        gtm_high = sum(1 for f in gtm_findings_all if f.severity == "high")
        lines.append(f"- Agents: {len(gtm_reports)} reporting")
        lines.append(
            f"- Findings: {gtm_crit} critical, {gtm_high} high, "
            f"{sum(1 for f in gtm_findings_all if f.severity == 'medium')} medium, "
            f"{sum(1 for f in gtm_findings_all if f.severity in ('low', 'info'))} low"
        )
        for r in gtm_reports:
            count = len(r.findings)
            worst = "clean"
            for sev in ("critical", "high", "medium", "low", "info"):
                if any(f.severity == sev for f in r.findings):
                    worst = sev
                    break
            lines.append(f"  - {r.agent}: {count} findings (worst: {worst})")
        lines.append("")

    # Normalized metrics comparison across teams
    lines.append("## Team Metrics Summary")
    lines.append("| Team | Agents | Findings | Critical | High | Health |")
    lines.append("|------|--------|----------|----------|------|--------|")
    for team_name, team_reports in [
        ("engineering", eng_reports),
        ("data", data_reports),
        ("product", product_reports),
        ("ops", ops_reports),
        ("finance", finance_reports),
        ("gtm", gtm_reports),
    ]:
        if not team_reports:
            continue
        t_findings = [f for r in team_reports for f in r.findings]
        t_crit = sum(1 for f in t_findings if f.severity == "critical")
        t_high = sum(1 for f in t_findings if f.severity == "high")
        penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
        t_penalty = sum(penalty.get(f.severity, 0) for f in t_findings)
        t_health = max(0.0, 100.0 - t_penalty)
        lines.append(
            f"| {team_name} | {len(team_reports)} | {len(t_findings)} | "
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
