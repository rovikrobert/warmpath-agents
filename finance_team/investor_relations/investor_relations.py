"""Investor Relations agent — investor readiness scanner.

Scans the codebase for signals that matter to investors: test count accuracy,
technical debt, schema maturity, feature completeness, security posture, and
agent team maturity. Produces a FinanceTeamReport for the CoS pipeline.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from finance_team.shared.config import (
    APP_DIR,
    MODELS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    TESTS_DIR,
)
from finance_team.shared.learning import FinanceLearningState
from finance_team.shared.report import FinancialFinding, FinanceTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "investor_relations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(errors="replace")
    except OSError as exc:
        logger.warning("investor_relations: could not read %s: %s", path, exc)
        return ""


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT, falling back to str(path)."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check 1: Test count claims in CLAUDE.md vs reality
# ---------------------------------------------------------------------------


def _check_test_count_claims(
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Compare test count claimed in CLAUDE.md against actual test functions in tests/."""
    claude_md_path = PROJECT_ROOT / "CLAUDE.md"
    source = _read_safe(claude_md_path)

    # Extract claimed test count from CLAUDE.md
    claimed_count: int | None = None
    for pattern in [r"\*\*(\d+)\s+tests\*\*", r"(\d+)\s+tests"]:
        match = re.search(pattern, source)
        if match:
            claimed_count = int(match.group(1))
            break

    metrics["test_count_claimed"] = claimed_count

    if claimed_count is None:
        findings.append(
            Finding(
                id="ir-tests-000",
                severity="low",
                category="investor_readiness",
                title="No test count claim found in CLAUDE.md",
                detail="Could not detect a '**N tests**' or 'N tests' pattern in CLAUDE.md",
                file=_relative(claude_md_path),
                recommendation="Add test count to CLAUDE.md Current Status section for data room accuracy",
            )
        )
        metrics["test_count_actual"] = None
        metrics["test_count_delta_pct"] = None
        return

    # Count actual test functions/classes across tests/ directory
    test_files = list(TESTS_DIR.glob("test_*.py")) + list(
        TESTS_DIR.glob("**/test_*.py")
    )
    test_files = list(set(test_files))  # deduplicate
    metrics["test_file_count"] = len(test_files)

    actual_count = 0
    for test_file in test_files:
        content = _read_safe(test_file)
        # Count only def test_ functions (class Test* are containers, not tests)
        actual_count += len(re.findall(r"def test_", content))

    metrics["test_count_actual"] = actual_count

    if claimed_count == 0:
        metrics["test_count_delta_pct"] = None
        return

    delta_pct = abs(claimed_count - actual_count) / claimed_count * 100
    metrics["test_count_delta_pct"] = round(delta_pct, 1)

    if delta_pct > 10:
        severity = "high" if delta_pct > 30 else "medium"
        findings.append(
            Finding(
                id="ir-tests-001",
                severity=severity,
                category="investor_readiness",
                title=f"Test count claim in CLAUDE.md is off by {delta_pct:.1f}%",
                detail=(
                    f"CLAUDE.md claims {claimed_count} tests; "
                    f"found {actual_count} test functions/classes across {len(test_files)} files"
                ),
                file=_relative(claude_md_path),
                recommendation=(
                    f"Update CLAUDE.md to reflect actual test count (~{actual_count}). "
                    "Investors rely on this number for due diligence."
                ),
            )
        )
        fin_findings.append(
            FinancialFinding(
                id="ir-fin-tests-001",
                category="billing",
                severity=severity,
                title=f"Data room test count inaccurate: claimed {claimed_count}, actual ~{actual_count}",
                file=_relative(claude_md_path),
                detail=f"Delta: {delta_pct:.1f}% off. Data room accuracy matters for investor trust.",
                recommendation="Sync CLAUDE.md test count with pytest output before sharing with investors.",
            )
        )
    else:
        logger.info(
            "investor_relations: test count within tolerance — claimed=%d actual=%d delta=%.1f%%",
            claimed_count,
            actual_count,
            delta_pct,
        )


# ---------------------------------------------------------------------------
# Check 2: TODO / FIXME technical debt
# ---------------------------------------------------------------------------

_DEBT_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


def _check_todo_fixme_debt(
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Scan app/ for TODO/FIXME/HACK/XXX comments. High debt signals execution risk."""
    py_files = list(APP_DIR.rglob("*.py"))
    total_debt = 0
    debt_by_file: dict[str, int] = {}

    for py_file in py_files:
        content = _read_safe(py_file)
        count = len(_DEBT_PATTERN.findall(content))
        if count > 0:
            debt_by_file[_relative(py_file)] = count
            total_debt += count

    metrics["todo_fixme_total"] = total_debt
    metrics["files_scanned_debt"] = len(py_files)
    metrics["files_with_debt"] = len(debt_by_file)
    # Top 3 debt-heavy files for reference
    top_files = sorted(debt_by_file.items(), key=lambda x: x[1], reverse=True)[:3]
    metrics["top_debt_files"] = [{"file": f, "count": c} for f, c in top_files]

    if total_debt > 50:
        severity = "high"
        title = f"High technical debt: {total_debt} TODO/FIXME/HACK/XXX markers in app/"
    elif total_debt > 20:
        severity = "medium"
        title = (
            f"Moderate technical debt: {total_debt} TODO/FIXME/HACK/XXX markers in app/"
        )
    else:
        logger.info(
            "investor_relations: technical debt within acceptable range (%d markers)",
            total_debt,
        )
        return

    findings.append(
        Finding(
            id="ir-debt-001",
            severity=severity,
            category="investor_readiness",
            title=title,
            detail=(
                f"{total_debt} debt markers across {len(debt_by_file)} files. "
                f"Top files: {', '.join(f for f, _ in top_files)}"
            ),
            recommendation=(
                "Resolve or document debt before investor due diligence. "
                "High TODO counts signal incomplete work to technical reviewers."
            ),
        )
    )
    fin_findings.append(
        FinancialFinding(
            id="ir-fin-debt-001",
            category="billing",
            severity=severity,
            title=f"Technical debt ({total_debt} markers) may concern investors in due diligence",
            detail=f"{len(debt_by_file)} files affected. Top: {', '.join(f for f, _ in top_files)}",
            recommendation="Address critical TODOs and annotate deferred items with issue references.",
        )
    )


# ---------------------------------------------------------------------------
# Check 3: Schema maturity (models vs. migrations)
# ---------------------------------------------------------------------------


def _check_schema_maturity(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Count model files, Column/relationship definitions, and Alembic migrations."""
    # Model files (exclude __init__.py)
    model_files = [f for f in MODELS_DIR.glob("*.py") if f.name != "__init__.py"]
    model_count = len(model_files)

    # Count Column and relationship definitions across all model files
    column_count = 0
    relationship_count = 0
    for model_file in model_files:
        content = _read_safe(model_file)
        column_count += len(re.findall(r"\bColumn\s*\(", content))
        relationship_count += len(re.findall(r"\brelationship\s*\(", content))

    # Count Alembic migration files
    alembic_versions_dir = PROJECT_ROOT / "alembic" / "versions"
    if alembic_versions_dir.is_dir():
        migration_files = list(alembic_versions_dir.glob("*.py"))
        migration_count = len([f for f in migration_files if f.name != "__init__.py"])
    else:
        migration_count = 0

    metrics["model_count"] = model_count
    metrics["column_count"] = column_count
    metrics["relationship_count"] = relationship_count
    metrics["migration_count"] = migration_count

    logger.info(
        "investor_relations: schema maturity — models=%d columns=%d relationships=%d migrations=%d",
        model_count,
        column_count,
        relationship_count,
        migration_count,
    )

    if migration_count < model_count:
        findings.append(
            Finding(
                id="ir-schema-001",
                severity="medium",
                category="investor_readiness",
                title=f"Migration count ({migration_count}) is less than model count ({model_count})",
                detail=(
                    f"{model_count} model files found in app/models/ but only {migration_count} "
                    f"Alembic migration files in alembic/versions/. "
                    f"Some models may not be covered by migrations."
                ),
                file=_relative(MODELS_DIR),
                recommendation=(
                    "Run 'alembic revision --autogenerate' to detect schema drift. "
                    "All production models must have corresponding migrations for reliable deploys."
                ),
            )
        )


# ---------------------------------------------------------------------------
# Check 4: Feature completeness from CLAUDE.md checkboxes
# ---------------------------------------------------------------------------

_CHECKBOX_DONE = re.compile(r"- \[x\]", re.IGNORECASE)
_CHECKBOX_PENDING = re.compile(r"- \[ \]")


def _check_feature_completeness(
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Parse CLAUDE.md 'Current Status' checkboxes to compute completion ratio."""
    claude_md_path = PROJECT_ROOT / "CLAUDE.md"
    source = _read_safe(claude_md_path)

    # Isolate the Current Status section to avoid counting unrelated checkboxes
    status_match = re.search(
        r"##\s+Current Status(.*?)(?=\n##\s|\Z)", source, re.DOTALL
    )
    search_text = status_match.group(1) if status_match else source

    done_count = len(_CHECKBOX_DONE.findall(search_text))
    pending_count = len(_CHECKBOX_PENDING.findall(search_text))
    total = done_count + pending_count

    metrics["checkboxes_done"] = done_count
    metrics["checkboxes_pending"] = pending_count
    metrics["checkboxes_total"] = total

    if total == 0:
        metrics["feature_completion_ratio"] = None
        logger.info(
            "investor_relations: no checkboxes found in CLAUDE.md Current Status section"
        )
        return

    ratio = done_count / total
    metrics["feature_completion_ratio"] = round(ratio, 3)

    logger.info(
        "investor_relations: feature completion — done=%d pending=%d ratio=%.2f",
        done_count,
        pending_count,
        ratio,
    )

    if ratio < 0.5:
        findings.append(
            Finding(
                id="ir-completeness-001",
                severity="medium",
                category="investor_readiness",
                title=f"Feature completion ratio is {ratio:.0%} ({done_count}/{total} items done)",
                detail=(
                    f"{pending_count} roadmap items remain incomplete. "
                    f"Investors reviewing CLAUDE.md will see significant pending work."
                ),
                file=_relative(claude_md_path),
                recommendation=(
                    "Prioritise completing post-launch items or explicitly move them to a "
                    "backlog section so the Current Status section reflects ship-ready state."
                ),
            )
        )
        fin_findings.append(
            FinancialFinding(
                id="ir-fin-completeness-001",
                category="billing",
                severity="medium",
                title=f"Only {ratio:.0%} of tracked features complete — investor perception risk",
                file=_relative(claude_md_path),
                detail=f"{pending_count} incomplete items visible in CLAUDE.md data room document.",
                recommendation="Complete or deprioritise pending items before investor calls.",
            )
        )


# ---------------------------------------------------------------------------
# Check 5: Security posture scoring
# ---------------------------------------------------------------------------

_SECURITY_CHECKS: list[tuple[str, str, str]] = [
    # (check_name, description, path_or_pattern)
    ("security_middleware", "app/middleware/security.py exists", ""),
    ("jwt_auth", "JWT authentication implementation", ""),
    ("rate_limiting", "Rate limiting implementation", ""),
    ("cors_config", "CORS configuration", ""),
    ("audit_logs_table", "audit_logs table in models", ""),
]


def _check_security_posture(
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Score 0-100 based on key security files and patterns present."""
    checks_passed: list[str] = []
    checks_failed: list[str] = []

    # 1. app/middleware/security.py exists
    security_mw = APP_DIR / "middleware" / "security.py"
    if security_mw.exists():
        checks_passed.append("security_middleware")
    else:
        checks_failed.append("security_middleware")

    # 2. JWT handling in app/api/auth.py or app/utils/security.py
    jwt_found = False
    for candidate in [
        APP_DIR / "api" / "auth.py",
        APP_DIR / "utils" / "security.py",
    ]:
        content = _read_safe(candidate)
        if content and (
            "jwt" in content.lower() or "jose" in content.lower() or "JWT" in content
        ):
            jwt_found = True
            break
    if not jwt_found:
        # Broader search across all utils/*.py
        for util_file in (
            (APP_DIR / "utils").glob("*.py") if (APP_DIR / "utils").is_dir() else []
        ):
            content = _read_safe(util_file)
            if "jwt" in content.lower() or "jose" in content.lower():
                jwt_found = True
                break
    if jwt_found:
        checks_passed.append("jwt_auth")
    else:
        checks_failed.append("jwt_auth")

    # 3. Rate limiting
    rate_limit_found = False
    for candidate in [
        APP_DIR / "middleware" / "rate_limit.py",
        APP_DIR / "middleware" / "security.py",
        APP_DIR / "utils" / "rate_limit.py",
    ]:
        content = _read_safe(candidate)
        if content and re.search(r"rate.?limit", content, re.IGNORECASE):
            rate_limit_found = True
            break
    if not rate_limit_found:
        # Broader search
        for src in (
            (APP_DIR / "middleware").glob("*.py")
            if (APP_DIR / "middleware").is_dir()
            else []
        ):
            content = _read_safe(src)
            if re.search(r"rate.?limit", content, re.IGNORECASE):
                rate_limit_found = True
                break
    if rate_limit_found:
        checks_passed.append("rate_limiting")
    else:
        checks_failed.append("rate_limiting")

    # 4. CORS configuration
    cors_found = False
    main_py = PROJECT_ROOT / "app" / "main.py"
    content = _read_safe(main_py)
    if re.search(r"CORS|cors_origins|CORSMiddleware", content, re.IGNORECASE):
        cors_found = True
    if not cors_found:
        for src in APP_DIR.rglob("*.py"):
            c = _read_safe(src)
            if re.search(r"CORSMiddleware|add_middleware.*CORS", c):
                cors_found = True
                break
    if cors_found:
        checks_passed.append("cors_config")
    else:
        checks_failed.append("cors_config")

    # 5. audit_logs table
    audit_found = False
    for model_file in MODELS_DIR.glob("*.py"):
        content = _read_safe(model_file)
        if "audit_logs" in content or "AuditLog" in content or "audit_log" in content:
            audit_found = True
            break
    if audit_found:
        checks_passed.append("audit_logs_table")
    else:
        checks_failed.append("audit_logs_table")

    total_checks = len(_SECURITY_CHECKS)
    score = round(len(checks_passed) / total_checks * 100)
    metrics["security_posture_score"] = score
    metrics["security_checks_passed"] = len(checks_passed)
    metrics["security_checks_total"] = total_checks
    metrics["security_checks_passed_list"] = checks_passed
    metrics["security_checks_failed_list"] = checks_failed

    logger.info(
        "investor_relations: security posture score=%d (%d/%d checks passed)",
        score,
        len(checks_passed),
        total_checks,
    )

    if checks_failed:
        severity = "high" if len(checks_failed) >= 3 else "medium"
        findings.append(
            Finding(
                id="ir-security-001",
                severity=severity,
                category="investor_readiness",
                title=f"Security posture score: {score}/100 — {len(checks_failed)} checks failed",
                detail=f"Failed: {', '.join(checks_failed)}. Passed: {', '.join(checks_passed)}.",
                recommendation=(
                    "Implement missing security controls before investor technical due diligence. "
                    "Investors will assess security posture as a proxy for engineering maturity."
                ),
            )
        )
        if score < 60:
            fin_findings.append(
                FinancialFinding(
                    id="ir-fin-security-001",
                    category="billing",
                    severity=severity,
                    title=f"Low security posture ({score}/100) is a fundraising risk",
                    detail=f"Missing: {', '.join(checks_failed)}",
                    recommendation=(
                        "Security gaps discovered in due diligence can block or delay funding rounds. "
                        "Address high-priority gaps before Series A conversations."
                    ),
                )
            )


# ---------------------------------------------------------------------------
# Check 6: Agent team maturity
# ---------------------------------------------------------------------------

_AGENT_TEAM_DIRS: list[str] = [
    "agents",
    "data_team",
    "product_team",
    "ops_team",
    "finance_team",
]


def _check_agent_team_maturity(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Count agent team directories and check each has an orchestrator.py."""
    teams_found: list[str] = []
    teams_with_orchestrator: list[str] = []
    teams_missing_orchestrator: list[str] = []

    for team_dir_name in _AGENT_TEAM_DIRS:
        team_path = PROJECT_ROOT / team_dir_name
        if team_path.is_dir():
            teams_found.append(team_dir_name)
            orchestrator = team_path / "orchestrator.py"
            if orchestrator.exists():
                teams_with_orchestrator.append(team_dir_name)
            else:
                teams_missing_orchestrator.append(team_dir_name)

    team_count = len(teams_found)
    coverage_ratio = (
        len(teams_with_orchestrator) / team_count if team_count > 0 else 0.0
    )

    metrics["agent_team_count"] = team_count
    metrics["agent_teams_found"] = teams_found
    metrics["agent_teams_with_orchestrator"] = teams_with_orchestrator
    metrics["agent_teams_missing_orchestrator"] = teams_missing_orchestrator
    metrics["agent_team_orchestrator_coverage"] = round(coverage_ratio, 2)

    logger.info(
        "investor_relations: agent team maturity — %d teams, %d/%d with orchestrator",
        team_count,
        len(teams_with_orchestrator),
        team_count,
    )

    if teams_missing_orchestrator:
        findings.append(
            Finding(
                id="ir-agents-001",
                severity="low",
                category="investor_readiness",
                title=(
                    f"{len(teams_missing_orchestrator)} agent team(s) missing orchestrator.py"
                ),
                detail=(
                    f"Teams without orchestrator: {', '.join(teams_missing_orchestrator)}. "
                    f"Coverage: {coverage_ratio:.0%} ({len(teams_with_orchestrator)}/{team_count})."
                ),
                recommendation=(
                    "Each agent team should have an orchestrator.py as the CLI entry point. "
                    "Incomplete teams reduce the investor story around autonomous engineering operations."
                ),
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> FinanceTeamReport:
    """Run all investor readiness checks and return a FinanceTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    fin_findings: list[FinancialFinding] = []
    metrics: dict = {}

    # Run all checks
    _check_test_count_claims(findings, fin_findings, metrics)
    _check_todo_fixme_debt(findings, fin_findings, metrics)
    _check_schema_maturity(findings, metrics)
    _check_feature_completeness(findings, fin_findings, metrics)
    _check_security_posture(findings, fin_findings, metrics)
    _check_agent_team_maturity(findings, metrics)

    duration = time.time() - start

    # -----------------------------------------------------------------------
    # Learning state — follow keevs.py pattern exactly
    # -----------------------------------------------------------------------

    ls = FinanceLearningState(AGENT_NAME)
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

    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # KPI tracking
    if metrics.get("test_count_delta_pct") is not None:
        ls.track_kpi("test_count_delta_pct", metrics["test_count_delta_pct"])
    ls.track_kpi("todo_fixme_total", metrics.get("todo_fixme_total", 0))
    ls.track_kpi("security_posture_score", metrics.get("security_posture_score", 0))
    if metrics.get("feature_completion_ratio") is not None:
        ls.track_kpi("feature_completion_ratio", metrics["feature_completion_ratio"])
    ls.track_kpi("agent_team_count", metrics.get("agent_team_count", 0))
    ls.track_kpi("migration_count", metrics.get("migration_count", 0))

    # Learning updates for CoS consumption
    learning_updates: list[str] = []

    claimed = metrics.get("test_count_claimed")
    actual = metrics.get("test_count_actual")
    if claimed is not None and actual is not None:
        delta = metrics.get("test_count_delta_pct", 0)
        learning_updates.append(
            f"Test count: claimed={claimed}, actual={actual}, delta={delta:.1f}%"
        )

    learning_updates.append(
        f"Technical debt: {metrics.get('todo_fixme_total', 0)} markers "
        f"across {metrics.get('files_with_debt', 0)} files"
    )
    learning_updates.append(
        f"Schema: {metrics.get('model_count', 0)} models, "
        f"{metrics.get('column_count', 0)} columns, "
        f"{metrics.get('migration_count', 0)} migrations"
    )
    completion = metrics.get("feature_completion_ratio")
    if completion is not None:
        learning_updates.append(
            f"Feature completion: {completion:.0%} "
            f"({metrics.get('checkboxes_done', 0)}/{metrics.get('checkboxes_total', 0)} items)"
        )
    learning_updates.append(
        f"Security posture: {metrics.get('security_posture_score', 0)}/100"
    )
    learning_updates.append(
        f"Agent teams: {metrics.get('agent_team_count', 0)} teams, "
        f"{metrics.get('agent_team_orchestrator_coverage', 0):.0%} orchestrator coverage"
    )

    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    patterns = ls.state.get("recurring_patterns", {})
    escalated = [k for k, v in patterns.items() if v.get("auto_escalated")]
    if escalated:
        learning_updates.append(f"Escalated recurring patterns: {len(escalated)}")

    return FinanceTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        financial_findings=fin_findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: FinanceTeamReport) -> Path:
    """Save report to finance_team/reports/investor_relations_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("investor_relations: report saved to %s", path)
    return path
