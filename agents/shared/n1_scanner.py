"""Shared N+1 query detector — AST-based scanner used by both perf_monitor and architect.

Detects database calls (execute, scalar, etc.) inside for/while loops.
Supports `# n1-ok` inline suppression for intentional batch pagination.

Finding IDs are location-specific: `{prefix}-{FILE_STEM}-L{LINE}` for stable
dedup against the resolved registry.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from agents.shared.report import Finding

logger = logging.getLogger(__name__)

# Methods on db/session objects that hit the database
DB_SESSION_METHODS = {
    "execute",
    "scalar",
    "scalar_one_or_none",
    "fetch_one",
    "fetch_all",
}

# Known async service functions whose names imply a DB round-trip
DB_SERVICE_FUNCS = {
    "check_suppression",
    "get_board_by_key",
    "get_user_credits",
    "get_credit_balance",
}

# Variable name suffixes that indicate an in-memory lookup structure
_SAFE_RECEIVER_SUFFIXES = (
    "_map",
    "_dict",
    "_cache",
    "_counts",
    "_lookup",
    "_index",
)

_DB_NAMES = {"db", "session", "database", "conn", "connection"}


def _is_db_receiver(node: ast.expr) -> bool:
    """Return True if *node* looks like a DB session variable."""
    if isinstance(node, ast.Name):
        return node.id in _DB_NAMES
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr.lstrip("_") in _DB_NAMES
    )


def scan_n_plus_one(
    py_files: list[Path],
    *,
    id_prefix: str = "N1",
    require_await: bool = False,
) -> list[Finding]:
    """Detect DB calls inside for/while loops across the given files.

    Args:
        py_files: Python files to scan.
        id_prefix: Prefix for finding IDs (e.g. "PERF-N1" or "ARCH-N+1").
        require_await: If True, only flag awaited calls (async patterns).
            If False, flag both sync and async calls.

    Returns:
        List of N+1 findings with location-specific IDs.
    """
    findings: list[Finding] = []

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        rel_path = str(path)
        source_lines = source.splitlines() if source else []
        seen_lines: set[int] = set()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                continue

            # Skip FastAPI DI pattern: `async for db in get_db()`
            if (
                isinstance(node, ast.AsyncFor)
                and isinstance(node.target, ast.Name)
                and node.target.id in _DB_NAMES
            ):
                continue

            # Collect iterator expression lines (safe — not in loop body)
            iter_lines: set[int] = set()
            if isinstance(node, (ast.For, ast.AsyncFor)) and node.iter:
                for iter_child in ast.walk(node.iter):
                    if hasattr(iter_child, "lineno"):
                        iter_lines.add(iter_child.lineno)

            # Walk loop body looking for DB calls
            body_nodes = list(node.body) + list(getattr(node, "orelse", []))
            found = False
            for body_stmt in body_nodes:
                if found:
                    break
                for child in ast.walk(body_stmt):
                    if found:
                        break

                    # Determine the call node
                    call_node: ast.Call | None = None
                    label: str | None = None

                    if isinstance(child, ast.Await) and isinstance(
                        child.value, ast.Call
                    ):
                        call_node = child.value
                    elif not require_await and isinstance(child, ast.Call):
                        call_node = child
                    else:
                        continue

                    if call_node is None:
                        continue

                    func = call_node.func

                    # Pattern 1: <obj>.<method>(...)
                    if isinstance(func, ast.Attribute):
                        method_name = func.attr

                        # Skip iterator-line calls
                        call_line = getattr(child, "lineno", 0)
                        if call_line in iter_lines:
                            continue

                        # Skip .get() on in-memory lookups
                        if (
                            method_name == "get"
                            and isinstance(func.value, ast.Name)
                            and any(
                                func.value.id.endswith(s)
                                for s in _SAFE_RECEIVER_SUFFIXES
                            )
                        ):
                            continue

                        # For .get(), require a DB-like receiver
                        if method_name == "get" and not _is_db_receiver(func.value):
                            continue

                        if method_name in DB_SESSION_METHODS:
                            label = method_name
                        elif method_name == "get" and _is_db_receiver(func.value):
                            label = "get"
                        else:
                            continue

                    # Pattern 2: <known_service_func>(...)
                    elif isinstance(func, ast.Name) and func.id in DB_SERVICE_FUNCS:
                        label = func.id
                    else:
                        continue

                    # Check suppression comment
                    call_line = getattr(child, "lineno", 0)
                    if call_line in seen_lines:
                        continue
                    if (
                        0 < call_line <= len(source_lines)
                        and "n1-ok" in source_lines[call_line - 1]
                    ):
                        continue

                    seen_lines.add(call_line)

                    # Extract loop variable for better messages
                    loop_info = ""
                    if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
                        node.target, ast.Name
                    ):
                        loop_info = f" (iterating over '{node.target.id}')"

                    file_stem = path.stem.upper()
                    findings.append(
                        Finding(
                            id=f"{id_prefix}-{file_stem}-L{call_line}",
                            severity="high",
                            category="n_plus_1",
                            title=f"Potential N+1: {label}() inside loop{loop_info}",
                            detail=(
                                f"DB call `{label}()` inside a loop at "
                                f"`{rel_path}:{call_line}`. This causes one query "
                                f"per iteration instead of a single batch query."
                            ),
                            file=rel_path,
                            line=call_line,
                            recommendation=(
                                "Batch the query: collect all IDs/values first, "
                                "then execute a single query with an IN clause. "
                                "Or use selectinload/joinedload for relationship loading."
                            ),
                            effort_hours=1.0,
                        )
                    )
                    found = True  # One finding per loop

    return findings
