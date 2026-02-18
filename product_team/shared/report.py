"""Product team report schema — ProductInsight, UXFinding, DesignFinding, ProductTeamReport.

Imports Finding from engineering agents for cross-compatibility.
ProductTeamReport exposes scan_duration_seconds for CoS cost tracking.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.shared.report import AgentReport, Finding


@dataclass
class ProductInsight:
    """A product-level insight from analysis."""

    id: str
    category: str  # feature_coverage | journey | persona | competitive | strategy
    title: str
    evidence: str
    impact: str
    recommendation: str
    confidence: float = 0.0  # 0.0 - 1.0
    persona: str = ""  # job_seeker | network_holder | both
    rice_score: float = 0.0
    actionable_by: str = ""  # team or person who should act


@dataclass
class UXFinding:
    """A UX-specific finding from frontend analysis."""

    id: str
    category: str  # accessibility | loading_state | error_state | empty_state | form_validation | responsive | privacy_ui | flow
    severity: str  # critical | high | medium | low | info
    title: str
    file: str = ""
    line: int = 0
    detail: str = ""
    heuristic: str = ""  # Which UX heuristic was violated
    recommendation: str = ""


@dataclass
class DesignFinding:
    """A design-system-specific finding from frontend analysis."""

    id: str
    category: str  # color | spacing | typography | component | dark_mode | animation | consistency
    severity: str  # critical | high | medium | low | info
    title: str
    file: str = ""
    line: int = 0
    detail: str = ""
    recommendation: str = ""


@dataclass
class ProductTeamReport:
    """Report produced by each product team agent.

    Compatible with CoS pipeline:
    - scan_duration_seconds feeds cost_tracker.py
    - findings (list[Finding]) are cross-compatible with engineering
    - cross_team_requests surface to CoS as CrossTeamRequest objects
    """

    agent: str
    timestamp: str = ""
    scan_duration_seconds: float = 0
    findings: list[Finding] = field(default_factory=list)
    product_insights: list[ProductInsight] = field(default_factory=list)
    ux_findings: list[UXFinding] = field(default_factory=list)
    design_findings: list[DesignFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    intelligence_applied: list[str] = field(default_factory=list)
    learning_updates: list[str] = field(default_factory=list)
    cross_team_requests: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    # -- Serialisation -------------------------------------------------------

    def serialize(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ProductTeamReport:
        findings = [Finding(**f) for f in data.pop("findings", [])]
        product_insights = [
            ProductInsight(**i) for i in data.pop("product_insights", [])
        ]
        ux_findings = [UXFinding(**u) for u in data.pop("ux_findings", [])]
        design_findings = [DesignFinding(**d) for d in data.pop("design_findings", [])]
        return cls(
            findings=findings,
            product_insights=product_insights,
            ux_findings=ux_findings,
            design_findings=design_findings,
            **data,
        )

    # -- Markdown rendering --------------------------------------------------

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.agent} Report")
        lines.append(
            f"*{self.timestamp}* — scanned in {self.scan_duration_seconds:.1f}s\n"
        )

        # Product insights
        if self.product_insights:
            lines.append(f"## Product Insights ({len(self.product_insights)})\n")
            for i in self.product_insights:
                lines.append(f"### [{i.id}] {i.title}")
                lines.append(
                    f"**Category:** {i.category} | **Confidence:** {i.confidence:.0%}"
                )
                if i.persona:
                    lines.append(f"**Persona:** {i.persona}")
                lines.append(f"{i.evidence}")
                lines.append(f"**Impact:** {i.impact}")
                lines.append(f"**Recommendation:** {i.recommendation}")
                lines.append("")

        # UX findings
        if self.ux_findings:
            lines.append(f"## UX Findings ({len(self.ux_findings)})\n")
            for u in self.ux_findings:
                loc = f"`{u.file}:{u.line}`" if u.file else ""
                lines.append(f"- [{u.severity.upper()}] **{u.title}** {loc}")
                if u.detail:
                    lines.append(f"  - {u.detail}")
                if u.recommendation:
                    lines.append(f"  - {u.recommendation}")
            lines.append("")

        # Design findings
        if self.design_findings:
            lines.append(f"## Design Findings ({len(self.design_findings)})\n")
            for d in self.design_findings:
                loc = f"`{d.file}:{d.line}`" if d.file else ""
                lines.append(f"- [{d.severity.upper()}] **{d.title}** {loc}")
                if d.detail:
                    lines.append(f"  - {d.detail}")
                if d.recommendation:
                    lines.append(f"  - {d.recommendation}")
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
