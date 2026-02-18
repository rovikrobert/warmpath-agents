"""Finance team report schema — FinancialInsight, CreditEconomyFinding, ComplianceFinding, FinanceTeamReport.

Imports Finding from engineering agents for cross-compatibility.
FinanceTeamReport exposes scan_duration_seconds for CoS cost tracking.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.shared.report import AgentReport, Finding


@dataclass
class FinancialInsight:
    """A financial insight from cost/revenue/credit analysis."""

    id: str
    category: str  # cost_efficiency | revenue | credit_economy | compliance | investor_readiness | budget
    title: str
    evidence: str
    impact: str
    recommendation: str
    confidence: float = 0.0  # 0.0 - 1.0
    urgency: str = ""  # critical | high | medium | low
    actionable_by: str = ""  # team or person who should act


@dataclass
class CreditEconomyFinding:
    """A credit economy finding from earn/spend/velocity analysis."""

    id: str
    category: (
        str  # earn_spend_balance | velocity | distribution | abuse | pricing | expiry
    )
    severity: str  # critical | high | medium | low | info
    title: str
    file: str = ""
    line: int = 0
    detail: str = ""
    recommendation: str = ""


@dataclass
class ComplianceFinding:
    """A regulatory/legal compliance finding."""

    id: str
    category: str  # privacy | financial_regulation | corporate | employment | contract
    severity: str  # critical | high | medium | low | info
    title: str
    regulation: str = ""  # e.g. GDPR, PDPA, FinCEN, Global
    file: str = ""
    detail: str = ""
    recommendation: str = ""
    deadline: str | None = None  # optional compliance deadline


@dataclass
class FinanceTeamReport:
    """Report produced by each finance team agent.

    Compatible with CoS pipeline:
    - scan_duration_seconds feeds cost_tracker.py
    - findings (list[Finding]) are cross-compatible with engineering
    - cross_team_requests surface to CoS as CrossTeamRequest objects
    """

    agent: str
    timestamp: str = ""
    scan_duration_seconds: float = 0
    findings: list[Finding] = field(default_factory=list)
    financial_findings: list[Finding] = field(default_factory=list)
    credit_findings: list[CreditEconomyFinding] = field(default_factory=list)
    compliance_findings: list[ComplianceFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    intelligence_applied: list[str] = field(default_factory=list)
    learning_updates: list[str] = field(default_factory=list)
    cost_snapshots: list[Any] = field(default_factory=list)  # list[CostSnapshot]
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
    def from_dict(cls, data: dict) -> FinanceTeamReport:
        findings = [Finding(**f) for f in data.pop("findings", [])]
        financial_findings = [Finding(**f) for f in data.pop("financial_findings", [])]
        credit_findings = [
            CreditEconomyFinding(**c) for c in data.pop("credit_findings", [])
        ]
        compliance_findings = [
            ComplianceFinding(**c) for c in data.pop("compliance_findings", [])
        ]
        return cls(
            findings=findings,
            financial_findings=financial_findings,
            credit_findings=credit_findings,
            compliance_findings=compliance_findings,
            **data,
        )

    # -- Markdown rendering --------------------------------------------------

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.agent} Report")
        lines.append(
            f"*{self.timestamp}* — scanned in {self.scan_duration_seconds:.1f}s\n"
        )

        sev_icons = {
            "critical": "!!",
            "high": "!",
            "medium": "~",
            "low": ".",
            "info": " ",
        }

        # Financial findings
        if self.financial_findings:
            lines.append(f"## Financial Findings ({len(self.financial_findings)})\n")
            for f in sorted(self.financial_findings, key=lambda f: f.sort_key):
                icon = sev_icons.get(f.severity, "")
                lines.append(f"- [{f.severity.upper()}]{icon} **{f.title}**")
                if f.file:
                    lines.append(f"  - `{f.file}:{f.line or ''}`")
                if getattr(f, "detail", ""):
                    lines.append(f"  - {f.detail}")
                if f.recommendation:
                    lines.append(f"  - {f.recommendation}")
            lines.append("")

        # Credit economy findings
        if self.credit_findings:
            lines.append(f"## Credit Economy Findings ({len(self.credit_findings)})\n")
            for c in self.credit_findings:
                loc = f"`{c.file}:{c.line}`" if c.file else ""
                lines.append(f"- [{c.severity.upper()}] **{c.title}** {loc}")
                if c.detail:
                    lines.append(f"  - {c.detail}")
                if c.recommendation:
                    lines.append(f"  - {c.recommendation}")
            lines.append("")

        # Compliance findings
        if self.compliance_findings:
            lines.append(f"## Compliance Findings ({len(self.compliance_findings)})\n")
            for c in self.compliance_findings:
                reg = f" ({c.regulation})" if c.regulation else ""
                lines.append(f"- [{c.severity.upper()}]{reg} **{c.title}**")
                if c.detail:
                    lines.append(f"  - {c.detail}")
                if c.recommendation:
                    lines.append(f"  - {c.recommendation}")
                if c.deadline:
                    lines.append(f"  - **Deadline:** {c.deadline}")
            lines.append("")

        # Findings (same format as engineering)
        if self.findings:
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
        # Merge financial_findings into findings for CoS
        all_findings = list(self.findings) + list(self.financial_findings)
        return AgentReport(
            agent=self.agent,
            timestamp=self.timestamp,
            scan_duration_seconds=self.scan_duration_seconds,
            findings=all_findings,
            metrics=self.metrics,
            intelligence_applied=self.intelligence_applied,
            learning_updates=self.learning_updates,
        )


# ---------------------------------------------------------------------------
# Aliases for backward compatibility with agent imports
# ---------------------------------------------------------------------------

FinancialFinding = Finding  # agents use Finding-compatible fields (id, category, severity, title, file, detail, recommendation)


@dataclass
class CostSnapshot:
    """Snapshot of estimated cost for an agent team scan."""

    team: str
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0
    duration_seconds: float = 0.0
