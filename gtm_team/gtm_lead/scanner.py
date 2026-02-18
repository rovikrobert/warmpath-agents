"""GTM Lead agent -- coordination, daily/weekly/monthly briefs, cross-team requests.

Loads reports from stratops, monetization, marketing, and partnerships
to produce GTM team briefs with market insights, competitive intel,
pricing experiments, partnership pipeline, and strategy alignment.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.shared.report import Finding
from gtm_team.shared.config import (
    GTM_AGENT_NAMES,
    HEALTH_WEIGHTS,
    KPI_TARGETS,
    REPORTS_DIR,
)
from gtm_team.shared.intelligence import GTMIntelligence
from gtm_team.shared.learning import GTMLearningState
from gtm_team.shared.report import (
    ComplianceReviewItem,
    GTMTeamReport,
    MarketInsight,
    PartnershipOpportunity,
    PricingExperiment,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "gtm_lead"


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[GTMTeamReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[GTMTeamReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for name in GTM_AGENT_NAMES:
        if name == AGENT_NAME:
            continue
        path = REPORTS_DIR / f"{name}_latest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            reports.append(GTMTeamReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _make_sub_reports(
    reports: list[GTMTeamReport],
) -> dict[str, Any]:
    """Aggregate findings across sub-agents, identify cross-agent conflicts."""
    all_findings: list[Finding] = []
    all_insights: list[MarketInsight] = []
    all_partnerships: list[PartnershipOpportunity] = []
    all_pricing: list[PricingExperiment] = []
    all_compliance: list[ComplianceReviewItem] = []
    all_metrics: dict[str, Any] = {}
    all_divergences: list[str] = []
    all_cross_team: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for r in reports:
        all_findings.extend(r.findings)
        all_insights.extend(r.market_insights)
        all_partnerships.extend(r.partnership_opportunities)
        all_pricing.extend(r.pricing_experiments)
        all_compliance.extend(r.compliance_reviews)
        all_divergences.extend(r.strategy_divergences)
        all_cross_team.extend(r.cross_team_requests)
        for k, v in r.metrics.items():
            all_metrics[k] = v

    # Cross-agent conflict detection: pricing vs. marketing misalignment
    pricing_agents = {r.agent for r in reports if r.pricing_experiments}
    marketing_agents = {r.agent for r in reports if r.market_insights}
    if pricing_agents and marketing_agents:
        pricing_tiers = set()
        marketing_tiers = set()
        for r in reports:
            for exp in r.pricing_experiments:
                if exp.hypothesis:
                    pricing_tiers.add(exp.hypothesis[:60])
            for ins in r.market_insights:
                if ins.category == "pricing" and ins.recommended_response:
                    marketing_tiers.add(ins.recommended_response[:60])
        if pricing_tiers and marketing_tiers and not pricing_tiers & marketing_tiers:
            conflicts.append(
                f"Potential pricing misalignment: monetization proposes "
                f"{len(pricing_tiers)} experiment(s), marketing references "
                f"{len(marketing_tiers)} different pricing approach(es)"
            )

    # Check for strategy divergences across agents
    if len(all_divergences) >= 3:
        conflicts.append(
            f"{len(all_divergences)} strategy divergences flagged across sub-agents "
            f"-- review for systemic misalignment"
        )

    return {
        "findings": all_findings,
        "market_insights": all_insights,
        "partnership_opportunities": all_partnerships,
        "pricing_experiments": all_pricing,
        "compliance_reviews": all_compliance,
        "metrics": all_metrics,
        "strategy_divergences": all_divergences,
        "cross_team_requests": all_cross_team,
        "conflicts": conflicts,
    }


def _compute_gtm_readiness(metrics: dict[str, Any]) -> float:
    """Compute composite GTM readiness score (0.0 - 1.0).

    Averages available sub-scores from KPI_TARGETS:
    - Each KPI contributes current/target (capped at 1.0)
    - Missing KPIs contribute 0
    """
    scores: list[float] = []
    for kpi_name, kpi_meta in KPI_TARGETS.items():
        target = kpi_meta.get("target", 1)
        current = metrics.get(kpi_name, 0)
        if (
            isinstance(current, (int, float))
            and isinstance(target, (int, float))
            and target > 0
        ):
            scores.append(min(1.0, current / target))
        else:
            scores.append(0.0)
    return round(sum(scores) / max(1, len(scores)), 3) if scores else 0.0


def _compute_health_score(
    reports: list[GTMTeamReport],
    findings: list[Finding],
) -> float:
    """Weighted health score across agents (0-100)."""
    if not reports:
        return 0.0

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}

    per_agent_scores: dict[str, float] = {}
    for r in reports:
        penalty = sum(severity_penalty.get(f.severity, 0) for f in r.findings)
        per_agent_scores[r.agent] = max(0.0, 100.0 - penalty)

    total_weight = 0
    weighted_sum = 0.0
    for agent, score in per_agent_scores.items():
        weight = HEALTH_WEIGHTS.get(agent, 10)
        weighted_sum += score * weight
        total_weight += weight

    return round(weighted_sum / max(1, total_weight), 1)


# ---------------------------------------------------------------------------
# Cross-team request generation
# ---------------------------------------------------------------------------


def _generate_cross_team_requests(
    findings: list[Finding],
    compliance_reviews: list[ComplianceReviewItem],
    pricing_experiments: list[PricingExperiment],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Emit cross-team requests based on aggregated findings."""
    requests: list[dict[str, Any]] = []

    # Critical findings -> request to relevant team
    critical = [f for f in findings if f.severity == "critical"]
    if critical:
        requests.append(
            {
                "team": "engineering",
                "request": (
                    f"{len(critical)} critical GTM finding(s) need engineering attention"
                ),
                "urgency": "high",
                "source": AGENT_NAME,
            }
        )

    # Marketing compliance gaps -> finance team (legal agent)
    blocked_compliance = [c for c in compliance_reviews if c.status == "blocked"]
    if blocked_compliance:
        requests.append(
            {
                "team": "finance",
                "request": (
                    f"{len(blocked_compliance)} marketing compliance item(s) blocked -- "
                    f"legal review required"
                ),
                "urgency": "high",
                "source": AGENT_NAME,
            }
        )

    # Pending compliance reviews -> finance team
    pending_compliance = [c for c in compliance_reviews if c.status == "pending"]
    if pending_compliance:
        requests.append(
            {
                "team": "finance",
                "request": (
                    f"{len(pending_compliance)} marketing compliance item(s) pending "
                    f"legal review"
                ),
                "urgency": "medium",
                "source": AGENT_NAME,
            }
        )

    # Pricing implementation gaps -> engineering team
    running_experiments = [
        e for e in pricing_experiments if e.status in ("designed", "running")
    ]
    if running_experiments:
        requests.append(
            {
                "team": "engineering",
                "request": (
                    f"{len(running_experiments)} pricing experiment(s) may need "
                    f"feature-flag or billing implementation"
                ),
                "urgency": "medium",
                "source": AGENT_NAME,
            }
        )

    # Data team request if conversion metrics are missing
    if not metrics.get("funnel_metrics_available"):
        requests.append(
            {
                "team": "data",
                "request": (
                    "GTM team needs funnel conversion metrics (signup -> upload -> search -> intro) "
                    "for channel attribution"
                ),
                "urgency": "medium",
                "source": AGENT_NAME,
            }
        )

    return requests


# ---------------------------------------------------------------------------
# Scan (public API)
# ---------------------------------------------------------------------------


def scan() -> GTMTeamReport:
    """GTM Lead scan: load sub-agent reports, aggregate, produce brief."""
    start = time.time()
    reports = _load_latest_reports()

    agg = _make_sub_reports(reports)
    findings: list[Finding] = agg["findings"]
    insights: list[MarketInsight] = agg["market_insights"]
    partnerships: list[PartnershipOpportunity] = agg["partnership_opportunities"]
    pricing: list[PricingExperiment] = agg["pricing_experiments"]
    compliance: list[ComplianceReviewItem] = agg["compliance_reviews"]
    metrics: dict[str, Any] = agg["metrics"]
    divergences: list[str] = agg["strategy_divergences"]
    conflicts: list[str] = agg["conflicts"]

    # Add lead-level metrics
    metrics["sub_agents_reporting"] = len(reports)
    metrics["total_findings"] = len(findings)
    metrics["total_market_insights"] = len(insights)
    metrics["total_partnerships"] = len(partnerships)
    metrics["total_pricing_experiments"] = len(pricing)
    metrics["total_compliance_reviews"] = len(compliance)
    metrics["gtm_readiness_score"] = _compute_gtm_readiness(metrics)

    # Health score
    health = _compute_health_score(reports, findings)
    metrics["gtm_health_score"] = health

    # Competitive alert level
    urgent_insights = [i for i in insights if i.urgency in ("immediate", "this_week")]
    competitive_alert = (
        "high" if len(urgent_insights) >= 3 else "medium" if urgent_insights else "low"
    )
    metrics["competitive_alert_level"] = competitive_alert

    # Cross-team requests
    cross_team = _generate_cross_team_requests(findings, compliance, pricing, metrics)
    # Include any sub-agent cross-team requests
    cross_team.extend(agg["cross_team_requests"])

    # Add conflicts as findings
    for conflict in conflicts:
        findings.append(
            Finding(
                id=f"gtm-conflict-{len(findings)}",
                severity="medium",
                category="cross_agent_conflict",
                title="Cross-agent conflict detected",
                detail=conflict,
                recommendation="Review conflicting recommendations and align strategy",
            )
        )

    duration = time.time() - start

    # Learning
    ls = GTMLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    for f in findings:
        ls.record_finding(
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
            }
        )
        ls.record_severity_calibration(f.severity)
    for ins in insights:
        ls.record_insight(
            {
                "id": ins.id,
                "category": ins.category,
                "title": ins.title,
                "confidence": ins.confidence,
            }
        )

    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("sub_agents_reporting", len(reports))
    ls.track_kpi("total_findings", len(findings))
    ls.track_kpi("gtm_readiness", metrics["gtm_readiness_score"])

    learning_updates = [f"Aggregated {len(reports)} sub-agent reports"]
    trajectory = ls.get_health_trajectory()
    if trajectory != "insufficient_data":
        learning_updates.append(f"Health trajectory: {trajectory}")
    if conflicts:
        learning_updates.append(f"{len(conflicts)} cross-agent conflict(s) detected")

    return GTMTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        market_insights=insights,
        partnership_opportunities=partnerships,
        pricing_experiments=pricing,
        compliance_reviews=compliance,
        metrics=metrics,
        cross_team_requests=cross_team,
        strategy_divergences=divergences,
        learning_updates=learning_updates,
    )


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def save_report(report: GTMTeamReport) -> Path:
    """Save report to gtm_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path


# ---------------------------------------------------------------------------
# Brief generators
# ---------------------------------------------------------------------------


def generate_daily_brief(
    reports: list[GTMTeamReport] | None = None,
) -> str:
    """Daily brief: active initiatives, decisions needed, GTM metrics,
    competitive moves, recommendations, cross-team requests."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# GTM Team Daily Brief - {today}\n")

    if not reports:
        lines.append("No agent reports available. Run GTM team scans first.")
        return "\n".join(lines)

    # Aggregate
    agg = _make_sub_reports(reports)
    findings: list[Finding] = agg["findings"]
    insights: list[MarketInsight] = agg["market_insights"]
    partnerships: list[PartnershipOpportunity] = agg["partnership_opportunities"]
    pricing: list[PricingExperiment] = agg["pricing_experiments"]
    metrics: dict[str, Any] = agg["metrics"]
    cross_team: list[dict[str, Any]] = agg["cross_team_requests"]
    conflicts: list[str] = agg["conflicts"]

    readiness = _compute_gtm_readiness(metrics)
    health = _compute_health_score(reports, findings)
    urgent_insights = [i for i in insights if i.urgency in ("immediate", "this_week")]
    competitive_alert = (
        "HIGH" if len(urgent_insights) >= 3 else "MEDIUM" if urgent_insights else "LOW"
    )

    # -- Active Initiatives ---------------------------------------------------
    lines.append("## Active Initiatives\n")
    lines.append(f"- **Sub-agents reporting:** {len(reports)}")
    active_partners = [p for p in partnerships if p.stage not in ("identified",)]
    if active_partners:
        lines.append(f"- **Active partnerships:** {len(active_partners)}")
    running_exp = [e for e in pricing if e.status in ("designed", "running")]
    if running_exp:
        lines.append(f"- **Pricing experiments in progress:** {len(running_exp)}")
    lines.append("")

    # -- Decisions Needed -----------------------------------------------------
    critical_high = [f for f in findings if f.severity in ("critical", "high")]
    blocked_compliance = [c for c in agg["compliance_reviews"] if c.status == "blocked"]
    if critical_high or blocked_compliance or conflicts:
        lines.append("## Decisions Needed\n")
        for f in sorted(critical_high, key=lambda x: x.sort_key)[:5]:
            lines.append(f"- **[{f.id}] {f.title}** ({f.severity})")
            if f.recommendation:
                lines.append(f"  - {f.recommendation}")
        for c in blocked_compliance:
            lines.append(f"- **BLOCKED** [{c.id}] {c.asset_type}: {c.description}")
        for conflict in conflicts:
            lines.append(f"- **CONFLICT:** {conflict}")
        lines.append("")

    # -- GTM Metrics ----------------------------------------------------------
    lines.append("## GTM Metrics\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| GTM Readiness | {readiness:.0%} |")
    lines.append(f"| Health Score | {health:.0f}/100 |")
    lines.append(f"| Competitive Alert | {competitive_alert} |")
    lines.append(f"| Market Insights | {len(insights)} |")
    lines.append(f"| Partnerships | {len(partnerships)} |")
    lines.append(f"| Findings | {len(findings)} |")
    lines.append("")

    # -- Competitive Moves ----------------------------------------------------
    if urgent_insights:
        lines.append(f"## Competitive Moves ({len(urgent_insights)} urgent)\n")
        for i in urgent_insights[:5]:
            lines.append(f"- **[{i.id}] {i.title}** ({i.category})")
            if i.recommended_response:
                lines.append(f"  - Response: {i.recommended_response}")
        lines.append("")

    # -- Recommendations ------------------------------------------------------
    lines.append("## Recommendations\n")
    rec_count = 0
    for i in insights:
        if i.recommended_response and rec_count < 3:
            lines.append(f"{rec_count + 1}. **{i.title}:** {i.recommended_response}")
            rec_count += 1
    if rec_count == 0:
        lines.append("No specific recommendations from current scan.")
    lines.append("")

    # -- Agent Status ---------------------------------------------------------
    lines.append("## Agent Status\n")
    for r in reports:
        finding_count = len(r.findings)
        worst = "clean"
        for sev in ("critical", "high", "medium", "low", "info"):
            if any(f.severity == sev for f in r.findings):
                worst = sev
                break
        lines.append(
            f"- **{r.agent}**: {finding_count} findings (worst: {worst}), "
            f"{r.scan_duration_seconds:.1f}s"
        )
    lines.append("")

    # -- Learning Updates -----------------------------------------------------
    lines.append("## Learning Updates\n")
    for r in reports:
        if r.learning_updates:
            for lu in r.learning_updates:
                lines.append(f"- **{r.agent}**: {lu}")
    for agent_name in [n for n in GTM_AGENT_NAMES if n != AGENT_NAME]:
        try:
            ls = GTMLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            trajectory = report.get("health_trajectory", "insufficient_data")
            total_scans = report.get("total_scans", 0)
            escalated = len(report.get("escalated_patterns", []))
            if total_scans > 0:
                lines.append(
                    f"- **{agent_name} meta**: {total_scans} scans, "
                    f"health={trajectory}, escalated={escalated}"
                )
        except Exception:
            pass
    lines.append("")

    # -- External Intelligence ------------------------------------------------
    try:
        gi = GTMIntelligence()
        urgent_intel = gi.get_urgent()
        unadopted = gi.get_unadopted()
        if urgent_intel or unadopted:
            lines.append("## External Intelligence\n")
            if urgent_intel:
                lines.append(f"**Urgent items:** {len(urgent_intel)}")
                for item in urgent_intel[:3]:
                    lines.append(f"- [{item.severity}] {item.title}")
            if unadopted:
                lines.append(f"**Unadopted items:** {len(unadopted)}")
            lines.append("")
    except Exception:
        pass

    # -- Cross-Team Requests --------------------------------------------------
    all_cross = cross_team + _generate_cross_team_requests(
        findings, agg["compliance_reviews"], pricing, metrics
    )
    if all_cross:
        lines.append(f"## Cross-Team Requests ({len(all_cross)})\n")
        for req in all_cross:
            lines.append(
                f"- [{req.get('urgency', 'medium')}] **{req.get('team', '?')}**: "
                f"{req.get('request', '')}"
            )
        lines.append("")

    return "\n".join(lines)


def generate_weekly_report(
    reports: list[GTMTeamReport] | None = None,
) -> str:
    """Weekly GTM strategy review: channel assessment, competitive landscape,
    pricing validation, partnership pipeline."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# GTM Team Weekly Report - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    agg = _make_sub_reports(reports)
    findings: list[Finding] = agg["findings"]
    insights: list[MarketInsight] = agg["market_insights"]
    partnerships: list[PartnershipOpportunity] = agg["partnership_opportunities"]
    pricing: list[PricingExperiment] = agg["pricing_experiments"]
    metrics: dict[str, Any] = agg["metrics"]

    readiness = _compute_gtm_readiness(metrics)

    # -- Channel Assessment ---------------------------------------------------
    lines.append("## Channel Assessment\n")
    lines.append("| Channel | Status | Detail |")
    lines.append("|---------|--------|--------|")

    content_depth = metrics.get("content_pipeline_depth", 0)
    content_target = KPI_TARGETS.get("content_pipeline_depth", {}).get("target", 20)
    content_status = "Good" if content_depth >= content_target else "Building"
    lines.append(
        f"| SEO/Content | {content_status} | {content_depth}/{content_target} articles |"
    )

    lp_ready = metrics.get("landing_page_readiness", 0)
    lp_target = KPI_TARGETS.get("landing_page_readiness", {}).get("target", 6)
    lp_status = "Good" if lp_ready >= lp_target else "Building"
    lines.append(f"| Landing Pages | {lp_status} | {lp_ready}/{lp_target} pages |")

    partner_count = len(partnerships)
    partner_target = KPI_TARGETS.get("partnership_pipeline", {}).get("target", 15)
    partner_status = "Good" if partner_count >= partner_target else "Building"
    lines.append(
        f"| Partnerships | {partner_status} | {partner_count}/{partner_target} active |"
    )

    supply_targets = metrics.get("supply_side_targets", 0)
    supply_target = KPI_TARGETS.get("supply_side_targets", {}).get("target", 50)
    supply_status = "Good" if supply_targets >= supply_target else "Building"
    lines.append(
        f"| Supply Seeding | {supply_status} | {supply_targets}/{supply_target} targets |"
    )
    lines.append("")

    # -- Competitive Landscape ------------------------------------------------
    lines.append("## Competitive Landscape\n")
    competitive_insights = [
        i for i in insights if i.category in ("competitive", "market_entry")
    ]
    if competitive_insights:
        for i in competitive_insights[:5]:
            lines.append(f"- **[{i.id}] {i.title}** (confidence: {i.confidence})")
            if i.evidence:
                lines.append(f"  - {i.evidence}")
            if i.recommended_response:
                lines.append(f"  - Response: {i.recommended_response}")
    else:
        lines.append("No competitive intelligence changes this week.")
    lines.append("")

    # -- Pricing Validation ---------------------------------------------------
    lines.append("## Pricing Validation\n")
    benchmarks = metrics.get("pricing_benchmarks", 0)
    bench_target = KPI_TARGETS.get("pricing_benchmarks", {}).get("target", 10)
    lines.append(f"- **Benchmarks analysed:** {benchmarks}/{bench_target}")
    if pricing:
        lines.append(f"- **Active experiments:** {len(pricing)}")
        for exp in pricing:
            lines.append(f"  - [{exp.id}] {exp.hypothesis} (status: {exp.status})")
    else:
        lines.append("- No pricing experiments in progress.")
    lines.append("")

    # -- Partnership Pipeline -------------------------------------------------
    lines.append("## Partnership Pipeline\n")
    if partnerships:
        by_stage: dict[str, list[PartnershipOpportunity]] = {}
        for p in partnerships:
            by_stage.setdefault(p.stage, []).append(p)
        for stage in (
            "signed",
            "negotiation",
            "proposal",
            "conversation",
            "outreach",
            "identified",
        ):
            stage_partners = by_stage.get(stage, [])
            if stage_partners:
                lines.append(f"### {stage.title()} ({len(stage_partners)})")
                for p in stage_partners:
                    lines.append(f"- **{p.partner_name}** ({p.partner_type})")
                    if p.next_action:
                        lines.append(f"  - Next: {p.next_action}")
        lines.append("")
    else:
        lines.append("No partnerships tracked.")
        lines.append("")

    # -- Findings by Category -------------------------------------------------
    lines.append("## Findings by Category\n")
    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- **{cat}**: {count} findings")
    lines.append("")

    # -- Learning Deep Dive ---------------------------------------------------
    lines.append("## Learning Deep Dive\n")
    for agent_name in [n for n in GTM_AGENT_NAMES if n != AGENT_NAME]:
        try:
            ls = GTMLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            lines.append(f"### {agent_name}")
            lines.append(
                f"- Scans: {report['total_scans']}, "
                f"Findings tracked: {report['total_findings_tracked']}"
            )
            lines.append(f"- Health trajectory: {report['health_trajectory']}")
            if report.get("escalated_patterns"):
                lines.append(
                    f"- Escalated patterns: {len(report['escalated_patterns'])}"
                )
            lines.append("")
        except Exception:
            pass

    # -- Intelligence Status --------------------------------------------------
    try:
        gi = GTMIntelligence()
        intel_report = gi.generate_intel_report()
        lines.append("## Intelligence Status\n")
        lines.append(
            f"- Categories: {intel_report['categories_fresh']} fresh / "
            f"{intel_report['categories_stale']} stale of {intel_report['categories_total']}"
        )
        lines.append(
            f"- Total items: {intel_report['total_items']}, "
            f"Urgent: {intel_report['urgent_items']}"
        )
        agenda = gi.generate_research_agenda()
        if agenda:
            lines.append(f"- Research agenda: {len(agenda)} items pending")
            for item in agenda[:3]:
                lines.append(f"  - [{item['priority']}] {item['category']}")
        lines.append("")
    except Exception:
        pass

    # -- GTM Readiness Summary ------------------------------------------------
    lines.append("## GTM Readiness Summary\n")
    lines.append(f"**Composite readiness: {readiness:.0%}**\n")
    for kpi_name, kpi_meta in KPI_TARGETS.items():
        current = metrics.get(kpi_name, 0)
        target = kpi_meta.get("target", "?")
        unit = kpi_meta.get("unit", "")
        status = (
            "met"
            if isinstance(current, (int, float))
            and isinstance(target, (int, float))
            and current >= target
            else "gap"
        )
        lines.append(f"- {kpi_name}: {current}/{target} {unit} [{status}]")
    lines.append("")

    return "\n".join(lines)


def generate_monthly_review(
    reports: list[GTMTeamReport] | None = None,
) -> str:
    """Monthly market position review: competitive positioning, market sizing,
    strategy evolution, expansion readiness."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# GTM Team Monthly Review - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    agg = _make_sub_reports(reports)
    findings: list[Finding] = agg["findings"]
    insights: list[MarketInsight] = agg["market_insights"]
    partnerships: list[PartnershipOpportunity] = agg["partnership_opportunities"]
    metrics: dict[str, Any] = agg["metrics"]
    divergences: list[str] = agg["strategy_divergences"]

    readiness = _compute_gtm_readiness(metrics)
    health = _compute_health_score(reports, findings)

    # -- Competitive Positioning ----------------------------------------------
    lines.append("## Competitive Positioning\n")

    competitive_insights = [i for i in insights if i.category == "competitive"]
    market_entry_insights = [i for i in insights if i.category == "market_entry"]

    lines.append(f"- **Competitive insights tracked:** {len(competitive_insights)}")
    lines.append(f"- **Market entry insights:** {len(market_entry_insights)}")
    lines.append(f"- **GTM readiness:** {readiness:.0%}")
    lines.append(f"- **Health score:** {health:.0f}/100")
    lines.append("")

    # Differentiation assessment
    lines.append("### Differentiation Strength\n")
    differentiators = [
        "Two-sided marketplace (network holders monetize connections)",
        "Privacy-first architecture (anonymized marketplace index)",
        "Cultural context enrichment (referral messages adapt to norms)",
        "Credit economy (non-transferable, avoids money transmitter regs)",
    ]
    for d in differentiators:
        lines.append(f"- {d}")
    lines.append("")

    # -- Market Sizing Validation ---------------------------------------------
    lines.append("## Market Sizing Validation\n")
    lines.append(
        "Review whether market assumptions remain valid based on "
        "intelligence gathered this month.\n"
    )
    lines.append("| Assumption | Confidence |")
    lines.append("|------------|------------|")
    lines.append(
        "| Cold apps convert 1-3%, referrals 10-40% | High (well-researched) |"
    )
    lines.append("| Mid-career tech professionals as wedge market | High |")
    lines.append("| $20-30/mo price point sustainable | Medium (needs validation) |")
    lines.append("| Network holders motivated by referral bonuses | Medium |")
    lines.append("")

    # -- Strategy Evolution ---------------------------------------------------
    lines.append("## Strategy Evolution\n")
    if divergences:
        lines.append(f"**{len(divergences)} strategy divergence(s) flagged:**\n")
        for d in divergences:
            lines.append(f"- {d}")
    else:
        lines.append("No strategy divergences detected. Agents aligned with docs.")
    lines.append("")

    # -- Expansion Readiness --------------------------------------------------
    lines.append("## Expansion Readiness\n")
    lines.append("| Dimension | Readiness | Notes |")
    lines.append("|-----------|-----------|-------|")

    # Geographic
    lines.append("| Singapore (home) | Active | Entity registered as Majiq Pte Ltd |")
    lines.append("| SEA expansion | Planning | Monitor via sea_tech_ecosystem intel |")
    lines.append("| US market | Future | Requires pricing localisation |")

    # Vertical
    bootcamp_partners = [p for p in partnerships if p.partner_type == "bootcamp"]
    uni_partners = [p for p in partnerships if p.partner_type == "university"]
    lines.append(
        f"| Bootcamp vertical | "
        f"{'Active' if bootcamp_partners else 'Identified'} | "
        f"{len(bootcamp_partners)} partner(s) |"
    )
    lines.append(
        f"| University vertical | "
        f"{'Active' if uni_partners else 'Identified'} | "
        f"{len(uni_partners)} partner(s) |"
    )

    # Persona
    lines.append("| Career coach persona | Planning | White-label referral tools |")
    lines.append("")

    # -- KPI Trends -----------------------------------------------------------
    lines.append("## KPI Trends (Monthly)\n")
    for agent_name in [n for n in GTM_AGENT_NAMES if n != AGENT_NAME]:
        try:
            ls = GTMLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            kpi_trends = report.get("kpi_trends", {})
            if kpi_trends:
                lines.append(f"### {agent_name}")
                for kpi, trend in kpi_trends.items():
                    lines.append(f"- {kpi}: {trend}")
                lines.append("")
        except Exception:
            pass

    # -- Roadmap --------------------------------------------------------------
    lines.append("## GTM Roadmap\n")
    lines.append(
        "1. **Phase 1 (Current):** Competitive positioning, pricing validation, content pipeline"
    )
    lines.append(
        "2. **Phase 2:** Supply seeding (10-15 network holders), demand seeding (10-15 job seekers)"
    )
    lines.append(
        "3. **Phase 3:** Channel expansion (SEO, partnerships, community), geographic expansion"
    )
    lines.append("")

    return "\n".join(lines)
