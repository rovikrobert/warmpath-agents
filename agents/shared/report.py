"""Shared report schema — Finding, AgentReport, serialisation, merging."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Finding:
    id: str
    severity: str  # critical | high | medium | low | info
    category: str
    title: str
    detail: str
    file: str | None = None
    line: int | None = None
    recommendation: str = ""
    effort_hours: float = 0
    recurrence_count: int = 1
    first_seen: str = ""
    auto_fixable: bool = False

    def __post_init__(self):
        if not self.first_seen:
            self.first_seen = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def sort_key(self) -> tuple:
        """Sort by severity (critical first), then recurrence, then effort."""
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        return (order.get(self.severity, 9), -self.recurrence_count, self.effort_hours)


@dataclass
class AgentReport:
    agent: str
    timestamp: str = ""
    scan_duration_seconds: float = 0
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    intelligence_applied: list[str] = field(default_factory=list)
    learning_updates: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    # -- Serialisation -------------------------------------------------------

    def serialize(self) -> str:
        """Return clean JSON string."""
        return json.dumps(asdict(self), indent=2, default=str)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentReport":
        findings = [Finding(**f) for f in data.pop("findings", [])]
        return cls(findings=findings, **data)

    @classmethod
    def from_json(cls, text: str) -> "AgentReport":
        return cls.from_dict(json.loads(text))

    # -- Markdown rendering --------------------------------------------------

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.agent} Report")
        lines.append(
            f"*{self.timestamp}* — scanned in {self.scan_duration_seconds:.1f}s\n"
        )

        if not self.findings:
            lines.append("No findings.\n")
        else:
            by_sev: dict[str, list[Finding]] = {}
            for f in sorted(self.findings, key=lambda f: f.sort_key):
                by_sev.setdefault(f.severity, []).append(f)

            sev_icons = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
                "info": "⚪",
            }
            for sev in ("critical", "high", "medium", "low", "info"):
                items = by_sev.get(sev, [])
                if not items:
                    continue
                lines.append(
                    f"## {sev_icons.get(sev, '')} {sev.upper()} ({len(items)})\n"
                )
                for f in items:
                    loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "")
                    lines.append(f"### [{f.id}] {f.title}")
                    if loc:
                        lines.append(f"**Location:** `{loc}`")
                    lines.append(f"{f.detail}")
                    if f.recommendation:
                        lines.append(f"**Recommendation:** {f.recommendation}")
                    if f.recurrence_count > 1:
                        lines.append(
                            f"*Seen {f.recurrence_count} times (first: {f.first_seen})*"
                        )
                    lines.append("")

        if self.metrics:
            lines.append("## Metrics\n")
            for k, v in self.metrics.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

        if self.intelligence_applied:
            lines.append("## Intelligence Applied\n")
            for i in self.intelligence_applied:
                lines.append(f"- {i}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report merging (for Lead agent dedup)
# ---------------------------------------------------------------------------


def merge_reports(
    reports: list[AgentReport], *, skip_resolved: bool = True
) -> list[Finding]:
    """Merge findings from multiple reports, deduplicating by file + line + category.

    When skip_resolved=True (default), findings that appear in the global
    resolved-issues registry are silently dropped.
    """
    seen: dict[str, Finding] = {}
    for report in reports:
        for f in report.findings:
            key = f"{f.file}:{f.line}:{f.category}"
            if key in seen:
                existing = seen[key]
                # Keep the higher severity
                sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
                if sev_order.get(f.severity, 9) < sev_order.get(existing.severity, 9):
                    f.recurrence_count = existing.recurrence_count + 1
                    f.first_seen = existing.first_seen
                    seen[key] = f
                else:
                    existing.recurrence_count += 1
            else:
                seen[key] = f

    merged = sorted(seen.values(), key=lambda f: f.sort_key)

    if skip_resolved:
        from agents.shared.learning import filter_resolved_findings

        merged = filter_resolved_findings(merged)

    return merged
