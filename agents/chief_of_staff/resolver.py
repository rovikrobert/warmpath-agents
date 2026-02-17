"""Conflict resolution framework for cross-team disagreements."""

from __future__ import annotations

from agents.shared.business_outcomes import OUTCOME_PRIORITY, OUTCOME_LABELS

from .cos_config import DECISION_PRINCIPLES
from .schemas import Conflict, Resolution


def attempt_resolution(conflict: Conflict) -> Resolution:
    """Attempt to resolve a conflict using the 4-level resolution framework.

    Level 1: Context clarification — check if additional info resolves it
    Level 2: Trade-off framing — use business outcome priorities
    Level 3: Compromise — scope cut, sequencing, or parallel track
    Level 4: Escalate — present both positions + CoS recommendation to founder
    """
    # Level 1: Context clarification
    if conflict.resolution_level <= 1:
        resolution = _try_context_resolution(conflict)
        if resolution:
            return resolution

    # Level 2: Trade-off against business outcomes
    if conflict.resolution_level <= 2:
        resolution = _try_tradeoff_resolution(conflict)
        if resolution:
            return resolution

    # Level 3: Compromise
    if conflict.resolution_level <= 3:
        resolution = _try_compromise(conflict)
        if resolution:
            return resolution

    # Level 4: Escalate to founder
    return _escalate_to_founder(conflict)


def _try_context_resolution(conflict: Conflict) -> Resolution | None:
    """Level 1: Check if the conflict resolves with shared context."""
    # If one side has no evidence, the other side's position stands
    teams_with_evidence = [
        team for team in conflict.teams
        if conflict.evidence.get(team)
    ]
    if len(teams_with_evidence) == 1:
        winner = teams_with_evidence[0]
        return Resolution(
            conflict_id=conflict.id,
            strategy_used="context_clarification",
            outcome=f"Resolved in favor of {winner} (only team with supporting evidence)",
            escalated=False,
        )
    return None


def _try_tradeoff_resolution(conflict: Conflict) -> Resolution | None:
    """Level 2: Frame as trade-off against business outcome priorities."""
    # Map each team's position to the highest-priority outcome it serves
    team_priorities: dict[str, int] = {}
    for team, position in conflict.positions.items():
        best_priority = len(DECISION_PRINCIPLES)
        pos_lower = position.lower()
        for i, principle in enumerate(DECISION_PRINCIPLES):
            if principle in pos_lower or _principle_keyword_match(principle, pos_lower):
                best_priority = min(best_priority, i)
        team_priorities[team] = best_priority

    if not team_priorities:
        return None

    # If one team clearly serves a higher-priority outcome
    sorted_teams = sorted(team_priorities.items(), key=lambda x: x[1])
    if len(sorted_teams) >= 2 and sorted_teams[0][1] < sorted_teams[1][1]:
        winner = sorted_teams[0][0]
        principle = DECISION_PRINCIPLES[sorted_teams[0][1]]
        return Resolution(
            conflict_id=conflict.id,
            strategy_used="tradeoff_framing",
            outcome=(
                f"Resolved in favor of {winner} — aligns with higher-priority "
                f"principle: {principle}"
            ),
            escalated=False,
        )

    return None


def _principle_keyword_match(principle: str, text: str) -> bool:
    """Check if a decision principle is referenced in text."""
    keywords: dict[str, list[str]] = {
        "safety_privacy": ["safety", "privacy", "security", "pii", "breach"],
        "help_job_seekers": ["job seeker", "referral", "candidate", "demand"],
        "network_builders": ["network holder", "supply", "upload", "connector"],
        "billion_dollar": ["scale", "infrastructure", "reliability", "billion"],
        "cost_efficiency": ["cost", "budget", "efficient", "optimize", "spend"],
    }
    return any(kw in text for kw in keywords.get(principle, []))


def _try_compromise(conflict: Conflict) -> Resolution | None:
    """Level 3: Propose a compromise — scope cut, sequencing, or parallel."""
    if len(conflict.teams) < 2:
        return None

    teams_str = " and ".join(conflict.teams)
    return Resolution(
        conflict_id=conflict.id,
        strategy_used="compromise",
        outcome=(
            f"Proposed compromise between {teams_str}: "
            f"sequence the work — address the higher-priority concern first, "
            f"then revisit the secondary concern in the next cycle"
        ),
        escalated=False,
    )


def _escalate_to_founder(conflict: Conflict) -> Resolution:
    """Level 4: Escalate with both positions + CoS recommendation."""
    positions_summary = "; ".join(
        f"{team}: {pos}" for team, pos in conflict.positions.items()
    )
    return Resolution(
        conflict_id=conflict.id,
        strategy_used="escalation",
        outcome=(
            f"Escalated to founder. Positions: {positions_summary}. "
            f"CoS recommendation: {conflict.cos_recommendation or 'See details'}"
        ),
        escalated=True,
    )
