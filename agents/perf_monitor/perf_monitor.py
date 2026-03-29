"""PerfMonitor agent — performance & token cost analyzer."""

import ast
import logging
import re
import time
from pathlib import Path
from typing import Any

from agents.shared.config import PROJECT_ROOT, SKIP_DIRS
from agents.shared.report import Finding, AgentReport
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "perf_monitor"

# Anthropic pricing (per million tokens, as of 2025)
CLAUDE_SONNET_INPUT_COST = 3.0  # $/M tokens
CLAUDE_SONNET_OUTPUT_COST = 15.0  # $/M tokens
CLAUDE_HAIKU_INPUT_COST = 0.80  # $/M tokens
CLAUDE_HAIKU_OUTPUT_COST = 4.0  # $/M tokens

# Average calls per user per month (conservative estimates)
CALLS_PER_USER_PER_MONTH = {
    "ai_matcher": 8,  # ~2 searches/week
    "intro_drafter": 4,  # ~1 intro request/week
    "coach_briefing": 20,  # daily briefing
    "coach_chat": 30,  # ~1 chat/day
    "coach_stream": 10,  # streaming variant
    "resume_parser": 1,  # one-time upload
    "job_fetcher": 2,  # occasional job scan
    "board_registry": 1,  # occasional board lookup
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_py_files(directory: Path) -> list[Path]:
    """Yield .py files, skipping excluded directories."""
    files = []
    if not directory.exists():
        return files
    for p in directory.rglob("*.py"):
        if any(skip in p.parts for skip in SKIP_DIRS):
            continue
        files.append(p)
    return files


def _safe_read(path: Path) -> str:
    """Read file contents, returning empty string on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _safe_parse_ast(source: str, path: Path) -> ast.Module | None:
    """Parse Python source into AST, returning None on failure."""
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token for English."""
    return max(1, len(text) // 4)


def _model_cost(model_hint: str) -> tuple[float, float]:
    """Return (input_cost_per_M, output_cost_per_M) based on model string."""
    if "haiku" in model_hint.lower():
        return (CLAUDE_HAIKU_INPUT_COST, CLAUDE_HAIKU_OUTPUT_COST)
    return (CLAUDE_SONNET_INPUT_COST, CLAUDE_SONNET_OUTPUT_COST)


# ---------------------------------------------------------------------------
# Analysis: AI Token Cost Estimation
# ---------------------------------------------------------------------------

_MESSAGES_CREATE_RE = re.compile(r"client\.messages\.(create|stream)", re.MULTILINE)
_MAX_TOKENS_RE = re.compile(r"max_tokens\s*=\s*(\d+)")
_MODEL_RE = re.compile(r'model\s*=\s*["\']([^"\']+)["\']')
_SYSTEM_ASSIGN_RE = re.compile(
    r"^(_[A-Z_]+PROMPT|SYSTEM_PROMPT)\s*=\s*(?:\"\"\"|\"|f\"\"\")",
    re.MULTILINE,
)


def _scan_ai_token_costs(app_dir: Path) -> tuple[list[Finding], dict[str, Any]]:
    """Scan for Anthropic API calls and estimate token costs."""
    findings: list[Finding] = []
    ai_calls: list[dict[str, Any]] = []

    service_files = _iter_py_files(app_dir / "services")

    for path in service_files:
        source = _safe_read(path)
        if not source:
            continue

        rel = str(path.relative_to(PROJECT_ROOT))

        # Find all client.messages.create/stream calls
        for match in _MESSAGES_CREATE_RE.finditer(source):
            call_type = match.group(1)  # "create" or "stream"
            pos = match.start()

            # Extract surrounding context (the function call block)
            # Look backwards and forwards for reasonable bounds
            block_start = max(0, pos - 200)
            block_end = min(len(source), pos + 500)
            block = source[block_start:block_end]

            # Extract max_tokens
            mt_match = _MAX_TOKENS_RE.search(block)
            max_tokens = int(mt_match.group(1)) if mt_match else 1024

            # Extract model
            model_match = _MODEL_RE.search(block)
            model = model_match.group(1) if model_match else "claude-sonnet"

            # Check if system prompt is used
            has_system = "system=" in block

            # Find the line number
            line_num = source[:pos].count("\n") + 1

            # Try to find the function name
            func_name = "unknown"
            lines_before = source[:pos].split("\n")
            for line in reversed(lines_before):
                func_match = re.match(r"\s*(?:async\s+)?def\s+(\w+)", line)
                if func_match:
                    func_name = func_match.group(1)
                    break

            # Estimate system prompt tokens
            system_tokens = 0
            if has_system:
                # Search the file for the system prompt variable
                for sp_match in _SYSTEM_ASSIGN_RE.finditer(source):
                    sp_start = sp_match.start()
                    # Find the closing triple-quote
                    sp_content_start = source.index('"""', sp_start)
                    try:
                        sp_content_end = source.index('"""', sp_content_start + 3)
                        prompt_text = source[sp_content_start + 3 : sp_content_end]
                        system_tokens = _estimate_tokens(prompt_text)
                    except ValueError:
                        system_tokens = 500  # fallback estimate
                    break
                if system_tokens == 0:
                    system_tokens = 500  # fallback

            # Build feature key from filename
            feature_key = path.stem
            if func_name != "unknown":
                feature_key = f"{path.stem}.{func_name}"

            input_cost, output_cost = _model_cost(model)

            # Estimated input tokens: system prompt + ~500 tokens user prompt
            est_input_tokens = system_tokens + 500
            est_output_tokens = min(max_tokens, max_tokens // 2)  # assume half of max

            cost_per_call = (est_input_tokens / 1_000_000) * input_cost + (
                est_output_tokens / 1_000_000
            ) * output_cost

            ai_calls.append(
                {
                    "file": rel,
                    "line": line_num,
                    "function": func_name,
                    "call_type": call_type,
                    "model": model,
                    "max_tokens": max_tokens,
                    "system_tokens": system_tokens,
                    "est_input_tokens": est_input_tokens,
                    "est_output_tokens": est_output_tokens,
                    "cost_per_call": round(cost_per_call, 5),
                    "feature_key": feature_key,
                }
            )

    # Cost projections
    total_cost_per_user_month = 0.0
    cost_breakdown: dict[str, float] = {}
    for call in ai_calls:
        # Map to usage pattern
        stem = Path(call["file"]).stem
        usage_key = stem
        for pattern_key in CALLS_PER_USER_PER_MONTH:
            if pattern_key in call["function"].lower() or pattern_key in stem:
                usage_key = pattern_key
                break
        calls_per_month = CALLS_PER_USER_PER_MONTH.get(usage_key, 5)
        monthly_cost = call["cost_per_call"] * calls_per_month
        cost_breakdown[call["feature_key"]] = round(monthly_cost, 4)
        total_cost_per_user_month += monthly_cost

    # Project at scale
    cost_100 = round(total_cost_per_user_month * 100, 2)
    cost_1k = round(total_cost_per_user_month * 1_000, 2)
    cost_10k = round(total_cost_per_user_month * 10_000, 2)

    # Findings for expensive calls
    for call in ai_calls:
        if call["max_tokens"] >= 4096:
            findings.append(
                Finding(
                    id=f"PERF-AI-LARGE-{call['function'].upper()}",
                    severity="medium",
                    category="ai_token_cost",
                    title=f"Large max_tokens ({call['max_tokens']}) in {call['function']}",
                    detail=(
                        f"API call in {call['file']}:{call['line']} uses "
                        f"max_tokens={call['max_tokens']} with model {call['model']}. "
                        f"Estimated cost per call: ${call['cost_per_call']:.4f}. "
                        f"Consider whether the output truly needs this many tokens."
                    ),
                    file=call["file"],
                    line=call["line"],
                    recommendation=(
                        "Audit actual output lengths in production logs. "
                        "Reduce max_tokens if median output is significantly smaller."
                    ),
                    effort_hours=0.5,
                )
            )

        if call["system_tokens"] > 1000:
            findings.append(
                Finding(
                    id=f"PERF-AI-PROMPT-{call['function'].upper()}",
                    severity="low",
                    category="ai_prompt_size",
                    title=f"Large system prompt (~{call['system_tokens']} tokens) in {call['function']}",
                    detail=(
                        f"System prompt in {call['file']} is approximately "
                        f"{call['system_tokens']} tokens. Each API call pays for "
                        f"these tokens as input. At scale this compounds."
                    ),
                    file=call["file"],
                    line=call["line"],
                    recommendation=(
                        "Review the system prompt for redundant instructions. "
                        "Consider caching prompt results for identical contexts."
                    ),
                    effort_hours=1.0,
                )
            )

    if cost_10k > 5000:
        findings.append(
            Finding(
                id="PERF-AI-COST-PROJECTION",
                severity="high",
                category="ai_token_cost",
                title=f"Projected AI cost at 10K users: ${cost_10k:,.0f}/month",
                detail=(
                    f"Monthly AI API cost projections: "
                    f"100 users = ${cost_100:,.2f}, "
                    f"1K users = ${cost_1k:,.2f}, "
                    f"10K users = ${cost_10k:,.2f}. "
                    f"Breakdown: {cost_breakdown}"
                ),
                recommendation=(
                    "Implement response caching for common queries. "
                    "Consider Haiku for lower-stakes features (briefings, chat). "
                    "Add token usage monitoring to usage_logs table."
                ),
                effort_hours=4.0,
            )
        )
    elif cost_10k > 1000:
        findings.append(
            Finding(
                id="PERF-AI-COST-PROJECTION",
                severity="medium",
                category="ai_token_cost",
                title=f"Projected AI cost at 10K users: ${cost_10k:,.0f}/month",
                detail=(
                    f"Monthly AI API cost projections: "
                    f"100 users = ${cost_100:,.2f}, "
                    f"1K users = ${cost_1k:,.2f}, "
                    f"10K users = ${cost_10k:,.2f}. "
                    f"Breakdown: {cost_breakdown}"
                ),
                recommendation=(
                    "Monitor actual token usage as users scale. "
                    "Consider Haiku for lower-stakes features."
                ),
                effort_hours=2.0,
            )
        )

    metrics = {
        "ai_calls_found": len(ai_calls),
        "estimated_monthly_cost_100_users": cost_100,
        "estimated_monthly_cost_1k_users": cost_1k,
        "estimated_monthly_cost_10k_users": cost_10k,
        "cost_per_user_per_month": round(total_cost_per_user_month, 4),
        "cost_breakdown_by_feature": cost_breakdown,
    }

    return findings, metrics


# ---------------------------------------------------------------------------
# Analysis: Database Index Check
# ---------------------------------------------------------------------------


def _extract_indexed_columns(models_dir: Path) -> dict[str, set[str]]:
    """Parse model files to find columns with index=True or in __table_args__ Index().

    Returns {model_class_name: {column_name, ...}}.
    """
    indexed: dict[str, set[str]] = {}

    for path in _iter_py_files(models_dir):
        source = _safe_read(path)
        tree = _safe_parse_ast(source, path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # Check if it's likely a model class (inherits from Base or has
            # __tablename__)
            is_model = False
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (
                            isinstance(target, ast.Name)
                            and target.id == "__tablename__"
                        ):
                            is_model = True
                            break
            if not is_model:
                continue

            class_name = node.name
            cols: set[str] = set()

            for item in node.body:
                # Handle: column_name: Mapped[...] = mapped_column(..., index=True)
                # and column_name = mapped_column(..., index=True)
                col_name = None

                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    col_name = item.target.id
                    value = item.value
                elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                    target = item.targets[0]
                    if isinstance(target, ast.Name):
                        col_name = target.id
                        value = item.value
                    else:
                        continue
                else:
                    continue

                if col_name is None or value is None:
                    continue

                # Check if the call has index=True in keywords
                if isinstance(value, ast.Call):
                    for kw in value.keywords:
                        if (
                            kw.arg == "index"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True
                        ):
                            cols.add(col_name)

            # Also check __table_args__ for Index() declarations
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "__table_args__":
                        table_args_value = item.value
                        elements = []
                        if isinstance(table_args_value, ast.Tuple):
                            elements = table_args_value.elts
                        for elem in elements:
                            if not isinstance(elem, ast.Call):
                                continue
                            # Check if this is an Index() call
                            func = elem.func
                            is_index = (
                                isinstance(func, ast.Name) and func.id == "Index"
                            ) or (
                                isinstance(func, ast.Attribute) and func.attr == "Index"
                            )
                            if not is_index:
                                continue
                            # Extract column names from positional args
                            # (skip first arg which is the index name)
                            for arg in elem.args[1:]:
                                if isinstance(arg, ast.Constant) and isinstance(
                                    arg.value, str
                                ):
                                    cols.add(arg.value)

            if cols:
                indexed[class_name] = cols

    return indexed


def _scan_missing_indexes(
    app_dir: Path, indexed: dict[str, set[str]]
) -> tuple[list[Finding], dict[str, Any]]:
    """Find columns used in WHERE clauses that lack indexes."""
    findings: list[Finding] = []

    # Pattern: .where(ModelName.column_name ==
    where_pattern = re.compile(r"\.where\(\s*(\w+)\.(\w+)\s*[=!<>]")

    # Build a set of (model, column) that are indexed
    indexed_set: set[tuple[str, str]] = set()
    for model, cols in indexed.items():
        for col in cols:
            indexed_set.add((model, col))

    # Collect all (model, column) used in where clauses
    queried: dict[
        tuple[str, str], list[tuple[str, int]]
    ] = {}  # (model, col) -> [(file, line)]
    all_model_names = set(indexed.keys())

    scan_dirs = [app_dir / "api", app_dir / "services", app_dir / "tasks"]
    for scan_dir in scan_dirs:
        for path in _iter_py_files(scan_dir):
            source = _safe_read(path)
            rel = str(path.relative_to(PROJECT_ROOT))
            for line_num, line in enumerate(source.split("\n"), 1):
                for m in where_pattern.finditer(line):
                    model_name = m.group(1)
                    col_name = m.group(2)
                    key = (model_name, col_name)
                    if key not in queried:
                        queried[key] = []
                    queried[key].append((rel, line_num))

    # Find unindexed columns that appear in WHERE clauses
    unindexed_query_cols: list[str] = []
    for (model, col), locations in queried.items():
        # Skip function calls or built-ins (func, select, etc.)
        if model.islower() or model in (
            "func",
            "select",
            "delete",
            "update",
            "and_",
            "or_",
        ):
            continue
        if (model, col) not in indexed_set:
            # Skip .id columns — primary keys are auto-indexed by PostgreSQL
            if col == "id":
                continue
            # Only flag if we recognize the model from our parsed set OR
            # the model name looks like a valid class name
            if model in all_model_names or (model[0].isupper() and len(model) > 2):
                label = f"{model}.{col}"
                unindexed_query_cols.append(label)
                # Report up to first 3 locations
                loc_str = "; ".join(f"{f}:{line}" for f, line in locations[:3])
                if len(locations) > 3:
                    loc_str += f" (+{len(locations) - 3} more)"

                recurrence = learning.get_recurrence_count(
                    AGENT_NAME, "missing_index", label
                )
                findings.append(
                    Finding(
                        id=f"PERF-IDX-{model.upper()}-{col.upper()}",
                        severity="medium" if len(locations) >= 3 else "low",
                        category="missing_index",
                        title=f"No index on {model}.{col} (queried in WHERE clause)",
                        detail=(
                            f"{model}.{col} is used in {len(locations)} WHERE clause(s) "
                            f"but has no index=True in the model definition. "
                            f"Locations: {loc_str}"
                        ),
                        file=locations[0][0],
                        line=locations[0][1],
                        recommendation=(
                            f"Add index=True to {model}.{col} in the model definition, "
                            f"then create an Alembic migration."
                        ),
                        effort_hours=0.5,
                        recurrence_count=recurrence + 1,
                    )
                )

    metrics = {
        "indexed_columns": sum(len(v) for v in indexed.values()),
        "unindexed_query_columns": len(unindexed_query_cols),
        "unindexed_details": unindexed_query_cols[:20],
    }
    return findings, metrics


# ---------------------------------------------------------------------------
# Analysis: N+1 Query Patterns
# ---------------------------------------------------------------------------


def _scan_n_plus_one(app_dir: Path) -> tuple[list[Finding], int]:
    """Detect db.execute calls inside for/while loops using AST."""
    findings: list[Finding] = []
    count = 0

    scan_dirs = [app_dir / "api", app_dir / "services", app_dir / "tasks"]
    for scan_dir in scan_dirs:
        for path in _iter_py_files(scan_dir):
            source = _safe_read(path)
            tree = _safe_parse_ast(source, path)
            if tree is None:
                continue

            rel = str(path.relative_to(PROJECT_ROOT))
            source_lines = source.splitlines() if source else []

            # Collect execute calls that live inside loops.
            # Deduplicate by (file, line) to avoid double-counting when
            # ast.walk yields both an Await node and its inner Call node,
            # or when nested loops cause the same call to be visited from
            # multiple ancestor loops.
            seen_lines: set[int] = set()

            for node in ast.walk(tree):
                if not isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
                    continue

                # Only inspect direct body of this loop (not nested loops)
                # to avoid double-counting from ancestor loop walks.
                body_nodes = list(node.body) + list(getattr(node, "orelse", []))
                worklist = list(body_nodes)
                while worklist:
                    child = worklist.pop()
                    # Skip nested loops — they'll be caught by their own
                    # top-level iteration.
                    if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                        continue
                    # Add child's sub-nodes (except nested loops)
                    for sub in ast.iter_child_nodes(child):
                        worklist.append(sub)

                    # Detect await <expr>.execute(...)
                    call_node: ast.Call | None = None
                    if isinstance(child, ast.Await) and isinstance(
                        child.value, ast.Call
                    ):
                        call_node = child.value
                    elif isinstance(child, ast.Call):
                        call_node = child
                    else:
                        continue

                    if call_node is None:
                        continue

                    func = call_node.func
                    if isinstance(func, ast.Attribute) and func.attr == "execute":
                        line_num = getattr(call_node, "lineno", 0)
                        if line_num in seen_lines:
                            continue
                        # Respect # n1-ok suppression comments
                        if 0 < line_num <= len(source_lines):
                            src_line = source_lines[line_num - 1]
                            if "n1-ok" in src_line:
                                continue
                        seen_lines.add(line_num)
                        count += 1

                        # Try to identify the loop variable
                        loop_info = ""
                        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
                            node.target, ast.Name
                        ):
                            loop_info = f" (iterating over '{node.target.id}')"

                        findings.append(
                            Finding(
                                id=f"PERF-N1-{Path(rel).stem.upper()}-L{line_num}",
                                severity="high",
                                category="n_plus_1",
                                title=f"Potential N+1: db.execute inside loop{loop_info}",
                                detail=(
                                    f"A database query (db.execute) is called inside a "
                                    f"loop at {rel}:{line_num}. This causes one query per "
                                    f"iteration instead of a single batch query."
                                ),
                                file=rel,
                                line=line_num,
                                recommendation=(
                                    "Batch the query: collect all IDs/values first, "
                                    "then execute a single query with an IN clause. "
                                    "Or use selectinload/joinedload for relationship loading."
                                ),
                                effort_hours=1.5,
                            )
                        )

    return findings, count


# ---------------------------------------------------------------------------
# Analysis: List Endpoints Without LIMIT
# ---------------------------------------------------------------------------

_SELECT_PATTERN = re.compile(r"\bselect\s*\(")
_LIMIT_PATTERN = re.compile(r"\.limit\s*\(")


def _scan_unlimited_list_endpoints(app_dir: Path) -> list[Finding]:
    """Find GET endpoints that execute select() queries without .limit()."""
    findings: list[Finding] = []

    api_dir = app_dir / "api"
    for path in _iter_py_files(api_dir):
        source = _safe_read(path)
        if not source:
            continue

        rel = str(path.relative_to(PROJECT_ROOT))
        lines = source.split("\n")

        # Find GET handler functions and check their body for select without limit
        in_get_handler = False
        handler_name = ""
        handler_start = 0
        handler_indent = 0
        handler_body: list[str] = []

        for i, line in enumerate(lines, 1):
            # Detect @router.get decorator
            if re.search(r"@router\.get\(", line):
                in_get_handler = True
                continue

            # If we just saw a GET decorator, the next def is the handler
            if in_get_handler and re.match(r"\s*(?:async\s+)?def\s+(\w+)", line):
                m = re.match(r"(\s*)(?:async\s+)?def\s+(\w+)", line)
                if m:
                    handler_indent = len(m.group(1))
                    handler_name = m.group(2)
                    handler_start = i
                    handler_body = []
                    in_get_handler = False
                    continue

            # Collect handler body lines
            if handler_name:
                stripped = line.rstrip()
                if stripped == "":
                    handler_body.append(line)
                    continue
                current_indent = len(line) - len(line.lstrip())
                if current_indent > handler_indent:
                    handler_body.append(line)
                else:
                    # Handler ended — analyze collected body
                    body_text = "\n".join(handler_body)
                    has_select = bool(_SELECT_PATTERN.search(body_text))
                    has_limit = bool(_LIMIT_PATTERN.search(body_text))

                    if has_select and not has_limit:
                        findings.append(
                            Finding(
                                id=f"PERF-NOLIMIT-{Path(rel).stem.upper()}-{handler_name.upper()}",
                                severity="medium",
                                category="no_limit",
                                title=f"GET /{handler_name} has select() without .limit()",
                                detail=(
                                    f"Handler '{handler_name}' in {rel}:{handler_start} "
                                    f"executes a select() query without a .limit() clause. "
                                    f"This can return unbounded result sets."
                                ),
                                file=rel,
                                line=handler_start,
                                recommendation=(
                                    "Add pagination with .limit() and .offset() parameters. "
                                    "Default to a reasonable page size (e.g. 50)."
                                ),
                                effort_hours=0.5,
                            )
                        )

                    handler_name = ""
                    handler_body = []

                    # Check if this line is another GET decorator
                    if re.search(r"@router\.get\(", line):
                        in_get_handler = True

        # Handle the last handler in the file
        if handler_name and handler_body:
            body_text = "\n".join(handler_body)
            has_select = bool(_SELECT_PATTERN.search(body_text))
            has_limit = bool(_LIMIT_PATTERN.search(body_text))

            if has_select and not has_limit:
                findings.append(
                    Finding(
                        id=f"PERF-NOLIMIT-{Path(rel).stem.upper()}-{handler_name.upper()}",
                        severity="medium",
                        category="no_limit",
                        title=f"GET /{handler_name} has select() without .limit()",
                        detail=(
                            f"Handler '{handler_name}' in {rel}:{handler_start} "
                            f"executes a select() query without a .limit() clause. "
                            f"This can return unbounded result sets."
                        ),
                        file=rel,
                        line=handler_start,
                        recommendation=(
                            "Add pagination with .limit() and .offset() parameters. "
                            "Default to a reasonable page size (e.g. 50)."
                        ),
                        effort_hours=0.5,
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Analysis: Test Timing
# ---------------------------------------------------------------------------


def _scan_test_timing() -> tuple[list[Finding], dict[str, Any]]:
    """Check for slow tests or parse timing data if available."""
    findings: list[Finding] = []

    # Count test files
    test_dir = PROJECT_ROOT / "tests"
    test_files = _iter_py_files(test_dir) if test_dir.exists() else []
    test_count = len(test_files)

    # Count test functions
    test_func_count = 0
    for path in test_files:
        source = _safe_read(path)
        tree = _safe_parse_ast(source, path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name.startswith("test_"):
                test_func_count += 1

    # Check for JUnit XML results
    junit_path = PROJECT_ROOT / "junit.xml"
    slow_tests: list[dict[str, Any]] = []
    if junit_path.exists():
        try:
            content = _safe_read(junit_path)
            # Simple regex parse for test case durations
            for m in re.finditer(
                r'<testcase\s+[^>]*name="([^"]+)"[^>]*time="([^"]+)"', content
            ):
                test_name = m.group(1)
                duration = float(m.group(2))
                if duration > 2.0:
                    slow_tests.append({"name": test_name, "duration": duration})
        except (ValueError, OSError):
            pass

    # Check pytest cache for lastfailed
    cache_dir = PROJECT_ROOT / ".pytest_cache"
    has_cache = cache_dir.exists()

    for slow in slow_tests:
        findings.append(
            Finding(
                id=f"PERF-SLOW-TEST-{slow['name'][:30].upper().replace(' ', '-')}",
                severity="low",
                category="slow_test",
                title=f"Slow test: {slow['name']} ({slow['duration']:.1f}s)",
                detail=(
                    f"Test '{slow['name']}' took {slow['duration']:.1f} seconds, "
                    f"exceeding the 2.0s threshold."
                ),
                recommendation="Investigate slow setup/teardown or add mocking.",
                effort_hours=0.5,
            )
        )

    metrics = {
        "test_file_count": test_count,
        "test_function_count": test_func_count,
        "slow_tests_found": len(slow_tests),
        "junit_xml_available": junit_path.exists(),
        "pytest_cache_available": has_cache,
    }
    return findings, metrics


# ---------------------------------------------------------------------------
# Analysis: Table Growth Estimation
# ---------------------------------------------------------------------------

# Estimated rows per user per year by table category
_GROWTH_ESTIMATES = {
    "contacts": 500,  # average LinkedIn CSV
    "warm_scores": 500,  # one per contact
    "match_results": 200,  # from searches
    "search_requests": 50,  # ~1/week
    "usage_logs": 2000,  # high-frequency tracking
    "credit_transactions": 100,
    "marketplace_listings": 200,  # subset of contacts
    "intro_facilitations": 20,
    "audit_logs": 300,  # security events
    "applications": 50,
    "csv_uploads": 5,
    "companies": 100,  # shared/deduplicated
    "enrichment_cache": 200,
    "memories": 500,  # agent scans + session indexing + manual saves (shared, not per-user)
}


def _scan_table_growth(models_dir: Path) -> tuple[list[Finding], dict[str, Any]]:
    """Estimate table sizes at various user counts."""
    findings: list[Finding] = []

    # Count model classes
    model_count = 0
    table_names: list[str] = []

    for path in _iter_py_files(models_dir):
        source = _safe_read(path)
        tree = _safe_parse_ast(source, path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if (
                                isinstance(target, ast.Name)
                                and target.id == "__tablename__"
                            ):
                                model_count += 1
                                if isinstance(item.value, ast.Constant):
                                    table_names.append(str(item.value.value))

    # Project growth
    projections: dict[str, dict[str, int]] = {}
    large_tables: list[str] = []

    for table in table_names:
        rows_per_user_year = _GROWTH_ESTIMATES.get(table, 50)
        proj = {
            "rows_100_users": rows_per_user_year * 100,
            "rows_1k_users": rows_per_user_year * 1_000,
            "rows_10k_users": rows_per_user_year * 10_000,
        }
        projections[table] = proj

        if proj["rows_10k_users"] > 5_000_000:
            large_tables.append(table)

    for table in large_tables:
        proj = projections[table]
        findings.append(
            Finding(
                id=f"PERF-GROWTH-{table.upper()}",
                severity="medium" if proj["rows_10k_users"] > 10_000_000 else "low",
                category="table_growth",
                title=f"Table '{table}' projected to exceed 5M rows at 10K users",
                detail=(
                    f"Projected rows — 100 users: {proj['rows_100_users']:,}, "
                    f"1K users: {proj['rows_1k_users']:,}, "
                    f"10K users: {proj['rows_10k_users']:,}. "
                    f"Consider partitioning, archival, or retention policies."
                ),
                recommendation=(
                    f"Add a data retention policy for '{table}'. "
                    f"Consider time-based partitioning or periodic archival."
                ),
                effort_hours=3.0,
            )
        )

    # Check if usage_logs has retention
    retention_check = False
    retention_files = _iter_py_files(PROJECT_ROOT / "app" / "services")
    for path in retention_files:
        source = _safe_read(path)
        if "usage_log" in source.lower() and (
            "delete" in source.lower()
            or "retention" in source.lower()
            or "cleanup" in source.lower()
            or "purge" in source.lower()
        ):
            retention_check = True
            break

    if not retention_check and "usage_logs" in table_names:
        findings.append(
            Finding(
                id="PERF-RETENTION-USAGE-LOGS",
                severity="medium",
                category="data_retention",
                title="No retention/cleanup policy detected for usage_logs",
                detail=(
                    "usage_logs is a high-write table (~2000 rows/user/year) "
                    "but no deletion or archival logic was found in services."
                ),
                recommendation=(
                    "Add a scheduled task to archive or delete usage_logs older "
                    "than 90 days. Keep aggregated summaries for analytics."
                ),
                effort_hours=2.0,
            )
        )

    metrics = {
        "model_count": model_count,
        "tables_detected": len(table_names),
        "tables_over_5m_at_10k": len(large_tables),
        "usage_logs_retention_found": retention_check,
    }
    return findings, metrics


# ---------------------------------------------------------------------------
# Analysis: Production Health Check
# ---------------------------------------------------------------------------


def _scan_production_health() -> tuple[list[Finding], dict[str, Any]]:
    """Hit the production /health endpoint and report status."""
    findings: list[Finding] = []
    metrics: dict[str, Any] = {}

    try:
        from agents.shared.api_client import check_health

        status = check_health()
        metrics["production_healthy"] = status.healthy
        metrics["production_status_code"] = status.status_code
        metrics["production_response_ms"] = round(status.response_ms, 1)

        if not status.healthy:
            findings.append(
                Finding(
                    id="PERF-PROD-UNHEALTHY",
                    severity="critical",
                    category="production_health",
                    title=f"Production health check failed (HTTP {status.status_code})",
                    detail=(
                        f"The /health endpoint returned status {status.status_code} "
                        f"(response time: {status.response_ms:.0f}ms). "
                        f"The production service may be down or degraded."
                    ),
                    recommendation=(
                        "Check Railway deployment logs. Verify the service is running "
                        "and database connections are healthy."
                    ),
                    effort_hours=0.5,
                )
            )
        elif status.response_ms > 2000:
            findings.append(
                Finding(
                    id="PERF-PROD-SLOW",
                    severity="high",
                    category="production_health",
                    title=f"Production response slow ({status.response_ms:.0f}ms)",
                    detail=(
                        f"The /health endpoint responded in {status.response_ms:.0f}ms "
                        f"which exceeds the 2000ms threshold. The service may be "
                        f"under load or experiencing connection pool exhaustion."
                    ),
                    recommendation=(
                        "Check database connection pool settings and Railway metrics. "
                        "Consider scaling the service if load is high."
                    ),
                    effort_hours=1.0,
                )
            )
        elif status.response_ms > 500:
            findings.append(
                Finding(
                    id="PERF-PROD-LATENCY",
                    severity="medium",
                    category="production_health",
                    title=f"Production latency elevated ({status.response_ms:.0f}ms)",
                    detail=(
                        f"The /health endpoint responded in {status.response_ms:.0f}ms "
                        f"(>500ms). This may indicate cold start or mild resource "
                        f"contention."
                    ),
                    recommendation="Monitor over multiple scans to confirm trend.",
                    effort_hours=0.5,
                )
            )
    except ImportError:
        metrics["production_health_skipped"] = "api_client not available"
    except Exception as exc:
        logger.warning("Production health check failed: %s", exc)
        metrics["production_health_error"] = str(exc)

    return findings, metrics


# ---------------------------------------------------------------------------
# Main scan entrypoint
# ---------------------------------------------------------------------------


def scan() -> AgentReport:
    """Run all performance analyses and return consolidated report."""
    start = time.time()
    all_findings: list[Finding] = []
    all_metrics: dict[str, Any] = {}
    learning_updates: list[str] = []

    app_dir = PROJECT_ROOT / "app"
    models_dir = app_dir / "models"

    # 1. AI Token Cost Estimation
    try:
        ai_findings, ai_metrics = _scan_ai_token_costs(app_dir)
        all_findings.extend(ai_findings)
        all_metrics.update(ai_metrics)
    except Exception as e:
        logger.error("AI token cost scan failed: %s", e)
        all_metrics["ai_scan_error"] = str(e)

    # 2. Database Index Check
    try:
        indexed = _extract_indexed_columns(models_dir)
        idx_findings, idx_metrics = _scan_missing_indexes(app_dir, indexed)
        all_findings.extend(idx_findings)
        all_metrics.update(idx_metrics)
    except Exception as e:
        logger.error("Index scan failed: %s", e)
        all_metrics["index_scan_error"] = str(e)

    # 3. N+1 Query Patterns
    try:
        n1_findings, n1_count = _scan_n_plus_one(app_dir)
        all_findings.extend(n1_findings)
        all_metrics["n_plus_1_patterns"] = n1_count
    except Exception as e:
        logger.error("N+1 scan failed: %s", e)
        all_metrics["n1_scan_error"] = str(e)

    # 4. List Endpoints Without LIMIT
    try:
        limit_findings = _scan_unlimited_list_endpoints(app_dir)
        all_findings.extend(limit_findings)
        all_metrics["unlimited_list_endpoints"] = len(limit_findings)
    except Exception as e:
        logger.error("Limit scan failed: %s", e)
        all_metrics["limit_scan_error"] = str(e)

    # 5. Test Timing
    try:
        test_findings, test_metrics = _scan_test_timing()
        all_findings.extend(test_findings)
        all_metrics.update(test_metrics)
    except Exception as e:
        logger.error("Test timing scan failed: %s", e)
        all_metrics["test_scan_error"] = str(e)

    # 6. Table Growth Estimation
    try:
        growth_findings, growth_metrics = _scan_table_growth(models_dir)
        all_findings.extend(growth_findings)
        all_metrics.update(growth_metrics)
    except Exception as e:
        logger.error("Growth scan failed: %s", e)
        all_metrics["growth_scan_error"] = str(e)

    # 7. Production Health Check
    try:
        health_findings, health_metrics = _scan_production_health()
        all_findings.extend(health_findings)
        all_metrics.update(health_metrics)
    except Exception as e:
        logger.error("Production health check failed: %s", e)
        all_metrics["production_health_error"] = str(e)

    # ---------------------------------------------------------------------------
    # Self-learning: record findings and update attention weights
    # ---------------------------------------------------------------------------
    try:
        # Record each finding
        for f in all_findings:
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

        # Update attention weights based on findings per file
        file_counts: dict[str, int] = {}
        for f in all_findings:
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1
        if file_counts:
            learning.update_attention_weights(AGENT_NAME, file_counts)

        # Record scan metrics for trend analysis
        learning.record_scan(
            AGENT_NAME,
            {
                "ai_calls_found": all_metrics.get("ai_calls_found", 0),
                "estimated_monthly_cost_100_users": all_metrics.get(
                    "estimated_monthly_cost_100_users", 0
                ),
                "n_plus_1_patterns": all_metrics.get("n_plus_1_patterns", 0),
                "indexed_columns": all_metrics.get("indexed_columns", 0),
                "unindexed_query_columns": all_metrics.get(
                    "unindexed_query_columns", 0
                ),
                "total_findings": len(all_findings),
            },
        )

        # Check trends
        cost_trend = learning.get_trend(AGENT_NAME, "estimated_monthly_cost_100_users")
        if cost_trend == "up":
            learning_updates.append(
                "AI cost trend is UP — new prompts or increased max_tokens detected."
            )
        elif cost_trend == "down":
            learning_updates.append(
                "AI cost trend is DOWN — optimization efforts are working."
            )

        n1_trend = learning.get_trend(AGENT_NAME, "n_plus_1_patterns")
        if n1_trend == "up":
            learning_updates.append(
                "N+1 pattern count is INCREASING — review recent service changes."
            )

        total_scans = learning.get_total_scans(AGENT_NAME)
        learning_updates.append(f"Total scans completed: {total_scans}")

    except Exception as e:
        logger.error("Learning update failed: %s", e)
        learning_updates.append(f"Learning update error: {e}")

    elapsed = time.time() - start

    return AgentReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=all_findings,
        metrics=all_metrics,
        learning_updates=learning_updates,
    )
