"""CoS Query Router — routes consultation queries to the most relevant team(s).

Keyword-based routing with confidence scoring. The CoS can handle cross-cutting
queries itself or dispatch to specialized teams.

Also provides cross-team request tracking (Gap 6): detected requests are routed,
assigned IDs, and tracked in cos_state.json until resolved.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .cos_learning import _load_state, _save_state
from .schemas import TrackedRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topic → Team mapping
# ---------------------------------------------------------------------------

_TEAM_KEYWORDS: dict[str, list[str]] = {
    "engineering": [
        "architecture",
        "api",
        "endpoint",
        "database",
        "migration",
        "alembic",
        "model",
        "schema",
        "test",
        "pytest",
        "performance",
        "query",
        "bug",
        "refactor",
        "dependency",
        "security",
        "auth",
        "jwt",
        "middleware",
        "celery",
        "redis",
        "sqlalchemy",
        "fastapi",
        "deploy",
        "railway",
        "docker",
        "ci",
        "cd",
        "backend",
        "code",
        "type hint",
    ],
    "data": [
        "data",
        "analytics",
        "funnel",
        "metric",
        "warm score",
        "calibration",
        "pipeline",
        "sql",
        "instrumentation",
        "telemetry",
        "usage log",
        "enrichment",
        "cache",
        "ab test",
        "cohort",
        "retention",
        "churn",
    ],
    "product": [
        "ux",
        "ui",
        "frontend",
        "react",
        "design",
        "accessibility",
        "aria",
        "onboarding",
        "user journey",
        "feature",
        "persona",
        "job seeker",
        "network holder",
        "flow",
        "page",
        "component",
        "tailwind",
        "mobile",
        "responsive",
        "navigation",
        "modal",
        "form",
    ],
    "ops": [
        "coaching",
        "coach",
        "keevs",
        "marketplace health",
        "satisfaction",
        "supply side",
        "activation",
        "nh ",
        "network holder experience",
        "response rate",
        "intro facilitation",
        "operational",
    ],
    "gtm": [
        "pricing",
        "credit",
        "monetization",
        "competition",
        "competitor",
        "marketing",
        "seo",
        "landing page",
        "positioning",
        "launch",
        "partnership",
        "community",
        "geographic",
        "market entry",
        "brand",
        "messaging",
        "growth",
        "acquisition",
        "conversion",
    ],
    "finance": [
        "stripe",
        "billing",
        "subscription",
        "invoice",
        "payment",
        "webhook",
        "compliance",
        "gdpr",
        "pdpa",
        "ccpa",
        "legal",
        "regulation",
        "investor",
        "fundraising",
        "burn rate",
        "cost",
        "budget",
        "audit",
        "fintech",
        "money transmitter",
    ],
}

# Queries that the CoS handles directly (cross-cutting)
_COS_KEYWORDS = [
    "strategy",
    "priority",
    "roadmap",
    "tradeoff",
    "team",
    "brief",
    "status",
    "overview",
    "decision",
    "ship",
    "launch",
    "milestone",
    "all teams",
    "cross-team",
    "founder",
    "business",
    "overall",
]


@dataclass
class RouteResult:
    """Result of routing a query to team(s)."""

    primary_team: str
    secondary_teams: list[str]
    confidence: float  # 0.0 - 1.0
    reasoning: str


def route_query(query: str) -> RouteResult:
    """Route a consultation query to the most relevant team(s).

    Returns a RouteResult with primary team and optional secondary teams.
    """
    query_lower = query.lower()
    scores: dict[str, float] = {}

    # Score each team by keyword matches
    for team, keywords in _TEAM_KEYWORDS.items():
        score = 0.0
        matched = []
        for kw in keywords:
            if kw in query_lower:
                # Longer keywords are more specific → higher weight
                weight = 1.0 + len(kw) / 20.0
                score += weight
                matched.append(kw)
        if matched:
            scores[team] = score

    # Check for CoS-level queries
    cos_score = 0.0
    for kw in _COS_KEYWORDS:
        if kw in query_lower:
            cos_score += 1.0 + len(kw) / 20.0

    # Decision logic
    if not scores and cos_score == 0:
        # No matches — default to CoS
        return RouteResult(
            primary_team="cos",
            secondary_teams=[],
            confidence=0.3,
            reasoning="No strong keyword match — defaulting to CoS for general guidance.",
        )

    # Sort teams by score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # If CoS keywords dominate, route to CoS
    top_team_score = ranked[0][1] if ranked else 0
    if cos_score > top_team_score:
        secondary = [t for t, _ in ranked[:2]]
        return RouteResult(
            primary_team="cos",
            secondary_teams=secondary,
            confidence=min(1.0, cos_score / 5.0),
            reasoning=f"Cross-cutting query — CoS will synthesize. Related teams: {', '.join(secondary)}.",
        )

    # Route to top team
    primary = ranked[0][0]
    secondary = [t for t, s in ranked[1:3] if s >= top_team_score * 0.5]

    # Include CoS as secondary if cross-cutting keywords present
    if cos_score > 0 and "cos" not in secondary:
        secondary.append("cos")

    confidence = min(1.0, top_team_score / 5.0)

    return RouteResult(
        primary_team=primary,
        secondary_teams=secondary,
        confidence=confidence,
        reasoning=f"Best match: {primary} team (score: {top_team_score:.1f}).",
    )


# ---------------------------------------------------------------------------
# Cross-team request routing & tracking (Gap 6)
# ---------------------------------------------------------------------------


def route_and_track_request(request: dict) -> TrackedRequest:
    """Route a cross-team request and persist it for tracking.

    Args:
        request: dict with keys: source_agent, request, urgency, blocking
    """
    req_text = request.get("request", "")
    source = request.get("source_agent", "unknown")
    urgency = request.get("urgency", "medium")

    # Route using the query router
    result = route_query(req_text)

    tracked = TrackedRequest(
        id=f"req-{uuid.uuid4().hex[:8]}",
        source_agent=source,
        request=req_text,
        urgency=urgency,
        routed_to=result.primary_team,
        status="routed",
        created_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    # Persist to state
    state = _load_state()
    requests_list = state.setdefault("tracked_requests", [])
    requests_list.append(tracked.model_dump())
    # Keep last 100 requests
    state["tracked_requests"] = requests_list[-100:]
    _save_state(state)

    logger.info(
        "Routed request from %s to %s: %s",
        source,
        result.primary_team,
        req_text[:60],
    )
    return tracked


def get_open_requests() -> list[TrackedRequest]:
    """Return all unresolved tracked requests."""
    state = _load_state()
    requests_list = state.get("tracked_requests", [])
    return [TrackedRequest(**r) for r in requests_list if r.get("status") != "resolved"]


def resolve_request(request_id: str) -> None:
    """Mark a tracked request as resolved."""
    state = _load_state()
    for r in state.get("tracked_requests", []):
        if r.get("id") == request_id:
            r["status"] = "resolved"
            r["resolved_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _save_state(state)
            return
    raise ValueError(f"Request {request_id} not found")


def get_stale_requests(days: int = 3) -> list[TrackedRequest]:
    """Return requests that have been open for more than `days` days."""
    now = datetime.now(timezone.utc)
    open_reqs = get_open_requests()
    stale: list[TrackedRequest] = []
    for r in open_reqs:
        if r.created_date:
            created = datetime.strptime(r.created_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if (now - created).days >= days:
                stale.append(r)
    return stale


def get_request_tracking_report() -> str:
    """Render open/stale requests as markdown for the daily brief."""
    open_reqs = get_open_requests()
    stale = get_stale_requests()

    if not open_reqs:
        return ""

    lines = ["### Cross-Team Requests\n"]
    lines.append(f"**{len(open_reqs)} open** ({len(stale)} stale >3 days)\n")

    for r in open_reqs:
        stale_flag = " [STALE]" if r in stale else ""
        lines.append(
            f"- [{r.urgency.upper()}]{stale_flag} {r.source_agent} → {r.routed_to}: "
            f"{r.request[:80]}"
        )
    lines.append("")
    return "\n".join(lines)
