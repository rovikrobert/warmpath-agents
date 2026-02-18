"""Cross-team shared intelligence broadcast.

When an agent discovers a pattern, insight, or resolution, it can broadcast it
here so other teams can benefit without duplicating work.

File-based storage at agents/shared/shared_insights.json. Each team reads this
during scan initialization.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SHARED_FILE = Path(__file__).resolve().parent / "shared_insights.json"
MAX_INSIGHTS = 200  # Keep the file bounded
INSIGHT_TTL_HOURS = 168  # 7 days


def _load() -> list[dict]:
    if not _SHARED_FILE.exists():
        return []
    try:
        return json.loads(_SHARED_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(insights: list[dict]) -> None:
    _SHARED_FILE.write_text(json.dumps(insights, indent=2, default=str))


def _prune(insights: list[dict]) -> list[dict]:
    """Remove expired insights and cap at MAX_INSIGHTS."""
    now = datetime.now(timezone.utc)
    valid = []
    for item in insights:
        try:
            ts = datetime.fromisoformat(item["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours <= INSIGHT_TTL_HOURS:
                valid.append(item)
        except (KeyError, ValueError):
            continue
    return valid[-MAX_INSIGHTS:]


def broadcast_insight(
    team: str,
    agent: str,
    insight_id: str,
    category: str,
    title: str,
    evidence: str = "",
    severity: str = "info",
) -> None:
    """Broadcast an insight for other teams to consume."""
    insights = _load()
    # Deduplicate by insight_id
    insights = [i for i in insights if i.get("insight_id") != insight_id]
    insights.append(
        {
            "team": team,
            "agent": agent,
            "insight_id": insight_id,
            "category": category,
            "title": title,
            "evidence": evidence,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    insights = _prune(insights)
    _save(insights)


def get_shared_insights(
    since_hours: int = 24,
    exclude_team: str | None = None,
    categories: list[str] | None = None,
) -> list[dict]:
    """Read recent cross-team insights, optionally filtering by team/category."""
    insights = _load()
    now = datetime.now(timezone.utc)
    results = []
    for item in insights:
        try:
            ts = datetime.fromisoformat(item["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours > since_hours:
                continue
        except (KeyError, ValueError):
            continue
        if exclude_team and item.get("team") == exclude_team:
            continue
        if categories and item.get("category") not in categories:
            continue
        results.append(item)
    return results


def get_insight_summary() -> dict:
    """Summary stats for operational health monitoring."""
    insights = _load()
    insights = _prune(insights)
    teams_contributing = {i.get("team") for i in insights if i.get("team")}
    return {
        "total_shared_insights": len(insights),
        "teams_contributing": sorted(teams_contributing),
        "categories": sorted(
            {i.get("category", "") for i in insights if i.get("category")}
        ),
    }
