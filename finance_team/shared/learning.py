"""Self-learning system for finance team agents.

Provides `FinanceLearningState` — a full learning state tracker with:
  - Finding recording + recurring pattern detection
  - Resolution tracking + fix effectiveness analysis
  - Attention weights (EMA + time decay) for hot spot detection
  - Severity calibration tracking
  - Tool accuracy tracking
  - Methodology/best-practice adoption records
  - Codebase health trajectory
  - KPI trend analysis
  - Meta-learning report generation

Same API pattern as ops_team/shared/learning.py but stores state in
finance_team/{agent}/state.json to keep the teams independent.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from finance_team.shared.config import (
    ATTENTION_WEIGHT_DECAY,
    FINANCE_TEAM_DIR,
    FIX_EFFECTIVENESS_WINDOW_DAYS,
    RECURRING_PATTERN_THRESHOLD,
    SYSTEMIC_PATTERN_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class ResolutionType(str, Enum):
    FIXED = "fixed"
    DEFERRED = "deferred"
    IGNORED = "ignored"
    FALSE_POSITIVE = "false_positive"
    WONT_FIX = "wont_fix"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class AttentionWeight:
    file: str
    weight: float
    last_updated: str = ""
    reason: str = ""

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class MethodologyRecord:
    name: str
    source: str
    effectiveness: float = 0.0
    adopted_at: str = ""

    def __post_init__(self):
        if not self.adopted_at:
            self.adopted_at = datetime.now(timezone.utc).isoformat()


@dataclass
class FixEffectivenessRecord:
    finding_id: str
    resolution_type: str
    resolved_at: str
    recurred: bool = False
    recurrence_count_after: int = 0
    days_until_recurrence: int | None = None
    effective: bool = True


@dataclass
class HealthSnapshot:
    score: float
    timestamp: str = ""
    finding_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# State defaults & migration
# ---------------------------------------------------------------------------

_STATE_DEFAULTS: dict[str, Any] = {
    "last_scan": None,
    "total_scans": 0,
    "finding_history": [],
    "insight_history": [],
    "kpi_history": {},
    "attention_weights": {},
    "predictions": [],
    "metrics_history": [],
    "resolutions": {},
    "recurring_patterns": {},
    "severity_calibration": {},
    "tool_accuracy": {},
    "methodologies": [],
    "codebase_health_history": [],
}


def _migrate_state(state: dict) -> dict:
    """Add missing keys with sane defaults — never modifies existing keys."""
    for key, default in _STATE_DEFAULTS.items():
        if key not in state:
            state[key] = (
                default if not isinstance(default, (list, dict)) else type(default)()
            )
    return state


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


def _state_path(agent: str) -> Path:
    return FINANCE_TEAM_DIR / agent / "state.json"


def _load_state(agent: str) -> dict:
    path = _state_path(agent)
    if path.exists():
        try:
            state = json.loads(path.read_text())
            return _migrate_state(state)
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt state for %s, resetting", agent)
    return {
        k: (v if not isinstance(v, (list, dict)) else type(v)())
        for k, v in _STATE_DEFAULTS.items()
    }


def _save_state(agent: str, state: dict) -> None:
    path = _state_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# FinanceLearningState class
# ---------------------------------------------------------------------------


class FinanceLearningState:
    """Full learning state for a finance team agent with advanced analytics."""

    def __init__(self, agent: str):
        self.agent = agent
        self.state = _load_state(agent)

    def save(self) -> None:
        _save_state(self.agent, self.state)

    def load(self) -> None:
        self.state = _load_state(self.agent)

    # -- Scan recording ------------------------------------------------------

    def record_scan(self, metrics: dict[str, Any]) -> None:
        self.state["last_scan"] = datetime.now(timezone.utc).isoformat()
        self.state["total_scans"] = self.state.get("total_scans", 0) + 1
        self.state["metrics_history"].append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics": metrics,
            }
        )
        self.state["metrics_history"] = self.state["metrics_history"][-90:]
        self.save()

    # -- Finding recording ---------------------------------------------------

    def record_finding(self, finding_dict: dict) -> None:
        """Append a finding to history and update recurring patterns."""
        entry = {
            "id": finding_dict.get("id") or str(uuid.uuid4())[:8],
            "severity": finding_dict.get("severity"),
            "category": finding_dict.get("category"),
            "file": finding_dict.get("file"),
            "line": finding_dict.get("line"),
            "title": finding_dict.get("title"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state["finding_history"].append(entry)
        self.state["finding_history"] = self.state["finding_history"][-500:]

        category = finding_dict.get("category", "")
        file_path = finding_dict.get("file", "")
        if category:
            self._update_recurring_pattern(category, file_path)

        self.save()

    def _update_recurring_pattern(self, category: str, file_path: str) -> None:
        patterns = self.state["recurring_patterns"]
        key = f"{category}:{file_path}" if file_path else category
        if key not in patterns:
            patterns[key] = {
                "category": category,
                "file": file_path,
                "count": 0,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": None,
                "auto_escalated": False,
                "systemic": False,
            }
        patterns[key]["count"] += 1
        patterns[key]["last_seen"] = datetime.now(timezone.utc).isoformat()

        if patterns[key]["count"] >= SYSTEMIC_PATTERN_THRESHOLD:
            patterns[key]["systemic"] = True
            patterns[key]["auto_escalated"] = True
        elif patterns[key]["count"] >= RECURRING_PATTERN_THRESHOLD:
            patterns[key]["auto_escalated"] = True

    # -- Insight recording ---------------------------------------------------

    def record_insight(self, insight_dict: dict) -> None:
        entry = {
            "id": insight_dict.get("id", ""),
            "category": insight_dict.get("category", ""),
            "title": insight_dict.get("title", ""),
            "confidence": insight_dict.get("confidence"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state["insight_history"].append(entry)
        self.state["insight_history"] = self.state["insight_history"][-200:]
        self.save()

    # -- Resolution tracking -------------------------------------------------

    def record_resolution(
        self, finding_id: str, resolution_type: str | ResolutionType
    ) -> None:
        if isinstance(resolution_type, ResolutionType):
            resolution_type = resolution_type.value

        self.state["resolutions"][finding_id] = {
            "type": resolution_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        finding = self._find_in_history(finding_id)
        if finding:
            severity = finding.get("severity", "unknown")
            self.record_severity_calibration(severity)

        self.save()

    def _find_in_history(self, finding_id: str) -> dict | None:
        for entry in reversed(self.state["finding_history"]):
            if entry.get("id") == finding_id:
                return entry
        return None

    # -- Fix effectiveness ---------------------------------------------------

    def check_fix_effectiveness(self, finding_id: str) -> FixEffectivenessRecord | None:
        resolution = self.state["resolutions"].get(finding_id)
        if not resolution:
            return None

        resolved_at = resolution["timestamp"]
        try:
            resolved_dt = datetime.fromisoformat(resolved_at)
            if resolved_dt.tzinfo is None:
                resolved_dt = resolved_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

        original = self._find_in_history(finding_id)
        if not original:
            return FixEffectivenessRecord(
                finding_id=finding_id,
                resolution_type=resolution["type"],
                resolved_at=resolved_at,
                effective=True,
            )

        window_end = resolved_dt + timedelta(days=FIX_EFFECTIVENESS_WINDOW_DAYS)
        now = datetime.now(timezone.utc)
        check_end = min(window_end, now)

        recurrence_count = 0
        first_recurrence_days = None
        for entry in self.state["finding_history"]:
            if entry.get("category") != original.get("category"):
                continue
            if entry.get("file") != original.get("file"):
                continue
            try:
                entry_dt = datetime.fromisoformat(entry["timestamp"])
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if resolved_dt < entry_dt <= check_end:
                recurrence_count += 1
                if first_recurrence_days is None:
                    first_recurrence_days = (entry_dt - resolved_dt).days

        return FixEffectivenessRecord(
            finding_id=finding_id,
            resolution_type=resolution["type"],
            resolved_at=resolved_at,
            recurred=recurrence_count > 0,
            recurrence_count_after=recurrence_count,
            days_until_recurrence=first_recurrence_days,
            effective=recurrence_count == 0,
        )

    # -- Recurring patterns --------------------------------------------------

    def detect_recurring_pattern(self, category: str, file: str | None = None) -> dict:
        key = f"{category}:{file}" if file else category
        pattern = self.state["recurring_patterns"].get(key)
        if not pattern:
            return {
                "count": 0,
                "auto_escalated": False,
                "systemic": False,
                "first_seen": None,
                "last_seen": None,
            }
        return {
            "count": pattern["count"],
            "auto_escalated": pattern["auto_escalated"],
            "systemic": pattern["systemic"],
            "first_seen": pattern["first_seen"],
            "last_seen": pattern["last_seen"],
        }

    def get_recurrence_count(self, category: str, file: str | None = None) -> int:
        count = 0
        for h in self.state["finding_history"]:
            if h.get("category") == category and (
                file is None or h.get("file") == file
            ):
                count += 1
        return count

    # -- Attention weights ---------------------------------------------------

    def update_attention_weights(self, file_findings: dict[str, int]) -> None:
        weights = self.state.get("attention_weights", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        for filepath, count in file_findings.items():
            existing = weights.get(filepath)
            if isinstance(existing, dict):
                current_val = existing.get("weight", 1.0)
                try:
                    last_dt = datetime.fromisoformat(
                        existing.get("last_updated", now_iso)
                    )
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    days_since = (datetime.now(timezone.utc) - last_dt).days
                    decay = max(0, days_since * ATTENTION_WEIGHT_DECAY)
                    current_val = max(0.1, current_val - decay)
                except (ValueError, TypeError):
                    pass
            elif isinstance(existing, (int, float)):
                current_val = float(existing)
            else:
                current_val = 1.0

            new_weight = round(current_val * 0.7 + (1.0 + count * 0.3) * 0.3, 2)
            weights[filepath] = {
                "weight": new_weight,
                "last_updated": now_iso,
                "reason": f"{count} finding(s) in latest scan",
            }

        self.state["attention_weights"] = weights
        self.save()

    def get_hot_spots(self, top_n: int = 5) -> list[AttentionWeight]:
        weights = self.state.get("attention_weights", {})
        items = []
        for filepath, data in weights.items():
            if isinstance(data, dict):
                items.append(
                    AttentionWeight(
                        file=filepath,
                        weight=data.get("weight", 1.0),
                        last_updated=data.get("last_updated", ""),
                        reason=data.get("reason", ""),
                    )
                )
            elif isinstance(data, (int, float)):
                items.append(AttentionWeight(file=filepath, weight=float(data)))
        items.sort(key=lambda x: x.weight, reverse=True)
        return items[:top_n]

    def get_stable_areas(self, threshold: float = 1.0) -> list[str]:
        weights = self.state.get("attention_weights", {})
        stable = []
        for filepath, data in weights.items():
            w = data.get("weight", 1.0) if isinstance(data, dict) else float(data)
            if w <= threshold:
                stable.append(filepath)
        return sorted(stable)

    # -- KPI tracking --------------------------------------------------------

    def track_kpi(self, kpi_name: str, value: float | str) -> None:
        history = self.state["kpi_history"].setdefault(kpi_name, [])
        history.append(
            {
                "value": value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.state["kpi_history"][kpi_name] = history[-90:]
        self.save()

    def get_kpi_trend(self, kpi_name: str) -> str:
        history = self.state["kpi_history"].get(kpi_name, [])
        if len(history) < 2:
            return "insufficient_data"
        values = [
            h["value"] for h in history if isinstance(h.get("value"), (int, float))
        ]
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

    # -- Prediction tracking -------------------------------------------------

    def record_prediction(self, prediction: dict) -> None:
        self.state["predictions"].append(
            {
                **prediction,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.state["predictions"] = self.state["predictions"][-50:]
        self.save()

    # -- Severity calibration ------------------------------------------------

    def record_severity_calibration(
        self, severity: str, was_overridden: bool = False
    ) -> None:
        cal = self.state["severity_calibration"]
        if severity not in cal:
            cal[severity] = {"total": 0, "overridden": 0}
        cal[severity]["total"] += 1
        if was_overridden:
            cal[severity]["overridden"] += 1

    def get_severity_calibration(self) -> dict[str, dict]:
        return dict(self.state.get("severity_calibration", {}))

    # -- Tool accuracy -------------------------------------------------------

    def record_tool_accuracy(
        self, tool: str, finding_id: str, confirmed: bool = True
    ) -> None:
        accuracy = self.state["tool_accuracy"]
        if tool not in accuracy:
            accuracy[tool] = {"confirmed": 0, "rejected": 0, "finding_ids": []}
        if confirmed:
            accuracy[tool]["confirmed"] += 1
        else:
            accuracy[tool]["rejected"] += 1
        accuracy[tool]["finding_ids"].append(finding_id)
        accuracy[tool]["finding_ids"] = accuracy[tool]["finding_ids"][-100:]
        self.save()

    def get_tool_reliability(self) -> dict[str, float]:
        result = {}
        for tool, data in self.state.get("tool_accuracy", {}).items():
            total = data.get("confirmed", 0) + data.get("rejected", 0)
            if total > 0:
                result[tool] = round(data["confirmed"] / total, 3)
            else:
                result[tool] = 1.0
        return result

    # -- Methodology tracking ------------------------------------------------

    def record_methodology(
        self, name: str, source: str, effectiveness: float = 0.0
    ) -> None:
        entry = MethodologyRecord(name=name, source=source, effectiveness=effectiveness)
        self.state["methodologies"].append(asdict(entry))
        self.state["methodologies"] = self.state["methodologies"][-50:]
        self.save()

    # -- Codebase health -----------------------------------------------------

    def record_health_snapshot(
        self, score: float, finding_counts: dict[str, int]
    ) -> None:
        snapshot = HealthSnapshot(score=score, finding_counts=finding_counts)
        self.state["codebase_health_history"].append(asdict(snapshot))
        self.state["codebase_health_history"] = self.state["codebase_health_history"][
            -90:
        ]
        self.save()

    def get_health_trajectory(self, window: int = 90) -> str:
        history = self.state.get("codebase_health_history", [])
        if len(history) < 2:
            return "insufficient_data"

        now = datetime.now(timezone.utc)
        recent_scores = []
        for entry in history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (now - ts).days <= window:
                    recent_scores.append(entry["score"])
            except (KeyError, ValueError, TypeError):
                continue

        if len(recent_scores) < 2:
            return "insufficient_data"

        mid = len(recent_scores) // 2
        first_half = sum(recent_scores[:mid]) / max(1, mid)
        second_half = sum(recent_scores[mid:]) / max(1, len(recent_scores) - mid)

        if second_half > first_half * 1.05:
            return "improving"
        elif second_half < first_half * 0.95:
            return "degrading"
        return "stable"

    # -- Meta learning report ------------------------------------------------

    def generate_meta_learning_report(self) -> dict:
        hot_spots = self.get_hot_spots(top_n=5)

        patterns = self.state.get("recurring_patterns", {})
        escalated = [
            {"key": k, **v} for k, v in patterns.items() if v.get("auto_escalated")
        ]
        systemic = [{"key": k, **v} for k, v in patterns.items() if v.get("systemic")]

        resolutions = self.state.get("resolutions", {})
        fix_records = []
        for fid in list(resolutions.keys())[-20:]:
            rec = self.check_fix_effectiveness(fid)
            if rec:
                fix_records.append(asdict(rec))

        effective_count = sum(1 for r in fix_records if r.get("effective"))
        total_checked = len(fix_records)
        fix_rate = (
            round(effective_count / total_checked, 3) if total_checked > 0 else None
        )

        tool_reliability = self.get_tool_reliability()
        severity_cal = self.get_severity_calibration()
        trajectory = self.get_health_trajectory()

        kpi_trends = {}
        for kpi_name in self.state.get("kpi_history", {}):
            kpi_trends[kpi_name] = self.get_kpi_trend(kpi_name)

        total_scans = self.state.get("total_scans", 0)
        total_findings = len(self.state.get("finding_history", []))
        total_insights = len(self.state.get("insight_history", []))

        return {
            "agent": self.agent,
            "total_scans": total_scans,
            "total_findings_tracked": total_findings,
            "total_insights_tracked": total_insights,
            "hot_spots": [asdict(h) for h in hot_spots],
            "escalated_patterns": escalated,
            "systemic_patterns": systemic,
            "fix_effectiveness_rate": fix_rate,
            "fix_records_sampled": len(fix_records),
            "tool_reliability": tool_reliability,
            "severity_calibration": severity_cal,
            "health_trajectory": trajectory,
            "kpi_trends": kpi_trends,
            "methodologies_adopted": len(self.state.get("methodologies", [])),
        }


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------


def get_learning_state(agent: str) -> FinanceLearningState:
    """Return a fully loaded FinanceLearningState instance."""
    return FinanceLearningState(agent)
