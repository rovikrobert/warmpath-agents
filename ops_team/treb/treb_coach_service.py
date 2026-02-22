"""Treb AI Network Partner — conversational coaching for network holders.

Parallel to Keevs (job seekers), Treb coaches network holders on sharing
their network, managing intro requests, and capturing referral bonuses.
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

from app.config import settings
from app.models.coaching import CoachingSession
from app.models.contact import Contact
from app.models.enrichment import UsageLog
from app.models.marketplace import (
    IntroFacilitation,
    MarketplaceListing,
    NetworkSharingPreferences,
)
from app.models.user import ConnectorProfile, User
from app.services.credits import get_balance
from app.services.dashboard_insights import _read_cache, _write_cache

logger = logging.getLogger(__name__)

CLAUDE_MODEL = settings.CLAUDE_MODEL

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_TREB_SYSTEM_PROMPT = """You are Treb, an AI network partner inside WarmPath — a platform where network holders share their professional connections to help job seekers get referred, while capturing referral bonuses their employers already offer.

PERSONALITY: Encouraging, strategic, celebrates generosity and referral bonus capture. You're a trusted advisor who understands the value of professional networks, not a pushy salesperson. Short paragraphs. No filler. Every sentence earns its place.

RULES:
- Always reference specific data when available. Never generic when specific is possible.
- For briefings: 3-5 sentences. Greeting, key insight, concrete next step. Include markdown links like [marketplace](/marketplace) or [contacts](/contacts).
- For chat: 1-3 paragraphs. Always end with something actionable.
- Do NOT invent data. If something is missing, acknowledge it and suggest filling it in.
- Include markdown links to relevant pages: [contacts](/contacts), [marketplace](/marketplace), [settings](/settings?tab=sharing), [credits](/credits).
- Never use guilt-tripping language. Sharing is a choice, not an obligation.
- Never mention that you're an AI unless directly asked.
- Celebrate milestones: first listing, first intro approved, reputation score increases.
- NEVER highlight empty states negatively for new users. Zero listings, zero intros are EXPECTED for someone who just joined. Focus on what they CAN do, not what is missing.

CONTEXT: You receive the user's data as a JSON snapshot. Use it to give personalized advice."""


# ---------------------------------------------------------------------------
# NH topic detection
# ---------------------------------------------------------------------------

_NH_TOPIC_PATTERNS = [
    re.compile(
        r"\b(?:shar|sharing|share)\b.*\b(?:network|contacts?|connections?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:intro|introduction)\s*(?:request|approval|pending|approve)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\breferral\s*bonus(?:es)?\b", re.IGNORECASE),
    re.compile(r"\bmarketplace\s*listing", re.IGNORECASE),
    re.compile(r"\bconnector\s*(?:reputation|score)\b", re.IGNORECASE),
    re.compile(r"\bprivacy\s*(?:control|setting)", re.IGNORECASE),
    re.compile(r"\bopt[\s-]*in\b", re.IGNORECASE),
    re.compile(r"\bnetwork\s*sharing\b", re.IGNORECASE),
    re.compile(r"\bwho\s*requested\b", re.IGNORECASE),
    re.compile(r"\bwhich\s*contacts?\s*(?:are\s*)?shared\b", re.IGNORECASE),
]


def is_nh_topic(message: str) -> bool:
    """Return True if the message is about network-holder topics."""
    return any(p.search(message) for p in _NH_TOPIC_PATTERNS)


# ---------------------------------------------------------------------------
# NH coaching stages
# ---------------------------------------------------------------------------

NH_STAGE_ONBOARDING = "nh_onboarding"
NH_STAGE_PASSIVE = "passive"
NH_STAGE_ACTIVE_SHARING = "active_sharing"
NH_STAGE_DORMANT = "nh_dormant"

_SESSION_GAP_HOURS = 6


def _determine_nh_stage(context: dict) -> str:
    """Determine network holder's coaching stage from their activity."""
    total_contacts = context.get("total_contacts", 0)
    listing_count = context.get("listings", {}).get("total", 0)
    opt_in = context.get("sharing_prefs", {}).get("opt_in_marketplace", False)
    last_activity_str = context.get("last_activity")

    if total_contacts == 0:
        return NH_STAGE_ONBOARDING

    if not opt_in or listing_count == 0:
        return NH_STAGE_PASSIVE

    # Check for dormancy (14+ days since last activity)
    if last_activity_str:
        try:
            last_dt = datetime.fromisoformat(last_activity_str)
            if (datetime.now(timezone.utc) - last_dt).days >= 14:
                return NH_STAGE_DORMANT
        except (ValueError, TypeError):
            pass

    return NH_STAGE_ACTIVE_SHARING


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

_CONTEXT_CACHE: dict[str, tuple[float, dict]] = {}
_CONTEXT_CACHE_TTL = 300  # 5 minutes


async def _assemble_nh_context(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Build an NH-specific context snapshot. Cached 5 minutes."""
    cache_key = f"treb:{user_id}"
    now_ts = datetime.now(timezone.utc).timestamp()

    if cache_key in _CONTEXT_CACHE:
        cached_ts, cached_ctx = _CONTEXT_CACHE[cache_key]
        if now_ts - cached_ts < _CONTEXT_CACHE_TTL:
            return cached_ctx

    async def _fetch_user():
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def _fetch_contact_count():
        result = await db.execute(
            select(func.count(Contact.id)).where(
                Contact.user_id == user_id,
                Contact.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0

    async def _fetch_enrichment_count():
        result = await db.execute(
            select(func.count(Contact.id)).where(
                Contact.user_id == user_id,
                Contact.deleted_at.is_(None),
                Contact.relationship_type.isnot(None),
            )
        )
        return result.scalar() or 0

    async def _fetch_listings():
        total_result = await db.execute(
            select(func.count(MarketplaceListing.id)).where(
                MarketplaceListing.network_holder_id == user_id,
                MarketplaceListing.deleted_at.is_(None),
            )
        )
        available_result = await db.execute(
            select(func.count(MarketplaceListing.id)).where(
                MarketplaceListing.network_holder_id == user_id,
                MarketplaceListing.deleted_at.is_(None),
                MarketplaceListing.is_available.is_(True),
            )
        )
        return {
            "total": total_result.scalar() or 0,
            "available": available_result.scalar() or 0,
        }

    async def _fetch_intros():
        result = await db.execute(
            select(IntroFacilitation.status, func.count(IntroFacilitation.id))
            .where(IntroFacilitation.network_holder_id == user_id)
            .group_by(IntroFacilitation.status)
        )
        return {row[0]: row[1] for row in result.all()}

    async def _fetch_sharing_prefs():
        result = await db.execute(
            select(NetworkSharingPreferences).where(
                NetworkSharingPreferences.user_id == user_id
            )
        )
        prefs = result.scalar_one_or_none()
        if not prefs:
            return {"opt_in_marketplace": False}
        return {
            "opt_in_marketplace": prefs.opt_in_marketplace,
            "category_filters": prefs.category_filters,
            "paused": prefs.paused_at is not None,
        }

    async def _fetch_connector_profile():
        result = await db.execute(
            select(ConnectorProfile).where(ConnectorProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None
        return {
            "intros_facilitated": profile.intros_facilitated,
            "response_rate": profile.response_rate,
            "avg_rating": profile.avg_rating,
        }

    async def _fetch_credits():
        return await get_balance(user_id, db)

    async def _fetch_last_activity():
        result = await db.execute(
            select(UsageLog.created_at)
            .where(UsageLog.user_id == user_id)
            .order_by(UsageLog.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row.isoformat() if row else None

    (
        user,
        total_contacts,
        enriched_contacts,
        listings,
        intro_counts,
        sharing_prefs,
        connector_profile,
        credit_balance,
        last_activity,
    ) = await asyncio.gather(
        _fetch_user(),
        _fetch_contact_count(),
        _fetch_enrichment_count(),
        _fetch_listings(),
        _fetch_intros(),
        _fetch_sharing_prefs(),
        _fetch_connector_profile(),
        _fetch_credits(),
        _fetch_last_activity(),
    )

    user_ctx: dict = {"name": None}
    if user:
        user_ctx["name"] = user.full_name

    enrichment_pct = (
        round(enriched_contacts / total_contacts * 100) if total_contacts > 0 else 0
    )

    context = {
        "user": user_ctx,
        "total_contacts": total_contacts,
        "enrichment_pct": enrichment_pct,
        "listings": listings,
        "intros": intro_counts,
        "sharing_prefs": sharing_prefs,
        "connector_profile": connector_profile,
        "credits": credit_balance,
        "last_activity": last_activity,
    }

    _CONTEXT_CACHE[cache_key] = (now_ts, context)
    return context


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


async def _get_or_create_nh_session(
    user_id: uuid.UUID, db: AsyncSession, context: dict
) -> CoachingSession:
    """Get current Treb session or create a new one."""
    result = await db.execute(
        select(CoachingSession)
        .where(
            CoachingSession.user_id == user_id,
            CoachingSession.persona == "treb",
        )
        .order_by(CoachingSession.started_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    stage = _determine_nh_stage(context)

    if latest is not None:
        last_activity = latest.last_message_at or latest.started_at
        if (now - last_activity) < timedelta(hours=_SESSION_GAP_HOURS):
            if latest.coaching_stage != stage:
                latest.coaching_stage = stage
            return latest

    count_result = await db.execute(
        select(func.count())
        .select_from(CoachingSession)
        .where(
            CoachingSession.user_id == user_id,
            CoachingSession.persona == "treb",
        )
    )
    prev_count = count_result.scalar() or 0

    session = CoachingSession(
        user_id=user_id,
        persona="treb",
        session_number=prev_count + 1,
        coaching_stage=stage,
        topics_covered={},
        message_count=0,
        started_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def _record_nh_topic(
    coaching_session: CoachingSession, topic: str, db: AsyncSession
) -> None:
    """Record that a topic was discussed in the current Treb session."""
    topics = dict(coaching_session.topics_covered or {})
    now_iso = datetime.now(timezone.utc).isoformat()
    if topic not in topics:
        topics[topic] = {"first_discussed": now_iso, "count": 1}
    else:
        topics[topic]["count"] = topics[topic].get("count", 0) + 1
    coaching_session.topics_covered = topics
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(coaching_session, "topics_covered")


async def _get_recent_nh_topics(user_id: uuid.UUID, db: AsyncSession) -> set[str]:
    """Get topics covered in the last 3 Treb sessions."""
    result = await db.execute(
        select(CoachingSession.topics_covered)
        .where(
            CoachingSession.user_id == user_id,
            CoachingSession.persona == "treb",
        )
        .order_by(CoachingSession.started_at.desc())
        .limit(3)
    )
    topics: set[str] = set()
    for tc in result.scalars().all():
        if tc:
            topics.update(tc.keys())
    return topics


# ---------------------------------------------------------------------------
# Suggested prompts
# ---------------------------------------------------------------------------


def get_nh_suggested_prompts(context: dict) -> list[str]:
    """Return 3-4 contextual prompt suggestions for network holders."""
    prompts: list[str] = []
    listings = context.get("listings", {})
    intros = context.get("intros", {})
    connector = context.get("connector_profile")
    pending = intros.get("pending", 0)

    if listings.get("total", 0) == 0:
        prompts.append("How do I share my network?")

    if pending > 0:
        prompts.append(
            f"Show me my {pending} pending intro request{'s' if pending != 1 else ''}"
        )

    prompts.append("How much are referral bonuses worth?")

    if connector and connector.get("intros_facilitated", 0) > 0:
        prompts.append("How's my connector reputation?")

    prompts.append("How do I control what's shared?")

    return prompts[:4]


# ---------------------------------------------------------------------------
# Topic detection
# ---------------------------------------------------------------------------


def _detect_nh_topic(message: str) -> str | None:
    """Detect which NH topic a message is about."""
    msg_lower = message.lower()
    topic_keywords = {
        "sharing": ("share", "sharing", "opt in", "opt-in", "marketplace listing"),
        "intros": ("intro", "introduction", "request", "approve", "pending"),
        "reputation": ("reputation", "score", "rating", "connector"),
        "credits": ("credit", "balance", "earn"),
        "referral_bonuses": ("referral bonus", "bonus", "referral pay"),
        "privacy_controls": ("privacy", "control", "exclude", "pause", "hide"),
        "getting_started": ("start", "begin", "how do i", "getting started"),
    }
    for topic, keywords in topic_keywords.items():
        if any(kw in msg_lower for kw in keywords):
            return topic
    return None


# ---------------------------------------------------------------------------
# Mock functions
# ---------------------------------------------------------------------------


def _mock_nh_briefing(
    context: dict, session_number: int = 1, stage: str = NH_STAGE_ONBOARDING
) -> str:
    """Generate a stage-aware, session-count-branched NH briefing."""
    user = context.get("user", {})
    name = user.get("name") or "there"
    first_name = name.split()[0] if name != "there" else "there"

    listings = context.get("listings", {})
    intros = context.get("intros", {})
    total_contacts = context.get("total_contacts", 0)
    connector = context.get("connector_profile")
    pending = intros.get("pending", 0)
    completed = intros.get("completed", 0)

    parts: list[str] = []

    # --- Greeting varies by session count ---
    if session_number == 1:
        parts.append(
            f"Welcome to WarmPath, {first_name}! I'm Treb, your network partner."
        )
    elif session_number <= 2:
        parts.append(
            f"Good to see you again, {first_name}. Let's check in on your network."
        )
    elif session_number <= 5:
        parts.append(
            f"Hey {first_name}, session #{session_number} — great to have you back."
        )
    else:
        parts.append(f"Hey {first_name}, welcome back (session #{session_number}).")

    # --- Stage-aware content ---
    if stage == NH_STAGE_ONBOARDING and session_number <= 2:
        parts.append(
            "Here's how sharing works: upload your LinkedIn contacts, "
            "opt in to the marketplace, and candidates see anonymized listings only. "
            "You approve every intro personally."
        )
        parts.append("[Upload your LinkedIn CSV](/contacts) to get started.")
    elif stage == NH_STAGE_ONBOARDING:
        parts.append(
            "You still haven't uploaded contacts — that's the first step to sharing "
            "your network. [Upload your CSV](/contacts) when you're ready."
        )
    elif stage == NH_STAGE_PASSIVE:
        parts.append(
            f"You have {total_contacts} contacts uploaded but haven't opted in to "
            "the marketplace yet. [Turn on sharing](/settings?tab=sharing) to start "
            "receiving intro requests and capturing referral bonuses."
        )
    elif stage == NH_STAGE_ACTIVE_SHARING:
        available = listings.get("available", 0)
        parts.append(
            f"You have {available} active marketplace listing{'s' if available != 1 else ''}."
        )
        if pending > 0:
            parts.append(
                f"**{pending} intro request{'s' if pending != 1 else ''}** "
                f"{'are' if pending != 1 else 'is'} waiting for your review — "
                "check your [marketplace](/marketplace)."
            )
        if completed > 0:
            parts.append(
                f"You've facilitated {completed} successful intro{'s' if completed != 1 else ''} so far."
            )
    elif stage == NH_STAGE_DORMANT:
        parts.append(
            "It's been a while since you were last active. "
            "New candidates may be looking for intros at your companies. "
            "[Check your marketplace](/marketplace) for any pending requests."
        )

    # Connector reputation milestone
    if connector and connector.get("intros_facilitated", 0) > 0:
        facilitated = connector["intros_facilitated"]
        if facilitated == 1:
            parts.append("You've facilitated your first intro — nice work!")
        elif facilitated >= 5:
            parts.append(
                f"With {facilitated} intros facilitated, you're building a strong connector reputation."
            )

    return " ".join(parts)


def _mock_nh_chat_response(
    message: str,
    context: dict,
    recent_topics: set[str] | None = None,
) -> tuple[str, str | None]:
    """Generate keyword-based mock NH chat responses with anti-repetition."""
    topic = _detect_nh_topic(message)
    seen = recent_topics or set()
    listings = context.get("listings", {})
    intros = context.get("intros", {})
    connector = context.get("connector_profile")
    total_contacts = context.get("total_contacts", 0)
    sharing_prefs = context.get("sharing_prefs", {})

    if topic == "sharing":
        if total_contacts == 0:
            return (
                "First, [upload your LinkedIn CSV](/contacts) — "
                "once your contacts are imported, you can opt in to share them "
                "on the marketplace. Only anonymized info (company + role level) is shown.",
                topic,
            )
        if not sharing_prefs.get("opt_in_marketplace"):
            return (
                f"You have {total_contacts} contacts ready. "
                "[Turn on marketplace sharing](/settings?tab=sharing) to start "
                "receiving intro requests. Candidates only see anonymized listings — "
                "you review and approve every request personally.",
                topic,
            )
        if "sharing" in seen:
            return (
                f"Your sharing is active with {listings.get('available', 0)} listings live. "
                "Tip: categorize your contacts with relationship types to improve match quality. "
                "[Review contacts](/contacts).",
                topic,
            )
        return (
            f"You're sharing {listings.get('available', 0)} contacts on the marketplace. "
            "Candidates see anonymized info only. You approve every intro. "
            "[Manage sharing settings](/settings?tab=sharing).",
            topic,
        )

    if topic == "intros":
        pending = intros.get("pending", 0)
        approved = intros.get("approved", 0)
        if pending > 0:
            return (
                f"You have {pending} pending intro request{'s' if pending != 1 else ''}. "
                "Review each one in your [marketplace](/marketplace) — you can approve, "
                "decline, or ask the candidate for more info.",
                topic,
            )
        if approved > 0:
            return (
                f"You've approved {approved} intro{'s' if approved != 1 else ''} recently. "
                "Make sure to confirm when you've sent the intro — that's how you earn credits. "
                "[Check marketplace](/marketplace).",
                topic,
            )
        return (
            "No pending intro requests right now. The more contacts you share, "
            "the more likely you'll receive requests. "
            "[Review your sharing settings](/settings?tab=sharing).",
            topic,
        )

    if topic == "reputation":
        if connector and connector.get("intros_facilitated", 0) > 0:
            facilitated = connector["intros_facilitated"]
            rate = connector.get("response_rate")
            rate_str = f" with a {rate}% response rate" if rate else ""
            return (
                f"You've facilitated {facilitated} intro{'s' if facilitated != 1 else ''}{rate_str}. "
                "Top connectors get priority visibility to high-quality candidates. "
                "Keep responding quickly to requests to maintain your score.",
                topic,
            )
        return (
            "Your connector reputation starts building when you approve your first intro. "
            "Metrics tracked: response rate, intros facilitated, and candidate ratings. "
            "[Share your network](/settings?tab=sharing) to get started.",
            topic,
        )

    if topic == "credits":
        balance = context.get("credits", 0)
        if "credits" in seen:
            return (
                f"Your balance is still {balance} credits. As a network holder, "
                "you earn 50 credits per facilitated intro plus 100 for uploading contacts. "
                "[View history](/credits).",
                topic,
            )
        return (
            f"You have {balance} credits. Network holders earn credits by uploading "
            "contacts (100) and facilitating intros (50). Credits are also useful "
            "if you ever search for referrals yourself. [Credit history](/credits).",
            topic,
        )

    if topic == "referral_bonuses":
        return (
            "Most companies pay $2,000-$10,000 per successful referral hire. "
            "WarmPath routes pre-qualified candidates to you so you can capture "
            "those bonuses through your employer's existing referral program. "
            "We don't take a cut — the full bonus goes to you.",
            topic,
        )

    if topic == "privacy_controls":
        if "privacy_controls" in seen:
            return (
                "Quick recap: [sharing settings](/settings?tab=sharing) lets you pause sharing, "
                "set category filters, and exclude specific contacts. "
                "No contact identity is ever revealed without your explicit approval.",
                topic,
            )
        return (
            "You have full control over what's shared:\n\n"
            "- **Opt in/out** anytime in [settings](/settings?tab=sharing)\n"
            "- **Exclude specific contacts** from marketplace listings\n"
            "- **Pause sharing** temporarily without losing your listings\n"
            "- **Category filters** to only share contacts in specific industries\n\n"
            "Candidates never see names or emails — only company + role level.",
            topic,
        )

    if topic == "getting_started":
        if "getting_started" in seen:
            return (
                "We've covered the basics. Where are you stuck? "
                "If you've uploaded contacts, [turn on sharing](/settings?tab=sharing). "
                "If you need help with a specific request, just ask.",
                topic,
            )
        return (
            "Here's your game plan as a network holder:\n\n"
            "1. [Upload your LinkedIn CSV](/contacts) — this maps your network.\n"
            "2. [Turn on marketplace sharing](/settings?tab=sharing) — only anonymized info is shown.\n"
            "3. Review intro requests as they come in — you approve each one personally.\n\n"
            "The payoff: your employer pays referral bonuses ($2-10K per hire) that you're "
            "currently leaving on the table. WarmPath sends you pre-qualified candidates.",
            topic,
        )

    # Fallback
    return (
        "I can help with sharing your network, managing intro requests, "
        "understanding referral bonuses, and privacy controls. "
        "Try asking about your sharing status, pending requests, or how to get started.",
        None,
    )


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------


async def generate_nh_briefing(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Generate (or return cached) daily briefing for network holders."""
    cache_key = f"treb_briefing:{user_id}"

    cached = await _read_cache(cache_key, db)
    if cached is not None:
        return cached

    context = await _assemble_nh_context(user_id, db)
    coaching_session = await _get_or_create_nh_session(user_id, db, context)
    session_number = coaching_session.session_number
    stage = coaching_session.coaching_stage

    if settings.AI_MOCK_MODE:
        briefing_text = _mock_nh_briefing(context, session_number, stage)
    else:
        briefing_text = await _generate_nh_briefing_via_claude(
            context, session_number, stage
        )

    suggested = get_nh_suggested_prompts(context)

    result = {
        "briefing": briefing_text,
        "context_snapshot": context,
        "suggested_prompts": suggested,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_number": session_number,
        "coaching_stage": stage,
        "persona": "treb",
    }

    await _write_cache(cache_key, result, settings.KEEVS_BRIEFING_CACHE_TTL_HOURS, db)
    await db.flush()

    return result


async def _generate_nh_briefing_via_claude(
    context: dict, session_number: int = 1, stage: str = NH_STAGE_ONBOARDING
) -> str:
    """Call Claude API for NH briefing generation."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

        session_guidance = ""
        if session_number == 1:
            session_guidance = (
                "First visit — welcome them warmly, explain how network sharing works. "
                "Do NOT mention zero intros or any empty counts. "
                "Focus on what they can do."
            )
        elif session_number <= 5:
            session_guidance = (
                f"Session {session_number} — they know the basics. "
                "Focus on their sharing status, pending requests, and next step."
            )
        else:
            session_guidance = (
                "Returning user — skip basics, focus on activity updates."
            )

        user_prompt = (
            f"Generate my daily network partner briefing. This is session #{session_number}, "
            f"coaching stage: {stage}. {session_guidance}\n\n"
            f"Data:\n{json.dumps(context, default=str, indent=2)}"
        )

        message = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=_TREB_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude NH briefing API failed: %s — falling back to mock", exc)
        return _mock_nh_briefing(context, session_number, stage)


# ---------------------------------------------------------------------------
# Chat generation
# ---------------------------------------------------------------------------


async def generate_nh_chat_response(
    user_id: uuid.UUID,
    message: str,
    conversation_history: list[dict] | None,
    context_snapshot: dict | None,
    db: AsyncSession,
) -> dict:
    """Generate a chat response from Treb with topic tracking."""
    if not context_snapshot:
        context_snapshot = await _assemble_nh_context(user_id, db)

    coaching_session = await _get_or_create_nh_session(user_id, db, context_snapshot)
    recent_topics = await _get_recent_nh_topics(user_id, db)

    if settings.AI_MOCK_MODE:
        response_text, topic = _mock_nh_chat_response(
            message, context_snapshot, recent_topics
        )
    else:
        response_text = await _generate_nh_chat_via_claude(
            message, conversation_history or [], context_snapshot
        )
        topic = _detect_nh_topic(message)

    if topic:
        await _record_nh_topic(coaching_session, topic, db)

    coaching_session.message_count += 1
    coaching_session.last_message_at = datetime.now(timezone.utc)

    db.add(
        UsageLog(
            user_id=user_id,
            action="coach_chat",
            resource_type="coach",
            metadata_={
                "message_length": len(message),
                "topic": topic,
                "persona": "treb",
            },
        )
    )

    return {"response": response_text}


def _build_nh_chat_messages(
    message: str,
    conversation_history: list[dict],
    context: dict,
) -> list[dict]:
    """Build Claude messages array with NH context injection + history."""
    messages: list[dict] = []

    context_msg = (
        "Here is the network holder's current data snapshot. "
        "Use it to personalize your responses:\n\n"
        f"{json.dumps(context, default=str, indent=2)}\n\n"
        "Acknowledge this context silently — do not repeat it back."
    )
    messages.append({"role": "user", "content": context_msg})
    messages.append(
        {
            "role": "assistant",
            "content": "Understood. I have your network sharing context. How can I help?",
        }
    )

    for entry in (conversation_history or [])[-10:]:
        if not isinstance(entry, dict):
            continue
        role_val = entry.get("role")
        content_val = entry.get("content")
        if role_val not in ("user", "treb") or not isinstance(content_val, str):
            continue
        role = "assistant" if role_val == "treb" else "user"
        messages.append({"role": role, "content": content_val[:5000]})

    messages.append({"role": "user", "content": message})
    return messages


async def _generate_nh_chat_via_claude(
    message: str,
    conversation_history: list[dict],
    context: dict,
) -> str:
    """Call Claude API for NH chat response."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_nh_chat_messages(message, conversation_history, context)

        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_TREB_SYSTEM_PROMPT,
            messages=messages,
        )

        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude NH chat API failed: %s — falling back to mock", exc)
        text, _ = _mock_nh_chat_response(message, context)
        return text


async def generate_nh_chat_response_stream(
    message: str,
    conversation_history: list[dict],
    context: dict,
):
    """Yield text chunks as they arrive from Claude. Mock mode yields full text at once."""
    if settings.AI_MOCK_MODE:
        text, _ = _mock_nh_chat_response(message, context)
        yield text
        return

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages = _build_nh_chat_messages(message, conversation_history, context)

        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_TREB_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as exc:
        logger.error("Claude NH stream API failed: %s — falling back to mock", exc)
        text, _ = _mock_nh_chat_response(message, context)
        yield text
