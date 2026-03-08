"""Health & infrastructure tools — service status, Redis, Celery."""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp_server.server import mcp

logger = logging.getLogger(__name__)


def _check_health_impl():
    from agents.shared.api_client import check_health as _impl

    return _impl()


def _get_redis_client():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
    except Exception as exc:
        logger.warning("Redis client creation failed: %s", exc)
        return None


def _check_db() -> dict[str, Any]:
    try:
        from data_team.shared.query_executor import get_executor

        qe = get_executor()
        if qe.is_available():
            return {"status": "ok"}
        return {
            "status": "unavailable",
            "reason": "DATABASE_URL not set or unreachable",
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _check_redis() -> dict[str, Any]:
    client = _get_redis_client()
    if client is None:
        return {"status": "unavailable", "reason": "REDIS_URL not set"}
    try:
        client.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    finally:
        client.close()


def _check_celery() -> dict[str, Any]:
    try:
        from app.celery_app import celery_app

        response = celery_app.control.ping(timeout=2.0)
        worker_count = len(response) if response else 0
        if worker_count > 0:
            return {"status": "ok", "workers": worker_count}
        return {"status": "no_workers", "workers": 0}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _check_alembic() -> dict[str, Any]:
    try:
        from data_team.shared.query_executor import get_executor

        qe = get_executor()
        if not qe.is_available():
            return {"status": "unavailable"}
        rows = qe.execute_sql(
            "SELECT version_num FROM alembic_version LIMIT 1",
            context="mcp_alembic_check",
        )
        if rows:
            return {"status": "ok", "head": rows[0]["version_num"]}
        return {"status": "no_migrations"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


@mcp.tool(
    name="check_health",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def check_health() -> dict[str, Any]:
    """Hit the production /health endpoint and return status + response time.

    Returns:
        {"healthy": bool, "status_code": int, "response_ms": float}.
    """
    status = _check_health_impl()
    return {
        "healthy": status.healthy,
        "status_code": status.status_code,
        "response_ms": status.response_ms,
    }


@mcp.tool(
    name="check_services",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def check_services() -> dict[str, Any]:
    """Aggregated health check across all backend services.

    Checks: database connection, Redis ping, Celery worker count,
    latest Alembic migration revision.

    Returns:
        {"database": dict, "redis": dict, "celery": dict, "alembic": dict}.
    """
    return {
        "database": _check_db(),
        "redis": _check_redis(),
        "celery": _check_celery(),
        "alembic": _check_alembic(),
    }


@mcp.tool(
    name="redis_info",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def redis_info() -> dict[str, Any]:
    """Redis server info — memory, clients, queue depth, key count.

    Returns:
        {"connected": bool, "memory": str, "celery_queues": dict, ...} on success.
        {"error": str} on failure.
    """
    client = _get_redis_client()
    if client is None:
        return {"error": "Redis unavailable (REDIS_URL not set)"}

    try:
        client.ping()
        info = client.info(section="memory")
        clients_info = client.info(section="clients")
        keyspace = client.info(section="keyspace")

        queues = {}
        for queue_name in ["celery", "csv_processing", "email", "feed"]:
            try:
                queues[queue_name] = client.llen(queue_name)
            except Exception:
                queues[queue_name] = -1

        return {
            "connected": True,
            "memory": info.get("used_memory_human", "unknown"),
            "memory_peak": info.get("used_memory_peak_human", "unknown"),
            "connected_clients": clients_info.get("connected_clients", 0),
            "keyspace": keyspace,
            "celery_queues": queues,
        }
    except Exception as exc:
        return {"error": f"Redis query failed: {exc}"}
    finally:
        client.close()
