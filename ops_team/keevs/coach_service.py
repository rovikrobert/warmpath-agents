"""Keevs AI Job Coach — conversational career guidance from user context.

Assembles the user's full data (network, preferences, applications, searches,
credits, market trends) into a context snapshot, then generates personalized
briefings and chat responses via Claude (or deterministic mocks).
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.enrichment import UsageLog
from app.models.job import Application, UserJobPreferences
from app.models.search_request import SearchRequest
from app.models.user import ConnectorProfile, User
from app.services.credits import get_balance
from app.services.dashboard_insights import (
    _get_network_analysis,
    _read_cache,
    _write_cache,
)

logger = logging.getLogger(__name__)

CLAUDE_MODEL = settings.CLAUDE_MODEL

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_KEEVS_SYSTEM_PROMPT = """You are Keevs, an AI career coach inside WarmPath — a platform that helps job seekers get employee referrals instead of applying cold.

PERSONALITY: Sharp, supportive, action-oriented. You're a smart career-savvy friend, not a corporate chatbot. Short paragraphs. No filler. Every sentence earns its place.

RULES:
- Always reference specific data when available. Never generic when specific is possible.
- For briefings: 3-5 sentences. Greeting, key insight, concrete next step. Include markdown links like [find referrals](/referrals) or [upload contacts](/contacts).
- For chat: 1-3 paragraphs. Always end with something actionable.
- Do NOT name specific contacts (privacy). Talk about counts at companies ("you have 3 contacts at Stripe").
- Do NOT invent data. If something is missing, acknowledge it and suggest filling it in.
- Include markdown links to relevant pages: [contacts](/contacts), [find referrals](/referrals), [applications](/applications), [preferences](/preferences), [credits](/credits).
- Never use "I hope this finds you well" or similar filler.
- Never mention that you're an AI unless directly asked.

CONTEXT: You receive the user's data as a JSON snapshot. Use it to give personalized advice."""


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


_CONTEXT_CACHE: dict[str, tuple[float, dict]] = {}
_CONTEXT_CACHE_TTL = 300  # 5 minutes


async def _assemble_context(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Build a context snapshot from all user data sources.

    Cached for 5 minutes to avoid re-running 7 queries on every chat message.
    Queries run in parallel via asyncio.gather for lower latency.
    """
    cache_key = str(user_id)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Return cached context if fresh
    if cache_key in _CONTEXT_CACHE:
        cached_ts, cached_ctx = _CONTEXT_CACHE[cache_key]
        if now_ts - cached_ts < _CONTEXT_CACHE_TTL:
            return cached_ctx

    # --- Run independent queries in parallel ---

    async def _fetch_user():
        result = await db.execute(
            select(User)
            .options(selectinload(User.connector_profile))
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _fetch_prefs():
        result = await db.execute(
            select(UserJobPreferences).where(UserJobPreferences.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _fetch_pipeline():
        result = await db.execute(
            select(Application.status, func.count(Application.id))
            .where(
                Application.user_id == user_id,
                Application.deleted_at.is_(None),
            )
            .group_by(Application.status)
        )
        return {row[0]: row[1] for row in result.all()}

    async def _fetch_followups():
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(func.count(Application.id)).where(
                Application.user_id == user_id,
                Application.deleted_at.is_(None),
                Application.follow_up_at.isnot(None),
                Application.follow_up_at <= now,
                Application.status.notin_(["rejected", "withdrawn", "offer_accepted"]),
            )
        )
        return result.scalar() or 0

    async def _fetch_searches():
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        result = await db.execute(
            select(SearchRequest.name, SearchRequest.status, SearchRequest.created_at)
            .where(
                SearchRequest.user_id == user_id,
                SearchRequest.deleted_at.is_(None),
                SearchRequest.created_at >= cutoff,
            )
            .order_by(SearchRequest.created_at.desc())
            .limit(5)
        )
        return [
            {
                "name": row[0],
                "status": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
            }
            for row in result.all()
        ]

    async def _fetch_credits():
        return await get_balance(user_id, db)

    # Run all 6 fast queries in parallel
    (
        user,
        prefs,
        status_counts,
        follow_ups_needed,
        recent_searches,
        credit_balance,
    ) = await asyncio.gather(
        _fetch_user(),
        _fetch_prefs(),
        _fetch_pipeline(),
        _fetch_followups(),
        _fetch_searches(),
        _fetch_credits(),
    )

    # Build user context
    user_ctx: dict = {"name": None, "title": None, "company": None, "location": None}
    if user:
        user_ctx["name"] = user.full_name
        profile: ConnectorProfile | None = user.connector_profile
        if profile:
            user_ctx["title"] = profile.current_title
            user_ctx["company"] = profile.current_company
            user_ctx["location"] = profile.location

    prefs_ctx: dict | None = None
    if prefs:
        prefs_ctx = {
            "target_role": prefs.target_role,
            "target_seniority": prefs.target_seniority,
            "target_industries": prefs.target_industries,
            "target_locations": prefs.target_locations,
            "open_to_remote": prefs.open_to_remote,
            "job_search_status": prefs.job_search_status,
        }

    # Network analysis — run separately (heavier, accesses dashboard_insights)
    network_ctx: dict | None = None
    try:
        network_ctx = await _get_network_analysis(user_id, db, prefs)
    except Exception:
        logger.exception("Coach: failed to get network analysis for %s", user_id)

    pipeline_ctx = {
        "status_counts": status_counts,
        "follow_ups_needed": follow_ups_needed,
        "total": sum(status_counts.values()),
    }

    # Skip market trends in chat context (expensive, only needed for briefing)
    # Briefing already caches its own result via generate_briefing()

    context = {
        "user": user_ctx,
        "preferences": prefs_ctx,
        "network": network_ctx,
        "pipeline": pipeline_ctx,
        "recent_searches": recent_searches,
        "credits": credit_balance,
        "market": None,
    }

    _CONTEXT_CACHE[cache_key] = (now_ts, context)
    return context


# ---------------------------------------------------------------------------
# Suggested prompts
# ---------------------------------------------------------------------------


def get_suggested_prompts(context: dict) -> list[str]:
    """Return 3-4 contextual prompt suggestions based on user state."""
    prompts: list[str] = []

    network = context.get("network")
    pipeline = context.get("pipeline", {})
    prefs = context.get("preferences")
    follow_ups = pipeline.get("follow_ups_needed", 0)
    total_contacts = (network or {}).get("total_contacts", 0)
    total_apps = pipeline.get("total", 0)

    if total_contacts == 0:
        prompts.append("How do I get started?")
    elif not context.get("recent_searches"):
        prompts.append("Which companies should I target?")

    if follow_ups > 0:
        prompts.append("What follow-ups should I send?")

    if prefs:
        prompts.append("What's the market like for my role?")

    if total_apps > 0:
        prompts.append("How's my pipeline looking?")

    if not prompts:
        prompts.append("What should I focus on today?")

    # Always include a general option
    if len(prompts) < 2:
        prompts.append("What should I focus on today?")

    return prompts[:4]


# ---------------------------------------------------------------------------
# Mock functions
# ---------------------------------------------------------------------------


def _mock_briefing(context: dict) -> str:
    """Generate a deterministic briefing from context data."""
    user = context.get("user", {})
    name = user.get("name") or "there"
    first_name = name.split()[0] if name != "there" else "there"

    parts: list[str] = [f"Hey {first_name}, here's your daily briefing."]

    pipeline = context.get("pipeline", {})
    total_apps = pipeline.get("total", 0)
    follow_ups = pipeline.get("follow_ups_needed", 0)

    if total_apps > 0:
        status_counts = pipeline.get("status_counts", {})
        active = sum(
            v for k, v in status_counts.items() if k not in ("rejected", "withdrawn")
        )
        parts.append(
            f"You have {active} active application{'s' if active != 1 else ''} in your pipeline."
        )

    if follow_ups > 0:
        parts.append(
            f"**{follow_ups} follow-up{'s' if follow_ups != 1 else ''}** "
            f"{'are' if follow_ups != 1 else 'is'} due — check your [applications](/applications)."
        )

    network = context.get("network")
    if network:
        total = network.get("total_contacts", 0)
        top = network.get("top_companies", [])
        if top:
            top_name = top[0]["company"]
            top_count = top[0]["count"]
            parts.append(
                f"Your network has {total} contacts — strongest at {top_name} ({top_count})."
            )
        else:
            parts.append(f"Your network has {total} contacts.")
    else:
        parts.append(
            "You haven't uploaded contacts yet — [upload your LinkedIn CSV](/contacts) to get started."
        )

    market = context.get("market")
    if market and market.get("summary"):
        parts.append(market["summary"])

    prefs = context.get("preferences")
    if not prefs:
        parts.append(
            "Set your [job preferences](/preferences) so I can give you targeted advice."
        )

    return " ".join(parts)


def _mock_chat_response(message: str, context: dict) -> str:
    """Generate keyword-based mock chat responses."""
    msg_lower = message.lower()
    network = context.get("network")
    pipeline = context.get("pipeline", {})
    prefs = context.get("preferences")

    if any(kw in msg_lower for kw in ("follow-up", "follow up", "followup")):
        follow_ups = pipeline.get("follow_ups_needed", 0)
        if follow_ups > 0:
            return (
                f"You have {follow_ups} follow-up{'s' if follow_ups != 1 else ''} due. "
                "Head to your [applications](/applications) to see which ones need attention. "
                "A good follow-up is short: restate your interest, add one new insight about "
                "the company, and ask about timeline."
            )
        return (
            "No follow-ups due right now. Keep your pipeline moving by "
            "[finding new referral paths](/referrals)."
        )

    if any(kw in msg_lower for kw in ("network", "contact", "connection")):
        if network:
            total = network.get("total_contacts", 0)
            top = network.get("top_companies", [])
            top_str = ", ".join(f"{c['company']} ({c['count']})" for c in top[:3])
            return (
                f"Your network has {total} contacts. Strongest at: {top_str}. "
                "To find referral paths at specific companies, head to "
                "[find referrals](/referrals)."
            )
        return (
            "You haven't uploaded contacts yet. [Upload your LinkedIn CSV](/contacts) "
            "and I can help you identify the best referral paths."
        )

    if any(kw in msg_lower for kw in ("company", "target", "should i")):
        if prefs and prefs.get("target_role"):
            role = prefs["target_role"]
            return (
                f"Based on your target role ({role}), I'd focus on companies where you "
                "already have contacts. Check your [network](/contacts) for companies with "
                "3+ connections — those give you the best referral odds. Then "
                "[search for referrals](/referrals) at those companies."
            )
        return (
            "I don't have your target role yet. "
            "[Set your preferences](/preferences) and I can give you specific guidance."
        )

    if any(kw in msg_lower for kw in ("credit", "balance")):
        balance = context.get("credits", 0)
        return (
            f"You have {balance} credits. Credits are used for cross-network searches (5) "
            "and intro requests (20). Earn more by uploading contacts (100) or "
            "facilitating intros (50). Check your [credit history](/credits)."
        )

    if any(kw in msg_lower for kw in ("start", "begin", "how do i", "getting started")):
        return (
            "Here's your game plan:\n\n"
            "1. [Upload your LinkedIn CSV](/contacts) — this maps your network.\n"
            "2. [Set your job preferences](/preferences) — target role, seniority, locations.\n"
            "3. [Search for referrals](/referrals) — I'll find warm paths to your target companies.\n\n"
            "The key insight: referrals convert at 10-40% vs 1-3% for cold applications. "
            "Your existing network is more valuable than you think."
        )

    if any(kw in msg_lower for kw in ("pipeline", "application")):
        total = pipeline.get("total", 0)
        if total > 0:
            status_counts = pipeline.get("status_counts", {})
            parts = [f"{v} {k}" for k, v in status_counts.items()]
            return (
                f"Your pipeline has {total} applications: {', '.join(parts)}. "
                "View details in your [applications](/applications). "
                "Keep targeting 5-10 companies deeply rather than spreading thin."
            )
        return (
            "No applications tracked yet. Once you find referral paths, "
            "start tracking applications in your [pipeline](/applications)."
        )

    # Fallback
    return (
        "I can help with your job search strategy, network analysis, "
        "follow-up timing, and referral approach. Try asking about your "
        "network, pipeline, or what to focus on next."
    )


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------


async def generate_briefing(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Generate (or return cached) daily briefing."""
    cache_key = f"keevs_briefing:{user_id}"

    # Check cache
    cached = await _read_cache(cache_key, db)
    if cached is not None:
        return cached

    # Assemble context
    context = await _assemble_context(user_id, db)

    # Generate briefing
    if settings.AI_MOCK_MODE:
        briefing_text = _mock_briefing(context)
    else:
        briefing_text = await _generate_briefing_via_claude(context)

    suggested = get_suggested_prompts(context)

    result = {
        "briefing": briefing_text,
        "context_snapshot": context,
        "suggested_prompts": suggested,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Cache and flush so it persists on the connection
    await _write_cache(cache_key, result, settings.KEEVS_BRIEFING_CACHE_TTL_HOURS, db)
    await db.flush()

    return result


async def _generate_briefing_via_claude(context: dict) -> str:
    """Call Claude API for briefing generation."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        user_prompt = (
            "Generate my daily career briefing based on this data:\n\n"
            f"{json.dumps(context, default=str, indent=2)}"
        )

        message = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=_KEEVS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude briefing API failed: %s — falling back to mock", exc)
        return _mock_briefing(context)


# ---------------------------------------------------------------------------
# Chat generation
# ---------------------------------------------------------------------------


async def generate_chat_response(
    user_id: uuid.UUID,
    message: str,
    conversation_history: list[dict] | None,
    context_snapshot: dict | None,
    db: AsyncSession,
) -> dict:
    """Generate a chat response from Keevs."""
    # If no context provided, assemble fresh
    if not context_snapshot:
        context_snapshot = await _assemble_context(user_id, db)

    if settings.AI_MOCK_MODE:
        response_text = _mock_chat_response(message, context_snapshot)
    else:
        response_text = await _generate_chat_via_claude(
            message, conversation_history or [], context_snapshot
        )

    # Log usage
    db.add(
        UsageLog(
            user_id=user_id,
            action="coach_chat",
            resource_type="coach",
            metadata_={"message_length": len(message)},
        )
    )

    return {"response": response_text}


def _build_chat_messages(
    message: str,
    conversation_history: list[dict],
    context: dict,
) -> list[dict]:
    """Build Claude messages array with context injection + history."""
    messages: list[dict] = []

    # Context injection as first user message
    context_msg = (
        "Here is the user's current data snapshot. Use it to personalize your responses:\n\n"
        f"{json.dumps(context, default=str, indent=2)}\n\n"
        "Acknowledge this context silently — do not repeat it back."
    )
    messages.append({"role": "user", "content": context_msg})
    messages.append(
        {
            "role": "assistant",
            "content": "Understood. I have your context. How can I help?",
        }
    )

    # Last 10 messages of history (validated entries only)
    for entry in (conversation_history or [])[-10:]:
        if not isinstance(entry, dict):
            continue
        role_val = entry.get("role")
        content_val = entry.get("content")
        if role_val not in ("user", "keevs") or not isinstance(content_val, str):
            continue
        role = "assistant" if role_val == "keevs" else "user"
        messages.append({"role": role, "content": content_val[:5000]})

    # Current message
    messages.append({"role": "user", "content": message})
    return messages


async def _generate_chat_via_claude(
    message: str,
    conversation_history: list[dict],
    context: dict,
) -> str:
    """Call Claude API for chat response."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_chat_messages(message, conversation_history, context)

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_KEEVS_SYSTEM_PROMPT,
            messages=messages,
        )

        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude chat API failed: %s — falling back to mock", exc)
        return _mock_chat_response(message, context)


async def generate_chat_response_stream(
    message: str,
    conversation_history: list[dict],
    context: dict,
):
    """Yield text chunks as they arrive from Claude. Mock mode yields full text at once."""
    if settings.AI_MOCK_MODE:
        yield _mock_chat_response(message, context)
        return

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_chat_messages(message, conversation_history, context)

        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_KEEVS_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as exc:
        logger.error("Claude stream API failed: %s — falling back to mock", exc)
        yield _mock_chat_response(message, context)
