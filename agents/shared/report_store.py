"""Redis-backed scan report storage.

Provides persistence for agent scan reports so that Railway Cron scans
(which run in ephemeral containers) can store reports that persist
across container restarts. Falls back to filesystem when Redis is
unavailable (local dev).

Key scheme: scan_report:{team}:{agent}_latest
TTL: 7 days (reports refresh daily, 7d gives margin for outages)
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "scan_report"
_REPORT_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Team name mapping: directory name → display name used in keys
_TEAM_DIRS = [
    "agents",
    "data_team",
    "product_team",
    "ops_team",
    "finance_team",
    "gtm_team",
    "agents/chief_of_staff",
]


def _get_sync_redis():
    """Get a sync Redis client, or None if unavailable."""
    try:
        import redis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, decode_responses=True, socket_timeout=5)
        client.ping()
        return client
    except Exception:
        logger.debug("Redis not available for report store")
        return None


def publish_report(team: str, agent_name: str, report_json: str) -> bool:
    """Publish a report to Redis. Returns True on success."""
    client = _get_sync_redis()
    if client is None:
        return False
    try:
        key = f"{_REDIS_KEY_PREFIX}:{team}:{agent_name}_latest"
        client.set(key, report_json, ex=_REPORT_TTL_SECONDS)
        logger.debug("Published report to Redis: %s", key)
        return True
    except Exception:
        logger.debug("Failed to publish report to Redis", exc_info=True)
        return False


def list_reports_from_redis() -> list[dict[str, Any]] | None:
    """List all reports from Redis. Returns None if Redis unavailable."""
    client = _get_sync_redis()
    if client is None:
        return None
    try:
        keys = client.keys(f"{_REDIS_KEY_PREFIX}:*_latest")
        reports = []
        for key in sorted(keys):
            # key format: scan_report:{team}:{agent}_latest
            parts = key.removeprefix(f"{_REDIS_KEY_PREFIX}:").rsplit(":", 1)
            if len(parts) != 2:
                continue
            team = parts[0]
            filename = parts[1] + ".json"  # e.g. "perf_monitor_latest.json"
            content = client.get(key)
            if content:
                reports.append(
                    {
                        "team": team,
                        "filename": filename,
                        "size_bytes": len(content),
                        "modified": _extract_timestamp(content),
                        "source": "redis",
                    }
                )
        return reports if reports else None
    except Exception:
        logger.debug("Failed to list reports from Redis", exc_info=True)
        return None


def read_report_from_redis(team: str, filename: str) -> dict[str, Any] | None:
    """Read a specific report from Redis. Returns None if not found."""
    client = _get_sync_redis()
    if client is None:
        return None
    try:
        # Convert filename back to key: "perf_monitor_latest.json" → "perf_monitor_latest"
        agent_key = (
            filename.removesuffix(".json").removesuffix(".md").removesuffix(".txt")
        )
        key = f"{_REDIS_KEY_PREFIX}:{team}:{agent_key}"
        content = client.get(key)
        if content is None:
            return None
        return {
            "team": team,
            "filename": filename,
            "content": content,
            "size_bytes": len(content),
            "source": "redis",
        }
    except Exception:
        logger.debug("Failed to read report from Redis", exc_info=True)
        return None


def load_all_reports_from_redis() -> list[dict] | None:
    """Load all report contents from Redis as parsed dicts.

    Used by CoS _load_reports() for daily brief generation.
    Returns None if Redis unavailable or empty.
    """
    client = _get_sync_redis()
    if client is None:
        return None
    try:
        keys = client.keys(f"{_REDIS_KEY_PREFIX}:*_latest")
        if not keys:
            return None
        reports = []
        for key in sorted(keys):
            content = client.get(key)
            if not content:
                continue
            try:
                data = json.loads(content)
                # Tag with team for downstream processing
                parts = key.removeprefix(f"{_REDIS_KEY_PREFIX}:").rsplit(":", 1)
                if len(parts) == 2:
                    data["_team"] = parts[0]
                reports.append(data)
            except json.JSONDecodeError:
                continue
        return reports if reports else None
    except Exception:
        logger.debug("Failed to load reports from Redis", exc_info=True)
        return None


def _extract_timestamp(content: str) -> float:
    """Extract timestamp from report JSON for sorting."""
    try:
        data = json.loads(content)
        ts = data.get("timestamp", "")
        if ts:
            from datetime import datetime

            return datetime.fromisoformat(ts).timestamp()
    except Exception:
        pass
    return 0.0
