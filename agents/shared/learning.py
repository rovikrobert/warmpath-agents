"""Self-learning system — track findings history, patterns, attention weights.

Provides both the new `AgentLearningState` class and backward-compatible
module-level functions used by all 7 agents + kpis.py + lead.py.
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

from agents.shared.config import (
    AGENTS_DIR,
    ATTENTION_WEIGHT_DECAY,
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

_NEW_STATE_DEFAULTS: dict[str, Any] = {
    "last_scan": None,
    "total_scans": 0,
    "finding_history": [],
    "attention_weights": {},
    "metrics_history": [],
    "resolutions": {},
    # New fields (v2)
    "recurring_patterns": {},
    "severity_calibration": {},
    "tool_accuracy": {},
    "methodologies": [],
    "codebase_health_history": [],
}


def _migrate_state(state: dict) -> dict:
    """Add missing keys with sane defaults — never modifies existing keys."""
    for key, default in _NEW_STATE_DEFAULTS.items():
        if key not in state:
            state[key] = (
                default if not isinstance(default, (list, dict)) else type(default)()
            )
    return state


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


def _state_path(agent: str) -> Path:
    return AGENTS_DIR / agent / "state.json"


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
        for k, v in _NEW_STATE_DEFAULTS.items()
    }


def _save_state(agent: str, state: dict) -> None:
    path = _state_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# AgentLearningState class
# ---------------------------------------------------------------------------


class AgentLearningState:
    """Full learning state for a single agent with advanced analytics."""

    def __init__(self, agent: str):
        self.agent = agent
        self.state = _load_state(agent)

    def save(self) -> None:
        _save_state(self.agent, self.state)

    def load(self) -> None:
        self.state = _load_state(self.agent)

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
        # Keep last 500 entries
        self.state["finding_history"] = self.state["finding_history"][-500:]

        # Update recurring patterns
        category = finding_dict.get("category", "")
        file_path = finding_dict.get("file", "")
        if category:
            self._update_recurring_pattern(category, file_path)

        self.save()

    def _update_recurring_pattern(self, category: str, file_path: str) -> None:
        """Track pattern recurrence for escalation."""
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

    # -- Resolution tracking -------------------------------------------------

    def record_resolution(
        self, finding_id: str, resolution_type: str | ResolutionType
    ) -> None:
        """Record how a finding was resolved."""
        if isinstance(resolution_type, ResolutionType):
            resolution_type = resolution_type.value

        self.state["resolutions"][finding_id] = {
            "type": resolution_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Update severity calibration
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
        """Check if a resolved finding has recurred within the effectiveness window."""
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

        # Find the original finding to get category/file
        original = self._find_in_history(finding_id)
        if not original:
            return FixEffectivenessRecord(
                finding_id=finding_id,
                resolution_type=resolution["type"],
                resolved_at=resolved_at,
                effective=True,
            )

        # Count recurrences after resolution within the window
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
        """Return pattern info including count and escalation status."""
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
        """How many times has this type of issue appeared historically?"""
        count = 0
        for h in self.state["finding_history"]:
            if h.get("category") == category:
                if file is None or h.get("file") == file:
                    count += 1
        return count

    # -- Attention weights ---------------------------------------------------

    def update_attention_weights(self, file_findings: dict[str, int]) -> None:
        """Files with more findings get higher attention weight (EMA + time decay)."""
        weights = self.state.get("attention_weights", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        for filepath, count in file_findings.items():
            existing = weights.get(filepath)
            if isinstance(existing, dict):
                current_val = existing.get("weight", 1.0)
                # Apply time-based decay
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
        """Return the top N files by attention weight."""
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
        """Return file paths with attention weight at or below threshold."""
        weights = self.state.get("attention_weights", {})
        stable = []
        for filepath, data in weights.items():
            w = data.get("weight", 1.0) if isinstance(data, dict) else float(data)
            if w <= threshold:
                stable.append(filepath)
        return sorted(stable)

    # -- Severity calibration ------------------------------------------------

    def record_severity_calibration(
        self, severity: str, was_overridden: bool = False
    ) -> None:
        """Track severity assignment patterns for calibration analysis."""
        cal = self.state["severity_calibration"]
        if severity not in cal:
            cal[severity] = {"total": 0, "overridden": 0}
        cal[severity]["total"] += 1
        if was_overridden:
            cal[severity]["overridden"] += 1

    def get_severity_calibration(self) -> dict[str, dict]:
        """Return severity calibration data."""
        return dict(self.state.get("severity_calibration", {}))

    # -- Tool accuracy -------------------------------------------------------

    def record_tool_accuracy(
        self, tool: str, finding_id: str, confirmed: bool = True
    ) -> None:
        """Record whether a tool's finding was confirmed as valid."""
        accuracy = self.state["tool_accuracy"]
        if tool not in accuracy:
            accuracy[tool] = {"confirmed": 0, "rejected": 0, "finding_ids": []}
        if confirmed:
            accuracy[tool]["confirmed"] += 1
        else:
            accuracy[tool]["rejected"] += 1
        accuracy[tool]["finding_ids"].append(finding_id)
        # Keep last 100 finding IDs per tool
        accuracy[tool]["finding_ids"] = accuracy[tool]["finding_ids"][-100:]
        self.save()

    def get_tool_reliability(self) -> dict[str, float]:
        """Return reliability score (0.0-1.0) for each tool."""
        result = {}
        for tool, data in self.state.get("tool_accuracy", {}).items():
            total = data.get("confirmed", 0) + data.get("rejected", 0)
            if total > 0:
                result[tool] = round(data["confirmed"] / total, 3)
            else:
                result[tool] = 1.0  # No data = assume reliable
        return result

    # -- Methodology tracking ------------------------------------------------

    def record_methodology(
        self, name: str, source: str, effectiveness: float = 0.0
    ) -> None:
        """Record a methodology/best practice adopted."""
        entry = MethodologyRecord(name=name, source=source, effectiveness=effectiveness)
        self.state["methodologies"].append(asdict(entry))
        # Keep last 50
        self.state["methodologies"] = self.state["methodologies"][-50:]
        self.save()

    # -- Codebase health -----------------------------------------------------

    def record_health_snapshot(
        self, score: float, finding_counts: dict[str, int]
    ) -> None:
        """Record a point-in-time codebase health score."""
        snapshot = HealthSnapshot(score=score, finding_counts=finding_counts)
        self.state["codebase_health_history"].append(asdict(snapshot))
        # Keep last 90 snapshots (~3 months daily)
        self.state["codebase_health_history"] = self.state["codebase_health_history"][
            -90:
        ]
        self.save()

    def get_health_trajectory(self, window: int = 90) -> str:
        """Return 'improving', 'stable', or 'degrading' based on health trend."""
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
        """Generate a comprehensive summary of all learning dimensions."""
        # Hot spots
        hot_spots = self.get_hot_spots(top_n=5)

        # Recurring patterns summary
        patterns = self.state.get("recurring_patterns", {})
        escalated = [
            {"key": k, **v} for k, v in patterns.items() if v.get("auto_escalated")
        ]
        systemic = [{"key": k, **v} for k, v in patterns.items() if v.get("systemic")]

        # Fix effectiveness
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

        # Tool reliability
        tool_reliability = self.get_tool_reliability()

        # Severity calibration
        severity_cal = self.get_severity_calibration()

        # Health trajectory
        trajectory = self.get_health_trajectory()

        # Total stats
        total_scans = self.state.get("total_scans", 0)
        total_findings = len(self.state.get("finding_history", []))

        return {
            "agent": self.agent,
            "total_scans": total_scans,
            "total_findings_tracked": total_findings,
            "hot_spots": [asdict(h) for h in hot_spots],
            "escalated_patterns": escalated,
            "systemic_patterns": systemic,
            "fix_effectiveness_rate": fix_rate,
            "fix_records_sampled": len(fix_records),
            "tool_reliability": tool_reliability,
            "severity_calibration": severity_cal,
            "health_trajectory": trajectory,
            "methodologies_adopted": len(self.state.get("methodologies", [])),
        }


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------


def get_learning_state(agent: str) -> AgentLearningState:
    """Return a fully loaded AgentLearningState instance."""
    return AgentLearningState(agent)


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------
# All 7 agents + kpis.py + lead.py call these via `learning.func(agent, ...)`.
# They MUST keep the same signatures and return types.


def record_finding(agent: str, finding_dict: dict) -> None:
    """Append a finding to the agent's history."""
    ls = AgentLearningState(agent)
    ls.record_finding(finding_dict)


def get_recurrence_count(agent: str, category: str, file: str | None = None) -> int:
    """How many times has this type of issue appeared historically?"""
    ls = AgentLearningState(agent)
    return ls.get_recurrence_count(category, file)


def get_trend(agent: str, metric: str, window_days: int = 30) -> str:
    """Return 'up', 'down', or 'stable' for a metric over the window."""
    state = _load_state(agent)
    history = state.get("metrics_history", [])
    if len(history) < 2:
        return "insufficient_data"

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
    # Preserve exact old behavior for backward compat:
    # Old callers expect attention_weights to be flat float values,
    # but AgentLearningState stores dicts. Use the old simple EMA.
    state = _load_state(agent)
    weights = state.get("attention_weights", {})
    for filepath, count in file_findings.items():
        if isinstance(weights.get(filepath), dict):
            current = weights[filepath].get("weight", 1.0)
        elif isinstance(weights.get(filepath), (int, float)):
            current = float(weights[filepath])
        else:
            current = 1.0
        # Exponential moving average (same formula as original)
        weights[filepath] = round(current * 0.7 + (1.0 + count * 0.3) * 0.3, 2)
    state["attention_weights"] = weights
    _save_state(agent, state)


def get_attention_weights(agent: str) -> dict[str, float]:
    """Return current attention weights (flat float values for compat)."""
    state = _load_state(agent)
    raw = state.get("attention_weights", {})
    result = {}
    for filepath, data in raw.items():
        if isinstance(data, dict):
            result[filepath] = data.get("weight", 1.0)
        elif isinstance(data, (int, float)):
            result[filepath] = float(data)
        else:
            result[filepath] = 1.0
    return result


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


# ---------------------------------------------------------------------------
# Global resolved-issues registry
# ---------------------------------------------------------------------------

_RESOLVED_REGISTRY_PATH = AGENTS_DIR / "shared" / "resolved_registry.json"


def _load_resolved_registry() -> dict[str, dict]:
    """Load the global resolved-issues registry."""
    if _RESOLVED_REGISTRY_PATH.exists():
        try:
            return json.loads(_RESOLVED_REGISTRY_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt resolved registry, returning empty")
    return {}


def _save_resolved_registry(registry: dict[str, dict]) -> None:
    """Persist the global resolved-issues registry."""
    _RESOLVED_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESOLVED_REGISTRY_PATH.write_text(json.dumps(registry, indent=2, default=str))


def resolve_issue(
    finding_id: str,
    resolution_type: str,
    reason: str = "",
    skip_days: int | None = 30,
) -> None:
    """Mark a finding as resolved in the global registry.

    Args:
        finding_id: The finding ID (e.g. "ARCH-N+1", "pipe-001").
        resolution_type: One of "fixed", "false_positive", "wont_fix", "deferred".
        reason: Human-readable explanation.
        skip_days: Days to suppress re-reporting (None = permanent for wont_fix/false_positive).
    """
    registry = _load_resolved_registry()
    now = datetime.now(timezone.utc)

    entry: dict[str, Any] = {
        "resolution_type": resolution_type,
        "resolved_at": now.isoformat(),
        "reason": reason,
    }

    if resolution_type in ("wont_fix", "false_positive"):
        entry["skip_until"] = None  # permanent
    elif skip_days is not None:
        entry["skip_until"] = (now + timedelta(days=skip_days)).isoformat()

    registry[finding_id] = entry
    _save_resolved_registry(registry)
    logger.info("Resolved %s as %s: %s", finding_id, resolution_type, reason)


def unresolve_issue(finding_id: str) -> bool:
    """Remove a finding from the resolved registry. Returns True if found."""
    registry = _load_resolved_registry()
    if finding_id in registry:
        del registry[finding_id]
        _save_resolved_registry(registry)
        return True
    return False


def is_resolved(finding_id: str) -> bool:
    """Check if a finding is currently resolved (and within skip window)."""
    registry = _load_resolved_registry()
    entry = registry.get(finding_id)
    if not entry:
        return False

    skip_until = entry.get("skip_until")
    if skip_until is None:
        # Permanent (wont_fix / false_positive)
        return True

    try:
        skip_dt = datetime.fromisoformat(skip_until)
        if skip_dt.tzinfo is None:
            skip_dt = skip_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < skip_dt
    except (ValueError, TypeError):
        return False


def list_resolved() -> dict[str, dict]:
    """Return all entries in the resolved registry."""
    return _load_resolved_registry()


def filter_resolved_findings(findings: list) -> list:
    """Remove findings that are in the resolved registry.

    Works with both Finding dataclass instances and dicts.
    Matches on finding.id.
    """
    registry = _load_resolved_registry()
    if not registry:
        return findings

    now = datetime.now(timezone.utc)
    result = []
    for f in findings:
        fid = f.id if hasattr(f, "id") else f.get("id", "")
        entry = registry.get(fid)
        if entry is None:
            result.append(f)
            continue

        skip_until = entry.get("skip_until")
        if skip_until is None:
            # Permanently resolved
            continue

        try:
            skip_dt = datetime.fromisoformat(skip_until)
            if skip_dt.tzinfo is None:
                skip_dt = skip_dt.replace(tzinfo=timezone.utc)
            if now < skip_dt:
                continue  # Still within skip window
        except (ValueError, TypeError):
            pass

        result.append(f)
    return result
