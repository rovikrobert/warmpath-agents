"""Message formatter for CoS -> Founder communication.

Generates structured text messages for Telegram bot delivery.
Also provides reply parsing grammar reused by the Telegram bridge.

Usage:
    from agents.shared.message_formatter import MessageFormatter

    fmt = MessageFormatter()
    msg = fmt.morning_brief(team_status, decisions, cost)
    fmt.save_message(msg, "daily")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Output directory for formatted messages
MESSAGE_DIR = Path("agents/chief_of_staff/reports/messages")


class MessageFormatter:
    """Formats messages for Telegram (max 5 lines, actionable, binary questions)."""

    def __init__(self) -> None:
        MESSAGE_DIR.mkdir(parents=True, exist_ok=True)

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

    def error_alert(
        self,
        time_str: str,
        method: str,
        path: str,
        error_type: str,
        error_msg: str,
        user_context: str = "unauthenticated",
    ) -> str:
        """Generate a bug/error alert message for the founder."""
        return "\n".join(
            [
                f"BUG ALERT [{time_str}]",
                "",
                f"{method} {path}",
                f"{error_type}: {error_msg}",
                f"User: {user_context}",
                "",
                "Fix needed. Check logs for full trace.",
            ]
        )

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

    def execution_summary(
        self,
        events: list[dict[str, str]],
    ) -> str:
        """Format autonomous execution events for the daily brief."""
        if not events:
            return "No autonomous actions overnight."

        auto_fixed = [e for e in events if e.get("action") == "auto_fixed"]
        prs = [e for e in events if e.get("action") == "pr_created"]
        escalated = [e for e in events if e.get("action") == "escalated"]

        lines = ["Autonomous Actions:"]
        if auto_fixed:
            lines.append(f"  Auto-fixed: {len(auto_fixed)}")
            for e in auto_fixed[:3]:
                lines.append(f"    - {e.get('detail', '?')}")
        if prs:
            lines.append(f"  PRs opened: {len(prs)}")
            for e in prs[:3]:
                pr_url = e.get("pr_url", "")
                lines.append(f"    - {e.get('detail', '?')} {pr_url}")
        if escalated:
            lines.append(f"  Escalated: {len(escalated)}")
            for e in escalated[:3]:
                lines.append(f"    - {e.get('detail', '?')}")

        return "\n".join(lines)

    # -----------------------------------------------------------------
    # Parse founder replies
    # -----------------------------------------------------------------

    @staticmethod
    def parse_reply(text: str) -> dict[str, Any]:
        """Parse a founder's reply into structured commands.

        Supports:
            "1" or "1=yes" -> approve decision 1
            "A" or "B" -> choose option A or B
            "Y" or "N" -> yes/no
            "status" -> request status
            "cost" -> request cost report
            "blockers" -> request blockers list
            "ship X" -> trigger ship feature
            "approve Z" -> approve pending decision
            "reprioritize: A > B" -> reorder priorities
            "brief me on X" -> request Notion brief
        """
        text = text.strip().lower()

        # Quick commands
        quick_commands = {
            "status": {"command": "status"},
            "cost": {"command": "cost"},
            "blockers": {"command": "blockers"},
            "stats": {"command": "stats"},
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
        filename = f"message-{msg_type}-{today}.txt"
        path = MESSAGE_DIR / filename
        path.write_text(message, encoding="utf-8")
        logger.info("Message saved: %s", path)
        return path

    def send(self, message: str, msg_type: str = "daily") -> dict[str, Any]:
        """Save message to file. Delivery handled by Telegram bridge."""
        path = self.save_message(message, msg_type)
        return {"file": str(path), "status": "file_only"}
