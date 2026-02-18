"""Analyst agent — funnel analysis, engagement metrics, marketplace health, anomaly detection.

Scans the codebase to identify instrumentation gaps and design analytics frameworks.
"""

from __future__ import annotations

import ast
import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from data_team.shared.config import APP_DIR, MODELS_DIR, SERVICES_DIR
from data_team.shared.learning import DataLearningState
from data_team.shared.report import DataTeamReport, Insight, KPISnapshot

logger = logging.getLogger(__name__)

AGENT_NAME = "analyst"

# Full user journey funnel
FUNNEL_STEPS = [
    "signup",
    "email_verify",
    "csv_upload",
    "contacts_list",
    "search_create",
    "smart_search",
    "marketplace_search",
    "intro_draft",
    "intro_request",
    "intro_approve",
    "application_create",
    "application_update",
]

# Application status enum values (expected)
APPLICATION_STATUSES = [
    "applied",
    "referred",
    "screening",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan_for_action_strings(directory: Path) -> set[str]:
    """Find all usage_log action strings in a directory."""
    actions: set[str] = set()
    if not directory.is_dir():
        return actions
    for path in directory.glob("*.py"):
        source = path.read_text()
        for match in re.finditer(r'action\s*=\s*["\']([^"\']+)["\']', source):
            actions.add(match.group(1))
        for match in re.finditer(
            r'["\'](csv_upload|smart_search|intro_draft|intro_request|marketplace_search|job_scan|application_create|search_create|contacts_list|contact_delete|coach_chat|ai_match|resume_parse)["\']',
            source,
        ):
            actions.add(match.group(1))
    return actions


def _find_api_endpoints(api_dir: Path) -> list[dict]:
    """Parse API files to find router endpoints."""
    endpoints: list[dict] = []
    if not api_dir.is_dir():
        return endpoints
    for path in sorted(api_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) or isinstance(
                node, ast.FunctionDef
            ):
                for deco in node.decorator_list:
                    deco_str = ast.dump(deco)
                    if any(
                        m in deco_str
                        for m in ["'get'", "'post'", "'put'", "'delete'", "'patch'"]
                    ):
                        endpoints.append(
                            {
                                "name": node.name,
                                "file": str(path),
                                "line": node.lineno,
                            }
                        )
    return endpoints


def _check_application_statuses(findings: list[Finding], metrics: dict) -> None:
    """Check if application status enum covers the full funnel."""
    job_model = MODELS_DIR / "job.py"
    if not job_model.exists():
        return

    source = job_model.read_text()
    found_statuses: set[str] = set()
    for match in re.finditer(r'["\'](\w+)["\']', source):
        val = match.group(1).lower()
        if val in APPLICATION_STATUSES:
            found_statuses.add(val)

    metrics["application_statuses_found"] = len(found_statuses)
    missing = set(APPLICATION_STATUSES) - found_statuses

    if missing:
        findings.append(
            Finding(
                id="analyst-003",
                severity="info",
                category="instrumentation",
                title=f"{len(missing)} application statuses not found in model",
                detail=f"Missing: {', '.join(sorted(missing))}. May be defined elsewhere.",
                file=str(job_model),
                recommendation="Verify application funnel completeness for outcome tracking",
            )
        )


def _check_marketplace_endpoints(
    endpoints: list[dict],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check marketplace endpoint coverage."""
    marketplace_file = APP_DIR / "api" / "marketplace.py"
    if not marketplace_file.exists():
        findings.append(
            Finding(
                id="analyst-004",
                severity="high",
                category="instrumentation",
                title="No marketplace API file found",
                detail="app/api/marketplace.py missing",
                recommendation="Marketplace endpoints are critical for supply/demand analytics",
            )
        )
        return

    source = marketplace_file.read_text()
    expected_patterns = ["search", "request", "approve", "decline", "listing"]
    found = [p for p in expected_patterns if p in source.lower()]
    metrics["marketplace_patterns_found"] = len(found)

    missing_patterns = [p for p in expected_patterns if p not in source.lower()]
    if missing_patterns:
        findings.append(
            Finding(
                id="analyst-005",
                severity="medium",
                category="instrumentation",
                title=f"Marketplace API may lack {len(missing_patterns)} action patterns",
                detail=f"Not found: {', '.join(missing_patterns)}",
                file=str(marketplace_file),
                recommendation="Ensure all marketplace actions are instrumented for analytics",
            )
        )


def _check_credit_transaction_types(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check credit transaction types cover earn/spend scenarios."""
    credits_service = SERVICES_DIR / "credits.py"
    if not credits_service.exists():
        return

    source = credits_service.read_text()
    expected_types = [
        "earn",
        "spend",
        "purchase",
        "upload",
        "intro",
        "search",
        "refund",
    ]
    found = [t for t in expected_types if t in source.lower()]
    metrics["credit_types_found"] = len(found)

    missing = [t for t in expected_types if t not in source.lower()]
    if len(missing) > 3:
        findings.append(
            Finding(
                id="analyst-006",
                severity="medium",
                category="instrumentation",
                title="Credit transaction types may be incomplete",
                detail=f"Expected terms not found: {', '.join(missing[:3])}",
                file=str(credits_service),
                recommendation="Verify all earn/spend scenarios have transaction_type strings",
            )
        )


# ---------------------------------------------------------------------------
# Live analytics (requires DATABASE_URL)
# ---------------------------------------------------------------------------


def _scan_anomaly_detection(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Detect anomalies in key metrics using Z-score analysis.

    Runs WEEKLY_ACTIVE_USERS and DAILY_SIGNUPS templates, computes
    rolling statistics, and flags values > 2 standard deviations from mean.
    """
    from data_team.shared.query_executor import get_executor

    qe = get_executor()
    if not qe.is_available():
        metrics["anomaly_detection_available"] = False
        return

    metrics["anomaly_detection_available"] = True
    anomalies_found = 0

    # Weekly active users — check for sudden drops or spikes
    wau_rows = qe.execute_template(
        "weekly_active_users",
        {"start_date": "2020-01-01"},
    )
    if len(wau_rows) >= 4:
        values = [r["active_users"] for r in wau_rows]
        anomaly = _detect_zscore_anomaly(values)
        metrics["wau_trend_length"] = len(values)
        metrics["wau_latest"] = values[-1]

        if anomaly:
            anomalies_found += 1
            direction = "spike" if anomaly["direction"] == "high" else "drop"
            findings.append(
                Finding(
                    id="analyst-anomaly-001",
                    severity="high" if anomaly["direction"] == "low" else "medium",
                    category="anomaly",
                    title=f"WAU {direction} detected (z={anomaly['z_score']:.1f})",
                    detail=(
                        f"Latest: {values[-1]}, mean: {anomaly['mean']:.0f}, "
                        f"std: {anomaly['std']:.1f}"
                    ),
                    recommendation=(
                        "Investigate cause — check for platform issues or marketing events"
                        if anomaly["direction"] == "low"
                        else "Positive growth signal — validate data quality"
                    ),
                )
            )

    # Credit flow — check for unusual transaction patterns
    credit_rows = qe.execute_template(
        "credit_flow",
        {"start_date": "2020-01-01", "end_date": "2099-01-01"},
    )
    if credit_rows:
        total_volume = sum(r.get("total_amount", 0) or 0 for r in credit_rows)
        metrics["credit_total_volume"] = total_volume
        earn_count = sum(
            r.get("tx_count", 0)
            for r in credit_rows
            if "earn" in str(r.get("transaction_type", "")).lower()
            or "upload" in str(r.get("transaction_type", "")).lower()
        )
        spend_count = sum(
            r.get("tx_count", 0)
            for r in credit_rows
            if "spend" in str(r.get("transaction_type", "")).lower()
            or "search" in str(r.get("transaction_type", "")).lower()
        )
        metrics["credit_earn_count"] = earn_count
        metrics["credit_spend_count"] = spend_count

        if earn_count > 0 and spend_count == 0:
            anomalies_found += 1
            findings.append(
                Finding(
                    id="analyst-anomaly-002",
                    severity="medium",
                    category="anomaly",
                    title="Credits earned but never spent — demand side inactive",
                    detail=f"Earn txns: {earn_count}, Spend txns: {spend_count}",
                    recommendation="Investigate demand-side activation — are job seekers searching?",
                )
            )

    metrics["anomalies_detected"] = anomalies_found

    if anomalies_found:
        insights.append(
            Insight(
                id="analyst-insight-anomaly",
                category="anomaly",
                title=f"{anomalies_found} metric anomalies detected",
                evidence=f"Z-score analysis on WAU + credit flow",
                impact="Anomalies may indicate platform issues, churn, or data quality problems",
                recommendation="Review anomaly details and cross-reference with deployment history",
                confidence=0.75,
                sample_size=len(wau_rows) + len(credit_rows),
            )
        )


def _scan_cohort_retention(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Analyse signup cohort retention curves from live data.

    Runs SIGNUP_COHORT_RETENTION and SIGNUP_COHORT_ACTIVATION templates,
    computes retention rates, and flags cohorts with steep drop-offs.
    """
    from data_team.shared.query_executor import get_executor

    qe = get_executor()
    if not qe.is_available():
        metrics["cohort_analysis_available"] = False
        return

    metrics["cohort_analysis_available"] = True

    # Retention: week-2 retained users per signup cohort
    retention_rows = qe.execute_template(
        "signup_cohort_retention",
        {"start_date": "2020-01-01"},
    )
    if retention_rows:
        cohort_count = len(retention_rows)
        metrics["cohort_count"] = cohort_count

        retention_rates = []
        for row in retention_rows:
            size = row.get("cohort_size", 0) or 0
            retained = row.get("retained_week_2", 0) or 0
            if size > 0:
                retention_rates.append(retained / size)

        if retention_rates:
            avg_retention = sum(retention_rates) / len(retention_rates)
            metrics["avg_week2_retention"] = round(avg_retention, 3)
            metrics["min_week2_retention"] = round(min(retention_rates), 3)
            metrics["max_week2_retention"] = round(max(retention_rates), 3)

            if avg_retention < 0.20:
                findings.append(
                    Finding(
                        id="analyst-cohort-001",
                        severity="high",
                        category="retention",
                        title=f"Week-2 retention is {avg_retention:.0%} — below 20% threshold",
                        detail=f"Across {cohort_count} cohorts, avg retention = {avg_retention:.1%}",
                        recommendation=(
                            "Focus on activation: reduce time-to-first-value, "
                            "improve onboarding, add re-engagement emails"
                        ),
                    )
                )

            insights.append(
                Insight(
                    id="analyst-insight-retention",
                    category="retention",
                    title="Cohort retention analysis",
                    evidence=(
                        f"{cohort_count} cohorts, avg week-2 retention: {avg_retention:.1%}, "
                        f"range: {min(retention_rates):.1%}–{max(retention_rates):.1%}"
                    ),
                    impact="Retention directly drives LTV and marketplace liquidity",
                    recommendation="Target 30%+ week-2 retention for marketplace viability",
                    confidence=0.85,
                    sample_size=sum(r.get("cohort_size", 0) or 0 for r in retention_rows),
                    actionable_by="product_team",
                )
            )

    # Activation: upload rate per signup cohort
    activation_rows = qe.execute_template(
        "signup_cohort_activation",
        {"start_date": "2020-01-01"},
    )
    if activation_rows:
        activation_rates = []
        for row in activation_rows:
            size = row.get("cohort_size", 0) or 0
            activated = row.get("activated", 0) or 0
            if size > 0:
                activation_rates.append(activated / size)

        if activation_rates:
            avg_activation = sum(activation_rates) / len(activation_rates)
            metrics["avg_activation_rate"] = round(avg_activation, 3)

            if avg_activation < 0.40:
                findings.append(
                    Finding(
                        id="analyst-cohort-002",
                        severity="medium",
                        category="retention",
                        title=f"Activation rate is {avg_activation:.0%} — below 40% target",
                        detail=f"Activation = first CSV upload after signup",
                        recommendation="Simplify onboarding, provide sample CSV, add activation nudges",
                    )
                )


def _detect_zscore_anomaly(
    values: list[float | int],
    threshold: float = 2.0,
) -> dict | None:
    """Check if the last value is anomalous relative to the series.

    Returns anomaly info dict or None if no anomaly.
    """
    if len(values) < 4:
        return None

    # Use all but the last value as the baseline
    baseline = values[:-1]
    latest = values[-1]

    mean = sum(baseline) / len(baseline)
    variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
    std = variance ** 0.5

    if std == 0:
        return None

    z = (latest - mean) / std

    if abs(z) >= threshold:
        return {
            "z_score": round(z, 2),
            "mean": mean,
            "std": std,
            "direction": "high" if z > 0 else "low",
        }
    return None


def _check_funnel_instrumentation(
    actions: set[str],
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Map funnel steps to instrumented actions."""
    # Map funnel steps to expected action names
    step_action_map = {
        "signup": {"signup", "register"},
        "email_verify": {"email_verify", "verify_email"},
        "csv_upload": {"csv_upload"},
        "contacts_list": {"contacts_list"},
        "search_create": {"search_create"},
        "smart_search": {"smart_search"},
        "marketplace_search": {"marketplace_search"},
        "intro_draft": {"intro_draft"},
        "intro_request": {"intro_request"},
        "intro_approve": {"intro_approve", "approve_intro"},
        "application_create": {"application_create"},
        "application_update": {"application_update"},
    }

    instrumented = 0
    gaps = []
    for step, expected_actions in step_action_map.items():
        if expected_actions & actions:
            instrumented += 1
        else:
            gaps.append(step)

    metrics["funnel_steps_total"] = len(FUNNEL_STEPS)
    metrics["funnel_steps_instrumented"] = instrumented
    metrics["funnel_coverage"] = round(instrumented / len(FUNNEL_STEPS), 2)

    if gaps:
        findings.append(
            Finding(
                id="analyst-001",
                severity="medium",
                category="instrumentation",
                title=f"{len(gaps)} funnel steps not instrumented in usage_logs",
                detail=f"Gaps: {', '.join(gaps)}",
                recommendation="Add usage_log entries for each funnel step to enable end-to-end conversion analysis",
            )
        )

    insights.append(
        Insight(
            id="analyst-insight-001",
            category="funnel",
            title="Funnel instrumentation readiness",
            evidence=f"{instrumented}/{len(FUNNEL_STEPS)} steps instrumented ({metrics['funnel_coverage']:.0%})",
            impact="Incomplete instrumentation prevents accurate conversion analysis",
            recommendation="Instrument all funnel steps before launching analytics dashboard",
            confidence=0.85,
            sample_size=len(actions),
        )
    )


def _check_engagement_tracking(
    actions: set[str],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check engagement event coverage."""
    engagement_events = {
        "coach_chat",
        "contacts_list",
        "search_create",
        "smart_search",
        "intro_draft",
        "intro_request",
    }
    found = engagement_events & actions
    metrics["engagement_events_instrumented"] = len(found)
    metrics["engagement_events_expected"] = len(engagement_events)

    missing = engagement_events - actions
    if missing:
        findings.append(
            Finding(
                id="analyst-002",
                severity="low",
                category="instrumentation",
                title=f"{len(missing)} engagement events may not be instrumented",
                detail=f"Missing: {', '.join(sorted(missing))}",
                recommendation="Verify these events are tracked for engagement analytics",
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> DataTeamReport:
    """Run all analyst checks and return a DataTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[Insight] = []
    metrics: dict = {}

    # Gather data
    api_actions = _scan_for_action_strings(APP_DIR / "api")
    service_actions = _scan_for_action_strings(SERVICES_DIR)
    all_actions = api_actions | service_actions
    endpoints = _find_api_endpoints(APP_DIR / "api")
    metrics["total_endpoints"] = len(endpoints)
    metrics["total_logged_actions"] = len(all_actions)

    # Run checks
    _check_funnel_instrumentation(all_actions, findings, insights, metrics)
    _check_engagement_tracking(all_actions, findings, metrics)
    _check_application_statuses(findings, metrics)
    _check_marketplace_endpoints(endpoints, findings, metrics)
    _check_credit_transaction_types(findings, metrics)
    _scan_anomaly_detection(findings, insights, metrics)
    _scan_cohort_retention(findings, insights, metrics)

    duration = time.time() - start

    # Learning — record scan, findings, attention weights, health snapshot
    ls = DataLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding(
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "file": getattr(f, "file", None),
            }
        )
        if getattr(f, "file", None):
            file_findings[f.file] = file_findings.get(f.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # Track KPIs
    ls.track_kpi("funnel_coverage", metrics.get("funnel_coverage", 0))
    ls.track_kpi("total_logged_actions", metrics.get("total_logged_actions", 0))

    # Record insights to learning state
    for i in insights:
        ls.record_insight(
            {
                "id": i.id,
                "category": i.category,
                "title": i.title,
                "confidence": i.confidence,
            }
        )

    learning_updates = [
        f"Scanned {len(endpoints)} endpoints, {len(all_actions)} actions"
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )
    patterns = ls.state.get("recurring_patterns", {})
    escalated = [k for k, v in patterns.items() if v.get("auto_escalated")]
    if escalated:
        learning_updates.append(f"Escalated patterns: {len(escalated)}")

    return DataTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: DataTeamReport) -> Path:
    """Save report to data_team/reports/."""
    from data_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
