"""Self-learning wrapper for data team agents.

Same API pattern as agents/shared/learning.py but stores state in
data_team/{agent}/state.json to keep the two teams independent.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_team.shared.config import DATA_TEAM_DIR

logger = logging.getLogger(__name__)


def _state_path(agent: str) -> Path:
    return DATA_TEAM_DIR / agent / "state.json"


def _default_state() -> dict:
    return {
        "last_scan": None,
        "total_scans": 0,
        "finding_history": [],
        "insight_history": [],
        "kpi_history": {},
        "attention_weights": {},
        "predictions": [],
    }


def _load_state(agent: str) -> dict:
    path = _state_path(agent)
    if path.exists():
        try:
            state = json.loads(path.read_text())
            # Migrate missing keys
            for key, default in _default_state().items():
                if key not in state:
                    state[key] = default if not isinstance(default, (list, dict)) else type(default)()
            return state
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt state for %s, resetting", agent)
    return _default_state()


def _save_state(agent: str, state: dict) -> None:
    path = _state_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


class DataLearningState:
    """Learning state for a data team agent."""

    def __init__(self, agent: str):
        self.agent = agent
        self.state = _load_state(agent)

    def save(self) -> None:
        _save_state(self.agent, self.state)

    def record_scan(self, metrics: dict[str, Any]) -> None:
        self.state["last_scan"] = datetime.now(timezone.utc).isoformat()
        self.state["total_scans"] = self.state.get("total_scans", 0) + 1
        self.save()

    def record_insight(self, insight_dict: dict) -> None:
        entry = {
            "id": insight_dict.get("id", ""),
            "category": insight_dict.get("category", ""),
            "title": insight_dict.get("title", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state["insight_history"].append(entry)
        self.state["insight_history"] = self.state["insight_history"][-200:]
        self.save()

    def track_kpi(self, kpi_name: str, value: float | str) -> None:
        history = self.state["kpi_history"].setdefault(kpi_name, [])
        history.append({
            "value": value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 90 per KPI
        self.state["kpi_history"][kpi_name] = history[-90:]
        self.save()

    def get_kpi_trend(self, kpi_name: str) -> str:
        history = self.state["kpi_history"].get(kpi_name, [])
        if len(history) < 2:
            return "insufficient_data"
        values = [h["value"] for h in history if isinstance(h.get("value"), (int, float))]
        if len(values) < 2:
            return "insufficient_data"
        mid = len(values) // 2
        first_half = sum(values[:mid]) / max(1, mid)
        second_half = sum(values[mid:]) / max(1, len(values) - mid)
        if second_half > first_half * 1.05:
            return "improving"
        elif second_half < first_half * 0.95:
            return "degrading"
        return "stable"

    def record_prediction(self, prediction: dict) -> None:
        self.state["predictions"].append({
            **prediction,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.state["predictions"] = self.state["predictions"][-50:]
        self.save()

    def record_finding(self, finding_dict: dict) -> None:
        entry = {
            "id": finding_dict.get("id", ""),
            "severity": finding_dict.get("severity", ""),
            "category": finding_dict.get("category", ""),
            "title": finding_dict.get("title", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state["finding_history"].append(entry)
        self.state["finding_history"] = self.state["finding_history"][-500:]
        self.save()


# Module-level convenience
def get_learning_state(agent: str) -> DataLearningState:
    return DataLearningState(agent)
