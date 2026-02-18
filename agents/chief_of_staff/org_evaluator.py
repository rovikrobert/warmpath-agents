"""Org restructuring evaluation — COS.md Section 7.

Evaluates triggers, runs agent value audits, and generates restructuring
proposals for the founder's review.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.shared.report import AgentReport

from .cos_config import COS_CONFIG, TEAM_REGISTRY
from .cos_learning import get_learning_summary
from .schemas import AgentAudit, OrgTrigger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trigger evaluation (COS.md 7.2)
# ---------------------------------------------------------------------------


def evaluate_triggers(
    reports: list[AgentReport],
    costs: dict[str, Any],
) -> list[OrgTrigger]:
    """Check all 4 trigger categories against live data.

    Returns a list of OrgTrigger objects for any triggers that fired.
    """
    triggers: list[OrgTrigger] = []
    triggers.extend(_check_performance_triggers(reports))
    triggers.extend(_check_structural_triggers(reports))
    triggers.extend(_check_cost_triggers(costs))
    return triggers


def _check_performance_triggers(reports: list[AgentReport]) -> list[OrgTrigger]:
    """Performance triggers: low output, idle agents, bottlenecks."""
    triggers: list[OrgTrigger] = []
    state = get_learning_summary()
    team_rel = state.get("team_reliability", {})

    for team, stats in team_rel.items():
        noise = stats.get("noise_ratio", 0.0)
        # High noise ratio suggests low-value output
        if noise > 0.5:
            triggers.append(
                OrgTrigger(
                    category="performance",
                    trigger=f"{team} has high noise ratio ({noise:.0%})",
                    evidence=f"{team} reports contain >50% info-severity findings",
                    severity="medium",
                    affected_teams=[team],
                )
            )

    # Check for agents with zero findings across multiple reports
    agent_findings: dict[str, int] = {}
    for r in reports:
        agent_findings[r.agent] = agent_findings.get(r.agent, 0) + len(r.findings)

    for agent, count in agent_findings.items():
        if count == 0:
            # Agent reporting but producing nothing — could be idle
            triggers.append(
                OrgTrigger(
                    category="performance",
                    trigger=f"{agent} produced zero findings",
                    evidence="Clean scan — may indicate agent is idle or scope is too narrow",
                    severity="low",
                    affected_teams=[_agent_to_team(agent)],
                )
            )

    return triggers


def _check_structural_triggers(reports: list[AgentReport]) -> list[OrgTrigger]:
    """Structural triggers: team size, overlapping agents."""
    triggers: list[OrgTrigger] = []

    # Count agents per team from reports
    team_agents: dict[str, set[str]] = {}
    for r in reports:
        team = _agent_to_team(r.agent)
        team_agents.setdefault(team, set()).add(r.agent)

    for team, agents in team_agents.items():
        if len(agents) > 6:
            triggers.append(
                OrgTrigger(
                    category="structural",
                    trigger=f"{team} has {len(agents)} agents (>6)",
                    evidence="Diminishing returns on coordination overhead",
                    severity="medium",
                    affected_teams=[team],
                )
            )
        elif len(agents) < 2 and team != "cos":
            triggers.append(
                OrgTrigger(
                    category="structural",
                    trigger=f"{team} has only {len(agents)} agent(s)",
                    evidence="May not justify team overhead — consider merging",
                    severity="low",
                    affected_teams=[team],
                )
            )

    return triggers


def _check_cost_triggers(costs: dict[str, Any]) -> list[OrgTrigger]:
    """Cost triggers: budget overruns, inefficient spending."""
    triggers: list[OrgTrigger] = []
    total = costs.get("total_estimated_cost_usd", 0.0)
    daily_cap = COS_CONFIG["cost_budget"].get("daily_cost_cap_usd", 3.0)

    if total > daily_cap:
        triggers.append(
            OrgTrigger(
                category="cost",
                trigger=f"Daily cost ${total:.2f} exceeds ${daily_cap:.2f} cap",
                evidence="Total daily cost exceeding budget",
                severity="high",
                affected_teams=["all"],
            )
        )

    # Check per-team cost from breakdown
    breakdown = costs.get("agent_breakdown", {})
    per_team_caps = COS_CONFIG["cost_budget"].get("per_team_cost_cap_usd", {})
    team_costs: dict[str, float] = {}
    for agent_name, agent_cost in breakdown.items():
        team = _agent_to_team(agent_name)
        team_costs[team] = team_costs.get(team, 0.0) + agent_cost.get(
            "estimated_cost_usd", 0.0
        )

    for team, cost in team_costs.items():
        cap = per_team_caps.get(team, 0.30)
        if cost > cap * 1.5:
            triggers.append(
                OrgTrigger(
                    category="cost",
                    trigger=f"{team} cost ${cost:.2f} exceeds 150% of ${cap:.2f} cap",
                    evidence=f"Team spending {cost / cap * 100:.0f}% of budget",
                    severity="medium",
                    affected_teams=[team],
                )
            )

    return triggers


# ---------------------------------------------------------------------------
# Agent value audit (COS.md 7.3)
# ---------------------------------------------------------------------------


def run_agent_value_audit(team: str, reports: list[AgentReport]) -> list[AgentAudit]:
    """Run value audit for all agents in a team based on report data."""
    state = get_learning_summary()
    team_rel = state.get("team_reliability", {}).get(team, {})
    audits: list[AgentAudit] = []

    team_reports = [r for r in reports if _agent_to_team(r.agent) == team]

    for r in team_reports:
        finding_count = len(r.findings)
        info_count = sum(1 for f in r.findings if f.severity == "info")
        info_ratio = info_count / finding_count if finding_count else 0.0
        cost = r.scan_duration_seconds * 0.001  # rough estimate

        # Determine verdict
        if finding_count == 0:
            verdict = "marginal"
        elif info_ratio > 0.7:
            verdict = "marginal"
        elif finding_count > 3 and info_ratio < 0.3:
            verdict = "essential"
        else:
            verdict = "valuable"

        audits.append(
            AgentAudit(
                agent=r.agent,
                team=team,
                reports_total=team_rel.get("reports_total", 0),
                findings_produced=finding_count,
                info_ratio=round(info_ratio, 3),
                cost_per_day=round(cost, 4),
                verdict=verdict,
            )
        )

    return audits


# ---------------------------------------------------------------------------
# Restructuring proposal (COS.md 7.4)
# ---------------------------------------------------------------------------


def generate_restructuring_proposal(triggers: list[OrgTrigger]) -> str:
    """Render triggered org changes as a markdown proposal."""
    if not triggers:
        return ""

    lines = ["## Org Restructuring Evaluation\n"]
    lines.append(f"**{len(triggers)} trigger(s) fired this week.**\n")

    by_category: dict[str, list[OrgTrigger]] = {}
    for t in triggers:
        by_category.setdefault(t.category, []).append(t)

    for category, trigs in by_category.items():
        lines.append(f"### {category.title()} Triggers\n")
        for t in trigs:
            severity_icon = {
                "critical": "[!!]",
                "high": "[!]",
                "medium": "[~]",
                "low": "[.]",
            }.get(t.severity, "[?]")
            lines.append(f"- {severity_icon} **{t.trigger}**")
            if t.evidence:
                lines.append(f"  - Evidence: {t.evidence}")
            if t.affected_teams:
                lines.append(f"  - Affected: {', '.join(t.affected_teams)}")
        lines.append("")

    # Add recommendation based on highest severity
    severities = [t.severity for t in triggers]
    if "critical" in severities or "high" in severities:
        lines.append("### CoS Recommendation\n")
        lines.append(
            "Schedule founder review this week to discuss restructuring options."
        )
    else:
        lines.append("### CoS Recommendation\n")
        lines.append("Monitor — no immediate action required. Re-evaluate next week.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_to_team(agent: str) -> str:
    """Map an agent name to its team using TEAM_REGISTRY."""
    for team, agents in TEAM_REGISTRY.items():
        if agent in agents:
            return team
    return "engineering"  # default
