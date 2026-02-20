"""DocKeeper agent — documentation-code sync checker."""

from __future__ import annotations

import ast
import logging
import re
import time
from pathlib import Path

from agents.shared.config import PROJECT_ROOT, SKIP_DIRS
from agents.shared.report import Finding, AgentReport
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "doc_keeper"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _py_files(root: Path) -> list[Path]:
    """Collect all .py files under *root*, skipping SKIP_DIRS."""
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT for readable output."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _read_text_safe(path: Path) -> str | None:
    """Read a file's text, returning None on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _load_claude_md() -> str | None:
    """Load CLAUDE.md content."""
    return _read_text_safe(PROJECT_ROOT / "CLAUDE.md")


# ---------------------------------------------------------------------------
# Individual scanners
# ---------------------------------------------------------------------------


def _check_test_count(findings: list[Finding]) -> tuple[int, int | None]:
    """Count test functions across tests/ and compare to CLAUDE.md claim.

    Returns (actual_count, claimed_count_or_None).
    """
    tests_dir = PROJECT_ROOT / "tests"
    actual_count = 0

    for py_file in _py_files(tests_dir):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name.startswith("test_"):
                actual_count += 1

    # Extract claimed count from CLAUDE.md
    claude_md = _load_claude_md()
    claimed_count: int | None = None
    if claude_md:
        # Pattern: **NNN tests** (e.g. "**738 tests**")
        match = re.search(r"\*\*(\d+)\s+tests?\*\*", claude_md)
        if match:
            claimed_count = int(match.group(1))

    if claimed_count is not None and actual_count != claimed_count:
        diff = actual_count - claimed_count
        direction = "more" if diff > 0 else "fewer"
        findings.append(
            Finding(
                id="DOC-TEST-COUNT",
                severity="medium",
                category="doc_sync",
                title=f"Test count mismatch: CLAUDE.md claims {claimed_count}, actual is {actual_count}",
                detail=(
                    f"CLAUDE.md states **{claimed_count} tests** but the codebase has "
                    f"{actual_count} test functions ({abs(diff)} {direction}). "
                    "Update the Current Status section in CLAUDE.md."
                ),
                file="CLAUDE.md",
                recommendation=f"Update CLAUDE.md test count from {claimed_count} to {actual_count}.",
                effort_hours=0.1,
                auto_fixable=True,
            )
        )

    return actual_count, claimed_count


def _check_test_file_count(findings: list[Finding]) -> tuple[int, int | None]:
    """Count test files in tests/ and compare to CLAUDE.md claim.

    Returns (actual_count, claimed_count_or_None).
    """
    tests_dir = PROJECT_ROOT / "tests"
    actual_count = 0

    if tests_dir.is_dir():
        for _py_file in sorted(tests_dir.glob("test_*.py")):
            actual_count += 1

    # Extract claimed file count from CLAUDE.md
    # Patterns: "across NN test files" or "tests/ (NN files)" or "(NN files)"
    claude_md = _load_claude_md()
    claimed_count: int | None = None
    if claude_md:
        # Try "across NN test files"
        match = re.search(r"across\s+(\d+)\s+test\s+files?", claude_md)
        if match:
            claimed_count = int(match.group(1))
        else:
            # Try "Tests in `tests/` (NN files)"
            match = re.search(r"[Tt]ests.*?\((\d+)\s+files?\)", claude_md)
            if match:
                claimed_count = int(match.group(1))

    if claimed_count is not None and actual_count != claimed_count:
        diff = actual_count - claimed_count
        direction = "more" if diff > 0 else "fewer"
        findings.append(
            Finding(
                id="DOC-TEST-FILE-COUNT",
                severity="medium",
                category="doc_sync",
                title=f"Test file count mismatch: CLAUDE.md claims {claimed_count}, actual is {actual_count}",
                detail=(
                    f"CLAUDE.md states {claimed_count} test files but tests/ contains "
                    f"{actual_count} test files ({abs(diff)} {direction})."
                ),
                file="CLAUDE.md",
                recommendation=f"Update CLAUDE.md test file count from {claimed_count} to {actual_count}.",
                effort_hours=0.1,
                auto_fixable=True,
            )
        )

    return actual_count, claimed_count


def _check_table_count(findings: list[Finding]) -> tuple[int, int | None]:
    """Count model classes with __tablename__ and compare to CLAUDE.md claim.

    Returns (actual_count, claimed_count_or_None).
    """
    models_dir = PROJECT_ROOT / "app" / "models"
    actual_count = 0
    table_names: list[str] = []

    for py_file in _py_files(models_dir):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__"
                        for t in item.targets
                    ):
                        actual_count += 1
                        # Extract the table name string if possible
                        if isinstance(item.value, ast.Constant) and isinstance(
                            item.value.value, str
                        ):
                            table_names.append(item.value.value)

    # Extract claimed count from CLAUDE.md
    claude_md = _load_claude_md()
    claimed_count: int | None = None
    if claude_md:
        # Pattern: "NN tables" (e.g. "27 tables")
        match = re.search(r"(\d+)\s+tables?\s*[-—]", claude_md)
        if match:
            claimed_count = int(match.group(1))

    if claimed_count is not None and actual_count != claimed_count:
        diff = actual_count - claimed_count
        direction = "more" if diff > 0 else "fewer"
        findings.append(
            Finding(
                id="DOC-TABLE-COUNT",
                severity="medium",
                category="doc_sync",
                title=f"Table count mismatch: CLAUDE.md claims {claimed_count}, actual is {actual_count}",
                detail=(
                    f"CLAUDE.md states {claimed_count} tables but app/models/ defines "
                    f"{actual_count} model classes with __tablename__ ({abs(diff)} {direction}). "
                    f"Tables found: {', '.join(sorted(table_names))}"
                ),
                file="CLAUDE.md",
                recommendation=f"Update CLAUDE.md table count from {claimed_count} to {actual_count}.",
                effort_hours=0.1,
                auto_fixable=True,
            )
        )

    return actual_count, claimed_count


def _check_endpoint_docstrings(findings: list[Finding]) -> tuple[int, int]:
    """Check that all router endpoint functions have docstrings.

    Returns (total_endpoints, documented_endpoints).
    """
    api_dir = PROJECT_ROOT / "app" / "api"
    total_endpoints = 0
    documented_endpoints = 0
    # HTTP method decorators to look for
    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for py_file in _py_files(api_dir):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel_path = _relative(py_file)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Check if the function is decorated with @router.<method>(...)
            is_endpoint = False
            for decorator in node.decorator_list:
                # @router.get(...), @router.post(...), etc.
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Attribute
                ):
                    if decorator.func.attr in http_methods:
                        is_endpoint = True
                        break
                # @router.get (without call, unlikely but possible)
                elif (
                    isinstance(decorator, ast.Attribute)
                    and decorator.attr in http_methods
                ):
                    is_endpoint = True
                    break

            if not is_endpoint:
                continue

            total_endpoints += 1
            docstring = ast.get_docstring(node)
            if docstring:
                documented_endpoints += 1
            else:
                findings.append(
                    Finding(
                        id="DOC-NO-DOCSTRING",
                        severity="low",
                        category="api_docs",
                        title=f"Endpoint missing docstring: {node.name}",
                        detail=(
                            f"Router endpoint `{node.name}` in `{rel_path}` (line {node.lineno}) "
                            "has no docstring. Docstrings serve as API documentation and appear "
                            "in the auto-generated OpenAPI spec."
                        ),
                        file=rel_path,
                        line=node.lineno,
                        recommendation=f"Add a docstring to `{node.name}` describing its purpose and parameters.",
                        effort_hours=0.1,
                    )
                )

    return total_endpoints, documented_endpoints


def _check_model_conventions(findings: list[Finding]) -> int:
    """Check that models follow timestamp column conventions.

    All models should have created_at and updated_at, except audit_logs
    which only has created_at.

    Returns number of violations found.
    """
    models_dir = PROJECT_ROOT / "app" / "models"
    violations = 0

    for py_file in _py_files(models_dir):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel_path = _relative(py_file)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Only check classes that have __tablename__
            tablename = None
            has_created_at = False
            has_updated_at = False

            for item in node.body:
                # Find __tablename__
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (
                            isinstance(target, ast.Name)
                            and target.id == "__tablename__"
                        ) and isinstance(item.value, ast.Constant):
                            tablename = item.value.value

                # Find created_at / updated_at as annotated assignments or regular assignments
                if isinstance(item, (ast.AnnAssign, ast.Assign)):
                    # For AnnAssign: created_at: Mapped[...] = ...
                    if isinstance(item, ast.AnnAssign) and isinstance(
                        item.target, ast.Name
                    ):
                        if item.target.id == "created_at":
                            has_created_at = True
                        elif item.target.id == "updated_at":
                            has_updated_at = True
                    # For Assign: created_at = Column(...)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == "created_at":
                                    has_created_at = True
                                elif target.id == "updated_at":
                                    has_updated_at = True

            if tablename is None:
                continue

            # audit_logs is special: only created_at, no updated_at
            if tablename == "audit_logs":
                if not has_created_at:
                    violations += 1
                    findings.append(
                        Finding(
                            id="DOC-CONVENTION-TS",
                            severity="medium",
                            category="convention",
                            title=f"Model '{tablename}' missing created_at column",
                            detail=(
                                f"Model class in `{rel_path}` with table '{tablename}' "
                                "is missing the created_at column. Convention requires "
                                "all tables to have created_at."
                            ),
                            file=rel_path,
                            recommendation="Add a created_at column with DateTime(timezone=True).",
                        )
                    )
                continue

            # All other models need both
            missing = []
            if not has_created_at:
                missing.append("created_at")
            if not has_updated_at:
                missing.append("updated_at")

            if missing:
                violations += 1
                findings.append(
                    Finding(
                        id="DOC-CONVENTION-TS",
                        severity="medium",
                        category="convention",
                        title=f"Model '{tablename}' missing {', '.join(missing)}",
                        detail=(
                            f"Model class in `{rel_path}` with table '{tablename}' "
                            f"is missing column(s): {', '.join(missing)}. "
                            "Convention requires all tables to have created_at and updated_at "
                            "(except audit_logs which only has created_at)."
                        ),
                        file=rel_path,
                        recommendation=f"Add missing column(s) ({', '.join(missing)}) to the model.",
                    )
                )

    return violations


def _check_response_envelope(findings: list[Finding]) -> int:
    """Check API endpoints for responses that don't use {"data": ..., "meta": ...} envelope.

    Scans for return statements with dict literals missing a "data" key.
    Returns number of violations.
    """
    api_dir = PROJECT_ROOT / "app" / "api"
    violations = 0
    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for py_file in _py_files(api_dir):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel_path = _relative(py_file)

        # Find all endpoint functions
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            is_endpoint = False
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in http_methods
                ):
                    is_endpoint = True
                    break

            if not is_endpoint:
                continue

            # Walk the function body for return statements with dict literals
            for child in ast.walk(node):
                if not isinstance(child, ast.Return) or child.value is None:
                    continue

                # Only check dict literals (return {...})
                if not isinstance(child.value, ast.Dict):
                    continue

                # Check if "data" is among the dict keys
                has_data_key = False
                for key in child.value.keys:
                    if isinstance(key, ast.Constant) and key.value == "data":
                        has_data_key = True
                        break

                if not has_data_key:
                    violations += 1
                    findings.append(
                        Finding(
                            id="DOC-ENVELOPE",
                            severity="low",
                            category="convention",
                            title=f"Response missing 'data' envelope in {node.name}",
                            detail=(
                                f"Endpoint `{node.name}` in `{rel_path}` (line {child.lineno}) "
                                "returns a dict literal without a 'data' key. "
                                'Convention requires responses to use {"data": ..., "meta": ...} envelope.'
                            ),
                            file=rel_path,
                            line=child.lineno,
                            recommendation='Wrap the response in {"data": ..., "meta": {...}} format.',
                        )
                    )

    return violations


def _check_password_storage(findings: list[Finding]) -> bool:
    """Verify bcrypt/passlib usage for password hashing.

    Returns True if verified, False if not found.
    """
    security_file = PROJECT_ROOT / "app" / "utils" / "security.py"
    auth_file = PROJECT_ROOT / "app" / "api" / "auth.py"
    verified = False

    for filepath in [security_file, auth_file]:
        content = _read_text_safe(filepath)
        if content is None:
            continue

        has_passlib = "passlib" in content or "CryptContext" in content
        has_bcrypt = "bcrypt" in content
        has_hash_password = "def hash_password" in content
        has_verify_password = "def verify_password" in content

        if (has_passlib or has_bcrypt) and has_hash_password and has_verify_password:
            verified = True
            break

    if not verified:
        findings.append(
            Finding(
                id="DOC-PRIVACY-PWD",
                severity="high",
                category="privacy_compliance",
                title="Cannot verify bcrypt/passlib password hashing",
                detail=(
                    "Privacy policy claims passwords are never stored in plaintext. "
                    "Could not find hash_password/verify_password functions using "
                    "passlib/bcrypt in app/utils/security.py or app/api/auth.py."
                ),
                recommendation=(
                    "Ensure password hashing uses passlib with bcrypt scheme and that "
                    "hash_password() and verify_password() functions are defined."
                ),
            )
        )

    return verified


def _check_suppression_hashing(findings: list[Finding]) -> bool:
    """Verify SHA-256 usage in suppression list hashing.

    Returns True if verified, False if not found.
    """
    hashing_file = PROJECT_ROOT / "app" / "utils" / "hashing.py"
    content = _read_text_safe(hashing_file)
    verified = False

    if content is not None:
        has_sha256 = "sha256" in content
        has_hashlib = "hashlib" in content
        if has_sha256 and has_hashlib:
            verified = True

    if not verified:
        findings.append(
            Finding(
                id="DOC-PRIVACY-HASH",
                severity="high",
                category="privacy_compliance",
                title="Cannot verify SHA-256 suppression list hashing",
                detail=(
                    "CLAUDE.md and the privacy policy state that the suppression list "
                    "uses SHA-256 hashing. Could not confirm sha256 + hashlib usage "
                    "in app/utils/hashing.py."
                ),
                file="app/utils/hashing.py",
                recommendation=(
                    "Ensure app/utils/hashing.py uses hashlib.sha256 for suppression "
                    "list matching on normalized inputs."
                ),
            )
        )

    return verified


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------


def scan() -> AgentReport:
    """Run all doc-keeper scans and return a consolidated report."""
    start = time.time()
    findings: list[Finding] = []
    metrics: dict[str, object] = {}
    intel_notes: list[str] = []
    learning_updates: list[str] = []

    # -- 1. Test count check --
    try:
        actual_tests, claimed_tests = _check_test_count(findings)
        metrics["actual_test_count"] = actual_tests
        if claimed_tests is not None:
            metrics["claimed_test_count"] = claimed_tests
    except Exception as exc:
        logger.warning("Test count check failed: %s", exc)

    # -- 2. Test file count --
    try:
        actual_test_files, claimed_test_files = _check_test_file_count(findings)
        metrics["actual_test_file_count"] = actual_test_files
        if claimed_test_files is not None:
            metrics["claimed_test_file_count"] = claimed_test_files
    except Exception as exc:
        logger.warning("Test file count check failed: %s", exc)

    # -- 3. Table count check --
    try:
        actual_tables, claimed_tables = _check_table_count(findings)
        metrics["actual_table_count"] = actual_tables
        if claimed_tables is not None:
            metrics["claimed_table_count"] = claimed_tables
    except Exception as exc:
        logger.warning("Table count check failed: %s", exc)

    # -- 4. Endpoint docstring check --
    try:
        total_endpoints, documented_endpoints = _check_endpoint_docstrings(findings)
        undocumented_endpoints = total_endpoints - documented_endpoints
        metrics["total_endpoints"] = total_endpoints
        metrics["documented_endpoints"] = documented_endpoints
        metrics["undocumented_endpoints"] = undocumented_endpoints
    except Exception as exc:
        logger.warning("Endpoint docstring check failed: %s", exc)
        total_endpoints = 0
        documented_endpoints = 0
        undocumented_endpoints = 0

    # -- 5. Convention checks: model timestamps --
    try:
        ts_violations = _check_model_conventions(findings)
        metrics["convention_violations"] = ts_violations
    except Exception as exc:
        logger.warning("Model convention check failed: %s", exc)
        ts_violations = 0

    # -- 6. Convention checks: response envelope --
    try:
        envelope_violations = _check_response_envelope(findings)
        metrics["convention_violations"] = (
            metrics.get("convention_violations", 0) + envelope_violations  # type: ignore[operator]
        )
    except Exception as exc:
        logger.warning("Response envelope check failed: %s", exc)

    # -- 7. Password storage verification --
    doc_claims_verified = 0
    doc_claims_mismatched = 0
    try:
        if _check_password_storage(findings):
            doc_claims_verified += 1
            intel_notes.append("Verified: passlib/bcrypt password hashing in place")
        else:
            doc_claims_mismatched += 1
    except Exception as exc:
        logger.warning("Password storage check failed: %s", exc)

    # -- 8. Suppression hashing verification --
    try:
        if _check_suppression_hashing(findings):
            doc_claims_verified += 1
            intel_notes.append("Verified: SHA-256 suppression list hashing in place")
        else:
            doc_claims_mismatched += 1
    except Exception as exc:
        logger.warning("Suppression hashing check failed: %s", exc)

    metrics["doc_claims_verified"] = doc_claims_verified
    metrics["doc_claims_mismatched"] = doc_claims_mismatched

    # -- 9. Record historical recurrence --
    for f in findings:
        try:
            prev = learning.get_recurrence_count(AGENT_NAME, f.category, f.file)
            if prev > 0:
                f.recurrence_count = prev + 1
        except Exception:
            pass

    # -- Self-learning updates --
    file_finding_counts: dict[str, int] = {}
    for f in findings:
        if f.file:
            file_finding_counts[f.file] = file_finding_counts.get(f.file, 0) + 1

    try:
        learning.record_scan(
            AGENT_NAME,
            {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
        )
        learning_updates.append(
            f"Recorded scan #{learning.get_total_scans(AGENT_NAME)}"
        )
    except Exception as exc:
        logger.warning("Failed to record scan: %s", exc)

    try:
        learning.update_attention_weights(AGENT_NAME, file_finding_counts)
        if file_finding_counts:
            top_file = max(file_finding_counts, key=file_finding_counts.get)  # type: ignore[arg-type]
            learning_updates.append(
                f"Top drift file: {top_file} ({file_finding_counts[top_file]} findings)"
            )
    except Exception as exc:
        logger.warning("Failed to update attention weights: %s", exc)

    try:
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
    except Exception as exc:
        logger.warning("Failed to record findings: %s", exc)

    # -- Build report --
    elapsed = time.time() - start
    report = AgentReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        metrics=metrics,
        intelligence_applied=intel_notes,
        learning_updates=learning_updates,
    )

    logger.info(
        "DocKeeper scan complete: %d findings in %.1fs "
        "(%d endpoints, %d documented, %d claims verified)",
        len(findings),
        elapsed,
        total_endpoints,
        documented_endpoints,
        doc_claims_verified,
    )
    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report = scan()

    # Print markdown to stdout
    print(report.to_markdown())

    # Summary exit
    sev_counts: dict[str, int] = {}
    for f in report.findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
    summary_parts = [f"{v} {k}" for k, v in sorted(sev_counts.items())]
    print(
        f"\nTotal: {len(report.findings)} findings ({', '.join(summary_parts) or 'clean'})"
    )

    # Exit non-zero if critical or high findings exist
    if sev_counts.get("critical", 0) or sev_counts.get("high", 0):
        sys.exit(1)
