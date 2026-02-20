"""TestEngineer agent — test coverage & quality analyzer."""

import ast
import json
import logging
import subprocess
import time
from pathlib import Path

from agents.shared.config import PROJECT_ROOT, SKIP_DIRS
from agents.shared.report import Finding, AgentReport
from agents.shared import learning
import contextlib

logger = logging.getLogger(__name__)

AGENT_NAME = "test_engineer"

# Critical modules that must have >= 90% coverage
CRITICAL_MODULES = {
    "app/services/suppression.py": "privacy compliance",
    "app/services/credits.py": "financial transactions",
    "app/utils/security.py": "auth",
}

COVERAGE_WARN_THRESHOLD = 80
COVERAGE_CRITICAL_THRESHOLD = 90


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _count_assertions(node: ast.FunctionDef) -> int:
    """Count assert statements, assert* method calls, and pytest.raises blocks."""
    count = 0
    for child in ast.walk(node):
        # Plain `assert` statements
        if isinstance(child, ast.Assert):
            count += 1
        # Method calls like self.assertEqual, self.assertRaises, etc.
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr.startswith("assert"):
                count += 1
        # `with pytest.raises(...)` context managers count as assertions
        if isinstance(child, ast.With):
            for item in child.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and (
                    (isinstance(ctx.func, ast.Attribute) and ctx.func.attr == "raises")
                    or isinstance(ctx.func, ast.Name)
                    and ctx.func.id == "raises"
                ):
                    count += 1
    return count


def _extract_test_functions(
    filepath: Path,
    node_registry: dict | None = None,
) -> list[dict]:
    """Parse a test file and return info about each test function.

    If node_registry is provided, also stores the AST node for each test
    keyed as 'relative_path::test_name' for downstream complexity analysis.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        logger.warning("Cannot parse %s: %s", filepath, e)
        return []

    rel_path = str(filepath.relative_to(PROJECT_ROOT))
    tests = []
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test_"):
            assertions = _count_assertions(node)
            tests.append(
                {
                    "name": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "assertions": assertions,
                }
            )
            if node_registry is not None:
                node_registry[f"{rel_path}::{node.name}"] = node
    return tests


def _extract_api_endpoints(filepath: Path) -> list[dict]:
    """Parse an API router file and extract route definitions."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        logger.warning("Cannot parse %s: %s", filepath, e)
        return []

    endpoints = []
    http_methods = {"get", "post", "put", "patch", "delete"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            # Match router.get("/path"), router.post("/path"), etc.
            if isinstance(decorator, ast.Call) and isinstance(
                decorator.func, ast.Attribute
            ):
                method = decorator.func.attr
                if method in http_methods:
                    path = ""
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        path = decorator.args[0].value
                    endpoints.append(
                        {
                            "function": node.name,
                            "method": method.upper(),
                            "path": path,
                            "file": str(filepath.relative_to(PROJECT_ROOT)),
                            "line": node.lineno,
                        }
                    )
    return endpoints


def _check_test_has_error_coverage(
    test_functions: list[dict],
    api_module_name: str,
) -> bool:
    """Check if any test for a given API module asserts a 4xx status code."""
    # Look for tests in files that seem related to the api module
    # e.g. api module "auth" -> test files containing "auth"
    for tf in test_functions:
        test_file = tf["file"]
        if api_module_name in test_file:
            # Read the test file and look for 4xx status code assertions
            full_path = PROJECT_ROOT / test_file
            try:
                source = full_path.read_text(encoding="utf-8")
                # Look for patterns like status_code == 4xx, 400, 401, 403, 404, 409, 422
                for code in ("400", "401", "403", "404", "409", "422", "429"):
                    if code in source:
                        return True
            except OSError:
                continue
    return False


# ---------------------------------------------------------------------------
# Main analysis steps
# ---------------------------------------------------------------------------


def _run_pytest_coverage() -> dict:
    """Run pytest with coverage and return parsed results."""
    coverage_json = PROJECT_ROOT / "coverage.json"
    # Remove stale coverage files
    for f in (coverage_json, PROJECT_ROOT / ".coverage"):
        if f.exists():
            with contextlib.suppress(OSError):
                f.unlink()

    cmd = [
        "python3",
        "-m",
        "pytest",
        f"--cov={PROJECT_ROOT / 'app'}",
        "--cov-report=json",
        "--cov-report=term",
        "-q",
        "--no-header",
        "-x",
        "--timeout=60",
        str(PROJECT_ROOT / "tests"),
    ]

    result = {
        "success": False,
        "output": "",
        "coverage_data": None,
        "total_coverage_pct": None,
    }

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        result["output"] = proc.stdout + proc.stderr
        result["success"] = proc.returncode == 0

        # Parse coverage.json if it was generated
        if coverage_json.exists():
            try:
                cov_data = json.loads(coverage_json.read_text())
                result["coverage_data"] = cov_data
                totals = cov_data.get("totals", {})
                result["total_coverage_pct"] = totals.get("percent_covered", None)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse coverage.json: %s", e)

    except subprocess.TimeoutExpired:
        result["output"] = "pytest timed out after 120 seconds"
        logger.warning("pytest coverage run timed out")
    except FileNotFoundError:
        result["output"] = "python3 or pytest not found"
        logger.warning("python3/pytest not found on PATH")
    except Exception as e:
        result["output"] = f"Unexpected error: {e}"
        logger.warning("pytest coverage run failed: %s", e)

    return result


def _analyze_coverage(cov_data: dict) -> list[Finding]:
    """Analyze coverage data and flag under-covered modules."""
    findings: list[Finding] = []
    if not cov_data:
        return findings

    files_data = cov_data.get("files", {})

    for filepath, file_info in files_data.items():
        # Normalize filepath — coverage.json may use absolute paths
        try:
            rel_path = str(Path(filepath).relative_to(PROJECT_ROOT))
        except ValueError:
            rel_path = filepath

        # Only analyze app/ modules
        if not rel_path.startswith("app/"):
            continue

        summary = file_info.get("summary", {})
        pct = summary.get("percent_covered", 100)

        # Check critical modules first
        is_critical = rel_path in CRITICAL_MODULES
        threshold = (
            COVERAGE_CRITICAL_THRESHOLD if is_critical else COVERAGE_WARN_THRESHOLD
        )

        if pct < threshold:
            reason = CRITICAL_MODULES.get(rel_path, "")
            severity = "high" if is_critical else "medium"
            label = f"critical module ({reason})" if is_critical else "module"

            num_missing = summary.get("missing_lines", 0)
            num_stmts = summary.get("num_statements", 0)

            recurrence = learning.get_recurrence_count(
                AGENT_NAME, "low_coverage", rel_path
            )

            findings.append(
                Finding(
                    id=f"TE-COV-{rel_path.replace('/', '-').replace('.', '-')}",
                    severity=severity,
                    category="low_coverage",
                    title=f"{label} {rel_path} at {pct:.0f}% coverage (threshold {threshold}%)",
                    detail=(
                        f"{num_missing} of {num_stmts} statements not covered. "
                        f"Target: {threshold}% line coverage."
                    ),
                    file=rel_path,
                    recommendation=(
                        f"Add tests for uncovered paths in {rel_path}. "
                        f"Focus on error handling branches and edge cases."
                    ),
                    effort_hours=max(0.5, num_missing * 0.05),
                    recurrence_count=recurrence + 1,
                )
            )

    return findings


def _measure_setup_complexity(node: ast.FunctionDef) -> dict:
    """Measure the complexity of a test function's setup.

    Returns a dict with:
      - await_calls: number of await expressions (async operations)
      - total_calls: total function/method calls
      - assignments: number of variable assignments
      - status_code_only: True if the only assertion checks .status_code
    """
    await_calls = 0
    total_calls = 0
    assignments = 0
    assertion_targets: list[str] = []

    for child in ast.walk(node):
        if isinstance(child, ast.Await):
            await_calls += 1
        if isinstance(child, ast.Call):
            total_calls += 1
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            assignments += 1
        # Track what assertions check
        if isinstance(child, ast.Assert) and isinstance(child.test, ast.Compare):
            # e.g. assert response.status_code == 200
            left = child.test.left
            if isinstance(left, ast.Attribute):
                assertion_targets.append(left.attr)

    status_code_only = len(assertion_targets) > 0 and all(
        t == "status_code" for t in assertion_targets
    )

    return {
        "await_calls": await_calls,
        "total_calls": total_calls,
        "assignments": assignments,
        "status_code_only": status_code_only,
    }


def _is_focused_test(name: str) -> bool:
    """Check if test name suggests a deliberately focused single-assertion test.

    Tests like test_invalid_email_returns_422 or test_login_fails_without_password
    are legitimately single-assertion by design.
    """
    focused_patterns = (
        "_returns_",
        "_fails_",
        "_rejects_",
        "_raises_",
        "_forbidden",
        "_unauthorized",
        "_not_found",
        "_invalid_",
        "_missing_",
        "_empty_",
        "_duplicate_",
        "_expired_",
        "_locked_",
    )
    return any(p in name for p in focused_patterns)


def _analyze_test_quality(
    all_tests: list[dict], test_nodes: dict | None = None
) -> list[Finding]:
    """Flag genuinely weak tests — complex setup with only status_code assertion.

    A test is weak when it has:
      1. High setup complexity (multiple await calls or assignments), AND
      2. Only 1 assertion that checks just .status_code (not response body)

    Tests with ≤1 assertions are NOT flagged if:
      - They are focused negative tests (name implies single-condition check)
      - Their setup is trivial (≤2 await calls, ≤3 assignments)
      - Their assertion checks something beyond status_code
    """
    findings: list[Finding] = []

    for t in all_tests:
        if t["assertions"] > 1:
            continue  # Tests with multiple assertions are fine

        # Zero-assertion tests are always suspicious
        if t["assertions"] == 0:
            recurrence = learning.get_recurrence_count(
                AGENT_NAME, "weak_test", t["file"]
            )
            findings.append(
                Finding(
                    id=f"TE-WEAK-{t['file'].replace('/', '-')}-{t['name']}",
                    severity="low",
                    category="weak_test",
                    title=f"Test with no assertions: {t['name']}",
                    detail=(
                        f"Test function `{t['name']}` in {t['file']} has no "
                        f"assertions. It may be a placeholder or smoke test."
                    ),
                    file=t["file"],
                    line=t["line"],
                    recommendation=(
                        "Add at least one assertion, or mark as a known "
                        "smoke test with a comment."
                    ),
                    effort_hours=0.25,
                    recurrence_count=recurrence + 1,
                )
            )
            continue

        # Single-assertion test — check if it's genuinely weak
        # Skip deliberately focused tests (name implies single check)
        if _is_focused_test(t["name"]):
            continue

        # If we have AST nodes, measure setup complexity
        node_key = f"{t['file']}::{t['name']}"
        if test_nodes and node_key in test_nodes:
            complexity = _measure_setup_complexity(test_nodes[node_key])
        else:
            # Without AST data, skip — we can't determine complexity
            continue

        # Only flag if: complex setup + status_code-only assertion
        is_complex = complexity["await_calls"] >= 3 or complexity["assignments"] >= 4
        if is_complex and complexity["status_code_only"]:
            recurrence = learning.get_recurrence_count(
                AGENT_NAME, "weak_test", t["file"]
            )
            findings.append(
                Finding(
                    id=f"TE-WEAK-{t['file'].replace('/', '-')}-{t['name']}",
                    severity="low",
                    category="weak_test",
                    title=f"Weak test: {t['name']} — complex setup but only checks status_code",
                    detail=(
                        f"Test `{t['name']}` in {t['file']} has "
                        f"{complexity['await_calls']} async calls and "
                        f"{complexity['assignments']} assignments but only "
                        f"asserts status_code. Response body content and "
                        f"side effects are not validated."
                    ),
                    file=t["file"],
                    line=t["line"],
                    recommendation=(
                        "Add assertions on response body (e.g. response.json()['data']) "
                        "or database state changes to ensure the full behavior is tested."
                    ),
                    effort_hours=0.25,
                    recurrence_count=recurrence + 1,
                )
            )

    return findings


def _analyze_error_test_coverage(
    all_tests: list[dict],
) -> list[Finding]:
    """Check each API module has tests that cover error paths (4xx responses)."""
    findings: list[Finding] = []

    api_dir = PROJECT_ROOT / "app" / "api"
    if not api_dir.is_dir():
        return findings

    for api_file in sorted(api_dir.glob("*.py")):
        if api_file.name.startswith("_"):
            continue

        module_name = api_file.stem  # e.g. "auth", "contacts", "marketplace"

        # Skip health check — no meaningful error paths
        if module_name == "health":
            continue

        endpoints = _extract_api_endpoints(api_file)
        if not endpoints:
            continue

        has_error_tests = _check_test_has_error_coverage(all_tests, module_name)

        if not has_error_tests:
            rel_path = str(api_file.relative_to(PROJECT_ROOT))
            endpoint_summary = ", ".join(
                f"{ep['method']} {ep['path']}" for ep in endpoints[:5]
            )
            if len(endpoints) > 5:
                endpoint_summary += f" ... (+{len(endpoints) - 5} more)"

            recurrence = learning.get_recurrence_count(
                AGENT_NAME, "missing_error_tests", rel_path
            )

            findings.append(
                Finding(
                    id=f"TE-ERR-{module_name}",
                    severity="medium",
                    category="missing_error_tests",
                    title=f"No error-path tests found for API module: {module_name}",
                    detail=(
                        f"API module {rel_path} exposes endpoints "
                        f"({endpoint_summary}) but no tests assert 4xx status codes. "
                        f"Error paths (bad input, auth failures, not found) should "
                        f"be tested."
                    ),
                    file=rel_path,
                    recommendation=(
                        f"Add tests for {module_name} that cover: invalid input (422), "
                        f"unauthorized access (401/403), missing resources (404), "
                        f"and duplicate/conflict scenarios (409) as applicable."
                    ),
                    effort_hours=1.0,
                    recurrence_count=recurrence + 1,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def scan() -> AgentReport:
    """Run all test engineering analyses and return a report."""
    start = time.time()
    findings: list[Finding] = []
    metrics: dict = {}
    intelligence_notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Collect all test functions via AST
    # ------------------------------------------------------------------
    tests_dir = PROJECT_ROOT / "tests"
    all_tests: list[dict] = []
    test_files: list[Path] = []
    test_nodes: dict = {}  # key: "file::test_name" -> AST node

    if tests_dir.is_dir():
        for tf in sorted(tests_dir.rglob("test_*.py")):
            # Skip dirs we don't care about
            if any(part in SKIP_DIRS for part in tf.parts):
                continue
            test_files.append(tf)
            all_tests.extend(_extract_test_functions(tf, node_registry=test_nodes))

    total_tests = len(all_tests)
    total_test_files = len(test_files)
    metrics["total_tests"] = total_tests
    metrics["total_test_files"] = total_test_files

    logger.info(
        "Found %d test functions across %d files", total_tests, total_test_files
    )

    # ------------------------------------------------------------------
    # 2. Run pytest with coverage
    # ------------------------------------------------------------------
    cov_result = _run_pytest_coverage()

    if cov_result["success"]:
        intelligence_notes.append("pytest run succeeded")
    else:
        # Extract a concise error summary (first few lines)
        output_lines = cov_result["output"].strip().splitlines()
        error_excerpt = "\n".join(output_lines[-10:]) if output_lines else "no output"
        findings.append(
            Finding(
                id="TE-RUN-FAIL",
                severity="high",
                category="test_run_failure",
                title="pytest run failed or timed out",
                detail=f"Could not complete test suite execution.\n\n```\n{error_excerpt}\n```",
                recommendation=(
                    "Fix failing tests before analyzing coverage. "
                    "Check for import errors, missing fixtures, or database issues."
                ),
                effort_hours=1.0,
            )
        )

    coverage_pct = cov_result.get("total_coverage_pct")
    if coverage_pct is not None:
        metrics["coverage_percent"] = round(coverage_pct, 1)
        intelligence_notes.append(f"Overall coverage: {coverage_pct:.1f}%")

    # ------------------------------------------------------------------
    # 3. Analyze per-module coverage
    # ------------------------------------------------------------------
    if cov_result.get("coverage_data"):
        findings.extend(_analyze_coverage(cov_result["coverage_data"]))

    # ------------------------------------------------------------------
    # 4. Analyze test quality (weak tests)
    # ------------------------------------------------------------------
    weak_tests = [t for t in all_tests if t["assertions"] <= 1]
    metrics["weak_test_count"] = len(weak_tests)

    quality_findings = _analyze_test_quality(all_tests, test_nodes=test_nodes)
    findings.extend(quality_findings)

    if weak_tests:
        intelligence_notes.append(f"{len(weak_tests)} tests have 0-1 assertions (weak)")

    # ------------------------------------------------------------------
    # 5. Analyze error-path test coverage
    # ------------------------------------------------------------------
    error_findings = _analyze_error_test_coverage(all_tests)
    findings.extend(error_findings)

    if error_findings:
        modules_missing = [f.file for f in error_findings if f.file]
        intelligence_notes.append(
            f"API modules without error-path tests: {', '.join(modules_missing)}"
        )

    # ------------------------------------------------------------------
    # 6. Coverage trend (self-learning)
    # ------------------------------------------------------------------
    if coverage_pct is not None:
        trend = learning.get_trend(AGENT_NAME, "coverage_percent")
        if trend == "down":
            findings.append(
                Finding(
                    id="TE-TREND-COV-DOWN",
                    severity="medium",
                    category="coverage_trend",
                    title="Coverage is trending downward",
                    detail=(
                        f"Current coverage: {coverage_pct:.1f}%. "
                        f"Coverage has been declining over recent scans. "
                        f"New code may be landing without adequate tests."
                    ),
                    recommendation=(
                        "Review recent commits for untested code paths. "
                        "Consider adding a coverage gate to the CI pipeline."
                    ),
                    effort_hours=2.0,
                )
            )
            intelligence_notes.append("Coverage trend: declining")
        elif trend == "up":
            intelligence_notes.append("Coverage trend: improving")
        elif trend == "stable":
            intelligence_notes.append("Coverage trend: stable")

    # ------------------------------------------------------------------
    # 7. Self-learning: record findings and metrics
    # ------------------------------------------------------------------
    learning_updates: list[str] = []

    try:
        # Record each finding in history
        file_finding_counts: dict[str, int] = {}
        for f in findings:
            learning.record_finding(
                AGENT_NAME,
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "file": f.file,
                    "line": f.line,
                    "title": f.title,
                },
            )
            if f.file:
                file_finding_counts[f.file] = file_finding_counts.get(f.file, 0) + 1

        # Update attention weights
        if file_finding_counts:
            learning.update_attention_weights(AGENT_NAME, file_finding_counts)
            learning_updates.append(
                f"Updated attention weights for {len(file_finding_counts)} files"
            )

        # Record scan metrics
        learning.record_scan(AGENT_NAME, metrics)
        learning_updates.append(
            f"Recorded scan #{learning.get_total_scans(AGENT_NAME)} with "
            f"{total_tests} tests, {metrics.get('coverage_percent', 'N/A')}% coverage"
        )
    except Exception as e:
        logger.warning("Self-learning update failed: %s", e)
        learning_updates.append(f"Learning update error: {e}")

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------
    elapsed = time.time() - start

    return AgentReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 1),
        findings=findings,
        metrics=metrics,
        intelligence_applied=intelligence_notes,
        learning_updates=learning_updates,
    )
