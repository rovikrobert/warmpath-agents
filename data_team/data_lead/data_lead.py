"""DataLead agent — strategy, KPIs, coordination, daily/weekly/monthly briefs.

Loads reports from pipeline, analyst, and model_engineer to produce
data team briefs with KPI dashboards, insights, and cross-team requests.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.report import Finding
from data_team.shared.config import DATA_AGENT_NAMES, KPI_TARGETS, REPORTS_DIR
from data_team.shared.intelligence import DataIntelligence
from data_team.shared.learning import DataLearningState
from data_team.shared.report import DataTeamReport, Insight

logger = logging.getLogger(__name__)

AGENT_NAME = "data_lead"


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[DataTeamReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[DataTeamReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for name in DATA_AGENT_NAMES:
        if name == AGENT_NAME:
            continue  # Don't load our own report
        path = REPORTS_DIR / f"{name}_latest.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            reports.append(DataTeamReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Brief generators
# ---------------------------------------------------------------------------


def generate_daily_brief(reports: list[DataTeamReport] | None = None) -> str:
    """Daily brief: KPI dashboard, top insights, anomalies, recommendations."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Data Team Daily Brief - {today}\n")

    if not reports:
        lines.append("No agent reports available. Run data team scans first.")
        return "\n".join(lines)

    # Aggregate metrics (deduplicate findings by ID)
    all_findings: list[Finding] = []
    all_insights: list[Insight] = []
    all_metrics: dict = {}
    _seen_ids: set[str] = set()
    for r in reports:
        for f in r.findings:
            if f.id not in _seen_ids:
                all_findings.append(f)
                _seen_ids.add(f.id)
        all_insights.extend(r.insights)
        for k, v in r.metrics.items():
            all_metrics[k] = v

    # KPI dashboard
    lines.append("## KPI Dashboard\n")
    lines.append("| KPI | Status | Detail |")
    lines.append("|-----|--------|--------|")

    instrumentation_coverage = all_metrics.get("instrumentation_coverage", 0)
    funnel_coverage = all_metrics.get("funnel_coverage", 0)
    tables_found = all_metrics.get("tables_in_models", 0)
    sql_valid = all_metrics.get("sql_templates_valid", 0)
    sql_total = all_metrics.get("sql_templates_count", 0)

    lines.append(
        f"| Instrumentation | {'green' if instrumentation_coverage >= 0.8 else 'yellow'} | {instrumentation_coverage:.0%} coverage |"
    )
    lines.append(
        f"| Funnel Coverage | {'green' if funnel_coverage >= 0.8 else 'yellow'} | {funnel_coverage:.0%} steps instrumented |"
    )
    lines.append(
        f"| Schema Coverage | {'green' if tables_found >= 20 else 'yellow'} | {tables_found} tables found |"
    )
    lines.append(
        f"| SQL Templates | {'green' if sql_valid == sql_total else 'red'} | {sql_valid}/{sql_total} valid |"
    )
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
        lines.append(f"## Insights ({len(all_insights)})\n")
        for i in all_insights[:5]:
            lines.append(
                f"- **{i.title}** ({i.category}, confidence={i.confidence:.0%})"
            )
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
        lines.append(
            f"- **{r.agent}**: {finding_count} findings (worst: {worst}), {r.scan_duration_seconds:.1f}s"
        )
    lines.append("")

    # Learning Updates section
    lines.append("## Learning Updates\n")
    for r in reports:
        if r.learning_updates:
            for lu in r.learning_updates:
                lines.append(f"- **{r.agent}**: {lu}")
    # Add meta-learning summaries
    for agent_name in ["pipeline", "analyst", "model_engineer"]:
        try:
            ls = DataLearningState(agent_name)
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

    # Intelligence section
    try:
        di = DataIntelligence()
        urgent = di.get_urgent()
        unadopted = di.get_unadopted()
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


def generate_weekly_report(reports: list[DataTeamReport] | None = None) -> str:
    """Weekly deep dive: cohort readiness, marketplace health, model calibration status."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Data Team Weekly Report - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_findings: list[Finding] = []
    all_metrics: dict = {}
    _seen_ids_w: set[str] = set()
    for r in reports:
        for f in r.findings:
            if f.id not in _seen_ids_w:
                all_findings.append(f)
                _seen_ids_w.add(f.id)
        all_metrics.update(r.metrics)

    # Analytics readiness scorecard
    lines.append("## Analytics Readiness Scorecard\n")
    lines.append("| Area | Status | Blockers |")
    lines.append("|------|--------|----------|")

    schema_ok = all_metrics.get("tables_in_models", 0) >= 20
    funnel_ok = all_metrics.get("funnel_coverage", 0) >= 0.8
    model_ok = bool(all_metrics.get("warm_score_weights"))
    privacy_ok = all_metrics.get("sql_templates_valid", 0) == all_metrics.get(
        "sql_templates_count", 0
    )

    lines.append(
        f"| Schema Coverage | {'Ready' if schema_ok else 'Gaps'} | {all_metrics.get('tables_in_models', '?')} tables |"
    )
    lines.append(
        f"| Funnel Instrumentation | {'Ready' if funnel_ok else 'Gaps'} | {all_metrics.get('funnel_coverage', '?')} |"
    )
    lines.append(
        f"| Model Calibration | {'Ready' if model_ok else 'Needs Work'} | {len(all_metrics.get('warm_score_weights', {}))} weights defined |"
    )
    lines.append(
        f"| Privacy Compliance | {'Passing' if privacy_ok else 'Failing'} | {all_metrics.get('sql_templates_valid', '?')}/{all_metrics.get('sql_templates_count', '?')} templates |"
    )
    lines.append("")

    # Category breakdown
    lines.append("## Findings by Category\n")
    by_cat: dict[str, int] = {}
    for f in all_findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- **{cat}**: {count} findings")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations\n")
    if not funnel_ok:
        lines.append(
            "1. **Instrument remaining funnel steps** — critical for conversion analysis"
        )
    if not model_ok:
        lines.append(
            "2. **Add outcome feedback loop** — correlate warm_score with intro approval"
        )
    if not schema_ok:
        lines.append(
            "3. **Verify table registry** — update config.py to match actual models"
        )
    if not any([not funnel_ok, not model_ok, not schema_ok]):
        lines.append("All major areas are in good shape.")
    lines.append("")

    # Learning deep dive (weekly)
    lines.append("## Learning Deep Dive\n")
    for agent_name in ["pipeline", "analyst", "model_engineer"]:
        try:
            ls = DataLearningState(agent_name)
            report = ls.generate_meta_learning_report()
            lines.append(f"### {agent_name}")
            lines.append(
                f"- Scans: {report['total_scans']}, "
                f"Findings tracked: {report['total_findings_tracked']}"
            )
            lines.append(f"- Health trajectory: {report['health_trajectory']}")
            if report.get("fix_effectiveness_rate") is not None:
                lines.append(
                    f"- Fix effectiveness: {report['fix_effectiveness_rate']:.0%}"
                )
            if report.get("escalated_patterns"):
                lines.append(
                    f"- Escalated patterns: {len(report['escalated_patterns'])}"
                )
            if report.get("systemic_patterns"):
                lines.append(f"- Systemic patterns: {len(report['systemic_patterns'])}")
            lines.append("")
        except Exception:
            pass

    # Intelligence status (weekly)
    try:
        di = DataIntelligence()
        intel_report = di.generate_intel_report()
        lines.append("## Intelligence Status\n")
        lines.append(
            f"- Categories: {intel_report['categories_fresh']} fresh / "
            f"{intel_report['categories_stale']} stale of {intel_report['categories_total']}"
        )
        lines.append(
            f"- Total items: {intel_report['total_items']}, "
            f"Urgent: {intel_report['urgent_items']}, "
            f"Unadopted: {intel_report['unadopted_items']}"
        )
        agenda = di.generate_research_agenda()
        if agenda:
            lines.append(f"- Research agenda: {len(agenda)} items pending")
            for item in agenda[:3]:
                lines.append(f"  - [{item['priority']}] {item['category']}")
        lines.append("")
    except Exception:
        pass

    return "\n".join(lines)


def generate_monthly_review(reports: list[DataTeamReport] | None = None) -> str:
    """Monthly strategy review: KPI assessment, roadmap, data maturity."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# Data Team Monthly Review - {today}\n")

    if not reports:
        lines.append("No agent reports available.")
        return "\n".join(lines)

    all_metrics: dict = {}
    for r in reports:
        all_metrics.update(r.metrics)

    # Data maturity assessment
    lines.append("## Data Maturity Assessment\n")
    maturity_score = 0
    total_checks = 5

    if all_metrics.get("tables_in_models", 0) >= 20:
        maturity_score += 1
    if all_metrics.get("funnel_coverage", 0) >= 0.8:
        maturity_score += 1
    if all_metrics.get("warm_score_weights"):
        maturity_score += 1
    if all_metrics.get("outcome_feedback_column"):
        maturity_score += 1
    if all_metrics.get("sql_templates_valid", 0) == all_metrics.get(
        "sql_templates_count", 0
    ):
        maturity_score += 1

    level = (
        "Foundational"
        if maturity_score <= 2
        else "Developing"
        if maturity_score <= 4
        else "Mature"
    )
    lines.append(f"**Level: {level}** ({maturity_score}/{total_checks} criteria met)\n")

    lines.append("## KPI Targets\n")
    lines.append("| KPI | Target | Status |")
    lines.append("|-----|--------|--------|")
    for kpi_name, target in KPI_TARGETS.items():
        lines.append(f"| {kpi_name} | {target['target']} | Awaiting live data |")
    lines.append("")

    lines.append("## Roadmap\n")
    lines.append(
        "1. **Phase 1 (Current):** Code audit, instrumentation gaps, query templates"
    )
    lines.append(
        "2. **Phase 2:** Live data connection, dashboard, A/B testing framework"
    )
    lines.append(
        "3. **Phase 3:** ML pipeline, automated calibration, anomaly detection"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Intelligence freshness + live KPIs
# ---------------------------------------------------------------------------


def _check_intel_freshness(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Flag stale intelligence categories as findings."""
    try:
        di = DataIntelligence()
        freshness = di.check_freshness()
        stale = [cat for cat, is_fresh in freshness.items() if not is_fresh]
        metrics["intel_categories_total"] = len(freshness)
        metrics["intel_categories_stale"] = len(stale)

        if stale:
            findings.append(
                Finding(
                    id="lead-intel-001",
                    severity="low",
                    category="intelligence",
                    title=f"{len(stale)} intelligence categories are stale",
                    detail=f"Stale: {', '.join(stale[:5])}",
                    recommendation=(
                        "Run --intel to refresh, or add web scraping for auto-refresh"
                    ),
                )
            )
    except Exception:
        pass


def _populate_live_kpis(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Populate KPI dashboard with live database values."""
    from data_team.shared.query_executor import get_executor

    qe = get_executor()
    if not qe.is_available():
        metrics["live_kpis_available"] = False
        return

    metrics["live_kpis_available"] = True
    kpi_values: dict[str, float | None] = {}

    # Activation rate: users who uploaded / total users
    funnel_rows = qe.execute_template(
        "activation_funnel",
        {"start_date": "2020-01-01", "end_date": "2099-01-01"},
    )
    if funnel_rows:
        total = funnel_rows[0].get("total_users", 0) or 0
        uploaded = funnel_rows[0].get("uploaded", 0) or 0
        searched = funnel_rows[0].get("searched", 0) or 0
        requested = funnel_rows[0].get("requested_intro", 0) or 0

        kpi_values["activation_rate"] = round(uploaded / total, 3) if total else None
        kpi_values["upload_to_search_rate"] = (
            round(searched / uploaded, 3) if uploaded else None
        )
        kpi_values["search_to_intro_rate"] = (
            round(requested / searched, 3) if searched else None
        )

    # Intro approval rate
    approval_rows = qe.execute_template(
        "intro_approval_rate",
        {"start_date": "2020-01-01", "end_date": "2099-01-01"},
    )
    if approval_rows:
        total = approval_rows[0].get("total_requests", 0) or 0
        approved = approval_rows[0].get("approved", 0) or 0
        kpi_values["intro_approval_rate"] = (
            round(approved / total, 3) if total else None
        )

    # Marketplace supply coverage (distinct companies)
    marketplace_rows = qe.execute_template(
        "marketplace_health",
        {"start_date": "2020-01-01"},
    )
    if marketplace_rows:
        kpi_values["marketplace_supply_coverage"] = marketplace_rows[0].get(
            "companies_represented", 0
        )

    metrics["live_kpi_values"] = kpi_values

    # Flag KPIs that are below red threshold
    for kpi_name, value in kpi_values.items():
        if value is None:
            continue
        target_info = KPI_TARGETS.get(kpi_name)
        if not target_info:
            continue
        yellow = target_info.get("yellow", 0)
        if (
            isinstance(value, (int, float))
            and isinstance(yellow, (int, float))
            and value < yellow
        ):
            findings.append(
                Finding(
                    id=f"lead-kpi-{kpi_name}",
                    severity="high",
                    category="kpi",
                    title=f"KPI '{kpi_name}' at {value} — below yellow threshold ({yellow})",
                    detail=f"Target: {target_info['target']}, Current: {value}",
                    recommendation=f"Investigate drivers of low {kpi_name}",
                )
            )


# ---------------------------------------------------------------------------
# Public API (scan pattern)
# ---------------------------------------------------------------------------


def scan() -> DataTeamReport:
    """DataLead scan: load sub-agent reports and produce a brief."""
    start = time.time()
    reports = _load_latest_reports()

    findings: list[Finding] = []
    insights: list[Insight] = []
    metrics: dict = {}
    cross_team_requests: list[dict] = []

    # Aggregate sub-agent metrics (deduplicate findings by ID)
    _seen_ids_s: set[str] = set()
    for r in reports:
        for f in r.findings:
            if f.id not in _seen_ids_s:
                findings.append(f)
                _seen_ids_s.add(f.id)
        insights.extend(r.insights)
        for k, v in r.metrics.items():
            metrics[k] = v

    metrics["sub_agents_reporting"] = len(reports)
    metrics["total_findings"] = len(findings)
    metrics["total_insights"] = len(insights)

    # Intelligence freshness — flag stale categories as findings
    _check_intel_freshness(findings, metrics)

    # Live KPIs — populate dashboard with actual values if DB available
    _populate_live_kpis(findings, insights, metrics)

    # Check for critical findings that need cross-team attention
    critical_findings = [f for f in findings if f.severity == "critical"]
    if critical_findings:
        cross_team_requests.append(
            {
                "team": "engineering",
                "request": f"{len(critical_findings)} critical data findings need engineering attention",
                "urgency": "high",
            }
        )

    # Check if instrumentation gaps need engineering work
    funnel_coverage = metrics.get("funnel_coverage", 0)
    if isinstance(funnel_coverage, (int, float)) and funnel_coverage < 0.7:
        cross_team_requests.append(
            {
                "team": "engineering",
                "request": f"Funnel instrumentation at {funnel_coverage:.0%} — need usage_log entries for missing steps",
                "urgency": "medium",
            }
        )

    duration = time.time() - start

    # Learning — record scan, findings, health snapshot, KPIs
    ls = DataLearningState(AGENT_NAME)
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

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("sub_agents_reporting", len(reports))
    ls.track_kpi("total_findings", len(findings))

    learning_updates = [f"Aggregated {len(reports)} sub-agent reports"]
    trajectory = ls.get_health_trajectory()
    if trajectory != "insufficient_data":
        learning_updates.append(f"Health trajectory: {trajectory}")

    return DataTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        insights=insights,
        metrics=metrics,
        cross_team_requests=cross_team_requests,
        learning_updates=learning_updates,
    )


def save_report(report: DataTeamReport) -> Path:
    """Save report to data_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
