"""Pod lifecycle management — COS.md Section 7.9.

Manages temporary cross-functional working groups: creation, health checks,
dissolution, and permanent-pod detection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .cos_learning import _load_state, _save_state
from .schemas import Pod, PodStatus

logger = logging.getLogger(__name__)

# Maximum concurrent pods (pre-launch)
MAX_CONCURRENT_PODS = 2


# ---------------------------------------------------------------------------
# Pod CRUD
# ---------------------------------------------------------------------------


def create_pod(
    name: str,
    mission: str,
    members: list[dict[str, str]],
    lead: str,
    duration_weeks: int = 2,
    exit_criteria: list[str] | None = None,
    cost_budget_per_day: float = 0.0,
) -> Pod:
    """Create a new pod and persist it to cos_state.json.

    Members format: [{"agent": "Architect", "team": "engineering", "role": "tech impl"}]
    """
    state = _load_state()
    pods = state.setdefault("pods", [])
    active = [p for p in pods if p.get("status") == "active"]

    if len(active) >= MAX_CONCURRENT_PODS:
        raise ValueError(
            f"Cannot create pod: {len(active)} active pods "
            f"(max {MAX_CONCURRENT_PODS} pre-launch)"
        )

    if len(members) > 5:
        raise ValueError("Pods must have 2-5 members")
    if len(members) < 2:
        raise ValueError("Pods must have at least 2 members")

    criteria = exit_criteria or []
    pod = Pod(
        id=f"pod-{uuid.uuid4().hex[:8]}",
        name=name,
        mission=mission,
        lead=lead,
        members=members,
        duration_weeks=duration_weeks,
        start_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        exit_criteria=criteria,
        exit_criteria_met=[False] * len(criteria),
        cost_budget_per_day=cost_budget_per_day,
        status="active",
    )

    pods.append(pod.model_dump())
    _save_state(state)
    logger.info("Created pod: %s (%s)", pod.name, pod.id)
    return pod


def get_active_pods() -> list[Pod]:
    """Return all active pods."""
    state = _load_state()
    pods = state.get("pods", [])
    return [Pod(**p) for p in pods if p.get("status") == "active"]


def get_all_pods() -> list[Pod]:
    """Return all pods (active + dissolved)."""
    state = _load_state()
    return [Pod(**p) for p in state.get("pods", [])]


# ---------------------------------------------------------------------------
# Pod health check
# ---------------------------------------------------------------------------


def check_pod_health(pod: Pod) -> PodStatus:
    """Assess the health of an active pod."""
    now = datetime.now(timezone.utc)
    start = datetime.strptime(pod.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_elapsed = (now - start).days
    days_total = pod.duration_weeks * 7

    exit_met = sum(1 for m in pod.exit_criteria_met if m)
    exit_total = len(pod.exit_criteria)

    # Health assessment
    progress_pct = exit_met / exit_total if exit_total else 0.0
    time_pct = days_elapsed / days_total if days_total else 0.0

    if days_elapsed > days_total:
        health = "red"
        note = f"Overdue by {days_elapsed - days_total} days"
    elif time_pct > 0.7 and progress_pct < 0.3:
        health = "red"
        note = "Behind schedule — 70%+ time used, <30% criteria met"
    elif time_pct > 0.5 and progress_pct < 0.3:
        health = "yellow"
        note = "At risk — 50%+ time used, <30% criteria met"
    else:
        health = "green"
        note = "On track"

    return PodStatus(
        pod_id=pod.id,
        name=pod.name,
        days_elapsed=days_elapsed,
        days_total=days_total,
        exit_met=exit_met,
        exit_total=exit_total,
        health=health,
        note=note,
    )


def update_exit_criteria(pod_id: str, criteria_index: int, met: bool) -> None:
    """Mark a specific exit criterion as met or unmet."""
    state = _load_state()
    for p in state.get("pods", []):
        if p.get("id") == pod_id:
            criteria_met = p.get("exit_criteria_met", [])
            if 0 <= criteria_index < len(criteria_met):
                criteria_met[criteria_index] = met
                p["exit_criteria_met"] = criteria_met
                _save_state(state)
                return
    raise ValueError(f"Pod {pod_id} not found or invalid criteria index")


# ---------------------------------------------------------------------------
# Pod dissolution
# ---------------------------------------------------------------------------


def dissolve_pod(pod_id: str, outcomes: str = "", learnings: str = "") -> None:
    """Dissolve a pod — archives it with outcomes and learnings."""
    state = _load_state()
    for p in state.get("pods", []):
        if p.get("id") == pod_id and p.get("status") == "active":
            p["status"] = "dissolved"
            p["dissolved_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            p["outcomes"] = outcomes
            p["learnings"] = learnings
            _save_state(state)
            logger.info("Dissolved pod: %s (%s)", p.get("name"), pod_id)
            return
    raise ValueError(f"Active pod {pod_id} not found")


# ---------------------------------------------------------------------------
# Pod reporting
# ---------------------------------------------------------------------------


def get_pod_report() -> str:
    """Render the ACTIVE PODS section for the daily brief."""
    active = get_active_pods()
    if not active:
        return ""

    lines = ["### Active Pods\n"]
    for pod in active:
        status = check_pod_health(pod)
        icon = {"green": "[G]", "yellow": "[Y]", "red": "[R]"}.get(status.health, "[?]")
        members_str = ", ".join(m.get("agent", "?") for m in pod.members)
        lines.append(
            f"- {icon} **{pod.name}** (Day {status.days_elapsed}/{status.days_total}): "
            f"{status.exit_met}/{status.exit_total} exit criteria met. {status.note}"
        )
        lines.append(f"  - Lead: {pod.lead} | Members: {members_str}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Permanent pod detection (COS.md anti-pattern)
# ---------------------------------------------------------------------------


def detect_permanent_pods() -> list[str]:
    """Detect pods that have reformed 2+ times with the same members.

    Returns warnings for pods that should be restructured permanently.
    """
    state = _load_state()
    all_pods = state.get("pods", [])
    dissolved = [p for p in all_pods if p.get("status") == "dissolved"]

    # Group by member sets (frozenset of agent names)
    member_groups: dict[str, int] = {}
    member_names: dict[str, str] = {}
    for p in dissolved:
        agents = frozenset(m.get("agent", "") for m in p.get("members", []))
        key = "|".join(sorted(agents))
        member_groups[key] = member_groups.get(key, 0) + 1
        member_names[key] = p.get("name", "unnamed")

    warnings: list[str] = []
    for key, count in member_groups.items():
        if count >= 2:
            agents = key.replace("|", ", ")
            warnings.append(
                f"Pod with members [{agents}] has reformed {count} times — "
                f"consider permanent restructuring (last pod: {member_names[key]})"
            )

    return warnings
