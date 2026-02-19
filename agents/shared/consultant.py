"""Shared consultant engine — LLM-powered interactive consultation for all agent teams.

Provides a `consult()` function that takes a query, loads relevant project context,
builds a team-specific system prompt, and returns a structured response via Claude API.
Falls back to a helpful message when AI_MOCK_MODE=true or no API key is set.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Maximum context chars to include from each source
_MAX_CONTEXT_CHARS = 8000


# ---------------------------------------------------------------------------
# Team prompt registry — each team provides its expertise description
# ---------------------------------------------------------------------------

TEAM_PROMPTS: dict[str, str] = {
    "engineering": (
        "You are the WarmPath Engineering team consultant. You advise on architecture, "
        "code quality, testing strategy, performance, dependency management, and security. "
        "You have deep knowledge of the FastAPI backend, SQLAlchemy models, Alembic migrations, "
        "React frontend, and the full test suite."
    ),
    "data": (
        "You are the WarmPath Data Science team consultant. You advise on data pipeline design, "
        "warm score calibration, funnel analytics, instrumentation coverage, SQL query optimization, "
        "and ML/AI model decisions. You understand the enrichment cache, usage logs, and metrics tables."
    ),
    "product": (
        "You are the WarmPath Product team consultant. You advise on user experience, feature "
        "prioritization, accessibility, design patterns, user journeys, onboarding flows, "
        "and frontend architecture. You understand both job seeker and network holder personas."
    ),
    "ops": (
        "You are the WarmPath Operations team consultant. You advise on coaching service quality, "
        "marketplace health, user satisfaction, network holder activation, supply-side experience, "
        "and operational metrics. You understand the two-sided marketplace dynamics."
    ),
    "gtm": (
        "You are the WarmPath Go-to-Market team consultant. You advise on competitive strategy, "
        "pricing and credit economy, marketing messaging, partnership opportunities, SEO, "
        "landing pages, and geographic market entry. You understand the $20-30/month pricing model."
    ),
    "finance": (
        "You are the WarmPath Finance team consultant. You advise on Stripe integration, credit "
        "economy accounting, subscription billing, regulatory compliance (GDPR, PDPA, FinCEN), "
        "investor data room readiness, and agent cost tracking."
    ),
    "cos": (
        "You are the WarmPath Chief of Staff. You synthesize insights across all teams — engineering, "
        "data, product, ops, GTM, and finance — to give the founder actionable advice. You prioritize "
        "business outcomes: user activation, marketplace liquidity, revenue, and regulatory readiness. "
        "You can route questions to specific teams or answer cross-cutting concerns yourself."
    ),
}


# ---------------------------------------------------------------------------
# Context loaders
# ---------------------------------------------------------------------------


def _load_file(path: Path, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    """Read a file, truncating to max_chars."""
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text
    except (OSError, UnicodeDecodeError):
        return ""


def _load_project_context() -> str:
    """Load core project context: CLAUDE.md summary + ARCHITECTURE.md summary."""
    parts: list[str] = []

    claude_md = _load_file(PROJECT_ROOT / "CLAUDE.md", 4000)
    if claude_md:
        parts.append(f"## CLAUDE.md (summary)\n{claude_md}")

    arch_md = _load_file(PROJECT_ROOT / "ARCHITECTURE.md", 4000)
    if arch_md:
        parts.append(f"## ARCHITECTURE.md (summary)\n{arch_md}")

    return "\n\n".join(parts)


def _load_recent_reports(team: str) -> str:
    """Load the most recent report for the given team, if available."""
    report_dirs = {
        "engineering": PROJECT_ROOT / "agents" / "reports",
        "data": PROJECT_ROOT / "data_team" / "reports",
        "product": PROJECT_ROOT / "product_team" / "reports",
        "ops": PROJECT_ROOT / "ops_team" / "reports",
        "gtm": PROJECT_ROOT / "gtm_team" / "reports",
        "finance": PROJECT_ROOT / "finance_team" / "reports",
        "cos": PROJECT_ROOT / "agents" / "reports" / "cos",
    }

    report_dir = report_dirs.get(team)
    if not report_dir or not report_dir.exists():
        return ""

    # Find most recent .json report
    reports = sorted(
        report_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not reports:
        return ""

    content = _load_file(reports[0], 3000)
    if content:
        return f"## Recent {team} report ({reports[0].name})\n{content}"
    return ""


# ---------------------------------------------------------------------------
# Consultation response
# ---------------------------------------------------------------------------


@dataclass
class ConsultResponse:
    """Structured response from a consultation."""

    team: str
    query: str
    answer: str
    confidence: str = "medium"  # high / medium / low
    follow_up_teams: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_markdown(self) -> str:
        lines = [
            f"## {self.team.upper()} Team Consultation",
            "",
            f"**Query:** {self.query}",
            "",
            self.answer,
            "",
        ]
        if self.follow_up_teams:
            lines.append(
                f"*Consider also consulting: {', '.join(self.follow_up_teams)}*"
            )
        lines.append(f"\n---\n*Responded in {self.duration_seconds:.1f}s*")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core consultation function
# ---------------------------------------------------------------------------


def consult(
    query: str,
    team: str = "cos",
    *,
    include_reports: bool = True,
    max_tokens: int = 2048,
    conversation_history: list[dict[str, str]] | None = None,
) -> ConsultResponse:
    """Run an interactive consultation with a specific team.

    Args:
        query: The question or topic to consult on.
        team: Which team to consult (engineering, data, product, ops, gtm, finance, cos).
        include_reports: Whether to include recent team reports as context.
        max_tokens: Max response tokens.
        conversation_history: Optional list of prior conversation turns for multi-turn
            support. Each entry is a dict with "role" (user/assistant) and "content".

    Returns:
        ConsultResponse with the team's answer.
    """
    start = time.time()
    team = team.lower().strip()

    if team not in TEAM_PROMPTS:
        return ConsultResponse(
            team=team,
            query=query,
            answer=f"Unknown team '{team}'. Available: {', '.join(sorted(TEAM_PROMPTS))}",
            confidence="low",
            duration_seconds=time.time() - start,
        )

    # Build system prompt
    system_prompt = TEAM_PROMPTS[team]
    system_prompt += (
        "\n\nYou are an interactive consultant. Answer the founder's question directly "
        "and concisely. Use bullet points for actionable items. If the question spans "
        "multiple teams, note which other teams should be consulted. "
        "Always ground your advice in the project's actual codebase and architecture."
    )

    # Build context
    context_parts: list[str] = [_load_project_context()]
    if include_reports:
        report_ctx = _load_recent_reports(team)
        if report_ctx:
            context_parts.append(report_ctx)

    context = "\n\n".join(filter(None, context_parts))

    # Build user message
    user_message = f"PROJECT CONTEXT:\n{context}\n\nQUESTION:\n{query}"

    # Check if we can use real AI
    try:
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        mock_mode = os.environ.get("AI_MOCK_MODE", "true").lower() in (
            "true",
            "1",
            "yes",
        )

        if mock_mode or not api_key:
            logger.info("Consultant running in mock mode for team '%s'", team)
            return _mock_consult(query, team, start)

        import anthropic

        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
        client = anthropic.Anthropic(api_key=api_key)

        # Build messages list — multi-turn when conversation_history is provided
        if conversation_history:
            messages: list[dict[str, str]] = [
                {"role": "user", "content": f"PROJECT CONTEXT:\n{context}"},
                {
                    "role": "assistant",
                    "content": "I've reviewed the project context. How can I help?",
                },
            ]
            for turn in conversation_history:
                messages.append(
                    {"role": turn["role"], "content": turn["content"]}
                )
            messages.append({"role": "user", "content": query})
        else:
            messages = [{"role": "user", "content": user_message}]

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        answer = message.content[0].text.strip()

        # Extract follow-up teams if mentioned
        follow_ups = []
        for t in TEAM_PROMPTS:
            if t != team and t in answer.lower():
                follow_ups.append(t)

        return ConsultResponse(
            team=team,
            query=query,
            answer=answer,
            confidence="high",
            follow_up_teams=follow_ups,
            duration_seconds=time.time() - start,
        )

    except Exception as exc:
        logger.error("Consultation failed for team '%s': %s", team, exc)
        return _mock_consult(query, team, start)


def _mock_consult(query: str, team: str, start: float) -> ConsultResponse:
    """Return a structured mock response when AI is unavailable."""
    team_label = team.upper()
    return ConsultResponse(
        team=team,
        query=query,
        answer=(
            f"**{team_label} Team Analysis** (mock mode)\n\n"
            f'Query received: "{query}"\n\n'
            f"To get a real AI-powered consultation, set `AI_MOCK_MODE=false` and "
            f"provide a valid `ANTHROPIC_API_KEY` in your environment.\n\n"
            f"In the meantime, you can:\n"
            f"- Run `python3 -m agents.orchestrator --all` for a full engineering scan\n"
            f"- Check recent reports in the team's reports/ directory\n"
            f"- Review CLAUDE.md and ARCHITECTURE.md for project context"
        ),
        confidence="low",
        duration_seconds=time.time() - start,
    )


# ---------------------------------------------------------------------------
# Multi-team consultation (used by CoS)
# ---------------------------------------------------------------------------


def consult_multiple(
    query: str,
    teams: list[str],
    **kwargs,
) -> list[ConsultResponse]:
    """Consult multiple teams and return all responses."""
    return [consult(query, team=t, **kwargs) for t in teams]
