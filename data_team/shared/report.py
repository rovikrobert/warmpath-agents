"""Data team report schema — Insight, KPISnapshot, DataTeamReport.

Imports Finding from engineering agents for cross-compatibility.
DataTeamReport exposes scan_duration_seconds for CoS cost tracking.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.shared.report import AgentReport, Finding


@dataclass
class Insight:
    """A data-driven insight from analysis."""

    id: str
    category: str  # funnel | engagement | marketplace | model | privacy
    title: str
    evidence: str
    impact: str
    recommendation: str
    confidence: float = 0.0  # 0.0 - 1.0
    statistical_significance: bool = False
    sample_size: int = 0
    actionable_by: str = ""  # team or person who should act


@dataclass
class KPISnapshot:
    """Point-in-time KPI measurement."""

    kpi_name: str
    current_value: float | str | None = None
    target_value: float | str | None = None
    trend: str = "stable"  # improving | stable | degrading | insufficient_data
    status: str = "unknown"  # green | yellow | red | unknown
    context: str = ""


@dataclass
class DataTeamReport:
    """Report produced by each data team agent.

    Compatible with CoS pipeline:
    - scan_duration_seconds feeds cost_tracker.py
    - findings (list[Finding]) are cross-compatible with engineering
    - cross_team_requests surface to CoS as CrossTeamRequest objects
    """

    agent: str
    timestamp: str = ""
    scan_duration_seconds: float = 0
    findings: list[Finding] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    kpi_snapshots: list[KPISnapshot] = field(default_factory=list)
    model_metrics: dict[str, Any] = field(default_factory=dict)
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
    def from_dict(cls, data: dict) -> DataTeamReport:
        findings = [Finding(**f) for f in data.pop("findings", [])]
        insights = [Insight(**i) for i in data.pop("insights", [])]
        kpi_snapshots = [KPISnapshot(**k) for k in data.pop("kpi_snapshots", [])]
        return cls(
            findings=findings,
            insights=insights,
            kpi_snapshots=kpi_snapshots,
            **data,
        )

    # -- Markdown rendering --------------------------------------------------

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.agent} Report")
        lines.append(
            f"*{self.timestamp}* — scanned in {self.scan_duration_seconds:.1f}s\n"
        )

        # KPI snapshots
        if self.kpi_snapshots:
            lines.append("## KPI Dashboard\n")
            lines.append("| KPI | Current | Target | Trend | Status |")
            lines.append("|-----|---------|--------|-------|--------|")
            for k in self.kpi_snapshots:
                lines.append(
                    f"| {k.kpi_name} | {k.current_value} | "
                    f"{k.target_value} | {k.trend} | {k.status} |"
                )
            lines.append("")

        # Insights
        if self.insights:
            lines.append(f"## Insights ({len(self.insights)})\n")
            for i in self.insights:
                lines.append(f"### [{i.id}] {i.title}")
                lines.append(f"**Category:** {i.category} | **Confidence:** {i.confidence:.0%}")
                lines.append(f"{i.evidence}")
                lines.append(f"**Impact:** {i.impact}")
                lines.append(f"**Recommendation:** {i.recommendation}")
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
