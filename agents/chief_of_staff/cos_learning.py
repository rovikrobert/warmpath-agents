"""CoS-specific self-learning — tracks resolution patterns, priority calibration, team reliability."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agents.shared.config import AGENTS_DIR

logger = logging.getLogger(__name__)

_STATE_PATH = AGENTS_DIR / "chief_of_staff" / "cos_state.json"


def _default_state() -> dict:
    return {
        "version": 1,
        "last_updated": "",
        "resolution_patterns": {
            "total_conflicts": 0,
            "resolved_without_escalation": 0,
            "founder_agreed_with_cos": 0,
        },
        "priority_calibration": {
            "items_ranked_critical": 0,
            "founder_agreed_critical": 0,
            "over_escalation_count": 0,
        },
        "team_reliability": {
            "engineering": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
            "data": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
            "product": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
            "ops": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
            "finance": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
            "gtm": {
                "reports_on_time": 0,
                "reports_total": 0,
                "noise_ratio": 0.0,
            },
        },
        "cost_trends": [],
        "meta_improvements": [],
    }


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt CoS state, resetting")
    return _default_state()


def _save_state(state: dict) -> None:
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def record_founder_decision(
    item_id: str, cos_recommendation: str, founder_decision: str
) -> None:
    """Record whether the founder agreed with CoS recommendation."""
    state = _load_state()
    agreed = cos_recommendation.lower().strip() == founder_decision.lower().strip()

    cal = state["priority_calibration"]
    cal["items_ranked_critical"] = cal.get("items_ranked_critical", 0) + 1
    if agreed:
        cal["founder_agreed_critical"] = cal.get("founder_agreed_critical", 0) + 1
    else:
        cal["over_escalation_count"] = cal.get("over_escalation_count", 0) + 1

    _save_state(state)


def record_resolution(
    conflict_id: str, strategy: str, outcome: str, escalated: bool = False
) -> None:
    """Record a conflict resolution outcome."""
    state = _load_state()
    rp = state["resolution_patterns"]
    rp["total_conflicts"] = rp.get("total_conflicts", 0) + 1
    if not escalated:
        rp["resolved_without_escalation"] = rp.get("resolved_without_escalation", 0) + 1
    _save_state(state)


def update_team_reliability(team: str, reports: list[Any]) -> None:
    """Update team reliability stats based on received reports."""
    state = _load_state()
    tr = state.setdefault("team_reliability", {})
    team_stats = tr.setdefault(
        team, {"reports_on_time": 0, "reports_total": 0, "noise_ratio": 0.0}
    )

    report_count = len(reports)
    team_stats["reports_total"] = team_stats.get("reports_total", 0) + report_count
    # Assume on-time if reports exist
    team_stats["reports_on_time"] = team_stats.get("reports_on_time", 0) + report_count

    # Noise ratio: proportion of info-severity findings
    total_findings = 0
    info_findings = 0
    for r in reports:
        for f in getattr(r, "findings", []):
            total_findings += 1
            if getattr(f, "severity", "") == "info":
                info_findings += 1
    if total_findings > 0:
        team_stats["noise_ratio"] = round(info_findings / total_findings, 3)

    _save_state(state)


def record_cost_snapshot(cost_data: dict[str, Any]) -> None:
    """Append a cost snapshot to the trends."""
    state = _load_state()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **cost_data,
    }
    state["cost_trends"].append(entry)
    # Keep last 90 entries
    state["cost_trends"] = state["cost_trends"][-90:]
    _save_state(state)


def weekly_reflect() -> list[str]:
    """Generate self-learning reflections for the weekly synthesis."""
    state = _load_state()
    notes: list[str] = []

    # Resolution accuracy
    rp = state.get("resolution_patterns", {})
    total = rp.get("total_conflicts", 0)
    no_esc = rp.get("resolved_without_escalation", 0)
    if total > 0:
        pct = (no_esc / total) * 100
        notes.append(
            f"Resolved {no_esc}/{total} conflicts without escalation ({pct:.0f}%)"
        )

    # Priority calibration
    cal = state.get("priority_calibration", {})
    ranked = cal.get("items_ranked_critical", 0)
    agreed = cal.get("founder_agreed_critical", 0)
    if ranked > 0:
        accuracy = (agreed / ranked) * 100
        notes.append(
            f"Priority calibration: founder agreed with {agreed}/{ranked} "
            f"recommendations ({accuracy:.0f}%)"
        )

    # Team reliability
    for team, stats in state.get("team_reliability", {}).items():
        total_reports = stats.get("reports_total", 0)
        noise = stats.get("noise_ratio", 0)
        if total_reports > 0:
            notes.append(
                f"{team}: {total_reports} reports processed, noise ratio {noise:.1%}"
            )

    if not notes:
        notes.append("Insufficient data for self-learning — keep running scans")

    return notes


def get_learning_summary() -> dict:
    """Return the full learning state for inspection."""
    return _load_state()
