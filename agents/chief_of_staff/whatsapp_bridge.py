"""WhatsApp bridge for Chief of Staff — formats and sends messages to Rovik.

Wraps the shared WhatsAppFormatter with CoS-specific logic:
- Extracts team status from synthesized briefs
- Generates morning briefs from FounderBrief data
- Handles cost alerts from budget checks
- Processes Rovik's quick commands

Phase 1 (current): Saves text files for manual copy-paste.
Phase 2 (post-launch): Sends via Twilio WhatsApp Business API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agents.shared.whatsapp_formatter import WhatsAppFormatter

from .cos_config import COS_CONFIG

logger = logging.getLogger(__name__)


class WhatsAppBridge:
    """CoS-specific WhatsApp message generation and command processing."""

    def __init__(self) -> None:
        self._formatter = WhatsAppFormatter()

    @property
    def twilio_enabled(self) -> bool:
        return self._formatter.twilio_enabled

    # -----------------------------------------------------------------
    # Generate messages from CoS data
    # -----------------------------------------------------------------

    def generate_morning_brief(
        self,
        brief_data: dict[str, Any],
        costs: dict[str, Any],
        alerts: list[str],
        notion_page_id: str = "",
    ) -> dict[str, Any]:
        """Generate and send the morning brief from synthesized data.

        Args:
            brief_data: FounderBrief-like dict with decisions_needed, etc.
            costs: Cost summary from get_team_cost_summary()
            alerts: Budget alerts from check_budget_alerts()
            notion_page_id: Notion page ID from push_daily_brief (for clickable link)
        """
        today = datetime.now(timezone.utc)
        date_str = today.strftime("%b %d")

        # Build team status from reports
        team_status = self._extract_team_status(brief_data)

        # Extract decision strings
        decisions = []
        for d in brief_data.get("decisions_needed", [])[:3]:
            decisions.append(d.get("summary", "Unknown decision"))

        # Cost string
        total_cost = costs.get("total_estimated_cost_usd", 0)
        cost_str = f"${total_cost:.2f}/day"

        # Build Notion URL if page was synced
        notion_url = (
            WhatsAppFormatter.notion_url(notion_page_id) if notion_page_id else ""
        )

        # Generate the message
        message = self._formatter.morning_brief(
            date=date_str,
            team_status=team_status,
            decisions_needed=decisions,
            cost_yesterday=cost_str,
            notion_url=notion_url,
        )

        # Append cost alert if any
        if alerts:
            message += "\n\n" + "\n".join(f"[!] {a}" for a in alerts)

        # Send/save
        result = self._formatter.send(message, msg_type="daily")
        logger.info("Morning brief generated: %s", result.get("file"))
        return result

    def generate_cost_alert(
        self,
        actual_cost: float,
        budget: float,
        cause: str,
        auto_action: str = "Throttled to Sonnet for today.",
    ) -> dict[str, Any]:
        """Generate and send a cost alert when budget is exceeded."""
        message = self._formatter.cost_alert(
            actual=f"${actual_cost:.2f}",
            budget=f"${budget:.2f}",
            cause=cause,
            auto_action=auto_action,
            question="Approve continued Opus for security?",
        )
        result = self._formatter.send(message, msg_type="cost-alert")
        logger.info("Cost alert generated: %s", result.get("file"))
        return result

    def generate_escalation(
        self,
        title: str,
        detail: str,
        option_a: str,
        option_b: str,
    ) -> dict[str, Any]:
        """Generate and send an urgent escalation."""
        message = self._formatter.urgent_escalation(
            title=title,
            detail=detail,
            option_a=option_a,
            option_b=option_b,
        )
        result = self._formatter.send(message, msg_type="escalation")
        logger.info("Escalation generated: %s", result.get("file"))
        return result

    def generate_weekly_summary(
        self,
        week_num: int,
        metrics: dict[str, Any],
        notion_page_id: str = "",
    ) -> dict[str, Any]:
        """Generate and send the weekly summary (Sunday 8 PM SGT)."""
        notion_url = (
            WhatsAppFormatter.notion_url(notion_page_id) if notion_page_id else ""
        )
        message = self._formatter.weekly_summary(
            week_num=week_num,
            users_active=metrics.get("users_active", 0),
            users_target=metrics.get("users_target", 15),
            intros=metrics.get("intros", 0),
            interviews=metrics.get("interviews", 0),
            mrr=metrics.get("mrr", "$0"),
            weekly_cost=metrics.get("weekly_cost", "$0"),
            daily_avg=metrics.get("daily_avg", "$0/day"),
            top_win=metrics.get("top_win", "No notable wins"),
            top_risk=metrics.get("top_risk", "No notable risks"),
            notion_url=notion_url,
        )
        result = self._formatter.send(message, msg_type="weekly")
        logger.info("Weekly summary generated: %s", result.get("file"))
        return result

    def generate_ship_notification(
        self,
        feature_name: str,
        details: list[str],
    ) -> dict[str, Any]:
        """Generate and send a feature ship notification."""
        message = self._formatter.feature_shipped(
            feature_name=feature_name,
            details=details,
        )
        result = self._formatter.send(message, msg_type="ship")
        logger.info("Ship notification generated: %s", result.get("file"))
        return result

    # -----------------------------------------------------------------
    # Process Rovik's commands
    # -----------------------------------------------------------------

    def process_command(self, text: str) -> dict[str, Any]:
        """Parse a WhatsApp command from Rovik and return the action to take.

        Returns a dict with 'command' key and relevant parameters.
        The CoS agent should act on this and respond.
        """
        parsed = WhatsAppFormatter.parse_reply(text)
        logger.info("Parsed WhatsApp command: %s", parsed)
        return parsed

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _extract_team_status(
        self, brief_data: dict[str, Any]
    ) -> dict[str, dict[str, str]]:
        """Extract per-team Red/Yellow/Green status from brief data."""
        team_status: dict[str, dict[str, str]] = {}

        # Count critical/high findings per team from decisions_needed
        team_issues: dict[str, int] = {}
        for d in brief_data.get("decisions_needed", []):
            # Infer team from outcomes or default to engineering
            team_issues["general"] = team_issues.get("general", 0) + 1

        # Build status for each active team
        active_teams = [
            name for name, cfg in COS_CONFIG["teams"].items() if cfg.get("active")
        ]

        progress_teams = set()
        for p in brief_data.get("progress", []):
            team = p.get("team", "engineering")
            progress_teams.add(team)

        for team in active_teams:
            if team_issues.get(team, 0) > 0:
                status = "red" if team_issues[team] >= 2 else "yellow"
            elif team in progress_teams:
                status = "green"
            else:
                status = "green"  # No report = assume fine

            # Get summary from progress if available
            summary = "No report"
            for p in brief_data.get("progress", []):
                if p.get("team") == team:
                    summary = p.get("note", "Clean scan")
                    break

            team_status[team] = {"status": status, "summary": summary}

        return team_status
