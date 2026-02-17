"""OpsLead agent — coordination, daily/weekly/monthly briefs, cross-team requests.

Loads reports from keevs, treb, naiv, and marsh
to produce ops team briefs with ecosystem health scorecard and strategy.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.report import Finding
from ops_team.shared.config import OPS_AGENT_NAMES, REPORTS_DIR
from ops_team.shared.intelligence import OpsIntelligence
from ops_team.shared.learning import OpsLearningState
from ops_team.shared.report import OpsInsight, OpsTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "ops_lead"


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[OpsTeamReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[OpsTeamReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for name in OPS_AGENT_NAMES:
        if name == AGENT_NAME:
            continue
        path = REPORTS_DIR / f"{name}_latest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            reports.append(OpsTeamReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Brief generators
# ---------------------------------------------------------------------------


def generate_daily_brief(reports: list[OpsTeamReport] | None = None) -> str:
    """Daily brief: ecosystem health, top findings, cross-team requests."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Ops Team Daily Brief - {today}\n")

    if not reports:
        lines.append("No agent reports available. Run ops team scans first.")
        return "\n".join(lines)

    # Aggregate
    all_findings: list[Finding] = []
    all_insights: list[OpsInsight] = []
    all_metrics: dict = {}
    all_cross_team: list[dict] = []
    for r in reports:
        all_findings.extend(r.findings)
        all_insights.extend(r.ops_insights)
        for k, v in r.metrics.items():
            all_metrics[k] = v
        all_cross_team.extend(r.cross_team_requests)

    # Ecosystem Health Scorecard
    lines.append("## Ecosystem Health Scorecard\n")
    lines.append("| Dimension | Score | Status |")
    lines.append("|-----------|-------|--------|")

    coaching_score = all_metrics.get("coaching_quality_score", "N/A")
    supply_score = all_metrics.get("nh_journey_coverage", "N/A")
    satisfaction_score = all_metrics.get("satisfaction_score", "N/A")
    marketplace_score = all_metrics.get("marketplace_completeness", "N/A")

    def _status(val):
        if not isinstance(val, (int, float)):
            return "Unknown"
        if val >= 0.80:
            return "Healthy"
        if val >= 0.60:
            return "Needs Work"
        return "At Risk"

    lines.append(f"| Coaching Quality | {coaching_score} | {_status(coaching_score)} |")
    lines.append(f"| Supply Activation | {supply_score} | {_status(supply_score)} |")
    lines.append(f"| User Satisfaction | {satisfaction_score} | {_status(satisfaction_score)} |")
    lines.append(f"| Marketplace Health | {marketplace_score} | {_status(marketplace_score)} |")
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

    # Key insights
    if all_insights:
        lines.append(f"## Key Insights ({len(all_insights)})\n")
        for i in all_insights[:5]:
            lines.append(f"- **{i.title}** ({i.category}, {i.confidence:.0%})")
            lines.append(f"  - {i.evidence}")
        lines.append("")

    # Cross-team requests
    if all_cross_team:
        lines.append(f"## Cross-Team Requests ({len(all_cross_team)})\n")
        for r in all_cross_team:
            lines.append(
                f"- [{r.get('urgency', 'medium')}] **{r.get('target_team', '?')}**: "
                f"{r.get('request', '')} (from {r.get('source_agent', '?')})"
            )
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
    for agent_name in ["keevs", "treb", "naiv", "marsh"]:
        try:
            ls = OpsLearningState(agent_name)
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
        oi = OpsIntelligence()
        urgent = oi.get_urgent()
        unadopted = oi.get_unadopted()
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


def generate_weekly_report(reports: list[OpsTeamReport] | None = None) -> str:
    """Weekly: ecosystem trends, supply-demand balance, satisfaction trajectory."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Ops Team Weekly Report - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_findings: list[Finding] = []
    all_metrics: dict = {}
    for r in reports:
        all_findings.extend(r.findings)
        all_metrics.update(r.metrics)

    # Ecosystem Readiness Scorecard
    lines.append("## Ecosystem Readiness\n")
    lines.append("| Area | Status | Detail |")
    lines.append("|------|--------|--------|")

    coaching = all_metrics.get("coaching_quality_score", 0)
    coaching_val = coaching if isinstance(coaching, (int, float)) else 0
    supply = all_metrics.get("nh_journey_coverage", 0)
    supply_val = supply if isinstance(supply, (int, float)) else 0
    mkt = all_metrics.get("marketplace_completeness", 0)
    mkt_val = mkt if isinstance(mkt, (int, float)) else 0

    lines.append(f"| Coaching | {'Good' if coaching_val >= 0.80 else 'Needs Work'} | Score: {coaching} |")
    lines.append(f"| Supply Activation | {'Good' if supply_val >= 0.70 else 'Needs Work'} | Score: {supply} |")
    lines.append(f"| Marketplace | {'Good' if mkt_val >= 0.80 else 'Needs Work'} | Score: {mkt} |")
    lines.append("")

    # Findings by category
    lines.append("## Findings by Category\n")
    by_cat: dict[str, int] = {}
    for f in all_findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    if by_cat:
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {count} |")
    else:
        lines.append("No findings this week.")
    lines.append("")

    # Trend indicators
    lines.append("## Trend Indicators\n")
    for agent_name in ["keevs", "treb", "naiv", "marsh"]:
        try:
            ls = OpsLearningState(agent_name)
            trajectory = ls.get_health_trajectory()
            lines.append(f"- **{agent_name}**: {trajectory}")
        except Exception:
            lines.append(f"- **{agent_name}**: no data")
    lines.append("")

    return "\n".join(lines)


def generate_monthly_review(reports: list[OpsTeamReport] | None = None) -> str:
    """Monthly: KPI progress, strategic recommendations, ecosystem maturity."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Ops Team Monthly Review - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_metrics: dict = {}
    for r in reports:
        all_metrics.update(r.metrics)

    # KPI Progress
    lines.append("## KPI Progress\n")
    from ops_team.shared.config import KPI_TARGETS
    lines.append("| KPI | Target | Current | Status |")
    lines.append("|-----|--------|---------|--------|")
    for kpi_name, kpi_def in KPI_TARGETS.items():
        target = kpi_def["target"]
        current = all_metrics.get(kpi_name, "N/A")
        if isinstance(current, (int, float)):
            status = "On Track" if current >= target else "Behind"
        else:
            status = "No Data"
        lines.append(f"| {kpi_name} | {target} | {current} | {status} |")
    lines.append("")

    # Strategic Recommendations
    lines.append("## Strategic Recommendations\n")
    all_findings = [f for r in reports for f in r.findings]
    critical_count = sum(1 for f in all_findings if f.severity in ("critical", "high"))
    total_count = len(all_findings)

    if critical_count == 0:
        lines.append("- Ecosystem is healthy. Focus on scaling supply side.")
    elif critical_count <= 3:
        lines.append(f"- {critical_count} critical/high issues need attention before launch push.")
    else:
        lines.append(f"- {critical_count} critical/high issues detected. Prioritize fixes before expanding.")
    lines.append(f"- Total findings across ops: {total_count}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scan (for orchestrator compatibility)
# ---------------------------------------------------------------------------


def scan() -> OpsTeamReport:
    """OpsLead scan: aggregate sub-agent reports, generate cross-team requests."""
    start = time.time()
    reports = _load_latest_reports()

    findings: list[Finding] = []
    insights: list[OpsInsight] = []
    metrics: dict = {}
    cross_team: list[dict] = []

    for r in reports:
        findings.extend(r.findings)
        insights.extend(r.ops_insights)
        metrics.update(r.metrics)
        cross_team.extend(r.cross_team_requests)

    # Generate cross-team requests from critical findings
    for f in findings:
        if f.severity in ("critical", "high") and f.category:
            target = _infer_target_team(f.category)
            if target:
                cross_team.append({
                    "target_team": target,
                    "urgency": f.severity,
                    "request": f"Fix: {f.title}",
                    "source_agent": f.id.split("-")[0] if "-" in f.id else "ops",
                    "finding_id": f.id,
                })

    # Ecosystem summary metrics
    metrics["ops_agents_reporting"] = len(reports)
    metrics["total_ops_findings"] = len(findings)
    metrics["total_ops_insights"] = len(insights)
    metrics["cross_team_requests_count"] = len(cross_team)

    elapsed = time.time() - start

    # Learning
    ls = OpsLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    learning_updates = []
    if len(reports) < 4:
        learning_updates.append(f"Only {len(reports)}/4 sub-agents reported")

    report = OpsTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        ops_insights=insights,
        metrics=metrics,
        cross_team_requests=cross_team,
        learning_updates=learning_updates,
    )

    return report


def _infer_target_team(category: str) -> str | None:
    """Map finding category to target team for cross-team requests."""
    engineering_cats = {"streaming", "api_quality", "error_handling", "security", "performance"}
    data_cats = {"instrumentation", "data_quality", "model_calibration"}
    product_cats = {"ux_quality", "empty_state", "journey_milestone", "feedback_collection"}

    if category in engineering_cats:
        return "engineering"
    if category in data_cats:
        return "data"
    if category in product_cats:
        return "product"
    return None


def save_report(report: OpsTeamReport) -> None:
    """Save report to disk."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("Saved %s report to %s", AGENT_NAME, path)
