"""Architect agent — code quality & structure scanner."""

from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
import time
from pathlib import Path

from agents.shared.config import (
    FILE_SIZE_WARN_LINES,
    FUNCTION_SIZE_WARN_LINES,
    PROJECT_ROOT,
    SCAN_TARGETS,
    SKIP_DIRS,
)
from agents.shared.report import AgentReport, Finding
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "architect"


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


def _run_tool(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    """Run an external CLI tool, returning None on any failure."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        logger.info("Tool not found: %s", cmd[0])
    except subprocess.TimeoutExpired:
        logger.warning("Tool timed out after %ds: %s", timeout, " ".join(cmd))
    except Exception as exc:
        logger.warning("Tool failed (%s): %s", cmd[0], exc)
    return None


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT for readable output."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Individual scanners
# ---------------------------------------------------------------------------


def _scan_ruff_check(findings: list[Finding]) -> int:
    """Run ruff check in JSON mode and create findings. Return issue count."""
    result = _run_tool(["ruff", "check", "app/", "--output-format=json"])
    if result is None:
        findings.append(
            Finding(
                id="ARCH-RUFF-UNAVAIL",
                severity="info",
                category="tooling",
                title="ruff not available",
                detail="Could not run ruff check. Install with: pip install ruff",
            )
        )
        return 0

    count = 0
    try:
        issues = json.loads(result.stdout) if result.stdout.strip() else []
        for issue in issues:
            count += 1
            code = issue.get("code", "?")
            message = issue.get("message", "")
            filename = issue.get("filename", "")
            location = issue.get("location", {})
            row = location.get("row")

            # Map ruff severity: E/F are errors, W warnings, rest info
            if code.startswith(("E", "F")):
                severity = "medium"
            elif code.startswith("W"):
                severity = "low"
            else:
                severity = "low"

            findings.append(
                Finding(
                    id=f"ARCH-LINT-{code}",
                    severity=severity,
                    category="lint",
                    title=f"Ruff {code}: {message}",
                    detail=message,
                    file=filename,
                    line=row,
                    recommendation="Run `ruff check --fix` to auto-fix, or address manually.",
                    auto_fixable=(issue.get("fix") or {}).get("applicability", "")
                    == "safe",
                )
            )
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse ruff output: %s", exc)
        if result.stderr.strip():
            findings.append(
                Finding(
                    id="ARCH-RUFF-ERR",
                    severity="info",
                    category="tooling",
                    title="ruff check produced errors",
                    detail=result.stderr[:500],
                )
            )
    return count


def _scan_ruff_format(findings: list[Finding]) -> None:
    """Run ruff format --check and flag files with formatting drift."""
    result = _run_tool(["ruff", "format", "--check", "app/"])
    if result is None:
        findings.append(
            Finding(
                id="ARCH-FMTCHK-UNAVAIL",
                severity="info",
                category="tooling",
                title="ruff format not available",
                detail="Could not run ruff format --check.",
            )
        )
        return

    # ruff format --check exits non-zero if files need formatting.
    # Unformatted files are listed on stdout, one per line.
    if result.returncode != 0:
        unformatted = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("error")
        ]
        if unformatted:
            findings.append(
                Finding(
                    id="ARCH-FMT-DRIFT",
                    severity="low",
                    category="formatting",
                    title=f"Formatting drift in {len(unformatted)} file(s)",
                    detail="Files with formatting drift:\n"
                    + "\n".join(f"  - {f}" for f in unformatted[:20]),
                    recommendation="Run `ruff format .` to fix all formatting.",
                    auto_fixable=True,
                )
            )


def _scan_file_sizes(py_files: list[Path], findings: list[Finding]) -> int:
    """Flag files exceeding FILE_SIZE_WARN_LINES. Return count of large files."""
    large_count = 0
    for path in py_files:
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        if line_count > FILE_SIZE_WARN_LINES:
            large_count += 1
            findings.append(
                Finding(
                    id="ARCH-LARGE-FILE",
                    severity="medium",
                    category="complexity",
                    title=f"Large file: {line_count} lines",
                    detail=(
                        f"`{_relative(path)}` has {line_count} lines "
                        f"(threshold: {FILE_SIZE_WARN_LINES}). "
                        "Consider splitting into smaller, focused modules."
                    ),
                    file=_relative(path),
                    recommendation="Extract related functions into a submodule.",
                    effort_hours=1.0,
                )
            )
    return large_count


def _scan_functions(py_files: list[Path], findings: list[Finding]) -> tuple[int, int]:
    """Parse files with ast. Flag long functions and missing type hints.

    Returns (total_functions, missing_hints_count).
    """
    total_functions = 0
    missing_hints = 0

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            total_functions += 1
            func_name = node.name
            start_line = node.lineno
            # Compute function length from body span
            end_line = max(
                getattr(child, "end_lineno", start_line)
                for child in ast.walk(node)
                if hasattr(child, "end_lineno")
            )
            func_length = end_line - start_line + 1

            rel_path = _relative(path)

            # --- Long function check ---
            if func_length > FUNCTION_SIZE_WARN_LINES:
                findings.append(
                    Finding(
                        id="ARCH-LONG-FUNC",
                        severity="medium",
                        category="complexity",
                        title=f"Long function: {func_name} ({func_length} lines)",
                        detail=(
                            f"`{func_name}` in `{rel_path}` spans {func_length} lines "
                            f"(threshold: {FUNCTION_SIZE_WARN_LINES}). "
                            "Long functions are harder to test and maintain."
                        ),
                        file=rel_path,
                        line=start_line,
                        recommendation="Extract helper functions or break into logical steps.",
                        effort_hours=0.5,
                    )
                )

            # --- Missing return type annotation ---
            if node.returns is None and not func_name.startswith("_"):
                missing_hints += 1
                # Only report public functions to keep noise down
                findings.append(
                    Finding(
                        id="ARCH-NO-RTYPE",
                        severity="low",
                        category="type_safety",
                        title=f"Missing return type: {func_name}",
                        detail=(
                            f"Public function `{func_name}` in `{rel_path}` "
                            "has no return type annotation."
                        ),
                        file=rel_path,
                        line=start_line,
                        recommendation="Add a return type annotation (-> ReturnType).",
                        auto_fixable=False,
                    )
                )

    return total_functions, missing_hints


def _scan_conventions(py_files: list[Path], findings: list[Finding]) -> None:
    """Check for convention violations documented in CLAUDE.md."""

    # Patterns to detect
    naive_datetime_re = re.compile(
        r"datetime\.now\(\s*\)"  # datetime.now() without tz argument
    )
    autoincrement_re = re.compile(
        r"(?:Integer|BigInteger)\s*,\s*primary_key\s*=\s*True"
        r"|autoincrement\s*=\s*True",
        re.IGNORECASE,
    )
    secret_patterns = [
        # Strings that look like hardcoded API keys or passwords
        re.compile(r"""['"]sk[-_][a-zA-Z0-9]{20,}['"]"""),  # Stripe-style sk-...
        re.compile(
            r"""['"](?:password|secret|api_key)\s*=\s*['"][^'"]{8,}['"]""",
            re.IGNORECASE,
        ),
        re.compile(r"""['"](?:ghp_|github_pat_)[a-zA-Z0-9]{20,}['"]"""),  # GitHub PATs
        re.compile(r"""['"](?:Bearer\s+)[a-zA-Z0-9._-]{20,}['"]"""),  # Bearer tokens
    ]

    for path in py_files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        rel_path = _relative(path)
        for lineno, line in enumerate(lines, start=1):
            # --- Naive datetime ---
            if naive_datetime_re.search(line):
                findings.append(
                    Finding(
                        id="ARCH-NAIVE-DT",
                        severity="medium",
                        category="convention",
                        title="datetime.now() without timezone",
                        detail=(
                            f"`datetime.now()` in `{rel_path}:{lineno}` — "
                            "convention requires `datetime.now(timezone.utc)`."
                        ),
                        file=rel_path,
                        line=lineno,
                        recommendation="Use `datetime.now(timezone.utc)` for UTC timestamps.",
                        auto_fixable=True,
                    )
                )

            # --- Autoincrement IDs ---
            if autoincrement_re.search(line):
                findings.append(
                    Finding(
                        id="ARCH-AUTOINC-ID",
                        severity="medium",
                        category="convention",
                        title="Possible autoincrement integer ID",
                        detail=(
                            f"Integer primary key or autoincrement detected at "
                            f"`{rel_path}:{lineno}`. Convention requires UUIDs."
                        ),
                        file=rel_path,
                        line=lineno,
                        recommendation="Use `Column(UUID, primary_key=True, default=uuid.uuid4)`.",
                    )
                )

            # --- Hardcoded secrets ---
            for pat in secret_patterns:
                if pat.search(line):
                    findings.append(
                        Finding(
                            id="ARCH-HARDCODED-SECRET",
                            severity="high",
                            category="security",
                            title="Possible hardcoded secret",
                            detail=(
                                f"String resembling a secret at `{rel_path}:{lineno}`. "
                                "Secrets must be loaded from environment variables."
                            ),
                            file=rel_path,
                            line=lineno,
                            recommendation="Move to environment variable and load via os.environ.",
                        )
                    )
                    break  # One finding per line is enough


def _scan_n_plus_one(py_files: list[Path], findings: list[Finding]) -> None:
    """Use ast to detect for-loops containing await db.execute / session.execute."""

    db_call_names = {"execute", "scalar", "scalars", "get", "fetch_one", "fetch_all"}

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel_path = _relative(path)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue

            # Walk the loop body looking for DB calls
            for child in ast.walk(node):
                if not isinstance(child, (ast.Call, ast.Await)):
                    continue

                # Unwrap Await(Call(...))
                call_node = child
                if isinstance(child, ast.Await) and isinstance(child.value, ast.Call):
                    call_node = child.value
                elif not isinstance(child, ast.Call):
                    continue

                # Check if call is <obj>.execute / <obj>.scalar / etc.
                func = call_node.func if isinstance(call_node, ast.Call) else None
                if isinstance(func, ast.Attribute) and func.attr in db_call_names:
                    findings.append(
                        Finding(
                            id="ARCH-N+1",
                            severity="high",
                            category="performance",
                            title=f"Potential N+1 query: {func.attr}() inside loop",
                            detail=(
                                f"Database call `{func.attr}()` found inside a loop at "
                                f"`{rel_path}:{node.lineno}`. This may cause N+1 query "
                                "performance issues."
                            ),
                            file=rel_path,
                            line=node.lineno,
                            recommendation=(
                                "Batch the query outside the loop using `IN` clause, "
                                "or use eager loading / joinedload."
                            ),
                            effort_hours=0.5,
                        )
                    )
                    break  # One finding per loop is enough


# ---------------------------------------------------------------------------
# Vault isolation check
# ---------------------------------------------------------------------------

# Models that hold per-user data and MUST be filtered by user_id
_VAULT_MODELS = {"Contact", "MarketplaceListing", "WarmScore", "MatchResult"}

# Patterns that indicate user_id scoping
_USER_ID_PATTERNS = re.compile(
    r"user_id|current_user|token_data|get_current_user", re.IGNORECASE
)


def _scan_vault_isolation(findings: list[Finding]) -> None:
    """Flag service/API functions that query vault models without user_id filtering."""
    scan_dirs = [
        PROJECT_ROOT / "app" / "services",
        PROJECT_ROOT / "app" / "api",
    ]
    for scan_dir in scan_dirs:
        for path in _py_files(scan_dir):
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            rel_path = _relative(path)
            # Skip test files and __init__
            if "test" in rel_path or path.name == "__init__.py":
                continue

            # Split into functions and check each
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                func_source = ast.get_source_segment(source, node)
                if func_source is None:
                    continue

                # Check if function references a vault model
                vault_hit = None
                for model in _VAULT_MODELS:
                    if model in func_source and (
                        f"select({model})" in func_source
                        or f".query({model})" in func_source
                        or f"select({model}," in func_source
                    ):
                        vault_hit = model
                        break

                if vault_hit is None:
                    continue

                # Check if user_id scoping is present
                if _USER_ID_PATTERNS.search(func_source):
                    continue

                findings.append(
                    Finding(
                        id="ARCH-VAULT-LEAK",
                        severity="high",
                        category="vault_isolation",
                        title=f"Vault query on {vault_hit} without user_id scope",
                        detail=(
                            f"Function `{node.name}` in `{rel_path}:{node.lineno}` "
                            f"queries {vault_hit} but has no visible user_id filtering. "
                            f"This could allow cross-user data leakage."
                        ),
                        file=rel_path,
                        line=node.lineno,
                        recommendation=(
                            f"Add .where({vault_hit}.user_id == current_user.id) "
                            f"to ensure vault isolation."
                        ),
                        effort_hours=0.5,
                    )
                )


# ---------------------------------------------------------------------------
# Circular import detection
# ---------------------------------------------------------------------------


def _scan_circular_imports(findings: list[Finding]) -> int:
    """Build import graph for app/ modules and detect circular dependencies.

    Returns the number of cycles detected.
    """
    app_dir = PROJECT_ROOT / "app"
    if not app_dir.is_dir():
        return 0

    # Build graph: module_path -> set of imported module_paths
    graph: dict[str, set[str]] = {}

    for path in _py_files(app_dir):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel = _relative(path)
        graph.setdefault(rel, set())

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Only track internal app imports
                if node.module.startswith("app."):
                    # Convert module path to file path
                    parts = node.module.replace(".", "/")
                    target = f"{parts}.py"
                    # Also check for package __init__
                    target_init = f"{parts}/__init__.py"
                    if (PROJECT_ROOT / target).exists():
                        graph[rel].add(target)
                    elif (PROJECT_ROOT / target_init).exists():
                        graph[rel].add(target_init)

    # DFS cycle detection
    cycles: list[list[str]] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    path_stack: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path_stack.append(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                # Found a cycle
                cycle_start = path_stack.index(neighbor)
                cycle = path_stack[cycle_start:] + [neighbor]
                cycles.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor)
        path_stack.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    # Report cycles (deduplicate by frozenset of members)
    seen_cycles: set[frozenset[str]] = set()
    for cycle in cycles:
        key = frozenset(cycle)
        if key in seen_cycles:
            continue
        seen_cycles.add(key)
        cycle_str = " -> ".join(cycle)
        findings.append(
            Finding(
                id="ARCH-CIRCULAR-IMPORT",
                severity="medium",
                category="circular_import",
                title=f"Circular import: {len(cycle) - 1} modules",
                detail=f"Import cycle detected: {cycle_str}",
                file=cycle[0],
                recommendation=(
                    "Break the cycle by moving shared types to a common module, "
                    "using TYPE_CHECKING imports, or restructuring dependencies."
                ),
                effort_hours=1.0,
            )
        )

    return len(seen_cycles)


# ---------------------------------------------------------------------------
# Dead code detection
# ---------------------------------------------------------------------------


def _scan_dead_code(py_files: list[Path], findings: list[Finding]) -> int:
    """Find public functions defined in app/ that are never referenced elsewhere.

    Returns count of dead functions detected.
    """
    # Phase 1: Collect all public function definitions
    definitions: dict[str, tuple[str, int]] = {}  # func_name -> (file, line)
    # Skip names that are commonly used via framework magic
    _FRAMEWORK_NAMES = {
        "startup",
        "shutdown",
        "lifespan",
        "get_db",
        "get_current_user",
        "main",
        "app",
        "create_app",
    }

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel = _relative(path)
        # Skip __init__.py (re-exports) and test files
        if path.name == "__init__.py" or "test" in rel:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            # Skip private, dunder, framework, and short names
            if (
                name.startswith("_")
                or name in _FRAMEWORK_NAMES
                or len(name) <= 2
            ):
                continue
            # Only track if not already seen (first definition wins)
            if name not in definitions:
                definitions[name] = (rel, node.lineno)

    # Phase 2: Scan all files for references to those names
    all_sources: list[str] = []
    for path in py_files:
        try:
            all_sources.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue

    # Also scan test files for references (tests count as usage)
    test_dir = PROJECT_ROOT / "tests"
    if test_dir.is_dir():
        for path in _py_files(test_dir):
            try:
                all_sources.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue

    combined = "\n".join(all_sources)

    dead_count = 0
    for name, (file, line) in definitions.items():
        # Count occurrences — must appear more than once (the definition itself)
        # Use word boundary to avoid partial matches
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        matches = pattern.findall(combined)
        if len(matches) <= 1:
            dead_count += 1
            findings.append(
                Finding(
                    id="ARCH-DEAD-CODE",
                    severity="low",
                    category="dead_code",
                    title=f"Potentially unused function: {name}",
                    detail=(
                        f"Public function `{name}` defined in `{file}:{line}` "
                        f"has no references elsewhere in the codebase. "
                        f"It may be dead code."
                    ),
                    file=file,
                    line=line,
                    recommendation=(
                        "Verify this function is truly unused. If so, remove it "
                        "to reduce maintenance burden."
                    ),
                    effort_hours=0.25,
                )
            )

    return dead_count


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------


def scan() -> AgentReport:
    """Run all architect scans and return a consolidated report."""
    start = time.time()
    findings: list[Finding] = []
    metrics: dict[str, object] = {}
    intel_notes: list[str] = []

    # Collect Python files to scan
    backend_root = SCAN_TARGETS.get("backend", PROJECT_ROOT / "app")
    if isinstance(backend_root, Path):
        py_files = _py_files(backend_root)
    else:
        py_files = []
    metrics["total_files_scanned"] = len(py_files)

    # -- 1. Ruff lint --
    lint_count = _scan_ruff_check(findings)
    metrics["lint_issues_count"] = lint_count

    # -- 2. Ruff format --
    _scan_ruff_format(findings)

    # -- 3. File sizes --
    large_count = _scan_file_sizes(py_files, findings)
    metrics["large_files_count"] = large_count

    # -- 4. Function analysis (length + missing type hints) --
    total_funcs, missing_hints = _scan_functions(py_files, findings)
    metrics["total_functions"] = total_funcs
    metrics["missing_return_types"] = missing_hints

    # -- 5. Convention checks --
    _scan_conventions(py_files, findings)

    # -- 6. N+1 query detection --
    _scan_n_plus_one(py_files, findings)

    # -- 7. Vault isolation check --
    _scan_vault_isolation(findings)

    # -- 8. Circular import detection --
    cycle_count = _scan_circular_imports(findings)
    metrics["circular_import_cycles"] = cycle_count

    # -- 9. Dead code detection --
    dead_count = _scan_dead_code(py_files, findings)
    metrics["dead_functions_detected"] = dead_count

    # -- 10. External intelligence --
    try:
        from agents.shared.intelligence import ExternalIntelligence

        ei = ExternalIntelligence()
        relevant = ei.get_for_agent(AGENT_NAME)
        for item in relevant:
            intel_notes.append(f"[{item.category}] {item.title}")
    except Exception:
        pass

    # -- 11. Record historical recurrence --
    for f in findings:
        prev = learning.get_recurrence_count(AGENT_NAME, f.category, f.file)
        if prev > 0:
            f.recurrence_count = prev + 1

    # -- Self-learning updates --
    file_finding_counts: dict[str, int] = {}
    for f in findings:
        if f.file:
            file_finding_counts[f.file] = file_finding_counts.get(f.file, 0) + 1

    learning_updates: list[str] = []
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
                f"Top hot-spot: {top_file} ({file_finding_counts[top_file]} findings)"
            )
    except Exception as exc:
        logger.warning("Failed to update attention weights: %s", exc)

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
        "Architect scan complete: %d findings in %.1fs (%d files, %d functions)",
        len(findings),
        elapsed,
        len(py_files),
        total_funcs,
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
