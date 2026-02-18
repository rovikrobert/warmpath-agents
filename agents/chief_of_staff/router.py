"""CoS Query Router — routes consultation queries to the most relevant team(s).

Keyword-based routing with confidence scoring. The CoS can handle cross-cutting
queries itself or dispatch to specialized teams.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topic → Team mapping
# ---------------------------------------------------------------------------

_TEAM_KEYWORDS: dict[str, list[str]] = {
    "engineering": [
        "architecture", "api", "endpoint", "database", "migration", "alembic",
        "model", "schema", "test", "pytest", "performance", "query", "bug",
        "refactor", "dependency", "security", "auth", "jwt", "middleware",
        "celery", "redis", "sqlalchemy", "fastapi", "deploy", "railway",
        "docker", "ci", "cd", "backend", "code", "type hint",
    ],
    "data": [
        "data", "analytics", "funnel", "metric", "warm score", "calibration",
        "pipeline", "sql", "instrumentation", "telemetry", "usage log",
        "enrichment", "cache", "ab test", "cohort", "retention", "churn",
    ],
    "product": [
        "ux", "ui", "frontend", "react", "design", "accessibility", "aria",
        "onboarding", "user journey", "feature", "persona", "job seeker",
        "network holder", "flow", "page", "component", "tailwind", "mobile",
        "responsive", "navigation", "modal", "form",
    ],
    "ops": [
        "coaching", "coach", "keevs", "marketplace health", "satisfaction",
        "supply side", "activation", "nh ", "network holder experience",
        "response rate", "intro facilitation", "operational",
    ],
    "gtm": [
        "pricing", "credit", "monetization", "competition", "competitor",
        "marketing", "seo", "landing page", "positioning", "launch",
        "partnership", "community", "geographic", "market entry", "brand",
        "messaging", "growth", "acquisition", "conversion",
    ],
    "finance": [
        "stripe", "billing", "subscription", "invoice", "payment", "webhook",
        "compliance", "gdpr", "pdpa", "ccpa", "legal", "regulation",
        "investor", "fundraising", "burn rate", "cost", "budget", "audit",
        "fintech", "money transmitter",
    ],
}

# Queries that the CoS handles directly (cross-cutting)
_COS_KEYWORDS = [
    "strategy", "priority", "roadmap", "tradeoff", "team", "brief",
    "status", "overview", "decision", "ship", "launch", "milestone",
    "all teams", "cross-team", "founder", "business", "overall",
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
