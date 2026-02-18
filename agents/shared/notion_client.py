"""Notion API client for agent-to-Notion integration.

Uses httpx to communicate with the Notion API v1.
Requires NOTION_API_KEY environment variable.

Usage:
    from agents.shared.notion_client import NotionClient

    client = NotionClient()
    client.create_page(database_id="...", properties={...}, children=[...])
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


class NotionClient:
    """Synchronous Notion API client using httpx."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self._enabled = bool(self._api_key)
        if not self._enabled:
            logger.info("Notion integration disabled (NOTION_API_KEY not set)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Notion API."""
        if not self._enabled:
            logger.warning("Notion API call skipped (not configured)")
            return {"object": "error", "status": 503, "message": "Not configured"}

        url = f"{NOTION_BASE_URL}{path}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method, url, headers=self._headers(), json=json_body
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Notion API error %s: %s", e.response.status_code, e.response.text
            )
            return {
                "object": "error",
                "status": e.response.status_code,
                "message": e.response.text,
            }
        except httpx.RequestError as e:
            logger.error("Notion request failed: %s", e)
            return {"object": "error", "status": 0, "message": str(e)}

    # -----------------------------------------------------------------
    # Database operations
    # -----------------------------------------------------------------

    def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new database under a parent page."""
        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        return self._request("POST", "/databases", body)

    def query_database(
        self,
        database_id: str,
        filter_obj: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """Query a database with optional filter and sorts."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts
        return self._request("POST", f"/databases/{database_id}/query", body)

    # -----------------------------------------------------------------
    # Page operations
    # -----------------------------------------------------------------

    def create_page(
        self,
        database_id: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a page (row) in a database."""
        body: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if children:
            body["children"] = children
        return self._request("POST", "/pages", body)

    def update_page(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Update properties on an existing page."""
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a page by ID."""
        return self._request("GET", f"/pages/{page_id}")

    def append_blocks(
        self,
        block_id: str,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append child blocks to a page or block."""
        return self._request(
            "PATCH", f"/blocks/{block_id}/children", {"children": children}
        )

    # -----------------------------------------------------------------
    # Block helpers
    # -----------------------------------------------------------------

    @staticmethod
    def heading_block(text: str, level: int = 2) -> dict[str, Any]:
        """Create a heading block (level 1-3)."""
        key = f"heading_{min(max(level, 1), 3)}"
        return {
            "object": "block",
            "type": key,
            key: {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            },
        }

    @staticmethod
    def paragraph_block(text: str) -> dict[str, Any]:
        """Create a paragraph block."""
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            },
        }

    @staticmethod
    def bulleted_list_block(text: str) -> dict[str, Any]:
        """Create a bulleted list item block."""
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
            },
        }

    @staticmethod
    def divider_block() -> dict[str, Any]:
        """Create a divider block."""
        return {"object": "block", "type": "divider", "divider": {}}

    @staticmethod
    def title_property(text: str) -> dict[str, Any]:
        """Create a title property value."""
        return {"title": [{"text": {"content": text}}]}

    @staticmethod
    def rich_text_property(text: str) -> dict[str, Any]:
        """Create a rich text property value."""
        return {"rich_text": [{"text": {"content": text}}]}

    @staticmethod
    def select_property(name: str) -> dict[str, Any]:
        """Create a select property value."""
        return {"select": {"name": name}}

    @staticmethod
    def multi_select_property(names: list[str]) -> dict[str, Any]:
        """Create a multi-select property value."""
        return {"multi_select": [{"name": n} for n in names]}

    @staticmethod
    def date_property(start: str, end: str | None = None) -> dict[str, Any]:
        """Create a date property value (ISO 8601 format)."""
        date: dict[str, str] = {"start": start}
        if end:
            date["end"] = end
        return {"date": date}

    @staticmethod
    def number_property(value: float) -> dict[str, Any]:
        """Create a number property value."""
        return {"number": value}
