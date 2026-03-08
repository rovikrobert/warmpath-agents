"""Redis Stream helpers for cto:events — the shared event bus.

All autonomous actions publish here. CoS subscribes for daily briefs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


STREAM_KEY = "cto:events"
REQUEST_STREAM_KEY = "cto:requests"


def format_event(
    team: str,
    agent: str,
    finding_id: str = "",
    tier: str = "",
    action: str = "",
    detail: str = "",
    pr_url: str = "",
) -> dict[str, str]:
    """Format an event for the cto:events stream."""
    return {
        "team": team,
        "agent": agent,
        "finding_id": finding_id,
        "tier": tier,
        "action": action,
        "detail": detail,
        "pr_url": pr_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def parse_event(raw: dict[bytes, bytes]) -> dict[str, str]:
    """Parse a raw Redis stream entry (bytes) to str dict."""
    return {
        k.decode() if isinstance(k, bytes) else k: v.decode()
        if isinstance(v, bytes)
        else v
        for k, v in raw.items()
    }


def get_recent_events(
    redis_client: Any,
    count: int = 50,
    since: str | None = None,
) -> list[dict[str, str]]:
    """Read recent events from cto:events stream."""
    try:
        start = since if since else "+"
        end = "-"
        entries = redis_client.xrevrange(STREAM_KEY, max=start, min=end, count=count)
        return [parse_event(entry[1]) for entry in entries]
    except Exception:
        return []
