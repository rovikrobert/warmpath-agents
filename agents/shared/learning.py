"""Self-learning system — track findings history, patterns, attention weights."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.shared.config import AGENTS_DIR

logger = logging.getLogger(__name__)


def _state_path(agent: str) -> Path:
    return AGENTS_DIR / agent / "state.json"


def _load_state(agent: str) -> dict:
    path = _state_path(agent)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt state for %s, resetting", agent)
    return {
        "last_scan": None,
        "total_scans": 0,
        "finding_history": [],
        "attention_weights": {},
        "metrics_history": [],
        "resolutions": {},
    }


def _save_state(agent: str, state: dict) -> None:
    path = _state_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_finding(agent: str, finding_dict: dict) -> None:
    """Append a finding to the agent's history."""
    state = _load_state(agent)
    entry = {
        "id": finding_dict.get("id"),
        "severity": finding_dict.get("severity"),
        "category": finding_dict.get("category"),
        "file": finding_dict.get("file"),
        "line": finding_dict.get("line"),
        "title": finding_dict.get("title"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    state["finding_history"].append(entry)
    # Keep last 500 entries
    state["finding_history"] = state["finding_history"][-500:]
    _save_state(agent, state)


def get_recurrence_count(agent: str, category: str, file: str | None = None) -> int:
    """How many times has this type of issue appeared historically?"""
    state = _load_state(agent)
    count = 0
    for h in state["finding_history"]:
        if h.get("category") == category:
            if file is None or h.get("file") == file:
                count += 1
    return count


def get_trend(agent: str, metric: str, window_days: int = 30) -> str:
    """Return 'up', 'down', or 'stable' for a metric over the window."""
    state = _load_state(agent)
    history = state.get("metrics_history", [])
    if len(history) < 2:
        return "insufficient_data"

    # Filter to window
    now = datetime.now(timezone.utc)
    recent = []
    for entry in history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            diff = (now - ts).days
            if diff <= window_days and metric in entry.get("metrics", {}):
                recent.append(entry["metrics"][metric])
        except (KeyError, ValueError):
            continue

    if len(recent) < 2:
        return "insufficient_data"

    first_half = sum(recent[: len(recent) // 2]) / max(1, len(recent) // 2)
    second_half = sum(recent[len(recent) // 2 :]) / max(
        1, len(recent) - len(recent) // 2
    )

    if second_half > first_half * 1.1:
        return "up"
    elif second_half < first_half * 0.9:
        return "down"
    return "stable"


def update_attention_weights(agent: str, file_findings: dict[str, int]) -> None:
    """Files with more findings get higher attention weight."""
    state = _load_state(agent)
    weights = state.get("attention_weights", {})
    for filepath, count in file_findings.items():
        current = weights.get(filepath, 1.0)
        # Exponential moving average
        weights[filepath] = round(current * 0.7 + (1.0 + count * 0.3) * 0.3, 2)
    state["attention_weights"] = weights
    _save_state(agent, state)


def get_attention_weights(agent: str) -> dict[str, float]:
    """Return current attention weights."""
    state = _load_state(agent)
    return state.get("attention_weights", {})


def record_scan(agent: str, metrics: dict[str, Any]) -> None:
    """Record that a scan completed, with its metrics."""
    state = _load_state(agent)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    state["total_scans"] = state.get("total_scans", 0) + 1
    state["metrics_history"].append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        }
    )
    # Keep last 90 entries (~3 months of daily scans)
    state["metrics_history"] = state["metrics_history"][-90:]
    _save_state(agent, state)


def record_resolution(agent: str, finding_id: str, resolution_type: str) -> None:
    """Record how a finding was resolved: 'fixed', 'deferred', 'ignored'."""
    state = _load_state(agent)
    state["resolutions"][finding_id] = {
        "type": resolution_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _save_state(agent, state)


def get_total_scans(agent: str) -> int:
    state = _load_state(agent)
    return state.get("total_scans", 0)
