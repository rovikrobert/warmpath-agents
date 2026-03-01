"""AgentMemory — sync-friendly bridge to the async MemoryService.

Allows agent teams (which run sync code in scan() functions) to persist and
retrieve memories without managing async boilerplate.  Every public method
catches exceptions and degrades gracefully so that a DB outage never crashes
an agent scan.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

# Shared executor for running async code when an event loop is already active
_THREAD_POOL = ThreadPoolExecutor(max_workers=2)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync code.

    If no event loop is running in the current thread, use ``asyncio.run()``.
    Otherwise, schedule the coroutine in a background thread so we don't block
    or nest event loops.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    # There's already a running loop (e.g. inside Jupyter or nested agent) —
    # spin up a new loop in a thread to avoid "cannot run nested event loops".

    future = _THREAD_POOL.submit(asyncio.run, coro)
    return future.result(timeout=30)


class AgentMemory:
    """Sync wrapper around :class:`~app.services.memory_service.MemoryService`.

    Usage inside an agent ``scan()`` function::

        mem = AgentMemory(team="agents", agent="architect")
        mem.remember("Detected 3 circular imports in app/services/")
        results = mem.recall("circular imports")
    """

    def __init__(self, team: str, agent: str) -> None:
        self.team = team
        self.agent = agent

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    def _is_enabled() -> bool:
        """Check if the memory service is enabled via feature flag."""
        try:
            from app.config import settings

            return bool(settings.MEMORY_SERVICE_ENABLED)
        except Exception:
            return False

    def remember(
        self,
        content: str,
        *,
        summary: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
        ttl_hours: int | None = None,
    ) -> None:
        """Store a memory.  Falls back silently on DB errors."""
        if not self._is_enabled():
            return
        try:
            _run_async(
                self._async_remember(
                    content,
                    summary=summary,
                    tags=tags,
                    metadata=metadata,
                    importance=importance,
                    ttl_hours=ttl_hours,
                )
            )
        except Exception:
            logger.warning(
                "AgentMemory.remember failed for %s/%s — skipping",
                self.team,
                self.agent,
                exc_info=True,
            )

    async def _async_remember(
        self,
        content: str,
        *,
        summary: str | None,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
        importance: float,
        ttl_hours: int | None,
    ) -> None:
        from app.database import _get_session_factory
        from app.services.memory_service import MemoryService

        async with _get_session_factory()() as session:
            svc = MemoryService(session)
            await svc.remember(
                content,
                source_type="agent_scan",
                source_id=self.agent,
                summary=summary,
                team=self.team,
                tags=tags,
                metadata=metadata,
                importance=importance,
                ttl_hours=ttl_hours,
            )

    # ------------------------------------------------------------------
    # Read — keyword / hybrid search
    # ------------------------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        team: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories.  Returns empty list on failure."""
        if not self._is_enabled():
            return []
        try:
            return _run_async(self._async_recall(query, top_k=top_k, team=team))
        except Exception:
            logger.warning(
                "AgentMemory.recall failed for %s/%s — returning empty",
                self.team,
                self.agent,
                exc_info=True,
            )
            return []

    async def _async_recall(
        self,
        query: str,
        *,
        top_k: int,
        team: str | None,
    ) -> list[dict[str, Any]]:
        from app.database import _get_session_factory
        from app.services.memory_service import MemoryService

        async with _get_session_factory()() as session:
            svc = MemoryService(session)
            return await svc.recall(
                query,
                top_k=top_k,
                team=team or self.team,
                source_type="agent_scan",
            )

    # ------------------------------------------------------------------
    # Read — file-specific
    # ------------------------------------------------------------------

    def recall_about_file(
        self,
        file_path: str,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find memories tagged with a specific file path."""
        if not self._is_enabled():
            return []
        try:
            return _run_async(self._async_recall_about_file(file_path, top_k=top_k))
        except Exception:
            logger.warning(
                "AgentMemory.recall_about_file failed for %s/%s — returning empty",
                self.team,
                self.agent,
                exc_info=True,
            )
            return []

    async def _async_recall_about_file(
        self,
        file_path: str,
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        from app.database import _get_session_factory
        from app.services.memory_service import MemoryService

        async with _get_session_factory()() as session:
            svc = MemoryService(session)
            return await svc.recall_about_file(file_path, top_k=top_k)
