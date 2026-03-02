"""Keevs AI Job Coach — conversational career guidance from user context.

Assembles the user's full data (network, preferences, applications, searches,
credits, market trends) into a context snapshot, then generates personalized
briefings and chat responses via Claude (or deterministic mocks).
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.coaching import CoachingSession
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
- When contact search results are provided, name specific contacts with their title and company. These are the user's own contacts — no privacy concern.
- When no search results are available, talk about counts at companies ("you have 3 contacts at Stripe").
- Do NOT invent data. If something is missing, acknowledge it and suggest filling it in.
- Include markdown links to relevant pages: [contacts](/contacts), [find referrals](/referrals), [applications](/applications), [preferences](/settings?tab=profile), [credits](/credits).
- Never use "I hope this finds you well" or similar filler.
- Never mention that you're an AI unless directly asked.
- NEVER highlight empty states negatively for new users. Zero applications, zero contacts, zero searches are EXPECTED for someone who just joined. Don't say "you have 0 applications" — instead focus on what they CAN do. Frame everything as opportunity, not deficit.
- If the user already has contacts uploaded (network.total_contacts > 0), do NOT suggest uploading contacts again. They've already done it.
- The user is looking for a NEW job EXTERNALLY. Never recommend reaching out to contacts at the user's CURRENT company (user.company) for referrals — that makes no sense. Focus on contacts at OTHER companies.
- Keep output scannable: 1-2 sentences per paragraph, separated by blank lines.
- If giving steps, use a short numbered list (max 4 items) with one sentence per item.

CONTEXT: You receive the user's data as a JSON snapshot. Use it to give personalized advice."""


# ---------------------------------------------------------------------------
# Contact search detection
# ---------------------------------------------------------------------------

_CONTACT_SEARCH_PATTERNS = [
    re.compile(r"\bwho\b.*\b(?:know|have|got)\b.*\bat\b", re.IGNORECASE),
    re.compile(r"\bcontacts?\b.*\bat\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\b(?:contacts?|people|connections?)\b", re.IGNORECASE),
    re.compile(r"\bany(?:one|body)?\b.*\bat\b", re.IGNORECASE),
    re.compile(r"\bfind\b.*\b(?:contacts?|people)\b", re.IGNORECASE),
    re.compile(r"\bsearch\b.*\b(?:contacts?|network)\b", re.IGNORECASE),
    re.compile(r"\bnetwork\b.*\bat\b", re.IGNORECASE),
    re.compile(r"\b\w+\s+contacts?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:senior|staff|lead|principal|director|vp|manager)\b.*"
        r"\b(?:engineers?|designers?|product)\b",
        re.IGNORECASE,
    ),
]


def is_contact_search_query(message: str) -> bool:
    """Detect if a chat message is asking about specific contacts."""
    return any(p.search(message) for p in _CONTACT_SEARCH_PATTERNS)


def _format_contact_results_markdown(search_result: dict, limit: int = 10) -> str:
    """Format contact search results as a markdown response for mock mode."""
    results = search_result["results"][:limit]
    total_matched = search_result["total_matched"]
    raw_query = search_result["interpretation"].get("raw_query", "")

    if not results:
        return (
            f'No contacts found matching "{raw_query}". '
            "Try [searching your contacts](/contacts) with different keywords."
        )

    lines = [f'Here are your contacts matching "{raw_query}":\n']
    for r in results:
        name = r["full_name"] or "Unknown"
        title = r["current_title"] or "Unknown role"
        company = r["current_company"] or "Unknown company"
        warm = r["warm_score"]
        warm_str = f" (warm score: {int(warm)})" if warm is not None else ""
        lines.append(f"- **{name}** — {title} at {company}{warm_str}")

    if total_matched > limit:
        lines.append(
            f"\nShowing {limit} of {total_matched} matches. "
            "[Search your contacts](/contacts) for the full list."
        )

    lines.append("\nWant me to help you draft a referral message to any of them?")
    return "\n".join(lines)


def _chunk_response_text(text: str) -> str:
    """Split dense prose into short, chat-friendly chunks."""
    if not text:
        return text

    sentence_re = re.compile(r"[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$")
    out_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^(?:[-*]\s|\d+\.\s)", line):
            out_lines.append(line)
            continue

        sentences = [s.strip() for s in sentence_re.findall(line) if s.strip()]
        if len(sentences) <= 2:
            out_lines.append(line)
            continue

        for i in range(0, len(sentences), 2):
            out_lines.append(" ".join(sentences[i : i + 2]).strip())

    return "\n".join(out_lines).strip()


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

    if prefs and total_contacts > 0:
        prompts.append("What's the market like for my role?")

    if total_apps > 0:
        prompts.append("How's my pipeline looking?")

    # Suggest contact search if user has contacts
    if total_contacts > 0:
        top = (network or {}).get("top_companies", [])
        if top:
            top_company = top[0]["company"]
            prompts.insert(1, f"Who do I know at {top_company}?")

    focus_prompt = "What should I focus on today?"
    if not prompts:
        prompts.append(focus_prompt)

    # Always include a general option (but avoid duplicates)
    if len(prompts) < 2 and focus_prompt not in prompts:
        prompts.append(focus_prompt)

    return prompts[:4]


# ---------------------------------------------------------------------------
# Session management (P4 foundation)
# ---------------------------------------------------------------------------

# Coaching stages (P1)
STAGE_ONBOARDING = "onboarding"
STAGE_ACTIVE_SEARCH = "active_search"
STAGE_NETWORK_BUILDING = "network_building"
STAGE_STALLED = "stalled"

# Session gap threshold: if >6 hours since last message, start new session
_SESSION_GAP_HOURS = 6


def _determine_coaching_stage(context: dict) -> str:
    """Determine user's coaching stage from their activity (P1)."""
    network = context.get("network")
    pipeline = context.get("pipeline", {})
    prefs = context.get("preferences")
    total_contacts = (network or {}).get("total_contacts", 0)
    total_apps = pipeline.get("total", 0)
    recent_searches = context.get("recent_searches") or []

    # No contacts uploaded → onboarding
    if total_contacts == 0:
        return STAGE_ONBOARDING

    # Has contacts but no preferences or apps → network building (or stalled if no activity)
    if not prefs or not prefs.get("target_role"):
        if total_apps == 0 and len(recent_searches) == 0:
            return STAGE_STALLED
        return STAGE_NETWORK_BUILDING

    # Has contacts + prefs but no apps and no recent searches → stalled
    if total_apps == 0 and len(recent_searches) == 0:
        return STAGE_STALLED

    # Actively searching/applying
    return STAGE_ACTIVE_SEARCH


async def _get_or_create_session(
    user_id: uuid.UUID, db: AsyncSession, context: dict
) -> CoachingSession:
    """Get current session or create a new one.

    A new session starts if:
    - No previous session exists
    - Last session's last_message_at is >6 hours ago
    """
    # Get most recent session
    result = await db.execute(
        select(CoachingSession)
        .where(CoachingSession.user_id == user_id)
        .order_by(CoachingSession.started_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    stage = _determine_coaching_stage(context)

    if latest is not None:
        # Check if session is still active (within gap threshold)
        last_activity = latest.last_message_at or latest.started_at
        if (now - last_activity) < timedelta(hours=_SESSION_GAP_HOURS):
            # Update stage if changed
            if latest.coaching_stage != stage:
                latest.coaching_stage = stage
            return latest

    # Count previous sessions to determine session_number
    count_result = await db.execute(
        select(func.count())
        .select_from(CoachingSession)
        .where(CoachingSession.user_id == user_id)
    )
    prev_count = count_result.scalar() or 0

    # Create new session
    session = CoachingSession(
        user_id=user_id,
        session_number=prev_count + 1,
        coaching_stage=stage,
        topics_covered={},
        message_count=0,
        started_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def _record_topic(
    coaching_session: CoachingSession, topic: str, db: AsyncSession
) -> None:
    """Record that a topic was discussed in the current session (P4)."""
    topics = dict(coaching_session.topics_covered or {})
    now_iso = datetime.now(timezone.utc).isoformat()
    if topic not in topics:
        topics[topic] = {"first_discussed": now_iso, "count": 1}
    else:
        topics[topic]["count"] = topics[topic].get("count", 0) + 1
    coaching_session.topics_covered = topics
    # Trigger SQLAlchemy dirty flag for JSONB
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(coaching_session, "topics_covered")


async def _get_recent_topics(user_id: uuid.UUID, db: AsyncSession) -> set[str]:
    """Get topics covered in the last 3 sessions (for anti-repetition)."""
    result = await db.execute(
        select(CoachingSession.topics_covered)
        .where(CoachingSession.user_id == user_id)
        .order_by(CoachingSession.started_at.desc())
        .limit(3)
    )
    rows = result.scalars().all()
    topics: set[str] = set()
    for tc in rows:
        if tc:
            topics.update(tc.keys())
    return topics


# ---------------------------------------------------------------------------
# Mock functions
# ---------------------------------------------------------------------------


def _mock_briefing(
    context: dict, session_number: int = 1, stage: str = STAGE_ONBOARDING
) -> str:
    """Generate a stage-aware, session-count-branched briefing (P1+P2+P3)."""
    user = context.get("user", {})
    name = user.get("name") or "there"
    first_name = name.split()[0] if name != "there" else "there"

    pipeline = context.get("pipeline", {})
    total_apps = pipeline.get("total", 0)
    follow_ups = pipeline.get("follow_ups_needed", 0)
    network = context.get("network")
    total_contacts = (network or {}).get("total_contacts", 0)
    prefs = context.get("preferences")
    recent_searches = context.get("recent_searches") or []

    parts: list[str] = []

    # --- Greeting varies by session count (P2: quick win) ---
    if session_number == 1:
        parts.append(
            f"Welcome to WarmPath, {first_name}! I'm Keevs, your career coach."
        )
    elif session_number <= 2:
        parts.append(
            f"Good to see you again, {first_name}. Let's pick up where we left off."
        )
    elif session_number <= 5:
        if stage == STAGE_STALLED:
            parts.append(
                f"Hey {first_name}, session #{session_number} — let's get things moving."
            )
        else:
            parts.append(
                f"Hey {first_name}, session #{session_number} — you're building momentum."
            )
    else:
        parts.append(f"Hey {first_name}, welcome back (session #{session_number}).")

    # --- Stage-aware content (P1) ---
    if stage == STAGE_ONBOARDING and session_number <= 2:
        # Orientation: explain the platform
        parts.append(
            "Here's how WarmPath works: upload your LinkedIn contacts, "
            "set your job preferences, and I'll find warm referral paths "
            "to your target companies."
        )
        parts.append("[Upload your LinkedIn CSV](/contacts) to get started.")
    elif stage == STAGE_ONBOARDING:
        # Returning user who still hasn't uploaded — nudge without re-explaining
        parts.append(
            "You still haven't uploaded contacts — that's the key to unlocking "
            "referral paths. [Upload your CSV](/contacts) when you're ready."
        )

    # --- Action-based dynamic sections (P3) ---

    # Pipeline: only show if user has apps (skip if onboarding)
    if total_apps > 0:
        status_counts = pipeline.get("status_counts", {})
        active = sum(
            v for k, v in status_counts.items() if k not in ("rejected", "withdrawn")
        )
        rejected = status_counts.get("rejected", 0)
        if active == 0 and rejected > 0:
            parts.append(
                f"Your pipeline has {rejected} closed application{'s' if rejected != 1 else ''}. "
                "Every 'no' gets you closer — [find new referral paths](/referrals)."
            )
        else:
            parts.append(
                f"You have {active} active application{'s' if active != 1 else ''} in your pipeline."
            )

    # Follow-ups: always show if due
    if follow_ups > 0:
        urgency = "**Urgent:** " if follow_ups >= 3 else ""
        parts.append(
            f"{urgency}**{follow_ups} follow-up{'s' if follow_ups != 1 else ''}** "
            f"{'are' if follow_ups != 1 else 'is'} due — check your [applications](/applications)."
        )

    # Network: only show upload prompt if they haven't uploaded (P3)
    if network and total_contacts > 0:
        top = network.get("top_companies", [])
        if session_number <= 5:
            # Early sessions: show network summary
            if top:
                top_name = top[0]["company"]
                top_count = top[0]["count"]
                parts.append(
                    f"Your network has {total_contacts} contacts — strongest at {top_name} ({top_count})."
                )
            else:
                parts.append(f"Your network has {total_contacts} contacts.")
        else:
            # Later sessions: skip basic network recap, focus on changes
            if top and len(recent_searches) > 0:
                parts.append(
                    f"You've searched {len(recent_searches)} companies recently. "
                    "[Find more referral paths](/referrals)."
                )
            elif top and stage == STAGE_STALLED:
                top_name = top[0]["company"]
                parts.append(
                    f"Your network still has strong paths — especially at {top_name}. "
                    "[Search for referral paths](/referrals)."
                )

    # Preferences: only prompt if missing AND early session (P3)
    if not prefs and session_number <= 3:
        parts.append(
            "Set your [job preferences](/settings?tab=profile) so I can give you targeted advice."
        )
    elif not prefs and session_number > 3:
        parts.append(
            "Reminder: [set your preferences](/settings?tab=profile) to unlock personalized matching."
        )

    # Stalled users: escalating nudge (P1)
    if stage == STAGE_STALLED and session_number > 3:
        if session_number <= 5:
            parts.append(
                "Looks like your search has slowed down. Want to [explore new companies](/referrals) "
                "or review your [network for untapped connections](/contacts)?"
            )
        elif session_number <= 8:
            parts.append(
                "Try [browsing the marketplace](/referrals) for companies you haven't considered — "
                "sometimes the best referral paths are ones you didn't expect."
            )
        else:
            parts.append(
                "Even one warm intro this week can change your trajectory. "
                "[Find a new referral path](/referrals) — your network has more reach than you think."
            )

    # Market data (unchanged — only show if available)
    market = context.get("market")
    if market and market.get("summary"):
        parts.append(market["summary"])

    return " ".join(parts)


def _detect_topic(message: str) -> str | None:
    """Detect which topic a message is about (for topic tracking)."""
    # Check contact search first (more specific than generic "network")
    if is_contact_search_query(message):
        return "contact_search"
    msg_lower = message.lower()
    topic_keywords = {
        "follow_ups": ("follow-up", "follow up", "followup"),
        "network": ("network", "contact", "connection"),
        "targeting": ("company", "target", "should i"),
        "credits": ("credit", "balance"),
        "getting_started": ("start", "begin", "how do i", "getting started"),
        "pipeline": ("pipeline", "application"),
    }
    for topic, keywords in topic_keywords.items():
        if any(kw in msg_lower for kw in keywords):
            return topic
    return None


def _mock_chat_response(
    message: str,
    context: dict,
    recent_topics: set[str] | None = None,
    contact_results: dict | None = None,
) -> tuple[str, str | None]:
    """Generate keyword-based mock chat responses with anti-repetition (P4).

    Returns (response_text, topic_name_or_none).
    """
    network = context.get("network")
    pipeline = context.get("pipeline", {})
    prefs = context.get("preferences")
    topic = _detect_topic(message)
    seen = recent_topics or set()

    # Contact search results — return formatted markdown
    if (
        topic == "contact_search"
        and contact_results is not None
        and contact_results["total_matched"] > 0
    ):
        return _format_contact_results_markdown(contact_results), topic
    # If contact_search topic but no results, fall through to network handler
    if topic == "contact_search":
        topic = "network"

    if topic == "follow_ups":
        follow_ups = pipeline.get("follow_ups_needed", 0)
        if follow_ups > 0:
            if "follow_ups" in seen:
                # Vary response when topic was recently discussed
                return (
                    f"Still {follow_ups} follow-up{'s' if follow_ups != 1 else ''} pending. "
                    "Remember: the best follow-ups reference something specific — "
                    "a recent company announcement, a shared connection, or a project you admire. "
                    "Check your [applications](/applications).",
                    topic,
                )
            return (
                f"You have {follow_ups} follow-up{'s' if follow_ups != 1 else ''} due. "
                "Head to your [applications](/applications) to see which ones need attention. "
                "A good follow-up is short: restate your interest, add one new insight about "
                "the company, and ask about timeline.",
                topic,
            )
        return (
            "No follow-ups due right now. Keep your pipeline moving by "
            "[finding new referral paths](/referrals).",
            topic,
        )

    if topic == "network":
        if network:
            total = network.get("total_contacts", 0)
            top = network.get("top_companies", [])
            top_parts: list[str] = []
            for c in top[:3]:
                if isinstance(c, dict):
                    top_parts.append(f"{c.get('company', '?')} ({c.get('count', '?')})")
                else:
                    top_parts.append(str(c))
            top_str = ", ".join(top_parts)
            if "network" in seen:
                return (
                    f"Your network ({total} contacts) hasn't changed since we last discussed it. "
                    "To strengthen your position, try [searching for referrals](/referrals) "
                    "at companies where you have 3+ contacts — those are your highest-probability paths.",
                    topic,
                )
            return (
                f"Your network has {total} contacts. Strongest at: {top_str}. "
                "To find referral paths at specific companies, head to "
                "[find referrals](/referrals).",
                topic,
            )
        return (
            "You haven't uploaded contacts yet. [Upload your LinkedIn CSV](/contacts) "
            "and I can help you identify the best referral paths.",
            topic,
        )

    if topic == "targeting":
        if prefs and prefs.get("target_role"):
            role = prefs["target_role"]
            if "targeting" in seen:
                return (
                    f"You're targeting {role} roles. Since we've covered targeting before, "
                    "here's a deeper tip: look beyond obvious companies. Mid-size firms "
                    "(500-2000 employees) often have less competition and faster hiring. "
                    "[Search your network](/referrals) for hidden gems.",
                    topic,
                )
            return (
                f"Based on your target role ({role}), I'd focus on companies where you "
                "already have contacts. Check your [network](/contacts) for companies with "
                "3+ connections — those give you the best referral odds. Then "
                "[search for referrals](/referrals) at those companies.",
                topic,
            )
        return (
            "I don't have your target role yet. "
            "[Set your preferences](/settings?tab=profile) and I can give you specific guidance.",
            topic,
        )

    if topic == "credits":
        balance = context.get("credits", 0)
        if "credits" in seen:
            return (
                f"Your balance is still {balance} credits. Quick reminder: "
                "uploading contacts earns 100, facilitating intros earns 50. "
                "Credits expire after 12 months. [View history](/credits).",
                topic,
            )
        return (
            f"You have {balance} credits. Credits are used for cross-network searches (5) "
            "and intro requests (20). Earn more by uploading contacts (100) or "
            "facilitating intros (50). Check your [credit history](/credits).",
            topic,
        )

    if topic == "getting_started":
        if "getting_started" in seen:
            return (
                "We've covered the basics before. Where are you stuck? "
                "If you've already uploaded contacts, try [searching for referrals](/referrals). "
                "If you need help with a specific company or role, just ask.",
                topic,
            )
        return (
            "Here's your game plan:\n\n"
            "1. [Upload your LinkedIn CSV](/contacts) — this maps your network.\n"
            "2. [Set your job preferences](/settings?tab=profile) — target role, seniority, locations.\n"
            "3. [Search for referrals](/referrals) — I'll find warm paths to your target companies.\n\n"
            "The key insight: referrals convert at 10-40% vs 1-3% for cold applications. "
            "Your existing network is more valuable than you think.",
            topic,
        )

    if topic == "pipeline":
        total = pipeline.get("total", 0)
        if total > 0:
            status_counts = pipeline.get("status_counts", {})
            parts = [f"{v} {k}" for k, v in status_counts.items()]
            if "pipeline" in seen:
                return (
                    f"Pipeline update: {total} applications ({', '.join(parts)}). "
                    "Focus on moving your strongest prospects forward — quality over quantity. "
                    "[View details](/applications).",
                    topic,
                )
            return (
                f"Your pipeline has {total} applications: {', '.join(parts)}. "
                "View details in your [applications](/applications). "
                "Keep targeting 5-10 companies deeply rather than spreading thin.",
                topic,
            )
        return (
            "No applications tracked yet. Once you find referral paths, "
            "start tracking applications in your [pipeline](/applications).",
            topic,
        )

    # Fallback
    return (
        "I can help with your job search strategy, network analysis, "
        "follow-up timing, and referral approach. Try asking about your "
        "network, pipeline, or what to focus on next.",
        None,
    )


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------


async def generate_briefing(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Generate (or return cached) daily briefing with session tracking."""
    cache_key = f"keevs_briefing:{user_id}"

    # Check cache
    cached = await _read_cache(cache_key, db)
    if cached is not None:
        return cached

    # Assemble context
    context = await _assemble_context(user_id, db)

    # Get or create coaching session
    coaching_session = await _get_or_create_session(user_id, db, context)
    session_number = coaching_session.session_number
    stage = coaching_session.coaching_stage

    # Generate briefing
    if settings.AI_MOCK_MODE:
        briefing_text = _mock_briefing(context, session_number, stage)
    else:
        briefing_text = await _generate_briefing_via_claude(
            context, session_number, stage
        )
    briefing_text = _chunk_response_text(briefing_text)

    suggested = get_suggested_prompts(context)

    result = {
        "briefing": briefing_text,
        "context_snapshot": context,
        "suggested_prompts": suggested,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_number": session_number,
        "coaching_stage": stage,
    }

    # Cache and flush so it persists on the connection
    await _write_cache(cache_key, result, settings.KEEVS_BRIEFING_CACHE_TTL_HOURS, db)
    await db.flush()

    return result


async def _generate_briefing_via_claude(
    context: dict, session_number: int = 1, stage: str = STAGE_ONBOARDING
) -> str:
    """Call Claude API for briefing generation."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        user_prompt = (
            f"Generate my daily career briefing. This is session #{session_number}, "
            f"coaching stage: {stage}. "
            f"{'First visit — welcome them warmly and orient them. Do NOT mention zero applications, zero searches, or any empty counts — they just joined, of course everything is zero. Focus on what they can do, not what is missing.' if session_number == 1 else ''}"
            f"{'Session ' + str(session_number) + ' — they know the basics. Focus on progress, suggest one concrete next step.' if 2 <= session_number <= 5 else ('Returning user — skip basics, focus on new insights and progress.' if session_number > 5 else '')}\n\n"
            f"Data:\n{json.dumps(context, default=str, indent=2)}"
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
        return _mock_briefing(context, session_number, stage)


# ---------------------------------------------------------------------------
# Chat generation
# ---------------------------------------------------------------------------


async def generate_chat_response(
    user_id: uuid.UUID,
    message: str,
    conversation_history: list[dict] | None,
    context_snapshot: dict | None,
    db: AsyncSession,
    contact_results: dict | None = None,
) -> dict:
    """Generate a chat response from Keevs with topic tracking (P4)."""
    # If no context provided, assemble fresh
    if not context_snapshot:
        context_snapshot = await _assemble_context(user_id, db)

    # Get coaching session + recent topics for anti-repetition
    coaching_session = await _get_or_create_session(user_id, db, context_snapshot)
    recent_topics = await _get_recent_topics(user_id, db)

    if settings.AI_MOCK_MODE:
        response_text, topic = _mock_chat_response(
            message, context_snapshot, recent_topics, contact_results
        )
    else:
        response_text = await _generate_chat_via_claude(
            message, conversation_history or [], context_snapshot, contact_results
        )
        topic = _detect_topic(message)
    response_text = _chunk_response_text(response_text)

    # Track topic in session (P4)
    if topic:
        await _record_topic(coaching_session, topic, db)

    # Update session activity
    coaching_session.message_count += 1
    coaching_session.last_message_at = datetime.now(timezone.utc)

    # Log usage
    db.add(
        UsageLog(
            user_id=user_id,
            action="coach_chat",
            resource_type="coach",
            metadata_={"message_length": len(message), "topic": topic},
        )
    )

    return {"response": response_text}


def _build_chat_messages(
    message: str,
    conversation_history: list[dict],
    context: dict,
    contact_results: dict | None = None,
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

    # Inject contact search results if available
    if contact_results and contact_results.get("total_matched", 0) > 0:
        results_json = json.dumps(contact_results["results"], default=str)
        search_msg = (
            "CONTACT SEARCH RESULTS for the user's query. "
            "These are the user's own contacts (no privacy issue). "
            "Reference them by name.\n\n"
            f"Matched {contact_results['total_matched']} contacts "
            f"(showing top {len(contact_results['results'])}):\n{results_json}"
        )
        messages.append({"role": "user", "content": search_msg})
        messages.append(
            {
                "role": "assistant",
                "content": "Got it. I'll reference these contacts by name in my response.",
            }
        )

    # Last 10 messages of history (validated entries only)
    for entry in (conversation_history or [])[-10:]:
        if not isinstance(entry, dict):
            continue
        role_val = entry.get("role")
        content_val = entry.get("content")
        if role_val not in ("user", "keevs", "treb") or not isinstance(
            content_val, str
        ):
            continue
        role = "assistant" if role_val in ("keevs", "treb") else "user"
        messages.append({"role": role, "content": content_val[:5000]})

    # Current message
    messages.append({"role": "user", "content": message})
    return messages


async def _generate_chat_via_claude(
    message: str,
    conversation_history: list[dict],
    context: dict,
    contact_results: dict | None = None,
) -> str:
    """Call Claude API for chat response."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_chat_messages(
            message, conversation_history, context, contact_results
        )

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_KEEVS_SYSTEM_PROMPT,
            messages=messages,
        )

        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude chat API failed: %s — falling back to mock", exc)
        text, _ = _mock_chat_response(message, context, contact_results=contact_results)
        return text


async def generate_chat_response_stream(
    message: str,
    conversation_history: list[dict],
    context: dict,
    contact_results: dict | None = None,
):
    """Yield text chunks as they arrive from Claude. Mock mode yields full text at once."""
    if settings.AI_MOCK_MODE:
        text, _ = _mock_chat_response(message, context, contact_results=contact_results)
        yield _chunk_response_text(text)
        return

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_chat_messages(
            message, conversation_history, context, contact_results
        )

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
        text, _ = _mock_chat_response(message, context, contact_results=contact_results)
        yield _chunk_response_text(text)
