"""WhatsApp message formatter for CoS → Founder communication.

Phase 1: Generates text files for manual copy-paste.
Phase 2: Sends via Twilio WhatsApp Business API.

Usage:
    from agents.shared.whatsapp_formatter import WhatsAppFormatter

    fmt = WhatsAppFormatter()
    msg = fmt.morning_brief(team_status, decisions, cost)
    fmt.save_message(msg, "daily")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Output directory for WhatsApp-formatted messages
WHATSAPP_DIR = Path("agents/chief_of_staff/reports/whatsapp")


class WhatsAppFormatter:
    """Formats messages for WhatsApp (max 5 lines, actionable, binary questions)."""

    def __init__(self) -> None:
        self._twilio_enabled = bool(os.environ.get("TWILIO_ACCOUNT_SID"))
        WHATSAPP_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def twilio_enabled(self) -> bool:
        return self._twilio_enabled

    @staticmethod
    def notion_url(page_id: str) -> str:
        """Convert a Notion page ID to a clickable URL."""
        return f"https://notion.so/{page_id.replace('-', '')}"

    # -----------------------------------------------------------------
    # Message templates
    # -----------------------------------------------------------------

    def morning_brief(
        self,
        date: str,
        team_status: dict[str, dict[str, str]],
        decisions_needed: list[str],
        cost_yesterday: str,
        notion_url: str = "",
    ) -> str:
        """Generate the daily morning brief (8 AM SGT).

        Args:
            date: Display date (e.g., "Feb 18")
            team_status: {team: {"status": "green/yellow/red", "summary": "..."}}
            decisions_needed: List of decision strings
            cost_yesterday: Cost string (e.g., "$2.40/day")
            notion_url: Optional Notion page URL for the full brief
        """
        status_icon = {"green": "[G]", "yellow": "[Y]", "red": "[R]"}
        lines = [f"WarmPath Daily — {date}", ""]

        for team, info in team_status.items():
            icon = status_icon.get(info.get("status", "green"), "[?]")
            lines.append(f"{team.title()}: {info.get('summary', 'No report')} {icon}")

        lines.append(f"Cost: {cost_yesterday}")

        if decisions_needed:
            lines.append("")
            lines.append("Need your call:")
            for i, d in enumerate(decisions_needed[:3], 1):
                lines.append(f"{i}. {d}")
            lines.append("")
            replies = ", ".join(
                f"{i}=yes" for i in range(1, min(len(decisions_needed), 4) + 1)
            )
            detail_link = notion_url if notion_url else "Notion"
            lines.append(f"Reply {replies}, or details: {detail_link}")

        if notion_url and not decisions_needed:
            lines.append("")
            lines.append(f"Full brief: {notion_url}")

        return "\n".join(lines)

    def urgent_escalation(
        self,
        title: str,
        detail: str,
        option_a: str,
        option_b: str,
    ) -> str:
        """Generate an urgent escalation message."""
        return "\n".join(
            [
                f"ALERT: {title} [R]",
                "",
                detail,
                "",
                "Action needed:",
                f"A) {option_a}",
                f"B) {option_b}",
                "",
                "Reply A or B",
            ]
        )

    def cost_alert(
        self,
        actual: str,
        budget: str,
        cause: str,
        auto_action: str,
        question: str,
    ) -> str:
        """Generate a cost alert message."""
        return "\n".join(
            [
                f"Cost spike: {actual} yesterday (budget: {budget})",
                "",
                f"Cause: {cause}",
                "",
                f"Auto-action: {auto_action}",
                f"{question} Y/N",
            ]
        )

    def weekly_summary(
        self,
        week_num: int,
        users_active: int,
        users_target: int,
        intros: int,
        interviews: int,
        mrr: str,
        weekly_cost: str,
        daily_avg: str,
        top_win: str,
        top_risk: str,
        notion_url: str = "",
    ) -> str:
        """Generate the weekly summary (Sunday 8 PM SGT)."""
        report_link = notion_url if notion_url else "Notion"
        return "\n".join(
            [
                f"Week {week_num} Summary",
                "",
                f"Users: {users_active} active (target: {users_target})",
                f"Intros: {intros} facilitated, {interviews} -> interviews",
                f"MRR: {mrr}",
                f"Cost: {weekly_cost} ({daily_avg} avg)",
                "",
                f"Top win: {top_win}",
                f"Top risk: {top_risk}",
                "",
                f"Full report: {report_link}",
            ]
        )

    def feature_shipped(
        self,
        feature_name: str,
        details: list[str],
    ) -> str:
        """Generate a feature ship notification."""
        lines = [f"Shipped: {feature_name}", ""]
        for d in details[:4]:
            lines.append(f"- {d}")
        lines.append("")
        lines.append("No action needed. Logged in Notion.")
        return "\n".join(lines)

    def pod_status(
        self,
        pods: list[dict[str, Any]],
    ) -> str:
        """Generate active pods status for daily brief."""
        if not pods:
            return ""
        lines = ["ACTIVE PODS:"]
        status_icon = {"green": "[G]", "yellow": "[Y]", "red": "[R]"}
        for pod in pods:
            icon = status_icon.get(pod.get("status", "green"), "[?]")
            name = pod.get("name", "Unknown")
            day = pod.get("day", "?")
            total = pod.get("total_days", "?")
            summary = pod.get("summary", "")
            lines.append(f" {name} (Day {day}/{total}): {summary} {icon}")
        return "\n".join(lines)

    # -----------------------------------------------------------------
    # Parse founder replies
    # -----------------------------------------------------------------

    @staticmethod
    def parse_reply(text: str) -> dict[str, Any]:
        """Parse a founder's WhatsApp reply into structured commands.

        Supports:
            "1" or "1=yes" → approve decision 1
            "A" or "B" → choose option A or B
            "Y" or "N" → yes/no
            "status" → request status
            "cost" → request cost report
            "blockers" → request blockers list
            "ship X" → trigger ship feature
            "approve Z" → approve pending decision
            "reprioritize: A > B" → reorder priorities
            "brief me on X" → request Notion brief
        """
        text = text.strip().lower()

        # Quick commands
        quick_commands = {
            "status": {"command": "status"},
            "cost": {"command": "cost"},
            "blockers": {"command": "blockers"},
        }
        if text in quick_commands:
            return quick_commands[text]

        # Yes/No
        if text in ("y", "yes"):
            return {"command": "approve", "value": True}
        if text in ("n", "no"):
            return {"command": "approve", "value": False}

        # A/B choice
        if text in ("a", "b", "c", "d"):
            return {"command": "choose", "value": text.upper()}

        # Numbered approval (e.g., "1", "1=yes", "2=yes")
        if text.isdigit():
            return {"command": "approve_item", "item": int(text)}
        if "=" in text and text.split("=")[0].isdigit():
            parts = text.split("=")
            return {"command": "approve_item", "item": int(parts[0]), "value": parts[1]}

        # Compound commands
        if text.startswith("ship "):
            return {"command": "ship", "feature": text[5:].strip()}
        if text.startswith("pause "):
            return {"command": "pause", "team": text[6:].strip()}
        if text.startswith("approve "):
            return {"command": "approve_decision", "decision": text[8:].strip()}
        if text.startswith("reprioritize:"):
            return {"command": "reprioritize", "instruction": text[13:].strip()}
        if text.startswith("brief me on "):
            return {"command": "brief", "topic": text[12:].strip()}

        return {"command": "unknown", "raw": text}

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------

    def save_message(self, message: str, msg_type: str = "daily") -> Path:
        """Save a formatted message to a text file for manual copy-paste."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"whatsapp-{msg_type}-{today}.txt"
        path = WHATSAPP_DIR / filename
        path.write_text(message, encoding="utf-8")
        logger.info("WhatsApp message saved: %s", path)
        return path

    def send_via_twilio(self, message: str) -> dict[str, Any]:
        """Send a message via Twilio WhatsApp Business API (Phase 2).

        Requires env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
        TWILIO_WHATSAPP_FROM, ROVIK_WHATSAPP_NUMBER.
        """
        if not self._twilio_enabled:
            logger.info("Twilio not configured — message saved to file only")
            return {"status": "file_only", "twilio": False}

        account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        from_number = os.environ["TWILIO_WHATSAPP_FROM"]
        to_number = os.environ["ROVIK_WHATSAPP_NUMBER"]

        try:
            import httpx

            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            data = {
                "From": f"whatsapp:{from_number}",
                "To": f"whatsapp:{to_number}",
                "Body": message,
            }
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, data=data, auth=(account_sid, auth_token))
                response.raise_for_status()
                result = response.json()
                logger.info("WhatsApp message sent via Twilio: %s", result.get("sid"))
                return {"status": "sent", "twilio": True, "sid": result.get("sid")}
        except Exception as e:
            logger.error("Twilio send failed: %s", e)
            return {"status": "error", "twilio": True, "error": str(e)}

    def send(self, message: str, msg_type: str = "daily") -> dict[str, Any]:
        """Save message and optionally send via Twilio."""
        path = self.save_message(message, msg_type)
        result: dict[str, Any] = {"file": str(path)}

        if self._twilio_enabled:
            twilio_result = self.send_via_twilio(message)
            result.update(twilio_result)
        else:
            result["status"] = "file_only"
            result["twilio"] = False

        return result
