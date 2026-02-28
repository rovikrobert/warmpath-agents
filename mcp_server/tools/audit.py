"""Audit & observability tools — audit logs, enrichment stats, privacy trail."""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.server import mcp

logger = logging.getLogger(__name__)

_data_executor = None
_guard = None


def _get_data_executor():
    global _data_executor
    if _data_executor is None:
        from data_team.shared.query_executor import get_executor

        _data_executor = get_executor()
    return _data_executor


def _get_guard():
    global _guard
    if _guard is None:
        from data_team.shared.privacy_guard import guard

        _guard = guard
    return _guard


@mcp.tool()
def query_audit_log(
    action: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search audit_logs table — append-only security log.

    Optional filters: action type. No PII in output.
    Audit logs are immutable — this is read-only.
    """
    qe = _get_data_executor()
    if not qe.is_available():
        return {"error": "Database unavailable"}

    sql = "SELECT action, COUNT(*) AS count FROM audit_logs"
    conditions = []
    params: dict[str, Any] = {}

    if action:
        conditions.append("action = :action")
        params["action"] = action

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " GROUP BY action HAVING COUNT(*) >= 5"
    sql += f" ORDER BY count DESC LIMIT {int(limit)}"

    try:
        rows = qe.execute_sql(sql, params, context="mcp_audit_log")
        return {"rows": rows, "count": len(rows)}
    except Exception as exc:
        return {"error": f"Audit log query failed: {exc}"}


@mcp.tool()
def enrichment_stats() -> dict[str, Any]:
    """Enrichment cache statistics — contacts by enrichment status.

    Shows how many contacts have relationship_type, would_refer,
    and other enrichment signals filled in.
    """
    qe = _get_data_executor()
    if not qe.is_available():
        return {"error": "Database unavailable"}

    sql = """
    SELECT
        COUNT(*) AS total_contacts,
        COUNT(CASE WHEN relationship_type IS NOT NULL THEN 1 END) AS has_relationship_type,
        COUNT(CASE WHEN would_refer IS NOT NULL THEN 1 END) AS has_would_refer
    FROM contacts
    WHERE user_id IS NOT NULL
    """

    try:
        rows = qe.execute_sql(sql, context="mcp_enrichment_stats")
        return {"rows": rows, "count": len(rows)}
    except Exception as exc:
        return {"error": f"Enrichment stats query failed: {exc}"}


@mcp.tool()
def privacy_audit_log(limit: int = 100) -> dict[str, Any]:
    """View PrivacyGuard's in-memory query audit trail.

    Shows the last N validated queries with timestamps, agent names,
    and SQL previews. Useful for debugging privacy violations.
    """
    guard = _get_guard()
    entries = guard.get_audit_log()
    entries = entries[-limit:]
    return {"entries": entries, "total": len(entries)}
