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
            self._save_state()
            logger.info("Daily brief synced to Notion: %s", result["id"])
            return {"synced": True, "page_id": result["id"]}

        logger.error("Failed to sync daily brief: %s", result)
        return {"synced": False, "error": result.get("message", "Unknown")}

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

            briefs.append({
                "page_id": page["id"],
                "title": title,
                "priority": priority,
            })

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
            if stripped.startswith("## "):
                blocks.append(NotionClient.heading_block(stripped[3:], level=2))
            elif stripped.startswith("# "):
                blocks.append(NotionClient.heading_block(stripped[2:], level=1))
            elif stripped.startswith("- "):
                blocks.append(NotionClient.bulleted_list_block(stripped[2:]))
            else:
                blocks.append(NotionClient.paragraph_block(stripped))
        # Notion limits to 100 blocks per request
        return blocks[:100]
