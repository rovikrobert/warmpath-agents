"""GTM team report schema — MarketInsight, PartnershipOpportunity, PricingExperiment,
ComplianceReviewItem, GTMTeamReport.

Imports Finding from engineering agents for cross-compatibility.
GTMTeamReport exposes scan_duration_seconds for CoS cost tracking.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.shared.report import AgentReport, Finding


@dataclass
class MarketInsight:
    """A market or competitive insight."""

    id: str
    category: (
        str  # competitive | market_entry | pricing | channel | partnership | compliance
    )
    title: str
    evidence: str = ""
    strategic_impact: str = ""
    recommended_response: str = ""
    urgency: str = "monitor"  # immediate | this_week | this_month | monitor
    confidence: str = "medium"  # high | medium | low


@dataclass
class PartnershipOpportunity:
    """A partnership or co-marketing opportunity."""

    id: str
    partner_name: str
    partner_type: str = (
        ""  # bootcamp | university | association | co_marketing | strategic
    )
    value_prop_to_them: str = ""
    value_prop_to_us: str = ""
    estimated_user_impact: str = ""
    estimated_revenue_impact: str = ""
    effort: str = "medium"  # low | medium | high
    stage: str = "identified"  # identified | outreach | conversation | proposal | negotiation | signed
    next_action: str = ""
    legal_review_required: bool = False
    legal_review_status: str = (
        "not_required"  # pending | approved | blocked | not_required
    )


@dataclass
class PricingExperiment:
    """A pricing experiment design or result."""

    id: str
    hypothesis: str = ""
    test_design: str = ""
    metrics_to_track: list[str] = field(default_factory=list)
    status: str = "designed"  # designed | running | completed | analyzed
    result: str = ""
    recommendation: str = ""
    credits_manager_impact: str = ""


@dataclass
class ComplianceReviewItem:
    """A marketing compliance review request/result."""

    id: str
    asset_type: str = (
        ""  # email_campaign | landing_page | content | ad | partnership | launch
    )
    description: str = ""
    jurisdiction: str = "global"  # US | Singapore | EU | APAC | global
    submitted_date: str = ""
    reviewer: str = ""  # legal_agent | privy_agent | both
    status: str = "pending"  # pending | approved | approved_with_changes | blocked
    changes_required: str = ""
    resolution_date: str = ""


@dataclass
class GTMTeamReport:
    """Report produced by each GTM team agent.

    Compatible with CoS pipeline:
    - scan_duration_seconds feeds cost_tracker.py
    - findings (list[Finding]) are cross-compatible with engineering
    - cross_team_requests surface to CoS as CrossTeamRequest objects
    """

    agent: str
    timestamp: str = ""
    scan_duration_seconds: float = 0
    findings: list[Finding] = field(default_factory=list)
    market_insights: list[MarketInsight] = field(default_factory=list)
    partnership_opportunities: list[PartnershipOpportunity] = field(
        default_factory=list
    )
    pricing_experiments: list[PricingExperiment] = field(default_factory=list)
    compliance_reviews: list[ComplianceReviewItem] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    intelligence_applied: list[str] = field(default_factory=list)
    learning_updates: list[str] = field(default_factory=list)
    cross_team_requests: list[dict[str, Any]] = field(default_factory=list)
    strategy_divergences: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    # -- Serialisation -------------------------------------------------------

    def serialize(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> GTMTeamReport:
        findings = [Finding(**f) for f in data.pop("findings", [])]
        market_insights = [MarketInsight(**i) for i in data.pop("market_insights", [])]
        partnerships = [
            PartnershipOpportunity(**p)
            for p in data.pop("partnership_opportunities", [])
        ]
        pricing = [PricingExperiment(**e) for e in data.pop("pricing_experiments", [])]
        compliance = [
            ComplianceReviewItem(**c) for c in data.pop("compliance_reviews", [])
        ]
        return cls(
            findings=findings,
            market_insights=market_insights,
            partnership_opportunities=partnerships,
            pricing_experiments=pricing,
            compliance_reviews=compliance,
            **data,
        )

    # -- Markdown rendering --------------------------------------------------

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.agent} Report")
        lines.append(
            f"*{self.timestamp}* — scanned in {self.scan_duration_seconds:.1f}s\n"
        )

        # Market insights
        if self.market_insights:
            lines.append(f"## Market Insights ({len(self.market_insights)})\n")
            for i in self.market_insights:
                lines.append(f"### [{i.id}] {i.title}")
                lines.append(
                    f"**Category:** {i.category} | **Urgency:** {i.urgency} | **Confidence:** {i.confidence}"
                )
                if i.evidence:
                    lines.append(f"{i.evidence}")
                if i.strategic_impact:
                    lines.append(f"**Impact:** {i.strategic_impact}")
                if i.recommended_response:
                    lines.append(f"**Response:** {i.recommended_response}")
                lines.append("")

        # Partnership opportunities
        if self.partnership_opportunities:
            lines.append(
                f"## Partnership Opportunities ({len(self.partnership_opportunities)})\n"
            )
            for p in self.partnership_opportunities:
                lines.append(
                    f"- **[{p.id}] {p.partner_name}** ({p.partner_type}, stage: {p.stage})"
                )
                if p.value_prop_to_us:
                    lines.append(f"  - Value to us: {p.value_prop_to_us}")
                if p.next_action:
                    lines.append(f"  - Next: {p.next_action}")
            lines.append("")

        # Pricing experiments
        if self.pricing_experiments:
            lines.append(f"## Pricing Experiments ({len(self.pricing_experiments)})\n")
            for e in self.pricing_experiments:
                lines.append(f"- **[{e.id}]** {e.hypothesis} (status: {e.status})")
            lines.append("")

        # Compliance reviews
        if self.compliance_reviews:
            lines.append(f"## Compliance Reviews ({len(self.compliance_reviews)})\n")
            for c in self.compliance_reviews:
                lines.append(
                    f"- **[{c.id}]** {c.asset_type}: {c.description} — {c.status}"
                )
            lines.append("")

        # Findings (same format as engineering)
        if self.findings:
            sev_icons = {
                "critical": "!!",
                "high": "!",
                "medium": "~",
                "low": ".",
                "info": " ",
            }
            lines.append(f"## Findings ({len(self.findings)})\n")
            for f in sorted(self.findings, key=lambda f: f.sort_key):
                icon = sev_icons.get(f.severity, "")
                lines.append(f"- [{f.severity.upper()}]{icon} **{f.title}**")
                if f.file:
                    lines.append(f"  - `{f.file}:{f.line or ''}`")
                if f.recommendation:
                    lines.append(f"  - {f.recommendation}")
            lines.append("")

        # Metrics
        if self.metrics:
            lines.append("## Metrics\n")
            for k, v in self.metrics.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

        # Strategy divergences
        if self.strategy_divergences:
            lines.append("## Strategy Divergences\n")
            for d in self.strategy_divergences:
                lines.append(f"- {d}")
            lines.append("")

        # Cross-team requests
        if self.cross_team_requests:
            lines.append("## Cross-Team Requests\n")
            for r in self.cross_team_requests:
                lines.append(f"- [{r.get('urgency', 'medium')}] {r.get('request', '')}")
            lines.append("")

        return "\n".join(lines)

    # -- CoS compatibility ---------------------------------------------------

    def to_agent_report(self) -> AgentReport:
        """Convert to AgentReport for CoS consumption."""
        return AgentReport(
            agent=self.agent,
            timestamp=self.timestamp,
            scan_duration_seconds=self.scan_duration_seconds,
            findings=list(self.findings),
            metrics=self.metrics,
            intelligence_applied=self.intelligence_applied,
            learning_updates=self.learning_updates,
        )
