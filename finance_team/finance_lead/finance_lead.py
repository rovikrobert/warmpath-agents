"""FinanceLead agent — coordination, daily/weekly/monthly briefs, cross-team requests.

Loads reports from finance_manager, credits_manager, investor_relations, and legal_compliance
to produce finance team briefs with financial health dashboard and strategy.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.report import Finding
from finance_team.shared.config import FINANCE_AGENT_NAMES, KPI_TARGETS, REPORTS_DIR
from finance_team.shared.intelligence import FinanceIntelligence
from finance_team.shared.learning import FinanceLearningState
from finance_team.shared.report import (
    ComplianceFinding,
    FinancialFinding,
    FinanceTeamReport,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "finance_lead"


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[FinanceTeamReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[FinanceTeamReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for name in FINANCE_AGENT_NAMES:
        if name == AGENT_NAME:
            continue
        path = REPORTS_DIR / f"{name}_latest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            reports.append(FinanceTeamReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Brief generators
# ---------------------------------------------------------------------------


def generate_daily_brief(reports: list[FinanceTeamReport] | None = None) -> str:
    """Daily brief: financial health dashboard, top findings, cross-team requests."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Finance Team Daily Brief - {today}\n")

    if not reports:
        lines.append("No agent reports available. Run finance team scans first.")
        return "\n".join(lines)

    # Aggregate
    all_findings: list[Finding] = []
    all_financial: list[FinancialFinding] = []
    all_compliance: list[ComplianceFinding] = []
    all_metrics: dict = {}
    all_cross_team: list[dict] = []
    for r in reports:
        all_findings.extend(r.findings)
        all_financial.extend(r.financial_findings)
        all_compliance.extend(r.compliance_findings)
        for k, v in r.metrics.items():
            all_metrics[k] = v
        all_cross_team.extend(r.cross_team_requests)

    # Financial Health Dashboard
    lines.append("## Financial Health Dashboard\n")
    lines.append("| Dimension | Score | Status |")
    lines.append("|-----------|-------|--------|")

    stripe_score = all_metrics.get("stripe_webhook_coverage", "N/A")
    credit_score = all_metrics.get("credit_economy_score", "N/A")
    compliance_score = all_metrics.get("compliance_score", "N/A")
    ir_score = all_metrics.get("investor_readiness_score", "N/A")

    def _status(val):
        if not isinstance(val, (int, float)):
            return "Unknown"
        if val >= 0.80:
            return "Healthy"
        if val >= 0.60:
            return "Needs Work"
        return "At Risk"

    lines.append(f"| Stripe Integration | {stripe_score} | {_status(stripe_score)} |")
    lines.append(f"| Credit Economy | {credit_score} | {_status(credit_score)} |")
    lines.append(f"| Regulatory Compliance | {compliance_score} | {_status(compliance_score)} |")
    lines.append(f"| Investor Readiness | {ir_score} | {_status(ir_score)} |")
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

    # Compliance findings
    if all_compliance:
        lines.append(f"## Compliance Findings ({len(all_compliance)})\n")
        for c in all_compliance[:5]:
            reg = f" ({c.regulation})" if c.regulation else ""
            lines.append(f"- [{c.severity.upper()}]{reg} **{c.title}**")
            if c.recommendation:
                lines.append(f"  - {c.recommendation}")
        lines.append("")

    # Financial findings
    if all_financial:
        lines.append(f"## Financial Findings ({len(all_financial)})\n")
        for f in all_financial[:5]:
            lines.append(f"- [{f.severity.upper()}] **{f.title}** ({f.category})")
            if f.recommendation:
                lines.append(f"  - {f.recommendation}")
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
    for agent_name in ["finance_manager", "credits_manager", "investor_relations", "legal_compliance"]:
        try:
            ls = FinanceLearningState(agent_name)
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
        fi = FinanceIntelligence()
        urgent = fi.get_urgent()
        unadopted = fi.get_unadopted()
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


def generate_weekly_report(reports: list[FinanceTeamReport] | None = None) -> str:
    """Weekly: financial readiness, findings by category, trend indicators."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Finance Team Weekly Report - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_findings: list[Finding] = []
    all_metrics: dict = {}
    for r in reports:
        all_findings.extend(r.findings)
        all_metrics.update(r.metrics)

    # Financial Readiness Scorecard
    lines.append("## Financial Readiness\n")
    lines.append("| Area | Status | Detail |")
    lines.append("|------|--------|--------|")

    stripe = all_metrics.get("stripe_webhook_coverage", 0)
    stripe_val = stripe if isinstance(stripe, (int, float)) else 0
    credit = all_metrics.get("credit_economy_score", 0)
    credit_val = credit if isinstance(credit, (int, float)) else 0
    compliance = all_metrics.get("compliance_score", 0)
    compliance_val = compliance if isinstance(compliance, (int, float)) else 0

    lines.append(f"| Stripe | {'Good' if stripe_val >= 0.80 else 'Needs Work'} | Score: {stripe} |")
    lines.append(f"| Credit Economy | {'Good' if credit_val >= 0.80 else 'Needs Work'} | Score: {credit} |")
    lines.append(f"| Compliance | {'Good' if compliance_val >= 0.80 else 'Needs Work'} | Score: {compliance} |")
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
    for agent_name in ["finance_manager", "credits_manager", "investor_relations", "legal_compliance"]:
        try:
            ls = FinanceLearningState(agent_name)
            trajectory = ls.get_health_trajectory()
            lines.append(f"- **{agent_name}**: {trajectory}")
        except Exception:
            lines.append(f"- **{agent_name}**: no data")
    lines.append("")

    return "\n".join(lines)


def generate_monthly_review(reports: list[FinanceTeamReport] | None = None) -> str:
    """Monthly: KPI progress, strategic recommendations, compliance status."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Finance Team Monthly Review - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_metrics: dict = {}
    for r in reports:
        all_metrics.update(r.metrics)

    # KPI Progress
    lines.append("## KPI Progress\n")
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
        lines.append("- Financial infrastructure is healthy. Focus on investor readiness.")
    elif critical_count <= 3:
        lines.append(f"- {critical_count} critical/high issues need attention before fundraise.")
    else:
        lines.append(f"- {critical_count} critical/high issues detected. Prioritize fixes before investor conversations.")
    lines.append(f"- Total findings across finance: {total_count}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scan (for orchestrator compatibility)
# ---------------------------------------------------------------------------


def scan() -> FinanceTeamReport:
    """FinanceLead scan: aggregate sub-agent reports, generate cross-team requests."""
    start = time.time()
    reports = _load_latest_reports()

    findings: list[Finding] = []
    financial_findings: list[FinancialFinding] = []
    compliance_findings: list[ComplianceFinding] = []
    metrics: dict = {}
    cross_team: list[dict] = []

    for r in reports:
        findings.extend(r.findings)
        financial_findings.extend(r.financial_findings)
        compliance_findings.extend(r.compliance_findings)
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
                    "source_agent": f.id.split("-")[0] if "-" in f.id else "finance",
                    "finding_id": f.id,
                })

    # Summary metrics
    metrics["finance_agents_reporting"] = len(reports)
    metrics["total_finance_findings"] = len(findings)
    metrics["total_financial_findings"] = len(financial_findings)
    metrics["total_compliance_findings"] = len(compliance_findings)
    metrics["cross_team_requests_count"] = len(cross_team)

    elapsed = time.time() - start

    # Learning
    ls = FinanceLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    learning_updates = []
    if len(reports) < 4:
        learning_updates.append(f"Only {len(reports)}/4 sub-agents reported")

    report = FinanceTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        financial_findings=financial_findings,
        compliance_findings=compliance_findings,
        metrics=metrics,
        cross_team_requests=cross_team,
        learning_updates=learning_updates,
    )

    return report


def _infer_target_team(category: str) -> str | None:
    """Map finding category to target team for cross-team requests."""
    engineering_cats = {"stripe_integration", "billing", "security_posture"}
    data_cats = {"instrumentation", "data_quality"}
    product_cats = {"ux_quality", "feature_coverage"}
    ops_cats = {"coaching_quality", "marketplace_health"}

    if category in engineering_cats:
        return "engineering"
    if category in data_cats:
        return "data"
    if category in product_cats:
        return "product"
    if category in ops_cats:
        return "ops"
    return None


def save_report(report: FinanceTeamReport) -> None:
    """Save report to disk."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("Saved %s report to %s", AGENT_NAME, path)
