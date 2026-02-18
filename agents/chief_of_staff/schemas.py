"""Pydantic models for the Chief of Staff agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CosFinding(BaseModel):
    """Engineering finding enriched with business context."""

    id: str
    severity: str  # critical | high | medium | low | info
    category: str
    summary: str
    evidence: str = ""
    business_impact: str = ""
    recommended_action: str = ""
    effort_estimate: str = ""
    outcome_alignment: list[str] = Field(default_factory=list)


class CrossTeamRequest(BaseModel):
    """A request from one team that needs another team's involvement."""

    team: str
    request: str
    urgency: str = "medium"  # critical | high | medium | low
    blocking: str | None = None


class TeamReport(BaseModel):
    """Synthesized report from a single team."""

    team: str
    date: str
    report_type: str = "daily"  # daily | weekly | ad_hoc
    findings: list[CosFinding] = Field(default_factory=list)
    needs_from_other_teams: list[CrossTeamRequest] = Field(default_factory=list)
    kpis: dict[str, Any] = Field(default_factory=dict)


class FounderBrief(BaseModel):
    """The daily brief delivered to the founder."""

    date: str
    decisions_needed: list[dict[str, Any]] = Field(default_factory=list)
    key_updates: list[dict[str, Any]] = Field(default_factory=list)
    progress: list[dict[str, Any]] = Field(default_factory=list)
    cross_team_requests: list[dict[str, Any]] = Field(default_factory=list)
    operational_health: list[dict[str, Any]] = Field(default_factory=list)
    cost_summary: dict[str, Any] = Field(default_factory=dict)
    kpi_snapshot: str = ""


class Conflict(BaseModel):
    """A cross-team conflict requiring resolution."""

    id: str
    teams: list[str]
    description: str
    positions: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    cos_recommendation: str = ""
    resolution_level: int = 1  # 1-4 (1=context, 2=trade-off, 3=compromise, 4=escalate)


class Resolution(BaseModel):
    """Outcome of a conflict resolution attempt."""

    conflict_id: str
    strategy_used: str
    outcome: str
    escalated: bool = False
    founder_agreed: bool | None = None
