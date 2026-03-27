"""Cross-team execution engine for autonomous agent actions.

Upgrades the report-only agent pipeline to a triage-and-act pipeline.
Findings are classified by risk, then routed to the appropriate tier:
- AUTO_DO: execute immediately, log to event stream
- AUTO_PR: write fix, open PR, assign founder
- ESCALATE: Telegram alert, don't touch anything
- REPORT_ONLY: fallback when engine is disabled

Safety rails:
- Kill switch: AUTONOMOUS_EXECUTION_ENABLED env var
- Circuit breaker: max N auto-merges per 24h
- Protected paths: auth, credits, payments never auto-touched
- All actions logged to cto:events Redis Stream
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agents.shared.event_stream import STREAM_KEY
from agents.shared.repair import repair_auto_fixable
from agents.shared.report import Finding
from agents.shared.risk_classifier import RiskLevel, classify_risk

logger = logging.getLogger(__name__)


class ExecutionTier(str, Enum):
    AUTO_DO = "auto_do"
    AUTO_PR = "auto_pr"
    ESCALATE = "escalate"
    REPORT_ONLY = "report_only"


class ExecutionAction(str, Enum):
    REPORTED = "reported"
    AUTO_FIXED = "auto_fixed"
    PR_CREATED = "pr_created"
    ESCALATED = "escalated"
    SKIPPED = "skipped"


@dataclass
class ExecutionResult:
    finding_id: str
    tier: ExecutionTier
    action: ExecutionAction
    detail: str = ""
    pr_url: str | None = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_event(self, team: str, agent: str) -> dict[str, Any]:
        """Format as a cto:events Redis Stream entry."""
        return {
            "team": team,
            "agent": agent,
            "finding_id": self.finding_id,
            "tier": self.tier.value,
            "action": self.action.value,
            "detail": self.detail,
            "pr_url": self.pr_url or "",
            "timestamp": self.timestamp,
        }


class ExecutionEngine:
    """Cross-team execution engine with triage, safety rails, and event publishing."""

    def __init__(
        self,
        enabled: bool | None = None,
        max_auto_merges_per_day: int = 10,
    ):
        if enabled is None:
            try:
                from app.config import settings

                enabled = settings.AUTONOMOUS_EXECUTION_ENABLED
            except Exception:
                enabled = (
                    os.getenv("AUTONOMOUS_EXECUTION_ENABLED", "false").lower() == "true"
                )
        self.enabled = enabled
        self.max_auto_merges_per_day = max_auto_merges_per_day
        # Resets per-run (new ExecutionEngine instance per orchestrator invocation),
        # not per-24h calendar window.
        self._auto_merge_count = 0
        self._results: list[ExecutionResult] = []

    @property
    def circuit_breaker_tripped(self) -> bool:
        return self._auto_merge_count >= self.max_auto_merges_per_day

    def triage(self, finding: Finding) -> ExecutionTier:
        """Classify a finding into an execution tier.

        Low-confidence findings (confidence < 0.5) are always report-only
        to prevent the engine from acting on statistically unreliable data.
        """
        if not self.enabled:
            return ExecutionTier.REPORT_ONLY

        if finding.confidence < 0.5:
            logger.info(
                "Finding %s has low confidence (%.2f) — downgrading to REPORT_ONLY",
                finding.id,
                finding.confidence,
            )
            return ExecutionTier.REPORT_ONLY

        risk = classify_risk(finding)

        if risk <= RiskLevel.LOW:
            if self.circuit_breaker_tripped:
                logger.warning(
                    "Circuit breaker tripped (%d/%d auto-merges) — downgrading %s to AUTO_PR",
                    self._auto_merge_count,
                    self.max_auto_merges_per_day,
                    finding.id,
                )
                return ExecutionTier.AUTO_PR
            return ExecutionTier.AUTO_DO

        if risk == RiskLevel.MEDIUM:
            return ExecutionTier.AUTO_PR

        # HIGH or CRITICAL
        return ExecutionTier.ESCALATE

    def execute(
        self, finding: Finding, tier: ExecutionTier, *, dry_run: bool = False
    ) -> ExecutionResult:
        """Execute a finding at the given tier."""
        if tier == ExecutionTier.REPORT_ONLY or dry_run:
            return ExecutionResult(
                finding_id=finding.id,
                tier=tier,
                action=ExecutionAction.REPORTED,
                detail=f"{'[DRY RUN] ' if dry_run else ''}Finding reported: {finding.title}",
            )

        if tier == ExecutionTier.ESCALATE:
            return ExecutionResult(
                finding_id=finding.id,
                tier=tier,
                action=ExecutionAction.ESCALATED,
                detail=f"Escalated: {finding.severity} {finding.title}",
            )

        if tier in (ExecutionTier.AUTO_DO, ExecutionTier.AUTO_PR):
            return self._execute_repair(finding, tier)

        return ExecutionResult(
            finding_id=finding.id,
            tier=tier,
            action=ExecutionAction.SKIPPED,
            detail="Unknown tier",
        )

    def _execute_repair(self, finding: Finding, tier: ExecutionTier) -> ExecutionResult:
        """Run repair_auto_fixable and return real results."""
        try:
            repair_result = repair_auto_fixable([finding])
            if repair_result.fixed_count > 0:
                if tier == ExecutionTier.AUTO_DO:
                    self._auto_merge_count += 1
                action = (
                    ExecutionAction.AUTO_FIXED
                    if tier == ExecutionTier.AUTO_DO
                    else ExecutionAction.PR_CREATED
                )
                return ExecutionResult(
                    finding_id=finding.id,
                    tier=tier,
                    action=action,
                    detail=f"Repaired: {finding.title}",
                    pr_url=repair_result.pr_url,
                )
            detail = "No changes produced"
            if repair_result.errors:
                detail = f"Repair failed: {repair_result.errors[0][:200]}"
            return ExecutionResult(
                finding_id=finding.id,
                tier=tier,
                action=ExecutionAction.SKIPPED,
                detail=detail,
            )
        except Exception as exc:
            logger.error("Repair failed for %s: %s", finding.id, exc)
            return ExecutionResult(
                finding_id=finding.id,
                tier=tier,
                action=ExecutionAction.SKIPPED,
                detail=f"Repair exception: {exc}",
            )

    def process_findings(
        self,
        findings: list[Finding],
        team: str = "engineering",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Process a batch of findings through triage and execution."""
        summary: dict[str, Any] = {
            "team": team,
            "total": len(findings),
            "auto_do_count": 0,
            "auto_pr_count": 0,
            "escalate_count": 0,
            "report_only_count": 0,
            "results": [],
        }

        for finding in findings:
            tier = self.triage(finding)
            result = self.execute(  # n1-ok: not a DB query
                finding, tier, dry_run=dry_run
            )
            self._results.append(result)

            if tier == ExecutionTier.AUTO_DO:
                summary["auto_do_count"] += 1
            elif tier == ExecutionTier.AUTO_PR:
                summary["auto_pr_count"] += 1
            elif tier == ExecutionTier.ESCALATE:
                summary["escalate_count"] += 1
            else:
                summary["report_only_count"] += 1

            summary["results"].append(result.to_event(team, ""))

        return summary

    def publish_events(self, team: str) -> int:
        """Publish all results to cto:events Redis Stream."""
        try:
            import redis

            redis_url = os.getenv("REDIS_URL")
            if not redis_url:
                return 0

            r = redis.from_url(redis_url)
            count = 0
            for result in self._results:
                event = result.to_event(team, "")
                r.xadd(STREAM_KEY, {k: str(v) for k, v in event.items()})
                count += 1
            return count
        except Exception as exc:
            logger.warning("Failed to publish events to Redis: %s", exc)
            return 0

    def get_summary_for_brief(self) -> str:
        """Generate a human-readable summary for CoS daily brief."""
        auto_fixed = [
            r for r in self._results if r.action == ExecutionAction.AUTO_FIXED
        ]
        prs = [r for r in self._results if r.action == ExecutionAction.PR_CREATED]
        escalated = [r for r in self._results if r.action == ExecutionAction.ESCALATED]

        lines = []
        if auto_fixed:
            lines.append(f"Auto-fixed: {len(auto_fixed)} issues")
        if prs:
            lines.append(f"PRs opened: {len(prs)}")
        if escalated:
            lines.append(f"Escalated: {len(escalated)} issues")
        if not lines:
            lines.append("No autonomous actions taken")

        return " | ".join(lines)
