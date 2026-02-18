"""Budget enforcement — throttle teams when they exceed cost caps.

Moves beyond alerting to actually recommending throttle actions (model
downgrades, scan skipping) when budgets are exceeded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .cos_config import COS_CONFIG
from .cos_learning import _load_state, _save_state
from .schemas import BudgetAction

logger = logging.getLogger(__name__)


def enforce_budget(
    costs: dict[str, Any],
) -> list[BudgetAction]:
    """Evaluate team costs and return enforcement actions.

    Actions: 'ok' (within budget), 'warn' (>100% but <150%), 'throttle' (>150%).
    """
    actions: list[BudgetAction] = []
    budget_cfg = COS_CONFIG["cost_budget"]
    per_team_caps = budget_cfg.get("per_team_cost_cap_usd", {})
    alert_pct = budget_cfg.get("alert_threshold_pct", 150) / 100.0

    # Compute per-team costs from agent breakdown
    breakdown = costs.get("agent_breakdown", {})
    team_costs: dict[str, float] = {}
    for agent_name, agent_cost in breakdown.items():
        team = _agent_to_team(agent_name)
        team_costs[team] = team_costs.get(team, 0.0) + agent_cost.get(
            "estimated_cost_usd", 0.0
        )

    for team, cap in per_team_caps.items():
        current = team_costs.get(team, 0.0)
        if cap <= 0:
            continue

        ratio = current / cap
        if ratio >= alert_pct:
            actions.append(
                BudgetAction(
                    team=team,
                    action="throttle",
                    reason=f"Cost ${current:.2f} is {ratio:.0%} of ${cap:.2f} cap",
                    current_cost=round(current, 4),
                    budget_cap=cap,
                    recommendation=f"Downgrade {team} agents to Haiku for remaining scans today",
                )
            )
        elif ratio >= 1.0:
            actions.append(
                BudgetAction(
                    team=team,
                    action="warn",
                    reason=f"Cost ${current:.2f} is {ratio:.0%} of ${cap:.2f} cap",
                    current_cost=round(current, 4),
                    budget_cap=cap,
                    recommendation=f"Monitor {team} — approaching throttle threshold",
                )
            )
        else:
            actions.append(
                BudgetAction(
                    team=team,
                    action="ok",
                    reason=f"Within budget ({ratio:.0%})",
                    current_cost=round(current, 4),
                    budget_cap=cap,
                )
            )

    # Check total daily cap
    total = costs.get("total_estimated_cost_usd", 0.0)
    daily_cap = budget_cfg.get("daily_cost_cap_usd", 3.0)
    if daily_cap > 0 and total / daily_cap >= alert_pct:
        actions.append(
            BudgetAction(
                team="all",
                action="throttle",
                reason=f"Total cost ${total:.2f} exceeds {alert_pct:.0%} of ${daily_cap:.2f}",
                current_cost=round(total, 4),
                budget_cap=daily_cap,
                recommendation="Skip non-critical scans for the rest of today",
            )
        )

    return actions


def get_throttle_status() -> dict[str, str]:
    """Return per-team throttle state from cos_state.json."""
    state = _load_state()
    return state.get("throttle_status", {})


def update_throttle_status(actions: list[BudgetAction]) -> None:
    """Persist throttle decisions to cos_state.json."""
    state = _load_state()
    throttle = state.setdefault("throttle_status", {})
    now = datetime.now(timezone.utc).isoformat()

    for a in actions:
        if a.action == "throttle":
            throttle[a.team] = {
                "status": "throttled",
                "reason": a.reason,
                "recommendation": a.recommendation,
                "since": now,
            }
        elif a.action == "ok" and a.team in throttle:
            # Clear throttle when back within budget
            del throttle[a.team]

    _save_state(state)


def should_throttle_team(team: str) -> bool:
    """Check if a team should be throttled before running scans."""
    status = get_throttle_status()
    team_throttle = status.get(team, {})
    if isinstance(team_throttle, dict):
        return team_throttle.get("status") == "throttled"
    return False


def get_budget_enforcement_report(actions: list[BudgetAction]) -> str:
    """Render budget enforcement actions as markdown for the daily brief."""
    throttled = [a for a in actions if a.action == "throttle"]
    warned = [a for a in actions if a.action == "warn"]

    if not throttled and not warned:
        return ""

    lines = ["### Budget Enforcement\n"]
    if throttled:
        for a in throttled:
            lines.append(f"- [THROTTLED] **{a.team}**: {a.reason}")
            lines.append(f"  - Action: {a.recommendation}")
    if warned:
        for a in warned:
            lines.append(f"- [WARNING] **{a.team}**: {a.reason}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_to_team(agent: str) -> str:
    """Map an agent name to its team."""
    from .cos_config import TEAM_REGISTRY

    for team, agents in TEAM_REGISTRY.items():
        if agent in agents:
            return team
    return "engineering"
