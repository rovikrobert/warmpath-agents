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
    founder_requests: list[dict[str, Any]] = Field(default_factory=list)
    resolutions: list[dict[str, Any]] = Field(default_factory=list)
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


# ---------------------------------------------------------------------------
# Org restructuring models (COS.md Section 7)
# ---------------------------------------------------------------------------


class OrgTrigger(BaseModel):
    """A trigger that fires when org structure evaluation is needed."""

    category: str  # performance | business | structural | cost
    trigger: str
    evidence: str = ""
    severity: str = "medium"  # critical | high | medium | low
    affected_teams: list[str] = Field(default_factory=list)


class AgentAudit(BaseModel):
    """Result of an agent value audit (COS.md 7.3)."""

    agent: str
    team: str
    reports_total: int = 0
    findings_produced: int = 0
    info_ratio: float = 0.0
    idle_ratio: float = 0.0
    cost_per_day: float = 0.0
    verdict: str = "valuable"  # essential | valuable | marginal | redundant


# ---------------------------------------------------------------------------
# Pod lifecycle models (COS.md Section 7.9)
# ---------------------------------------------------------------------------


class Pod(BaseModel):
    """A temporary cross-functional working group."""

    id: str
    name: str
    mission: str
    lead: str
    members: list[dict[str, str]] = Field(default_factory=list)  # [{agent, team, role}]
    duration_weeks: int = 2
    start_date: str = ""
    exit_criteria: list[str] = Field(default_factory=list)
    exit_criteria_met: list[bool] = Field(default_factory=list)
    cost_budget_per_day: float = 0.0
    status: str = "active"  # active | dissolved


class PodStatus(BaseModel):
    """Health check result for an active pod."""

    pod_id: str
    name: str
    days_elapsed: int = 0
    days_total: int = 14
    exit_met: int = 0
    exit_total: int = 0
    health: str = "green"  # green | yellow | red
    note: str = ""


# ---------------------------------------------------------------------------
# Cross-team request tracking (Gap 6)
# ---------------------------------------------------------------------------


class TrackedRequest(BaseModel):
    """A cross-team request that has been routed and is being tracked."""

    id: str
    source_agent: str
    request: str
    urgency: str = "medium"
    routed_to: str = ""
    status: str = "pending"  # pending | routed | resolved
    created_date: str = ""
    resolved_date: str = ""


# ---------------------------------------------------------------------------
# Budget enforcement (Gap 7)
# ---------------------------------------------------------------------------


class BudgetAction(BaseModel):
    """Action to take when a team exceeds its budget."""

    team: str
    action: str  # throttle | warn | ok
    reason: str = ""
    current_cost: float = 0.0
    budget_cap: float = 0.0
    recommendation: str = ""
