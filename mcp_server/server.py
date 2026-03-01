"""MCP server setup and tool registration."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("warmpath")


def register_tools() -> None:
    """Import tool modules to trigger @mcp.tool() registration."""
    from mcp_server.tools import audit, database, health, memory, reports, stripe  # noqa: F401

    logger.info("All MCP tools registered")
