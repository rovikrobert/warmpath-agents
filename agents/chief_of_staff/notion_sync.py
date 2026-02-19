"""Notion sync for Chief of Staff — pushes briefs and decisions to Notion.

Manages the Notion workspace structure described in COS.md Section 4.2:
- Founder Briefs database
- CoS Daily Briefs database
- Decision Log database

Requires NOTION_API_KEY and database IDs in environment or cos_config.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.shared.notion_client import NotionClient

logger = logging.getLogger(__name__)

# Notion database IDs — set via environment or cos_config
_STATE_FILE = Path("agents/chief_of_staff/notion_state.json")


class NotionSync:
    """Syncs CoS outputs to Notion databases."""

    def __init__(self) -> None:
        self._client = NotionClient()
        self._state = self._load_state()

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    # -----------------------------------------------------------------
    # State persistence (tracks database IDs and last sync)
    # -----------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        """Load Notion sync state (database IDs, last sync timestamps)."""
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "daily_briefs_db": os.environ.get("NOTION_DAILY_BRIEFS_DB", ""),
            "decision_log_db": os.environ.get("NOTION_DECISION_LOG_DB", ""),
            "founder_briefs_db": os.environ.get("NOTION_FOUNDER_BRIEFS_DB", ""),
            "team_reports_db": os.environ.get("NOTION_TEAM_REPORTS_DB", ""),
            "weekly_synthesis_db": os.environ.get("NOTION_WEEKLY_SYNTHESIS_DB", ""),
            "command_center_page": os.environ.get("NOTION_COMMAND_CENTER_PAGE", ""),
            "last_daily_sync": None,
            "last_weekly_sync": None,
        }

    def _save_state(self) -> None:
        """Persist Notion sync state."""
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(self._state, indent=2))

    # -----------------------------------------------------------------
    # Database setup (run once to initialize workspace)
    # -----------------------------------------------------------------

    def setup_databases(self, parent_page_id: str) -> dict[str, str]:
        """Create the Notion database structure under a parent page.

        Call once during workspace setup. Returns database IDs.
        """
        if not self.enabled:
            logger.warning("Notion not configured — skipping database setup")
            return {}

        db_ids: dict[str, str] = {}

        # 1. CoS Daily Briefs database
        result = self._client.create_database(
            parent_page_id=parent_page_id,
            title="CoS Daily Briefs",
            properties={
                "Date": {"date": {}},
                "Headline": {"title": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Published", "color": "green"},
                            {"name": "Draft", "color": "yellow"},
                        ]
                    }
                },
                "Cost": {"rich_text": {}},
                "Decisions Needed": {"number": {}},
                "Blockers": {"number": {}},
            },
        )
        if result.get("id"):
            db_ids["daily_briefs"] = result["id"]
            self._state["daily_briefs_db"] = result["id"]

        # 2. Decision Log database
        result = self._client.create_database(
            parent_page_id=parent_page_id,
            title="Decision Log",
            properties={
                "Decision": {"title": {}},
                "Date": {"date": {}},
                "Decider": {
                    "select": {
                        "options": [
                            {"name": "Founder", "color": "red"},
                            {"name": "CoS", "color": "blue"},
                            {"name": "TeamLead", "color": "green"},
                        ]
                    }
                },
                "Business Outcome": {
                    "multi_select": {
                        "options": [
                            {"name": "#1 Job seekers land jobs", "color": "blue"},
                            {"name": "#2 NH contribute value", "color": "green"},
                            {"name": "#3 $1B valuation", "color": "purple"},
                            {"name": "#4 Cost efficiency", "color": "orange"},
                        ]
                    }
                },
                "Context": {"rich_text": {}},
                "Outcome": {"rich_text": {}},
            },
        )
        if result.get("id"):
            db_ids["decision_log"] = result["id"]
            self._state["decision_log_db"] = result["id"]

        # 3. Founder Briefs database
        result = self._client.create_database(
            parent_page_id=parent_page_id,
            title="Founder Briefs",
            properties={
                "Title": {"title": {}},
                "Priority": {
                    "select": {
                        "options": [
                            {"name": "P0", "color": "red"},
                            {"name": "P1", "color": "orange"},
                            {"name": "P2", "color": "yellow"},
                            {"name": "P3", "color": "gray"},
                        ]
                    }
                },
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Draft", "color": "gray"},
                            {"name": "Active", "color": "blue"},
                            {"name": "Closed", "color": "green"},
                        ]
                    }
                },
                "Teams Involved": {
                    "multi_select": {
                        "options": [
                            {"name": "Engineering"},
                            {"name": "Product"},
                            {"name": "GTM"},
                            {"name": "Finance"},
                            {"name": "Data"},
                            {"name": "Ops"},
                        ]
                    }
                },
                "Business Outcome": {
                    "multi_select": {
                        "options": [
                            {"name": "#1 Job seekers land jobs"},
                            {"name": "#2 NH contribute value"},
                            {"name": "#3 $1B valuation"},
                            {"name": "#4 Cost efficiency"},
                        ]
                    }
                },
                "Due Date": {"date": {}},
            },
        )
        if result.get("id"):
            db_ids["founder_briefs"] = result["id"]
            self._state["founder_briefs_db"] = result["id"]

        # 4. Team Reports database
        result = self._client.create_database(
            parent_page_id=parent_page_id,
            title="Team Reports",
            properties={
                "Team": {"title": {}},
                "Date": {"date": {}},
                "Health": {
                    "select": {
                        "options": [
                            {"name": "Green", "color": "green"},
                            {"name": "Yellow", "color": "yellow"},
                            {"name": "Red", "color": "red"},
                        ]
                    }
                },
                "Summary": {"rich_text": {}},
                "Agents": {"number": {}},
                "Findings": {"number": {}},
            },
        )
        if result.get("id"):
            db_ids["team_reports"] = result["id"]
            self._state["team_reports_db"] = result["id"]

        # 5. Weekly Synthesis database
        result = self._client.create_database(
            parent_page_id=parent_page_id,
            title="Weekly Synthesis",
            properties={
                "Title": {"title": {}},
                "Date": {"date": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Published", "color": "green"},
                            {"name": "Draft", "color": "yellow"},
                        ]
                    }
                },
            },
        )
        if result.get("id"):
            db_ids["weekly_synthesis"] = result["id"]
            self._state["weekly_synthesis_db"] = result["id"]

        # Store parent as command center page
        self._state["command_center_page"] = parent_page_id

        self._save_state()
        logger.info("Notion databases created: %s", db_ids)
        return db_ids

    # -----------------------------------------------------------------
    # Daily brief sync
    # -----------------------------------------------------------------

    def push_daily_brief(
        self,
        date: str,
        headline: str,
        team_status: dict[str, dict[str, str]],
        decisions_needed: list[dict[str, Any]],
        blockers: list[str],
        cost_yesterday: str,
        brief_markdown: str,
    ) -> dict[str, Any]:
        """Push a daily brief to the Notion CoS Daily Briefs database."""
        db_id = self._state.get("daily_briefs_db", "")
        if not db_id or not self.enabled:
            logger.info("Daily brief not synced to Notion (not configured)")
            return {"synced": False}

        # Build content blocks from the markdown brief
        children = self._markdown_to_blocks(brief_markdown)

        # Build team status summary for the page
        team_lines = []
        status_icon = {"green": "G", "yellow": "Y", "red": "R"}
        for team, info in team_status.items():
            icon = status_icon.get(info.get("status", "green"), "?")
            team_lines.append(f"[{icon}] {team.title()}: {info.get('summary', '')}")

        result = self._client.create_page(
            database_id=db_id,
            properties={
                "Headline": NotionClient.title_property(headline),
                "Date": NotionClient.date_property(date),
                "Status": NotionClient.select_property("Published"),
                "Cost": NotionClient.rich_text_property(cost_yesterday),
                "Decisions Needed": NotionClient.number_property(len(decisions_needed)),
                "Blockers": NotionClient.number_property(len(blockers)),
            },
            children=children,
        )

        if result.get("id"):
            self._state["last_daily_sync"] = date
            self._state["last_daily_page_id"] = result["id"]
            self._save_state()
            logger.info("Daily brief synced to Notion: %s", result["id"])
            return {"synced": True, "page_id": result["id"]}

        logger.error("Failed to sync daily brief: %s", result)
        return {"synced": False, "error": result.get("message", "Unknown")}

    # -----------------------------------------------------------------
    # Team report sync
    # -----------------------------------------------------------------

    def push_team_report(
        self,
        date: str,
        team: str,
        health: str,
        summary: str,
        agent_count: int = 0,
        finding_count: int = 0,
        detail_markdown: str = "",
    ) -> dict[str, Any]:
        """Push a per-team daily report to the Notion Team Reports database."""
        db_id = self._state.get("team_reports_db", "")
        if not db_id or not self.enabled:
            logger.info("Team report not synced to Notion (not configured)")
            return {"synced": False}

        health_label = {"green": "Green", "yellow": "Yellow", "red": "Red"}.get(
            health, "Green"
        )
        children = self._markdown_to_blocks(detail_markdown) if detail_markdown else []

        result = self._client.create_page(
            database_id=db_id,
            properties={
                "Team": NotionClient.title_property(team.title()),
                "Date": NotionClient.date_property(date),
                "Health": NotionClient.select_property(health_label),
                "Summary": NotionClient.rich_text_property(summary),
                "Agents": NotionClient.number_property(agent_count),
                "Findings": NotionClient.number_property(finding_count),
            },
            children=children or None,
        )

        if result.get("id"):
            logger.info("Team report synced to Notion: %s (%s)", team, result["id"])
            return {"synced": True, "page_id": result["id"]}
        return {"synced": False, "error": result.get("message", "Unknown")}

    # -----------------------------------------------------------------
    # Weekly synthesis sync
    # -----------------------------------------------------------------

    def push_weekly_synthesis(
        self,
        date: str,
        brief_markdown: str,
    ) -> dict[str, Any]:
        """Push a weekly synthesis to the Notion Weekly Synthesis database."""
        db_id = self._state.get("weekly_synthesis_db", "")
        if not db_id or not self.enabled:
            logger.info("Weekly synthesis not synced to Notion (not configured)")
            return {"synced": False}

        children = self._markdown_to_blocks(brief_markdown)

        result = self._client.create_page(
            database_id=db_id,
            properties={
                "Title": NotionClient.title_property(f"Weekly Synthesis — {date}"),
                "Date": NotionClient.date_property(date),
                "Status": NotionClient.select_property("Published"),
            },
            children=children or None,
        )

        if result.get("id"):
            self._state["last_weekly_sync"] = date
            self._save_state()
            logger.info("Weekly synthesis synced to Notion: %s", result["id"])
            return {"synced": True, "page_id": result["id"]}
        return {"synced": False, "error": result.get("message", "Unknown")}

    # -----------------------------------------------------------------
    # Communication guide
    # -----------------------------------------------------------------

    def push_communication_guide(self) -> dict[str, Any]:
        """Create the static Communication Guide page in Notion."""
        parent_id = self._state.get("command_center_page", "")
        if not parent_id or not self.enabled:
            logger.info("Communication guide not synced to Notion (not configured)")
            return {"synced": False}

        blocks = self._build_communication_guide_blocks()
        result = self._client.create_child_page(
            parent_page_id=parent_id,
            title="Communication Guide",
            children=blocks,
        )

        if result.get("id"):
            logger.info("Communication guide created: %s", result["id"])
            return {"synced": True, "page_id": result["id"]}
        return {"synced": False, "error": result.get("message", "Unknown")}

    def _build_communication_guide_blocks(self) -> list[dict[str, Any]]:
        """Build Notion blocks for the Communication Guide page."""
        blocks: list[dict[str, Any]] = []

        blocks.append(NotionClient.heading_block("CLI Commands", level=2))
        for cmd in [
            "python3 -m agents.orchestrator --cos-daily — Run daily cycle",
            "python3 -m agents.orchestrator --all — Full scan all teams",
            'python3 -m agents.orchestrator --consult "Q" — Ask CoS a question',
            "python3 -m agents.orchestrator --weekly — Weekly synthesis",
            "python3 -m agents.orchestrator --monthly — Monthly review",
            "python3 -m TEAM.orchestrator --agent NAME — Run single agent",
            'python3 -m TEAM.orchestrator --consult "Q" — Consult specific team',
        ]:
            blocks.append(NotionClient.bulleted_list_block(cmd))

        blocks.append(NotionClient.heading_block("Notion Patterns", level=2))
        for tip in [
            "Create a Founder Brief with priority P0-P3 and status Active — CoS reads it next daily cycle",
            "Check Daily Brief page each morning for decisions needed",
            "Drill into Team Reports for per-team details",
            "Review Decision Log for audit trail of all decisions",
        ]:
            blocks.append(NotionClient.bulleted_list_block(tip))

        blocks.append(NotionClient.heading_block("Telegram Commands", level=2))
        for cmd in [
            "status — Get current status snapshot",
            "cost — Get cost report",
            "blockers — Get current blockers",
            "1, 2, 3 or 1=yes — Approve numbered decisions from daily brief",
            "A / B — Choose between escalation options",
            "Y / N — Yes/no to pending questions",
            "ship X — Trigger feature ship pipeline",
            "approve X — Approve a pending decision by name",
            "brief me on X — Request a brief on topic X",
            "pause TEAM — Pause a team's scans",
            "reprioritize: A > B — Reorder priorities",
        ]:
            blocks.append(NotionClient.bulleted_list_block(cmd))

        return blocks[:100]

    # -----------------------------------------------------------------
    # Decision log
    # -----------------------------------------------------------------

    def log_decision(
        self,
        decision: str,
        decider: str,
        context: str,
        outcome: str = "",
        business_outcomes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Log a decision to the Notion Decision Log database."""
        db_id = self._state.get("decision_log_db", "")
        if not db_id or not self.enabled:
            logger.info("Decision not logged to Notion (not configured)")
            return {"logged": False}

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        properties: dict[str, Any] = {
            "Decision": NotionClient.title_property(decision),
            "Date": NotionClient.date_property(today),
            "Decider": NotionClient.select_property(decider),
            "Context": NotionClient.rich_text_property(context),
        }
        if outcome:
            properties["Outcome"] = NotionClient.rich_text_property(outcome)
        if business_outcomes:
            properties["Business Outcome"] = NotionClient.multi_select_property(
                business_outcomes
            )

        result = self._client.create_page(database_id=db_id, properties=properties)

        if result.get("id"):
            logger.info("Decision logged to Notion: %s", result["id"])
            return {"logged": True, "page_id": result["id"]}

        return {"logged": False, "error": result.get("message", "Unknown")}

    # -----------------------------------------------------------------
    # Founder brief reader
    # -----------------------------------------------------------------

    def get_active_briefs(self) -> list[dict[str, Any]]:
        """Read active founder briefs from Notion (Rovik → CoS communication)."""
        db_id = self._state.get("founder_briefs_db", "")
        if not db_id or not self.enabled:
            return []

        result = self._client.query_database(
            database_id=db_id,
            filter_obj={
                "property": "Status",
                "select": {"equals": "Active"},
            },
            sorts=[{"property": "Priority", "direction": "ascending"}],
        )

        briefs = []
        for page in result.get("results", []):
            props = page.get("properties", {})
            title_parts = props.get("Title", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "Untitled"
            priority_obj = props.get("Priority", {}).get("select")
            priority = priority_obj["name"] if priority_obj else "P3"

            briefs.append(
                {
                    "page_id": page["id"],
                    "title": title,
                    "priority": priority,
                }
            )

        return briefs

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
        """Convert simple markdown to Notion blocks (headings + paragraphs)."""
        blocks: list[dict[str, Any]] = []
        for line in markdown.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("### "):
                blocks.append(NotionClient.heading_block(stripped[4:], level=3))
            elif stripped.startswith("## "):
                blocks.append(NotionClient.heading_block(stripped[3:], level=2))
            elif stripped.startswith("# "):
                blocks.append(NotionClient.heading_block(stripped[2:], level=1))
            elif stripped.startswith("- "):
                blocks.append(NotionClient.bulleted_list_block(stripped[2:]))
            else:
                blocks.append(NotionClient.paragraph_block(stripped))
        # Notion limits to 100 blocks per request
        return blocks[:100]
