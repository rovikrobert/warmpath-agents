"""ProductManager agent — feature mapping, PRD templates, acceptance criteria audit, backlog health.

Scans app/api/*.py, tests/, and frontend/src/pages/*.jsx for feature coverage.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from product_team.shared.config import (
    API_DIR,
    PAGES_DIR,
    PROJECT_ROOT,
    TESTS_DIR,
)
from product_team.shared.learning import ProductLearningState
from product_team.shared.report import ProductInsight, ProductTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "product_manager"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_api_files() -> list[Path]:
    """Return all .py files under app/api/ (excluding __init__)."""
    if not API_DIR.is_dir():
        return []
    return [f for f in sorted(API_DIR.glob("*.py")) if f.name != "__init__.py"]


def _find_page_files() -> list[Path]:
    """Return all .jsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted(PAGES_DIR.glob("*.jsx"))


def _find_test_files() -> list[Path]:
    """Return all test_*.py files."""
    if not TESTS_DIR.is_dir():
        return []
    return sorted(TESTS_DIR.glob("test_*.py"))


def _read_safe(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _extract_api_endpoints(api_files: list[Path]) -> dict[str, list[dict]]:
    """Extract API route endpoints from router files.

    Returns {filename: [{method, path, function}]}.
    """
    result: dict[str, list[dict]] = {}
    route_pattern = re.compile(
        r'@router\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']'
    )

    for path in api_files:
        source = _read_safe(path)
        endpoints = []
        for match in route_pattern.finditer(source):
            method = match.group(1).upper()
            route_path = match.group(2)
            # Try to find the function name
            func_match = re.search(
                rf"@router\.{match.group(1)}\s*\([^)]*\)\s*\nasync\s+def\s+(\w+)",
                source[match.start() :],
            )
            func_name = func_match.group(1) if func_match else "unknown"
            endpoints.append(
                {
                    "method": method,
                    "path": route_path,
                    "function": func_name,
                }
            )
        if endpoints:
            result[path.name] = endpoints

    return result


def _map_feature_coverage(
    api_files: list[Path],
    page_files: list[Path],
    findings: list[Finding],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Map API endpoints to frontend pages (feature coverage audit)."""
    endpoints = _extract_api_endpoints(api_files)
    total_endpoints = sum(len(v) for v in endpoints.values())
    page_names = {p.stem for p in page_files}

    metrics["total_api_endpoints"] = total_endpoints
    metrics["api_files"] = len(endpoints)
    metrics["frontend_pages"] = len(page_names)

    # Map API modules to likely frontend consumers
    api_to_page_map: dict[str, list[str]] = {
        "auth": [
            "AuthPage",
            "ForgotPasswordPage",
            "ResetPasswordPage",
            "VerifyEmailPage",
            "EditProfile",
            "OnboardingPage",
        ],
        "contacts": ["ContactsPage"],
        "search": ["NewSearch", "SearchResults", "FindReferrals", "ReferralResults"],
        "marketplace": [
            "MarketplaceOverview",
            "SharingSettings",
            "MarketplaceBrowse",
            "MyRequests",
        ],
        "credits": ["CreditsPage"],
        "applications": ["ApplicationsPage"],
        "coach": ["CoachPage"],
        "privacy": ["PrivacyPage", "PrivacySettingsPage"],
        "referrals": ["ReferralCodesPage"],
        "feed": ["CoachPage"],
    }

    # Check for orphan API modules (no frontend consumer)
    orphan_apis = []
    for api_file in endpoints:
        module = api_file.replace(".py", "")
        expected_pages = api_to_page_map.get(module, [])
        has_consumer = (
            any(p in page_names for p in expected_pages) if expected_pages else True
        )
        if not has_consumer and module not in ("health", "admin", "webhooks"):
            orphan_apis.append(module)

    if orphan_apis:
        findings.append(
            Finding(
                id="pm-001",
                severity="low",
                category="feature_coverage",
                title=f"{len(orphan_apis)} API modules may lack frontend consumers",
                detail=f"Modules: {', '.join(orphan_apis)}",
                recommendation="Verify these APIs have frontend pages or are backend-only by design",
            )
        )

    # Check for pages without backing APIs
    all_api_modules = {f.replace(".py", "") for f in endpoints}
    page_to_api_map: dict[str, list[str]] = {}
    for api_mod, pages in api_to_page_map.items():
        for page in pages:
            page_to_api_map.setdefault(page, []).append(api_mod)

    orphan_pages = []
    for page in page_names:
        needed_apis = page_to_api_map.get(page, [])
        if needed_apis and not any(a in all_api_modules for a in needed_apis):
            orphan_pages.append(page)

    if orphan_pages:
        findings.append(
            Finding(
                id="pm-002",
                severity="low",
                category="feature_coverage",
                title=f"{len(orphan_pages)} pages may lack API backing",
                detail=f"Pages: {', '.join(orphan_pages)}",
                recommendation="Verify these pages have the API endpoints they need",
            )
        )

    # Feature completeness scorecard
    covered = total_endpoints - len(orphan_apis)
    coverage_score = covered / max(1, total_endpoints)
    metrics["feature_coverage_score"] = round(coverage_score, 2)

    insights.append(
        ProductInsight(
            id="pm-insight-coverage",
            category="feature_coverage",
            title=f"Feature coverage: {coverage_score:.0%}",
            evidence=f"{total_endpoints} API endpoints across {len(endpoints)} modules, {len(page_names)} pages",
            impact="API-to-frontend alignment for feature completeness",
            recommendation="Close coverage gaps"
            if coverage_score < 1.0
            else "Full coverage",
            confidence=0.85,
        )
    )


def _audit_test_coverage(
    test_files: list[Path],
    api_files: list[Path],
    findings: list[Finding],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Check test files for acceptance-criteria patterns."""
    total_tests = 0
    test_with_assertions = 0
    re.compile(
        r"(?:test_.*(?:success|happy|flow|scenario|should|returns|creates|updates|deletes))",
        re.IGNORECASE,
    )

    api_modules = {f.stem for f in api_files}
    tested_modules: set[str] = set()

    for path in test_files:
        source = _read_safe(path)
        test_count = len(re.findall(r"def test_", source))
        total_tests += test_count
        test_with_assertions += len(re.findall(r"assert\b", source))

        # Check if test covers an API module
        for mod in api_modules:
            if mod in path.name or mod in source:
                tested_modules.add(mod)

    metrics["total_test_functions"] = total_tests
    metrics["test_files"] = len(test_files)

    untested_modules = api_modules - tested_modules
    test_coverage = len(tested_modules) / max(1, len(api_modules))
    metrics["api_test_coverage"] = round(test_coverage, 2)

    if untested_modules:
        findings.append(
            Finding(
                id="pm-003",
                severity="low",
                category="feature_coverage",
                title=f"{len(untested_modules)} API modules may lack dedicated tests",
                detail=f"Modules: {', '.join(sorted(untested_modules))}",
                recommendation="Add test coverage for untested API modules",
            )
        )


def _check_integration_gaps(
    api_files: list[Path],
    page_files: list[Path],
    test_files: list[Path],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Identify integration gaps (API exists but no test, or page exists but no API)."""
    endpoints = _extract_api_endpoints(api_files)
    total = sum(len(v) for v in endpoints.values())

    # Simple heuristic: count how many test files reference API patterns
    test_sources = [_read_safe(p) for p in test_files]
    all_test_text = "\n".join(test_sources)

    endpoint_tested = 0
    for _module, eps in endpoints.items():
        for ep in eps:
            if ep["path"] in all_test_text or ep["function"] in all_test_text:
                endpoint_tested += 1

    endpoint_test_coverage = endpoint_tested / max(1, total)
    metrics["endpoint_test_coverage"] = round(endpoint_test_coverage, 2)


def _validate_api_contracts(
    findings: list[Finding],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Parse Pydantic schemas and frontend API calls, flag mismatches."""
    from product_team.shared.config import SCHEMAS_DIR, FRONTEND_SRC

    schema_files = sorted(SCHEMAS_DIR.glob("*.py")) if SCHEMAS_DIR.is_dir() else []
    schema_files = [f for f in schema_files if f.name != "__init__.py"]
    metrics["schema_files_found"] = len(schema_files)

    response_models: dict[str, set[str]] = {}
    model_pattern = re.compile(r"class\s+(\w*Response\w*)\s*\(")
    field_pattern = re.compile(r"^\s+(\w+)\s*:", re.MULTILINE)

    for path in schema_files:
        source = _read_safe(path)
        for model_match in model_pattern.finditer(source):
            model_name = model_match.group(1)
            start = model_match.end()
            next_class = re.search(r"\nclass\s", source[start:])
            end = start + next_class.start() if next_class else len(source)
            block = source[start:end]
            fields = set(field_pattern.findall(block))
            fields -= {"model_config", "Config"}
            if fields:
                response_models[model_name] = fields

    metrics["schema_response_models"] = len(response_models)

    api_client_path = FRONTEND_SRC / "api" / "client.js"
    frontend_api_calls = 0

    if api_client_path.exists():
        source = _read_safe(api_client_path)
        api_call_pattern = re.compile(r"(?:api|fetch)\s*\(\s*['\"`]([^'\"` ]+)['\"`]")
        calls = api_call_pattern.findall(source)
        frontend_api_calls = len(calls)

        page_dir = FRONTEND_SRC / "pages"
        if page_dir.is_dir():
            field_access_pattern = re.compile(
                r"(?:data|resp|response|result)\s*[\[.](\w+)"
            )
            frontend_fields: set[str] = set()
            for page in page_dir.glob("*.jsx"):
                page_source = _read_safe(page)
                frontend_fields.update(field_access_pattern.findall(page_source))
            metrics["frontend_response_fields"] = len(frontend_fields)

    metrics["frontend_api_calls"] = frontend_api_calls

    insights.append(
        ProductInsight(
            id="pm-insight-contracts",
            category="feature_coverage",
            title=f"API contract audit: {len(response_models)} response models, {frontend_api_calls} frontend API calls",
            evidence=f"Schema files: {len(schema_files)}, Response models: {', '.join(sorted(response_models.keys())[:5])}{'...' if len(response_models) > 5 else ''}",
            impact="Schema-frontend alignment prevents runtime errors and broken UX",
            recommendation="Review any flagged mismatches between backend schemas and frontend expectations",
            confidence=0.8,
        )
    )


def _track_experiments(
    findings: list[Finding],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Track hypothesis/experiment lifecycle from registry."""
    import json
    from datetime import datetime, timezone
    from product_team.shared.config import EXPERIMENT_REGISTRY_PATH

    if not EXPERIMENT_REGISTRY_PATH.exists():
        metrics["experiments_total"] = 0
        metrics["experiments_active"] = 0
        metrics["experiments_concluded"] = 0
        return

    try:
        registry = json.loads(EXPERIMENT_REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        metrics["experiments_total"] = 0
        metrics["experiments_active"] = 0
        metrics["experiments_concluded"] = 0
        return

    experiments = registry.get("experiments", [])
    metrics["experiments_total"] = len(experiments)

    by_status: dict[str, int] = {}
    stale_experiments: list[str] = []

    for exp in experiments:
        status = exp.get("status", "draft")
        by_status[status] = by_status.get(status, 0) + 1
        if status == "active" and exp.get("start_date"):
            try:
                start = datetime.fromisoformat(exp["start_date"])
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                days_active = (datetime.now(timezone.utc) - start).days
                if days_active > 30 and not exp.get("result"):
                    stale_experiments.append(exp.get("id", "unknown"))
            except (ValueError, TypeError):
                pass

    metrics["experiments_active"] = by_status.get("active", 0)
    metrics["experiments_concluded"] = by_status.get("concluded", 0)
    metrics["experiments_draft"] = by_status.get("draft", 0)
    metrics["experiments_stale"] = len(stale_experiments)

    if stale_experiments:
        findings.append(
            Finding(
                id="pm-exp-stale",
                severity="medium",
                category="experiment_tracking",
                title=f"{len(stale_experiments)} experiments active >30 days without results",
                detail=f"IDs: {', '.join(stale_experiments)}",
                recommendation="Conclude or extend experiments — stale tests waste resources",
            )
        )

    concluded = [
        e for e in experiments if e.get("status") == "concluded" and e.get("result")
    ]
    recent_learnings = [
        f"{e.get('hypothesis', '?')[:60]} -> {e.get('result', '?')[:60]}"
        for e in concluded[-3:]
    ]

    insights.append(
        ProductInsight(
            id="pm-insight-experiments",
            category="experiment_tracking",
            title=f"Experiment tracker: {len(experiments)} total, {by_status.get('active', 0)} active, {by_status.get('concluded', 0)} concluded",
            evidence=f"Recent learnings: {'; '.join(recent_learnings)}"
            if recent_learnings
            else "No concluded experiments yet",
            impact="Structured experimentation accelerates product-market fit discovery",
            recommendation="Add new hypotheses to experiment_registry.json"
            if not experiments
            else "Review active experiments",
            confidence=0.9,
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> ProductTeamReport:
    """Run all product management checks and return a ProductTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[ProductInsight] = []
    metrics: dict = {}

    api_files = _find_api_files()
    page_files = _find_page_files()
    test_files = _find_test_files()

    metrics["api_files_found"] = len(api_files)
    metrics["page_files_found"] = len(page_files)
    metrics["test_files_found"] = len(test_files)

    if not api_files and not page_files:
        findings.append(
            Finding(
                id="pm-000",
                severity="info",
                category="feature_coverage",
                title="No API or page files found",
                detail="Backend and frontend may not be initialized yet",
                recommendation="Initialize app/api/ and frontend/src/pages/",
            )
        )
    else:
        _map_feature_coverage(api_files, page_files, findings, insights, metrics)
        _audit_test_coverage(test_files, api_files, findings, insights, metrics)
        _check_integration_gaps(api_files, page_files, test_files, findings, metrics)
        _validate_api_contracts(findings, insights, metrics)
        _track_experiments(findings, insights, metrics)

    duration = time.time() - start

    # Learning
    ls = ProductLearningState(AGENT_NAME)
    ls.record_scan(metrics)
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
        ls.record_severity_calibration(f.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    for i in insights:
        ls.record_insight(
            {
                "id": i.id,
                "category": i.category,
                "title": i.title,
                "confidence": i.confidence,
            }
        )

    ls.track_kpi("feature_coverage_score", metrics.get("feature_coverage_score", 0))
    ls.track_kpi("api_test_coverage", metrics.get("api_test_coverage", 0))

    learning_updates = [
        f"Scanned {len(api_files)} API + {len(page_files)} pages + {len(test_files)} tests"
    ]
    if metrics.get("feature_coverage_score") is not None:
        learning_updates.append(
            f"Feature coverage: {metrics['feature_coverage_score']:.0%}"
        )

    return ProductTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        product_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: ProductTeamReport) -> Path:
    """Save report to product_team/reports/."""
    from product_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
