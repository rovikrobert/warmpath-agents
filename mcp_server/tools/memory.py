"""Memory tools — search, save, and index session learnings via unified memory store."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from mcp_server.server import mcp

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync MCP tool context.

    Uses asyncio.run() since MCP tools are called from sync context with no
    running event loop.
    """
    return asyncio.run(coro)


async def _get_session() -> Any:
    """Create an async DB session for one-shot use."""
    from app.database import _get_session_factory

    return _get_session_factory()()


def _check_enabled() -> dict[str, Any] | None:
    """Return an error dict if memory service is disabled, else None."""
    from app.config import settings

    if not settings.MEMORY_SERVICE_ENABLED:
        return {"error": "Memory service is disabled (MEMORY_SERVICE_ENABLED=false)"}
    return None


@mcp.tool()
def search_memory(
    query: str,
    team: str | None = None,
    top_k: int = 10,
    bm25_weight: float | None = None,
    temporal_half_life: int | None = None,
) -> dict[str, Any]:
    """Search the unified memory store using hybrid BM25 + vector search.

    Finds memories from agent scans, Claude Code sessions, shared insights,
    and manual notes. Results ranked by hybrid relevance with temporal decay
    and MMR diversity re-ranking.

    Args:
        query: Free-text search query.
        team: Optional team filter (e.g. "agents", "data_team").
        top_k: Maximum results to return (default 10).
        bm25_weight: Override BM25 weight in hybrid scoring.
        temporal_half_life: Override temporal decay half-life in days.
    """
    disabled = _check_enabled()
    if disabled:
        return disabled

    if not query or not query.strip():
        return {"count": 0, "results": []}

    try:
        from app.services.memory_service import MemoryService

        async def _search() -> dict[str, Any]:
            session = await _get_session()
            try:
                svc = MemoryService(session)
                kwargs: dict[str, Any] = {"top_k": min(top_k, 100)}
                if team:
                    kwargs["team"] = team
                if bm25_weight is not None:
                    kwargs["bm25_weight"] = bm25_weight
                if temporal_half_life is not None:
                    kwargs["temporal_half_life"] = temporal_half_life
                results = await svc.recall(query, **kwargs)
                return {"count": len(results), "results": results}
            finally:
                await session.close()

        return _run_async(_search())
    except Exception as exc:
        logger.exception("search_memory failed")
        return {"error": f"Search failed: {exc}"}


@mcp.tool()
def save_memory(
    content: str,
    summary: str | None = None,
    team: str | None = None,
    tags: list[str] | None = None,
    importance: float = 0.5,
    ttl_hours: int | None = None,
) -> dict[str, Any]:
    """Save a new memory to the unified memory store.

    Persist knowledge, decisions, debugging insights, or patterns for
    future retrieval. Memories are indexed for both keyword and semantic
    search.

    Args:
        content: The memory content to store.
        summary: Optional short summary (used for embedding if provided).
        team: Optional team tag (e.g. "agents", "data_team").
        tags: Optional list of tags for categorisation.
        importance: Importance weight 0.0-1.0 (default 0.5).
        ttl_hours: Optional time-to-live in hours (None = never expires).
    """
    disabled = _check_enabled()
    if disabled:
        return disabled

    if not content or not content.strip():
        return {"error": "Content cannot be empty"}

    try:
        from app.services.memory_service import MemoryService

        async def _save() -> dict[str, Any]:
            session = await _get_session()
            try:
                svc = MemoryService(session)
                memory_id = await svc.remember(
                    content=content,
                    source_type="mcp_tool",
                    source_id=f"mcp-{uuid.uuid4().hex[:8]}",
                    summary=summary,
                    team=team,
                    tags=tags,
                    importance=max(0.0, min(1.0, importance)),
                    ttl_hours=ttl_hours,
                )
                return {"id": str(memory_id), "status": "saved"}
            finally:
                await session.close()

        return _run_async(_save())
    except Exception as exc:
        logger.exception("save_memory failed")
        return {"error": f"Save failed: {exc}"}


@mcp.tool()
def index_session(
    session_summary: str,
    key_learnings: list[str] | None = None,
) -> dict[str, Any]:
    """Index a Claude Code session's key learnings into memory.

    Each learning becomes a separate, searchable memory tagged with
    source_type='claude_code_session'. The session summary is also
    stored as a memory.

    Args:
        session_summary: Overall summary of the session.
        key_learnings: Optional list of individual learnings to index.
    """
    disabled = _check_enabled()
    if disabled:
        return disabled

    if not session_summary or not session_summary.strip():
        return {"error": "Session summary cannot be empty"}

    try:
        from app.services.memory_service import MemoryService

        async def _index() -> dict[str, Any]:
            session = await _get_session()
            try:
                svc = MemoryService(session)
                session_source_id = f"session-{uuid.uuid4().hex[:8]}"
                memories_created = 0

                # Store the session summary itself
                await svc.remember(
                    content=session_summary,
                    source_type="claude_code_session",
                    source_id=session_source_id,
                    summary=f"Session summary: {session_summary[:200]}",
                    tags=["session_summary"],
                    importance=0.6,
                )
                memories_created += 1

                # Store each learning as a separate memory (cap at 50)
                for i, learning in enumerate((key_learnings or [])[:50]):
                    if not learning or not learning.strip():
                        continue
                    await svc.remember(
                        content=learning,
                        source_type="claude_code_session",
                        source_id=f"{session_source_id}-learning-{i}",
                        summary=learning[:200] if len(learning) > 200 else None,
                        tags=["session_learning"],
                        importance=0.7,
                    )
                    memories_created += 1

                return {"status": "indexed", "memories_created": memories_created}
            finally:
                await session.close()

        return _run_async(_index())
    except Exception as exc:
        logger.exception("index_session failed")
        return {"error": f"Index failed: {exc}"}
