"""ProductLead agent — coordination, daily/weekly/monthly briefs, cross-team requests.

Loads reports from user_researcher, product_manager, ux_lead, and design_lead
to produce product team briefs with insights, UX/design debt, and strategy.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.report import Finding
from product_team.shared.config import PRODUCT_AGENT_NAMES, REPORTS_DIR
from product_team.shared.intelligence import ProductIntelligence
from product_team.shared.learning import ProductLearningState
from product_team.shared.report import ProductInsight, ProductTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "product_lead"


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[ProductTeamReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[ProductTeamReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for name in PRODUCT_AGENT_NAMES:
        if name == AGENT_NAME:
            continue
        path = REPORTS_DIR / f"{name}_latest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            reports.append(ProductTeamReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Brief generators
# ---------------------------------------------------------------------------


def generate_daily_brief(reports: list[ProductTeamReport] | None = None) -> str:
    """Daily brief: top insight, UX friction, design debt, competitive intel."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Product Team Daily Brief - {today}\n")

    if not reports:
        lines.append("No agent reports available. Run product team scans first.")
        return "\n".join(lines)

    # Aggregate
    all_findings: list[Finding] = []
    all_insights: list[ProductInsight] = []
    all_metrics: dict = {}
    for r in reports:
        all_findings.extend(r.findings)
        all_insights.extend(r.product_insights)
        for k, v in r.metrics.items():
            all_metrics[k] = v

    # Scorecard
    lines.append("## Product Scorecard\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    ux_score = all_metrics.get("ux_health_score", "N/A")
    ds_score = all_metrics.get("design_system_score", "N/A")
    fc_score = all_metrics.get("feature_coverage_score", "N/A")
    lines.append(f"| UX Health | {ux_score} |")
    lines.append(f"| Design System | {ds_score} |")
    lines.append(f"| Feature Coverage | {fc_score} |")
    lines.append("")

    # Top findings
    critical_high = [f for f in all_findings if f.severity in ("critical", "high")]
    if critical_high:
        lines.append(f"## Attention Required ({len(critical_high)} items)\n")
        for f in sorted(critical_high, key=lambda f: f.sort_key)[:5]:
            lines.append(f"- **[{f.id}] {f.title}** ({f.severity})")
            if f.recommendation:
                lines.append(f"  - {f.recommendation}")
        lines.append("")

    # Top insights
    if all_insights:
        lines.append(f"## Key Insights ({len(all_insights)})\n")
        for i in all_insights[:5]:
            lines.append(f"- **{i.title}** ({i.category}, {i.confidence:.0%})")
            lines.append(f"  - {i.evidence}")
        lines.append("")

    # Agent status
    lines.append("## Agent Status\n")
    for r in reports:
        finding_count = len(r.findings)
        worst = "clean"
        for sev in ("critical", "high", "medium", "low", "info"):
            if any(f.severity == sev for f in r.findings):
                worst = sev
                break
        lines.append(f"- **{r.agent}**: {finding_count} findings (worst: {worst}), {r.scan_duration_seconds:.1f}s")
    lines.append("")

    # Learning Updates
    lines.append("## Learning Updates\n")
    for r in reports:
        if r.learning_updates:
            for lu in r.learning_updates:
                lines.append(f"- **{r.agent}**: {lu}")
    for agent_name in ["user_researcher", "product_manager", "ux_lead", "design_lead"]:
        try:
            ls = ProductLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            trajectory = report.get("health_trajectory", "insufficient_data")
            total_scans = report.get("total_scans", 0)
            escalated = len(report.get("escalated_patterns", []))
            if total_scans > 0:
                lines.append(f"- **{agent_name} meta**: {total_scans} scans, "
                             f"health={trajectory}, escalated={escalated}")
        except Exception:
            pass
    lines.append("")

    # Intelligence
    try:
        pi = ProductIntelligence()
        urgent = pi.get_urgent()
        unadopted = pi.get_unadopted()
        if urgent or unadopted:
            lines.append("## External Intelligence\n")
            if urgent:
                lines.append(f"**Urgent items:** {len(urgent)}")
                for item in urgent[:3]:
                    lines.append(f"- [{item.severity}] {item.title}")
            if unadopted:
                lines.append(f"**Unadopted items:** {len(unadopted)}")
            lines.append("")
    except Exception:
        pass

    return "\n".join(lines)


def generate_weekly_report(reports: list[ProductTeamReport] | None = None) -> str:
    """Weekly: feature scorecard, UX/design debt, research priorities."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Product Team Weekly Report - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_findings: list[Finding] = []
    all_metrics: dict = {}
    for r in reports:
        all_findings.extend(r.findings)
        all_metrics.update(r.metrics)

    # Product readiness scorecard
    lines.append("## Product Readiness Scorecard\n")
    lines.append("| Area | Status | Detail |")
    lines.append("|------|--------|--------|")

    ux_ok = all_metrics.get("ux_health_score", 0)
    ux_ok_val = ux_ok if isinstance(ux_ok, (int, float)) else 0
    ds_ok = all_metrics.get("design_system_score", 0)
    ds_ok_val = ds_ok if isinstance(ds_ok, (int, float)) else 0
    fc_ok = all_metrics.get("feature_coverage_score", 0)
    fc_ok_val = fc_ok if isinstance(fc_ok, (int, float)) else 0

    lines.append(f"| UX Health | {'Good' if ux_ok_val >= 70 else 'Needs Work'} | Score: {ux_ok} |")
    lines.append(f"| Design System | {'Good' if ds_ok_val >= 90 else 'Needs Work'} | Score: {ds_ok}% |")
    lines.append(f"| Feature Coverage | {'Good' if fc_ok_val >= 0.9 else 'Gaps'} | Score: {fc_ok} |")
    lines.append("")

    # Findings by category
    lines.append("## Findings by Category\n")
    by_cat: dict[str, int] = {}
    for f in all_findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- **{cat}**: {count} findings")
    lines.append("")

    # Learning deep dive
    lines.append("## Learning Deep Dive\n")
    for agent_name in ["user_researcher", "product_manager", "ux_lead", "design_lead"]:
        try:
            ls = ProductLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            lines.append(f"### {agent_name}")
            lines.append(f"- Scans: {report['total_scans']}, "
                         f"Findings tracked: {report['total_findings_tracked']}")
            lines.append(f"- Health trajectory: {report['health_trajectory']}")
            if report.get("escalated_patterns"):
                lines.append(f"- Escalated patterns: {len(report['escalated_patterns'])}")
            lines.append("")
        except Exception:
            pass

    # Intelligence status
    try:
        pi = ProductIntelligence()
        intel_report = pi.generate_intel_report()
        lines.append("## Intelligence Status\n")
        lines.append(f"- Categories: {intel_report['categories_fresh']} fresh / "
                     f"{intel_report['categories_stale']} stale of {intel_report['categories_total']}")
        lines.append(f"- Total items: {intel_report['total_items']}, "
                     f"Urgent: {intel_report['urgent_items']}")
        agenda = pi.generate_research_agenda()
        if agenda:
            lines.append(f"- Research agenda: {len(agenda)} items pending")
            for item in agenda[:3]:
                lines.append(f"  - [{item['priority']}] {item['category']}")
        lines.append("")
    except Exception:
        pass

    return "\n".join(lines)


def generate_monthly_review(reports: list[ProductTeamReport] | None = None) -> str:
    """Monthly: persona refresh, strategy assessment, roadmap."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Product Team Monthly Review - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_metrics: dict = {}
    for r in reports:
        all_metrics.update(r.metrics)

    # Product maturity assessment
    lines.append("## Product Maturity Assessment\n")
    maturity_score = 0
    total_checks = 5

    if all_metrics.get("ux_health_score", 0) >= 50:
        maturity_score += 1
    if all_metrics.get("design_system_score", 0) >= 80:
        maturity_score += 1
    if all_metrics.get("feature_coverage_score", 0) >= 0.8:
        maturity_score += 1
    if all_metrics.get("pages_found", 0) >= 10:
        maturity_score += 1
    if all_metrics.get("total_api_endpoints", 0) >= 20:
        maturity_score += 1

    level = "Foundational" if maturity_score <= 2 else "Developing" if maturity_score <= 4 else "Mature"
    lines.append(f"**Level: {level}** ({maturity_score}/{total_checks} criteria met)\n")

    lines.append("## Persona Refresh\n")
    from product_team.shared.config import PERSONAS
    for pid, persona in PERSONAS.items():
        lines.append(f"### {persona['label']}")
        lines.append(f"- Tier: {persona['tier']}")
        lines.append(f"- Page coverage: {all_metrics.get(f'{pid}_page_coverage', 'N/A')}")
        lines.append(f"- Key pages: {', '.join(persona.get('key_pages', []))}")
        lines.append("")

    lines.append("## Roadmap\n")
    lines.append("1. **Phase 1 (Current):** UX audit, design system, feature mapping")
    lines.append("2. **Phase 2:** User research, persona validation, usability testing")
    lines.append("3. **Phase 3:** Competitive analysis, feature prioritization, PRD generation")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API (scan pattern)
# ---------------------------------------------------------------------------


def scan() -> ProductTeamReport:
    """ProductLead scan: load sub-agent reports and produce a brief."""
    start = time.time()
    reports = _load_latest_reports()

    findings: list[Finding] = []
    insights: list[ProductInsight] = []
    metrics: dict = {}
    cross_team_requests: list[dict] = []

    # Aggregate sub-agent metrics
    for r in reports:
        findings.extend(r.findings)
        insights.extend(r.product_insights)
        for k, v in r.metrics.items():
            metrics[k] = v

    metrics["sub_agents_reporting"] = len(reports)
    metrics["total_findings"] = len(findings)
    metrics["total_insights"] = len(insights)

    # Check for critical findings needing engineering attention
    critical_findings = [f for f in findings if f.severity == "critical"]
    if critical_findings:
        cross_team_requests.append({
            "team": "engineering",
            "request": f"{len(critical_findings)} critical product findings need engineering attention",
            "urgency": "high",
        })

    # Check UX health for cross-team escalation
    ux_score = metrics.get("ux_health_score", 100)
    if isinstance(ux_score, (int, float)) and ux_score < 50:
        cross_team_requests.append({
            "team": "engineering",
            "request": f"UX health score is {ux_score} — frontend needs accessibility improvements",
            "urgency": "medium",
        })

    # Check feature coverage gaps
    fc_score = metrics.get("feature_coverage_score", 1.0)
    if isinstance(fc_score, (int, float)) and fc_score < 0.7:
        cross_team_requests.append({
            "team": "engineering",
            "request": f"Feature coverage at {fc_score:.0%} — API-frontend alignment needed",
            "urgency": "medium",
        })

    duration = time.time() - start

    # Learning
    ls = ProductLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    for f in findings:
        ls.record_finding({"id": f.id, "severity": f.severity, "category": f.category, "title": f.title})
        ls.record_severity_calibration(f.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("sub_agents_reporting", len(reports))
    ls.track_kpi("total_findings", len(findings))

    learning_updates = [f"Aggregated {len(reports)} sub-agent reports"]
    trajectory = ls.get_health_trajectory()
    if trajectory != "insufficient_data":
        learning_updates.append(f"Health trajectory: {trajectory}")

    return ProductTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        product_insights=insights,
        metrics=metrics,
        cross_team_requests=cross_team_requests,
        learning_updates=learning_updates,
    )


def save_report(report: ProductTeamReport) -> Path:
    """Save report to product_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
