"""Cost tracking — per-agent cost estimation and budget alerts."""

from __future__ import annotations

from typing import Any

from agents.shared.report import AgentReport

# Rough cost estimate: ~$0.003 per 1K tokens (Claude Haiku-class for agents)
_COST_PER_SECOND = 0.001  # Rough proxy: $0.001 per second of scan time
_TOKENS_PER_SECOND = 50  # Rough estimate of token throughput


def get_agent_costs(reports: list[AgentReport]) -> dict[str, dict[str, Any]]:
    """Per-agent cost from scan_duration_seconds + token estimates."""
    costs: dict[str, dict[str, Any]] = {}
    for r in reports:
        duration = r.scan_duration_seconds
        est_tokens = int(duration * _TOKENS_PER_SECOND)
        est_cost = round(duration * _COST_PER_SECOND, 4)
        costs[r.agent] = {
            "duration_seconds": round(duration, 1),
            "estimated_tokens": est_tokens,
            "estimated_cost_usd": est_cost,
        }
    return costs


def get_team_cost_summary(reports: list[AgentReport]) -> dict[str, Any]:
    """Total cost, per-agent breakdown, budget utilization."""
    agent_costs = get_agent_costs(reports)
    total_duration = sum(c["duration_seconds"] for c in agent_costs.values())
    total_tokens = sum(c["estimated_tokens"] for c in agent_costs.values())
    total_cost = sum(c["estimated_cost_usd"] for c in agent_costs.values())

    return {
        "total_duration_seconds": round(total_duration, 1),
        "total_estimated_tokens": total_tokens,
        "total_estimated_cost_usd": round(total_cost, 4),
        "agent_breakdown": agent_costs,
        "agent_count": len(agent_costs),
    }


def check_budget_alerts(
    costs: dict[str, Any], budgets: dict[str, Any]
) -> list[str]:
    """Flag agents/teams exceeding budget thresholds.

    Args:
        costs: Output of get_team_cost_summary()
        budgets: Budget config with keys like total_daily_max_tokens,
                 alert_threshold_pct
    """
    alerts: list[str] = []
    threshold_pct = budgets.get("alert_threshold_pct", 150)
    max_tokens = budgets.get("total_daily_max_tokens", 25000)

    total_tokens = costs.get("total_estimated_tokens", 0)
    if max_tokens > 0:
        utilization = (total_tokens / max_tokens) * 100
        if utilization >= threshold_pct:
            alerts.append(
                f"Total token usage ({total_tokens}) is at "
                f"{utilization:.0f}% of daily budget ({max_tokens})"
            )

    cos_max = budgets.get("cos_daily_max_tokens", 3000)
    cos_tokens = costs.get("agent_breakdown", {}).get(
        "chief_of_staff", {}
    ).get("estimated_tokens", 0)
    if cos_max > 0 and cos_tokens > 0:
        cos_util = (cos_tokens / cos_max) * 100
        if cos_util >= threshold_pct:
            alerts.append(
                f"CoS token usage ({cos_tokens}) is at "
                f"{cos_util:.0f}% of budget ({cos_max})"
            )

    return alerts
