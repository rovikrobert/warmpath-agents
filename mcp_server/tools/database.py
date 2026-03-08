"""Database tools — query templates, raw SQL, schema introspection."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect

from mcp_server.server import mcp

logger = logging.getLogger(__name__)

_data_executor = None
_finance_executor = None


def _get_data_executor():
    global _data_executor
    if _data_executor is None:
        from data_team.shared.query_executor import get_executor

        _data_executor = get_executor()
    return _data_executor


def _get_finance_executor():
    global _finance_executor
    if _finance_executor is None:
        from finance_team.shared.query_executor import FinanceQueryExecutor

        _finance_executor = FinanceQueryExecutor()
    return _finance_executor


def _get_engine():
    """Return sync SQLAlchemy engine, or None."""
    try:
        qe = _get_data_executor()
        return qe._engine if qe.is_available() else None
    except Exception:
        return None


@mcp.tool(
    name="list_templates",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def list_templates() -> list[dict[str, str]]:
    """List all available SQL query templates (data team + finance team).

    Returns template names and which team they belong to.
    Use these names with the query_template tool.

    Returns:
        List of {"name": str, "source": str} dicts.
    """
    from data_team.shared.sql_templates import ALL_TEMPLATES
    from finance_team.shared.sql_templates import FINANCE_TEMPLATES

    result = []
    for name in sorted(ALL_TEMPLATES):
        result.append({"name": name, "source": "data_team"})
    for name in sorted(FINANCE_TEMPLATES):
        result.append({"name": name, "source": "finance_team"})
    return result


@mcp.tool(
    name="query_template",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def query_template(
    name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a named SQL template with optional parameters.

    Templates are pre-approved, privacy-validated queries. Use list_templates
    to see available names. Common params: start_date, end_date, user_id.

    Returns:
        {"template": str, "rows": list[dict], "count": int} on success.
        {"error": str} on failure.
    """
    from data_team.shared.sql_templates import ALL_TEMPLATES
    from finance_team.shared.sql_templates import FINANCE_TEMPLATES

    params = params or {}

    if name in ALL_TEMPLATES:
        qe = _get_data_executor()
        if not qe.is_available():
            return {
                "error": "Database unavailable (DATABASE_URL not set or unreachable)"
            }
        rows = qe.execute_template(name, params)
        return {"template": name, "rows": rows, "count": len(rows)}

    if name in FINANCE_TEMPLATES:
        fqe = _get_finance_executor()
        if not fqe.is_available():
            return {
                "error": "Database unavailable (DATABASE_URL not set or unreachable)"
            }
        rows = fqe.query_template(name, params)
        return {"template": name, "rows": rows, "count": len(rows)}

    return {
        "error": f"Unknown template: {name}. Use list_templates to see available names."
    }


@mcp.tool(
    name="query_sql",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def query_sql(
    sql: str,
    params: dict[str, Any] | None = None,
    context: str = "mcp_query",
) -> dict[str, Any]:
    """Execute raw SQL with privacy validation.

    All queries are validated by PrivacyGuard before execution:
    - PII columns (email, name, etc.) blocked in SELECT
    - k-anonymity enforced on GROUP BY (HAVING COUNT >= 5)
    - Vault tables require user_id scoping
    - Cross-vault JOINs rejected without consent gates
    - Audit logs are immutable (no UPDATE/DELETE)

    Use parameterized queries with :param_name placeholders.

    Returns:
        {"rows": list[dict], "count": int} on success.
        {"error": str} on failure.
    """
    from data_team.shared.privacy_guard import PrivacyViolation

    qe = _get_data_executor()
    if not qe.is_available():
        return {"error": "Database unavailable (DATABASE_URL not set or unreachable)"}

    try:
        rows = qe.execute_sql(sql, params or {}, context=context)
        return {"rows": rows, "count": len(rows)}
    except PrivacyViolation as exc:
        return {
            "error": f"Privacy violation: {exc}",
            "violation_type": exc.violation_type,
            "privy_category": exc.privy_category,
        }
    except Exception as exc:
        return {"error": f"Query failed: {exc}"}


@mcp.tool(
    name="get_schema",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def get_schema(table_name: str | None = None) -> dict[str, Any]:
    """Introspect database schema — list tables, columns, types.

    If table_name is provided, returns columns for that table only.
    Otherwise returns all tables with their columns.

    Returns:
        {"tables": list[dict], "table_count": int} on success.
        {"error": str} on failure.
    """
    engine = _get_engine()
    if engine is None:
        return {"error": "Database unavailable (DATABASE_URL not set or unreachable)"}

    try:
        inspector = sa_inspect(engine)
        table_names = [table_name] if table_name else inspector.get_table_names()

        tables = []
        for tname in table_names:
            columns = []
            for col in inspector.get_columns(tname):
                columns.append(
                    {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                    }
                )
            tables.append(
                {"name": tname, "columns": columns, "column_count": len(columns)}
            )

        return {"tables": tables, "table_count": len(tables)}
    except Exception as exc:
        return {"error": f"Schema introspection failed: {exc}"}
