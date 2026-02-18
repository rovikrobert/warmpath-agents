"""Pipeline agent — schema audit, index analysis, data quality, query template validation.

Scans the codebase (not live DB) to audit data infrastructure readiness.
"""

from __future__ import annotations

import ast
import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from data_team.shared.config import (
    ALL_TABLES,
    APP_DIR,
    DATABASE_TABLES,
    DATA_TEAM_DIR,
    MODELS_DIR,
    SERVICES_DIR,
)
from data_team.shared.learning import DataLearningState
from data_team.shared.privacy_guard import PII_COLUMNS, VAULT_TABLES, guard
from data_team.shared.report import DataTeamReport, Insight

logger = logging.getLogger(__name__)

AGENT_NAME = "pipeline"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_model_files() -> list[Path]:
    """Return all model .py files (excluding __init__)."""
    if not MODELS_DIR.is_dir():
        return []
    return [f for f in sorted(MODELS_DIR.glob("*.py")) if f.name != "__init__.py"]


def _extract_tablenames(model_files: list[Path]) -> dict[str, Path]:
    """Extract __tablename__ from model files. Returns {table_name: file_path}."""
    tables: dict[str, Path] = {}
    for path in model_files:
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (
                        isinstance(item, ast.Assign)
                        and any(
                            isinstance(t, ast.Name) and t.id == "__tablename__"
                            for t in item.targets
                        )
                        and isinstance(item.value, ast.Constant)
                    ):
                        tables[item.value.value] = path
    return tables


def _extract_columns(model_files: list[Path]) -> dict[str, list[str]]:
    """Extract Column definitions per table. Returns {tablename: [col_names]}."""
    result: dict[str, list[str]] = {}
    for path in model_files:
        try:
            source = path.read_text()
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                tablename = None
                cols: list[str] = []
                for item in node.body:
                    # Get tablename
                    if (
                        isinstance(item, ast.Assign)
                        and any(
                            isinstance(t, ast.Name) and t.id == "__tablename__"
                            for t in item.targets
                        )
                        and isinstance(item.value, ast.Constant)
                    ):
                        tablename = item.value.value
                    # Get column assignments (name: Mapped[...] = mapped_column(...))
                    if isinstance(item, ast.AnnAssign) and isinstance(
                        item.target, ast.Name
                    ):
                        cols.append(item.target.id)
                if tablename:
                    result[tablename] = cols
    return result


def _extract_indexes(model_files: list[Path]) -> dict[str, list[str]]:
    """Extract index definitions from __table_args__ and index=True columns."""
    indexes: dict[str, list[str]] = {}
    for path in model_files:
        source = path.read_text()
        # Find Index() definitions
        for match in re.finditer(r'Index\(\s*["\']([^"\']+)["\']', source):
            idx_name = match.group(1)
            # Try to associate with a table
            tablename_match = re.search(
                r'__tablename__\s*=\s*["\']([^"\']+)["\']', source
            )
            if tablename_match:
                table = tablename_match.group(1)
                indexes.setdefault(table, []).append(idx_name)
        # Find index=True in mapped_column
        for match in re.finditer(r"(\w+).*?mapped_column.*?index\s*=\s*True", source):
            col_name = match.group(1)
            tablename_match = re.search(
                r'__tablename__\s*=\s*["\']([^"\']+)["\']', source
            )
            if tablename_match:
                table = tablename_match.group(1)
                indexes.setdefault(table, []).append(f"{col_name}_idx")
    return indexes


def _check_usage_log_actions() -> tuple[set[str], set[str]]:
    """Find usage_log actions from code. Returns (logged_actions, expected_actions)."""
    logged: set[str] = set()
    # Scan service + API files for usage_log action strings
    for directory in [SERVICES_DIR, APP_DIR / "api"]:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.py"):
            source = path.read_text()
            # Match action="..." patterns and _ACTION_MAP values
            for match in re.finditer(r'action\s*=\s*["\']([^"\']+)["\']', source):
                logged.add(match.group(1))
            # Match _ACTION_MAP or _METERED_ROUTES keys
            for match in re.finditer(r'["\'](\w+)["\']\s*:', source):
                if match.group(1) not in ("action", "resource_type", "metadata"):
                    logged.add(match.group(1))

    # Expected core actions for a complete analytics funnel
    expected = {
        "csv_upload",
        "search_create",
        "smart_search",
        "intro_draft",
        "intro_request",
        "marketplace_search",
        "application_create",
        "contacts_list",
        "contact_delete",
    }
    return logged, expected


# ---------------------------------------------------------------------------
# Scan checks
# ---------------------------------------------------------------------------


def _check_schema_completeness(
    actual_tables: dict[str, Path],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Verify all expected tables exist in models."""
    expected = set(ALL_TABLES)
    actual = set(actual_tables.keys())
    metrics["tables_in_models"] = len(actual)
    metrics["tables_expected"] = len(expected)

    missing = expected - actual
    if missing:
        findings.append(
            Finding(
                id="pipe-001",
                severity="medium",
                category="schema_coverage",
                title=f"{len(missing)} expected tables not found in models",
                detail=f"Missing: {', '.join(sorted(missing))}",
                recommendation="Verify table registry in data_team/shared/config.py matches actual models",
            )
        )

    extra = actual - expected
    if extra:
        findings.append(
            Finding(
                id="pipe-002",
                severity="info",
                category="schema_coverage",
                title=f"{len(extra)} tables in models not in registry",
                detail=f"Extra: {', '.join(sorted(extra))}",
                recommendation="Add to DATABASE_TABLES in config.py if analytics-relevant",
            )
        )


def _check_column_quality(
    columns: dict[str, list[str]],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for missing standard columns."""
    tables_missing_timestamps = []
    for table, cols in columns.items():
        if table == "audit_logs":
            continue  # audit_logs only has created_at
        if "created_at" not in cols:
            tables_missing_timestamps.append(table)

    if tables_missing_timestamps:
        findings.append(
            Finding(
                id="pipe-003",
                severity="medium",
                category="data_quality",
                title=f"{len(tables_missing_timestamps)} tables missing created_at",
                detail=f"Tables: {', '.join(tables_missing_timestamps[:5])}",
                recommendation="Add created_at for time-series analytics",
            )
        )
    metrics["tables_with_timestamps"] = len(columns) - len(tables_missing_timestamps)


def _check_index_coverage(
    indexes: dict[str, list[str]],
    actual_tables: dict[str, Path],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for analytics-critical missing indexes."""
    total_indexes = sum(len(v) for v in indexes.values())
    metrics["index_count"] = total_indexes

    # Tables that should have analytics indexes
    analytics_tables = {
        "usage_logs",
        "csv_uploads",
        "search_requests",
        "applications",
        "match_results",
        "credit_transactions",
        "intro_facilitations",
    }
    missing_idx = analytics_tables - set(indexes.keys())
    # Only flag tables that actually exist
    missing_idx = missing_idx & set(actual_tables.keys())

    if missing_idx:
        findings.append(
            Finding(
                id="pipe-004",
                severity="medium",
                category="instrumentation",
                title=f"{len(missing_idx)} analytics tables may lack explicit indexes",
                detail=f"Tables: {', '.join(sorted(missing_idx))}",
                recommendation="Add composite indexes for date-range + user_id queries",
            )
        )


def _check_pii_protection(
    columns: dict[str, list[str]],
    findings: list[Finding],
) -> None:
    """Verify PII columns are in the privacy guard registry."""
    contacts_cols = set(columns.get("contacts", []))
    known_pii = set(PII_COLUMNS)
    sensitive_in_contacts = contacts_cols & known_pii
    metrics_count = len(sensitive_in_contacts)

    if metrics_count < 10:
        findings.append(
            Finding(
                id="pipe-005",
                severity="high",
                category="privacy_compliance",
                title="PII column registry may be incomplete",
                detail=f"Found {metrics_count} of 13 expected PII columns in contacts model",
                recommendation="Verify all encrypted columns are in PII_COLUMNS",
            )
        )


def _check_instrumentation(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Check usage_log action coverage."""
    logged, expected = _check_usage_log_actions()
    metrics["logged_actions"] = len(logged)
    metrics["expected_actions"] = len(expected)

    missing_actions = expected - logged
    coverage = 1.0 - (len(missing_actions) / max(1, len(expected)))
    metrics["instrumentation_coverage"] = round(coverage, 2)

    if missing_actions:
        findings.append(
            Finding(
                id="pipe-006",
                severity="medium",
                category="instrumentation",
                title=f"{len(missing_actions)} expected actions not instrumented",
                detail=f"Missing: {', '.join(sorted(missing_actions))}",
                recommendation="Add usage_log entries for missing funnel actions",
            )
        )

    insights.append(
        Insight(
            id="pipe-insight-001",
            category="instrumentation",
            title="Instrumentation coverage assessment",
            evidence=f"{len(logged)} actions logged, {len(expected)} expected, coverage={coverage:.0%}",
            impact="Gaps prevent end-to-end funnel analysis",
            recommendation="Prioritize instrumenting missing actions before analytics launch",
            confidence=0.9,
            sample_size=len(logged),
        )
    )


def _check_data_retention(
    findings: list[Finding],
) -> None:
    """Check data retention policies exist in code."""
    retention_file = SERVICES_DIR / "data_retention.py"
    if not retention_file.exists():
        findings.append(
            Finding(
                id="pipe-007",
                severity="high",
                category="privacy_compliance",
                title="No data retention service found",
                detail="data_retention.py not found in services",
                recommendation="Implement data retention sweeps per CLAUDE.md (12mo usage_logs, 24mo credit archive)",
                file=str(retention_file),
            )
        )
        return

    source = retention_file.read_text()
    if "usage_logs" not in source:
        findings.append(
            Finding(
                id="pipe-008",
                severity="medium",
                category="privacy_compliance",
                title="Data retention may not cover usage_logs",
                detail="'usage_logs' not found in data_retention.py",
                recommendation="Verify usage_logs purge is implemented (12-month TTL)",
                file=str(retention_file),
            )
        )


def _validate_sql_templates(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Re-validate SQL templates (defense-in-depth)."""
    from data_team.shared.sql_templates import ALL_TEMPLATES, validate_all_templates

    errors = validate_all_templates()
    metrics["sql_templates_count"] = len(ALL_TEMPLATES)
    metrics["sql_templates_valid"] = len(ALL_TEMPLATES) - len(errors)

    if errors:
        findings.append(
            Finding(
                id="pipe-009",
                severity="critical",
                category="privacy_compliance",
                title=f"{len(errors)} SQL templates failed privacy validation",
                detail="\n".join(errors[:3]),
                recommendation="Fix privacy violations in sql_templates.py",
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> DataTeamReport:
    """Run all pipeline checks and return a DataTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[Insight] = []
    metrics: dict = {}

    model_files = _find_model_files()
    actual_tables = _extract_tablenames(model_files)
    columns = _extract_columns(model_files)
    indexes = _extract_indexes(model_files)

    _check_schema_completeness(actual_tables, findings, metrics)
    _check_column_quality(columns, findings, metrics)
    _check_index_coverage(indexes, actual_tables, findings, metrics)
    _check_pii_protection(columns, findings)
    _check_instrumentation(findings, insights, metrics)
    _check_data_retention(findings)
    _validate_sql_templates(findings, metrics)

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
                "file": f.file,
            }
        )
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    # Record severity calibration
    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot (higher = healthier; penalize by finding severity)
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # Track KPIs
    ls.track_kpi("tables_in_models", metrics.get("tables_in_models", 0))
    ls.track_kpi("instrumentation_coverage", metrics.get("instrumentation_coverage", 0))

    learning_updates = [
        f"Scanned {len(model_files)} model files, {len(actual_tables)} tables"
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
