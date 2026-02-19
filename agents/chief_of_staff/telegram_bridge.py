"""Telegram Bot bridge for Chief of Staff -> Founder communication.

Replaces WhatsApp/Twilio with the free Telegram Bot API.
Uses httpx (already a project dependency) for HTTP calls.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.shared.whatsapp_formatter import WhatsAppFormatter

logger = logging.getLogger(__name__)

TELEGRAM_DIR = Path("agents/chief_of_staff/reports/telegram")
TELEGRAM_MAX_LENGTH = 4000  # Telegram limit is 4096; leave buffer


def split_telegram_message(
    text: str, max_length: int = TELEGRAM_MAX_LENGTH
) -> list[str]:
    """Split a message into chunks that fit within Telegram's character limit.

    Splits at paragraph boundaries first, then line boundaries, then hard-cuts.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a paragraph boundary (\n\n)
        cut = remaining.rfind("\n\n", 0, max_length)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 2 :]
            continue

        # Try to split at a line boundary (\n)
        cut = remaining.rfind("\n", 0, max_length)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1 :]
            continue

        # Hard cut
        chunks.append(remaining[:max_length])
        remaining = remaining[max_length:]

    return chunks


_MD_ESCAPE_CHARS = r"\_*[]()~`>#+-=|{}.!"
_MD_ESCAPE_RE = re.compile(r"([" + re.escape(_MD_ESCAPE_CHARS) + r"])")


class TelegramBridge:
    """Formats and sends messages via Telegram Bot API."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self._bot_token and self._chat_id)
        self._output_dir = output_dir or TELEGRAM_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def escape_md(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        return _MD_ESCAPE_RE.sub(r"\\\1", text)

    # -- Message templates ---------------------------------------------------

    def format_daily_brief(
        self,
        date: str,
        team_summaries: list[dict[str, Any]],
        decisions: list[str],
        cost: str,
        notion_url: str = "",
    ) -> str:
        status_icon = {"green": "[G]", "yellow": "[Y]", "red": "[R]"}
        lines = [f"WarmPath Daily — {date}", ""]
        for ts in team_summaries:
            icon = status_icon.get(ts.get("health", "green"), "[?]")
            team = ts.get("team", "unknown").title()
            summary = ts.get("summary", "No report")
            lines.append(f"{team}: {summary} {icon}")
        lines.append(f"Cost: {cost}")
        if decisions:
            lines.append("")
            lines.append("Need your call:")
            for i, d in enumerate(decisions[:3], 1):
                lines.append(f"{i}. {d}")
            lines.append("")
            replies = ", ".join(
                f"{i}=yes" for i in range(1, min(len(decisions), 4) + 1)
            )
            detail_link = notion_url or "Notion"
            lines.append(f"Reply {replies}, or details: {detail_link}")
        if notion_url and not decisions:
            lines.append("")
            lines.append(f"Full brief: {notion_url}")
        return "\n".join(lines)

    def format_weekly_summary(
        self,
        week_num: int,
        cost: str = "$0",
        daily_avg: str = "$0/day",
        top_win: str = "No notable wins",
        top_risk: str = "No notable risks",
        notion_url: str = "",
    ) -> str:
        report_link = notion_url or "Notion"
        return "\n".join(
            [
                f"Week {week_num} Summary",
                "",
                f"Cost: {cost} ({daily_avg} avg)",
                "",
                f"Top win: {top_win}",
                f"Top risk: {top_risk}",
                "",
                f"Full report: {report_link}",
            ]
        )

    def format_escalation(
        self,
        title: str,
        detail: str,
        option_a: str,
        option_b: str,
    ) -> str:
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

    def format_cost_alert(
        self,
        actual: str,
        budget: str,
        cause: str,
        auto_action: str,
        question: str,
    ) -> str:
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

    # -- Reply parsing (shared grammar) --------------------------------------

    @staticmethod
    def parse_reply(text: str) -> dict[str, Any]:
        return WhatsAppFormatter.parse_reply(text)

    # -- CoS-level generators ------------------------------------------------

    def generate_daily_brief(
        self,
        brief_data: dict[str, Any],
        costs: dict[str, Any],
        alerts: list[str],
        notion_page_id: str = "",
    ) -> dict[str, Any]:
        today = datetime.now(timezone.utc)
        date_str = today.strftime("%b %d")
        team_summaries = brief_data.get("team_summaries", [])
        decisions = [
            d.get("summary", "Unknown")
            for d in brief_data.get("decisions_needed", [])[:3]
        ]
        total_cost = costs.get("total_estimated_cost_usd", 0)
        cost_str = f"${total_cost:.2f}/day"
        notion_url = ""
        if notion_page_id:
            notion_url = f"https://notion.so/{notion_page_id.replace('-', '')}"
        message = self.format_daily_brief(
            date=date_str,
            team_summaries=team_summaries,
            decisions=decisions,
            cost=cost_str,
            notion_url=notion_url,
        )
        if alerts:
            message += "\n\n" + "\n".join(f"[!] {a}" for a in alerts)
        return self.send(message, msg_type="daily")

    def generate_weekly_summary(
        self,
        week_num: int,
        metrics: dict[str, Any],
        notion_page_id: str = "",
    ) -> dict[str, Any]:
        notion_url = ""
        if notion_page_id:
            notion_url = f"https://notion.so/{notion_page_id.replace('-', '')}"
        message = self.format_weekly_summary(
            week_num=week_num,
            cost=metrics.get("weekly_cost", "$0"),
            daily_avg=metrics.get("daily_avg", "$0/day"),
            top_win=metrics.get("top_win", "No notable wins"),
            top_risk=metrics.get("top_risk", "No notable risks"),
            notion_url=notion_url,
        )
        return self.send(message, msg_type="weekly")

    # -- Send ----------------------------------------------------------------

    def save_message(self, message: str, msg_type: str = "daily") -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"telegram-{msg_type}-{today}.txt"
        path = self._output_dir / filename
        path.write_text(message, encoding="utf-8")
        logger.info("Telegram message saved: %s", path)
        return path

    def send_via_bot_api(self, message: str) -> dict[str, Any]:
        if not self._enabled:
            logger.info("Telegram not configured — message saved to file only")
            return {"status": "file_only", "telegram": False}
        try:
            import httpx

            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            chunks = split_telegram_message(message)
            last_msg_id = None
            with httpx.Client(timeout=15.0) as client:
                for chunk in chunks:
                    payload: dict[str, Any] = {"chat_id": self._chat_id, "text": chunk}
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    last_msg_id = result.get("result", {}).get("message_id")
            logger.info(
                "Telegram message sent (%d part%s): message_id=%s",
                len(chunks),
                "s" if len(chunks) > 1 else "",
                last_msg_id,
            )
            return {
                "status": "sent",
                "telegram": True,
                "message_id": last_msg_id,
                "parts": len(chunks),
            }
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return {"status": "error", "telegram": True, "error": str(e)}

    def send(self, message: str, msg_type: str = "daily") -> dict[str, Any]:
        path = self.save_message(message, msg_type)
        result: dict[str, Any] = {"file": str(path)}
        if self._enabled:
            tg_result = self.send_via_bot_api(message)
            result.update(tg_result)
        else:
            result["status"] = "file_only"
            result["telegram"] = False
        return result
