"""Architect agent — code quality & structure scanner."""

from __future__ import annotations

import ast
import copy
import json
import logging
import random
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
import contextlib

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


# Type alias for the AST cache: {path: (source_text, parsed_tree)}
ASTCache = dict[Path, tuple[str, ast.Module]]


def _build_ast_cache(py_files: list[Path]) -> ASTCache:
    """Parse all Python files once and return a reusable cache."""
    cache: ASTCache = {}
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            cache[path] = (source, tree)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
    return cache


# ---------------------------------------------------------------------------
# Individual scanners
# ---------------------------------------------------------------------------


def _scan_ruff_check(findings: list[Finding]) -> int:
    """Run ruff check in JSON mode and create findings. Return issue count."""
    result = _run_tool(["ruff", "check", "app/", "mcp_server/", "--output-format=json"])
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
    result = _run_tool(["ruff", "format", "--check", "app/", "mcp_server/"])
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


def _scan_file_sizes(
    py_files: list[Path], findings: list[Finding], cache: ASTCache | None = None
) -> int:
    """Flag files exceeding FILE_SIZE_WARN_LINES. Return count of large files."""
    large_count = 0
    _cache = cache or {}
    for path in py_files:
        cached = _cache.get(path)
        if cached:
            line_count = len(cached[0].splitlines())
        else:
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


def _scan_functions(
    py_files: list[Path], findings: list[Finding], cache: ASTCache | None = None
) -> tuple[int, int]:
    """Parse files with ast. Flag long functions and missing type hints.

    Returns (total_functions, missing_hints_count).
    """
    total_functions = 0
    missing_hints = 0

    _cache = cache or {}
    for path in py_files:
        cached = _cache.get(path)
        if cached:
            source, tree = cached
        else:
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


def _scan_conventions(
    py_files: list[Path], findings: list[Finding], cache: ASTCache | None = None
) -> None:
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

    _cache = cache or {}
    for path in py_files:
        cached = _cache.get(path)
        if cached:
            lines = cached[0].splitlines()
        else:
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


def _scan_n_plus_one(
    py_files: list[Path], findings: list[Finding], cache: ASTCache | None = None
) -> None:
    """Detect awaited DB calls inside for/while loops using shared scanner."""
    from agents.shared.n1_scanner import scan_n_plus_one

    results = scan_n_plus_one(py_files, id_prefix="ARCH-N+1", require_await=True)
    findings.extend(results)


# ---------------------------------------------------------------------------
# Vault isolation check
# ---------------------------------------------------------------------------

# Models that hold per-user data and MUST be filtered by user_id
_VAULT_MODELS = {"Contact", "MarketplaceListing", "WarmScore", "MatchResult"}

# Patterns that indicate user_id scoping
_USER_ID_PATTERNS = re.compile(
    r"user_id|current_user|token_data|get_current_user", re.IGNORECASE
)


_CROSS_VAULT_ALLOWLIST = {
    "_propagate_direct",
    "_create_company_change_feed_items",
}


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

                # Skip allowlisted cross-vault functions (blind-index operations)
                if node.name in _CROSS_VAULT_ALLOWLIST:
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


def _scan_circular_imports(
    findings: list[Finding], cache: ASTCache | None = None
) -> int:
    """Build import graph for app/ modules and detect circular dependencies.

    Returns the number of cycles detected.
    """
    app_dir = PROJECT_ROOT / "app"
    if not app_dir.is_dir():
        return 0

    # Build graph: module_path -> set of imported module_paths
    graph: dict[str, set[str]] = {}

    _cache = cache or {}
    for path in _py_files(app_dir):
        cached = _cache.get(path)
        if cached:
            source, tree = cached
        else:
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

        rel = _relative(path)
        graph.setdefault(rel, set())

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("app.")
            ):
                # Only track internal app imports
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


def _scan_dead_code(
    py_files: list[Path], findings: list[Finding], cache: ASTCache | None = None
) -> int:
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

    _cache = cache or {}
    for path in py_files:
        cached = _cache.get(path)
        if cached:
            source, tree = cached
        else:
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
            if name.startswith("_") or name in _FRAMEWORK_NAMES or len(name) <= 2:
                continue
            # Only track if not already seen (first definition wins)
            if name not in definitions:
                definitions[name] = (rel, node.lineno)

    # Phase 2: Scan all files for references to those names
    all_sources: list[str] = []
    for path in py_files:
        cached = _cache.get(path)
        if cached:
            all_sources.append(cached[0])
        else:
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
# Mypy type checking
# ---------------------------------------------------------------------------


def _scan_mypy(findings: list[Finding]) -> dict[str, object]:
    """Run mypy on app/ and create findings from type errors.

    Returns metrics dict with error counts by category.
    """
    metrics: dict[str, object] = {}

    result = _run_tool(
        ["mypy", "app/", "mcp_server/", "--no-error-summary", "--no-color"],
        timeout=60,
    )
    if result is None:
        findings.append(
            Finding(
                id="ARCH-MYPY-UNAVAIL",
                severity="info",
                category="tooling",
                title="mypy not available",
                detail=(
                    "Could not run mypy. Install with: pip install mypy. "
                    "Type checking helps catch bugs before runtime."
                ),
            )
        )
        metrics["mypy_available"] = False
        return metrics

    metrics["mypy_available"] = True

    # Parse mypy output: file:line: severity: message  [error-code]
    error_re = re.compile(
        r"^(.+?):(\d+):\s+(error|warning|note):\s+(.+?)(?:\s+\[(.+?)\])?$"
    )

    errors_by_code: dict[str, int] = {}
    errors_by_file: dict[str, int] = {}
    total_errors = 0
    total_warnings = 0

    for line in (result.stdout or "").splitlines():
        m = error_re.match(line.strip())
        if not m:
            continue

        filepath, lineno, severity, message, code = m.groups()
        code = code or "unknown"

        if severity == "error":
            total_errors += 1
            errors_by_code[code] = errors_by_code.get(code, 0) + 1
            errors_by_file[filepath] = errors_by_file.get(filepath, 0) + 1
        elif severity == "warning":
            total_warnings += 1

    metrics["mypy_errors"] = total_errors
    metrics["mypy_warnings"] = total_warnings
    metrics["mypy_error_codes"] = dict(
        sorted(errors_by_code.items(), key=lambda x: -x[1])[:10]
    )

    # Create findings based on severity thresholds
    if total_errors > 50:
        # Top offending files
        worst_files = sorted(errors_by_file.items(), key=lambda x: -x[1])[:5]
        worst_str = ", ".join(f"`{f}` ({n})" for f, n in worst_files)
        findings.append(
            Finding(
                id="ARCH-MYPY-ERRORS",
                severity="medium",
                category="type_safety",
                title=f"mypy reports {total_errors} type errors",
                detail=(
                    f"mypy found {total_errors} errors across "
                    f"{len(errors_by_file)} files. "
                    f"Top error codes: {errors_by_code}. "
                    f"Worst files: {worst_str}."
                ),
                recommendation=(
                    "Focus on the most common error code first. "
                    "Consider adding a mypy pre-commit hook to prevent regression."
                ),
                effort_hours=4.0,
            )
        )
    elif total_errors > 10:
        findings.append(
            Finding(
                id="ARCH-MYPY-ERRORS",
                severity="low",
                category="type_safety",
                title=f"mypy reports {total_errors} type errors",
                detail=(
                    f"mypy found {total_errors} errors. Error codes: {errors_by_code}."
                ),
                recommendation="Gradually address type errors to improve safety.",
                effort_hours=2.0,
            )
        )
    elif total_errors == 0:
        findings.append(
            Finding(
                id="ARCH-MYPY-CLEAN",
                severity="info",
                category="type_safety",
                title="mypy: zero type errors",
                detail="mypy reports no type errors. Type safety is strong.",
            )
        )

    return metrics


# ---------------------------------------------------------------------------
# Mutation testing (lightweight built-in sampler)
# ---------------------------------------------------------------------------

# Critical service files to mutation-test (highest business logic density)
_MUTATION_TARGETS = [
    "app/services/warm_scorer.py",
    "app/services/credits.py",
]

# Targeted test files for each mutation target (avoids full-suite pytest runs)
_MUTATION_TEST_MAP: dict[str, list[str]] = {
    "app/services/warm_scorer.py": ["tests/test_warm_scorer.py"],
    "app/services/credits.py": ["tests/test_credits.py"],
}

# Simple AST mutations: swap comparison operators
_OPERATOR_SWAPS: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
}


class _MutationVisitor(ast.NodeTransformer):
    """Apply a single mutation at a target location."""

    def __init__(self, target_line: int, mutation_type: str) -> None:
        self.target_line = target_line
        self.mutation_type = mutation_type
        self.applied = False

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        if (
            not self.applied
            and node.lineno == self.target_line
            and self.mutation_type == "compare_swap"
            and node.ops
        ):
            op_type = type(node.ops[0])
            swap_to = _OPERATOR_SWAPS.get(op_type)
            if swap_to:
                new_node = copy.deepcopy(node)
                new_node.ops[0] = swap_to()
                self.applied = True
                return new_node
        return self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if (
            not self.applied
            and node.lineno == self.target_line
            and self.mutation_type == "return_none"
            and node.value is not None
        ):
            new_node = copy.deepcopy(node)
            new_node.value = ast.Constant(value=None)
            self.applied = True
            return ast.fix_missing_locations(new_node)
        return self.generic_visit(node)


def _collect_mutation_sites(source: str) -> list[tuple[int, str]]:
    """Find lines where we can apply mutations. Returns [(line, type), ...]."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and node.ops:
            op_type = type(node.ops[0])
            if op_type in _OPERATOR_SWAPS:
                sites.append((node.lineno, "compare_swap"))
        elif isinstance(node, ast.Return) and node.value is not None:
            sites.append((node.lineno, "return_none"))
    return sites


def _apply_mutation(source: str, line: int, mutation_type: str) -> str | None:
    """Apply a single mutation and return the mutated source, or None on failure."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    visitor = _MutationVisitor(line, mutation_type)
    new_tree = visitor.visit(tree)
    if not visitor.applied:
        return None

    try:
        return ast.unparse(ast.fix_missing_locations(new_tree))
    except Exception:
        return None


def _restore_mutation_backups() -> None:
    """Restore any source files left mutated by a previous interrupted run.

    Uses a journaling pattern: before mutating a file we write the original
    to ``<file>.mutation_backup``. If that backup still exists on the next
    scan, the previous run was interrupted mid-mutation and we restore.
    """
    for rel_path in _MUTATION_TARGETS:
        backup = PROJECT_ROOT / (rel_path + ".mutation_backup")
        target = PROJECT_ROOT / rel_path
        if backup.exists():
            try:
                target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
                backup.unlink()
                logger.warning("Restored %s from mutation backup", rel_path)
            except OSError as exc:
                logger.error("Failed to restore %s from backup: %s", rel_path, exc)


def _scan_mutation_testing(findings: list[Finding]) -> dict[str, object]:
    """Run lightweight mutation sampling on critical service files.

    For each target file:
    1. Collect mutation sites (operator swaps, return-None)
    2. Sample up to 5 mutations per file
    3. Apply each, run tests, check if tests catch it
    4. Report mutation kill rate

    Returns metrics dict.
    """
    # Recover from any interrupted previous run
    _restore_mutation_backups()

    metrics: dict[str, object] = {}
    total_tested = 0
    total_killed = 0
    total_survived = 0
    file_results: dict[str, dict[str, int]] = {}

    for rel_path in _MUTATION_TARGETS:
        target = PROJECT_ROOT / rel_path
        if not target.exists():
            continue

        try:
            original = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        sites = _collect_mutation_sites(original)
        if not sites:
            continue

        # Write backup before any mutations (journal)
        backup = PROJECT_ROOT / (rel_path + ".mutation_backup")
        try:
            backup.write_text(original, encoding="utf-8")
        except OSError:
            continue  # skip file if we can't create a safety backup

        # Sample 1 mutation per file (reduced from 5 for performance)
        sampled = random.sample(sites, min(1, len(sites)))
        killed = 0
        survived = 0

        for line, mut_type in sampled:
            mutated = _apply_mutation(original, line, mut_type)
            if mutated is None:
                continue

            total_tested += 1

            # Write mutation, run targeted tests, restore
            test_files = _MUTATION_TEST_MAP.get(rel_path, ["tests/"])
            try:
                target.write_text(mutated, encoding="utf-8")
                result = _run_tool(
                    [
                        "python3",
                        "-m",
                        "pytest",
                        *test_files,
                        "-x",
                        "-q",
                        "--timeout=10",
                        "--no-header",
                        "-p",
                        "no:warnings",
                    ],
                    timeout=30,
                )
                if result is not None and result.returncode != 0:
                    killed += 1
                    total_killed += 1
                else:
                    survived += 1
                    total_survived += 1
            except Exception:
                survived += 1
                total_survived += 1
            finally:
                # Always restore original
                target.write_text(original, encoding="utf-8")

        # All mutations done for this file — remove backup journal
        with contextlib.suppress(OSError):
            backup.unlink(missing_ok=True)

        file_results[rel_path] = {
            "sites": len(sites),
            "tested": len(sampled),
            "killed": killed,
            "survived": survived,
        }

    metrics["mutation_files_tested"] = len(file_results)
    metrics["mutation_total_tested"] = total_tested
    metrics["mutation_killed"] = total_killed
    metrics["mutation_survived"] = total_survived
    if total_tested > 0:
        kill_rate = total_killed / total_tested
        metrics["mutation_kill_rate"] = round(kill_rate, 2)

        if kill_rate < 0.60:
            # Identify weak files
            weak = [
                f
                for f, r in file_results.items()
                if r["tested"] > 0 and r["killed"] / r["tested"] < 0.5
            ]
            weak_str = ", ".join(f"`{f}`" for f in weak) if weak else "see details"
            findings.append(
                Finding(
                    id="ARCH-MUTATION-WEAK",
                    severity="medium",
                    category="test_quality",
                    title=f"Mutation kill rate: {kill_rate:.0%} ({total_survived} survived)",
                    detail=(
                        f"Tested {total_tested} mutations across "
                        f"{len(file_results)} critical files. "
                        f"{total_killed} killed, {total_survived} survived. "
                        f"Weak files: {weak_str}. "
                        f"Surviving mutations indicate test gaps."
                    ),
                    recommendation=(
                        "Add assertions for edge cases in surviving mutation files. "
                        "Focus on boundary conditions and return value checks."
                    ),
                    effort_hours=3.0,
                )
            )
        elif kill_rate < 0.80:
            findings.append(
                Finding(
                    id="ARCH-MUTATION-OK",
                    severity="low",
                    category="test_quality",
                    title=f"Mutation kill rate: {kill_rate:.0%}",
                    detail=(
                        f"Tested {total_tested} mutations, killed {total_killed}. "
                        f"Room for improvement — {total_survived} mutations survived."
                    ),
                    recommendation="Review surviving mutations to identify test gaps.",
                    effort_hours=2.0,
                )
            )
        else:
            findings.append(
                Finding(
                    id="ARCH-MUTATION-STRONG",
                    severity="info",
                    category="test_quality",
                    title=f"Mutation kill rate: {kill_rate:.0%} — strong",
                    detail=(
                        f"Tested {total_tested} mutations, killed {total_killed}. "
                        f"Tests are effective at catching code mutations."
                    ),
                )
            )
    else:
        metrics["mutation_kill_rate"] = None

    metrics["mutation_file_details"] = file_results
    return metrics


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
    py_files = _py_files(backend_root) if isinstance(backend_root, Path) else []
    mcp_root = SCAN_TARGETS.get("mcp_server")
    if isinstance(mcp_root, Path):
        py_files.extend(_py_files(mcp_root))
    metrics["total_files_scanned"] = len(py_files)

    # Build AST cache once — all scan functions reuse it
    ast_cache = _build_ast_cache(py_files)

    # -- 1. Ruff lint --
    lint_count = _scan_ruff_check(findings)
    metrics["lint_issues_count"] = lint_count

    # -- 2. Ruff format --
    _scan_ruff_format(findings)

    # -- 3. File sizes --
    large_count = _scan_file_sizes(py_files, findings, ast_cache)
    metrics["large_files_count"] = large_count

    # -- 4. Function analysis (length + missing type hints) --
    total_funcs, missing_hints = _scan_functions(py_files, findings, ast_cache)
    metrics["total_functions"] = total_funcs
    metrics["missing_return_types"] = missing_hints

    # -- 5. Convention checks --
    _scan_conventions(py_files, findings, ast_cache)

    # -- 6. N+1 query detection --
    _scan_n_plus_one(py_files, findings, ast_cache)

    # -- 7. Vault isolation check --
    _scan_vault_isolation(findings)

    # -- 8. Circular import detection --
    cycle_count = _scan_circular_imports(findings, ast_cache)
    metrics["circular_import_cycles"] = cycle_count

    # -- 9. Dead code detection --
    dead_count = _scan_dead_code(py_files, findings, ast_cache)
    metrics["dead_functions_detected"] = dead_count

    # -- 10. Mypy type checking --
    mypy_metrics = _scan_mypy(findings)
    metrics.update(mypy_metrics)

    # -- 11. Mutation testing (sampled) --
    mutation_metrics = _scan_mutation_testing(findings)
    metrics.update(mutation_metrics)

    # -- 12. External intelligence --
    try:
        from agents.shared.intelligence import ExternalIntelligence

        ei = ExternalIntelligence()
        relevant = ei.get_for_agent(AGENT_NAME)
        for item in relevant:
            intel_notes.append(f"[{item.category}] {item.title}")
    except Exception:
        pass

    # -- 13. Record historical recurrence (batch — single state load) --
    recurrence_keys = [(f.category, f.file) for f in findings]
    recurrence_counts = learning.get_recurrence_counts_batch(
        AGENT_NAME, recurrence_keys
    )
    for f, prev in zip(findings, recurrence_counts, strict=False):
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
