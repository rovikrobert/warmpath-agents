"""Unified Memory Service CLI.

Usage:
    python3 -m agents.memory search "query" --team engineering --top-k 5
    python3 -m agents.memory save --content "..." --tags tag1,tag2 --team claude_code
    python3 -m agents.memory recent --days 7 --team cos
    python3 -m agents.memory stats
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path (mirrors agents/orchestrator.py pattern).
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.database import _get_session_factory  # noqa: E402
from app.services.memory_service import MemoryService  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_timestamp(iso: str | None) -> str:
    """Render an ISO timestamp as a human-friendly string."""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16] if iso else "-"


def _format_tags(tags: list[str] | None) -> str:
    """Comma-join tags for display."""
    if not tags:
        return "-"
    return ", ".join(tags)


def _truncate(text: str, length: int = 120) -> str:
    """Truncate text for single-line display."""
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


def _print_memory(mem: dict, idx: int | None = None) -> None:
    """Pretty-print a single memory dict."""
    prefix = f"  [{idx}]" if idx is not None else "  *"
    score_part = f"  score={mem['score']:.4f}" if "score" in mem else ""

    print(f"{prefix} {mem['id'][:8]}...{score_part}")
    print(f"       content:  {_truncate(mem['content'])}")
    if mem.get("summary"):
        print(f"       summary:  {_truncate(mem['summary'])}")
    print(f"       team:     {mem.get('team') or '-'}")
    print(
        f"       source:   {mem.get('source_type', '-')} / {mem.get('source_id', '-')}"
    )
    print(f"       tags:     {_format_tags(mem.get('tags'))}")
    print(
        f"       importance: {mem.get('importance', 0.5):.2f}  "
        f"created: {_format_timestamp(mem.get('created_at'))}"
    )
    print()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


async def cmd_search(args: argparse.Namespace) -> None:
    """Search memories with hybrid BM25 + vector recall."""
    async with _get_session_factory()() as session:
        svc = MemoryService(db=session)
        results = await svc.recall(
            args.query,
            top_k=args.top_k,
            team=args.team,
            source_type=args.source_type,
        )

    if not results:
        print("No memories found.")
        return

    print(f"\n  Found {len(results)} memor{'y' if len(results) == 1 else 'ies'}:\n")
    for i, mem in enumerate(results, 1):
        _print_memory(mem, idx=i)


async def cmd_save(args: argparse.Namespace) -> None:
    """Save a new memory."""
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    async with _get_session_factory()() as session:
        svc = MemoryService(db=session)
        memory_id = await svc.remember(
            content=args.content,
            source_type=args.source_type,
            source_id=args.source_id,
            summary=args.summary,
            team=args.team,
            tags=tags,
            importance=args.importance,
            ttl_hours=args.ttl_hours,
        )

    print(f"  Saved memory: {memory_id}")


async def cmd_recent(args: argparse.Namespace) -> None:
    """List recently created memories."""
    async with _get_session_factory()() as session:
        svc = MemoryService(db=session)
        results = await svc.recall_recent(
            days=args.days,
            team=args.team,
            top_k=args.top_k,
        )

    if not results:
        print("No recent memories found.")
        return

    print(
        f"\n  {len(results)} memor{'y' if len(results) == 1 else 'ies'} "
        f"from the last {args.days} day{'s' if args.days != 1 else ''}:\n"
    )
    for i, mem in enumerate(results, 1):
        _print_memory(mem, idx=i)


async def cmd_stats(args: argparse.Namespace) -> None:
    """Print aggregate stats from the memories table."""
    from sqlalchemy import text

    async with _get_session_factory()() as session:
        # Total count
        result = await session.execute(text("SELECT count(*) FROM memories"))
        total = result.scalar() or 0

        # Breakdown by team
        result = await session.execute(
            text(
                "SELECT coalesce(team, '(none)') AS team, count(*) AS cnt "
                "FROM memories GROUP BY team ORDER BY cnt DESC"
            )
        )
        by_team = result.fetchall()

        # Breakdown by source_type
        result = await session.execute(
            text(
                "SELECT source_type, count(*) AS cnt "
                "FROM memories GROUP BY source_type ORDER BY cnt DESC"
            )
        )
        by_source = result.fetchall()

        # Expired count
        result = await session.execute(
            text(
                "SELECT count(*) FROM memories "
                "WHERE expires_at IS NOT NULL AND expires_at < NOW()"
            )
        )
        expired = result.scalar() or 0

    print("\n  Memory Store Stats")
    print(f"  {'=' * 40}")
    print(f"  Total memories:   {total}")
    print(f"  Expired:          {expired}")
    print()

    if by_team:
        print("  By Team:")
        for row in by_team:
            print(f"    {row[0]:<20} {row[1]:>6}")
        print()

    if by_source:
        print("  By Source Type:")
        for row in by_source:
            print(f"    {row[0]:<20} {row[1]:>6}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m agents.memory",
        description="Unified Memory Service CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- search ---
    sp_search = subparsers.add_parser(
        "search", help="Search memories (hybrid BM25 + vector)"
    )
    sp_search.add_argument("query", type=str, help="Search query")
    sp_search.add_argument(
        "--top-k", type=int, default=10, help="Max results (default: 10)"
    )
    sp_search.add_argument("--team", type=str, default=None, help="Filter by team")
    sp_search.add_argument(
        "--source-type", type=str, default=None, help="Filter by source_type"
    )

    # --- save ---
    sp_save = subparsers.add_parser("save", help="Save a new memory")
    sp_save.add_argument(
        "--content", type=str, required=True, help="Memory content (required)"
    )
    sp_save.add_argument("--summary", type=str, default=None, help="Short summary")
    sp_save.add_argument(
        "--tags",
        type=str,
        default=None,
        help="Comma-separated tags (e.g. lint,workflow)",
    )
    sp_save.add_argument("--team", type=str, default=None, help="Team name")
    sp_save.add_argument(
        "--source-type", type=str, default="cli", help="Source type (default: cli)"
    )
    sp_save.add_argument(
        "--source-id", type=str, default="agents.memory", help="Source identifier"
    )
    sp_save.add_argument(
        "--importance",
        type=float,
        default=0.5,
        help="Importance weight 0.0-1.0 (default: 0.5)",
    )
    sp_save.add_argument(
        "--ttl-hours", type=int, default=None, help="Auto-expire after N hours"
    )

    # --- recent ---
    sp_recent = subparsers.add_parser("recent", help="List recent memories")
    sp_recent.add_argument(
        "--days", type=int, default=7, help="Look back N days (default: 7)"
    )
    sp_recent.add_argument("--team", type=str, default=None, help="Filter by team")
    sp_recent.add_argument(
        "--top-k", type=int, default=10, help="Max results (default: 10)"
    )

    # --- stats ---
    subparsers.add_parser("stats", help="Show memory store statistics")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "search": cmd_search,
        "save": cmd_save,
        "recent": cmd_recent,
        "stats": cmd_stats,
    }

    cmd_fn = dispatch[args.command]
    asyncio.run(cmd_fn(args))


if __name__ == "__main__":
    main()
