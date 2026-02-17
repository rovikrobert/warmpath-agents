"""Strategy document loader — loads and indexes WarmPath strategy docs for all GTM agents.

Every GTM agent MUST consume this context before producing work.
Strategy docs are the source of truth. If an agent's recommendation
diverges from strategy docs, it must explicitly acknowledge the divergence.

Handles missing files gracefully — not all strategy docs exist yet.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from gtm_team.shared.config import STRATEGY_DOCS_DIR, STRATEGY_DOC_NAMES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file safely, returning empty string on error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def load_strategy_docs() -> dict[str, str]:
    """Load all strategy documents. Returns {filename: content} for existing files."""
    docs: dict[str, str] = {}
    for name in STRATEGY_DOC_NAMES:
        path = STRATEGY_DOCS_DIR / name
        content = _read_safe(path)
        if content:
            docs[name] = content
            logger.debug("Loaded strategy doc: %s (%d chars)", name, len(content))
        else:
            logger.debug("Strategy doc not found or empty: %s", name)
    return docs


def get_strategy_doc(name: str) -> str:
    """Load a single strategy document by filename."""
    path = STRATEGY_DOCS_DIR / name
    return _read_safe(path)


# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------


def extract_pricing_info(docs: dict[str, str] | None = None) -> dict[str, Any]:
    """Extract pricing tiers and credit economy from strategy docs."""
    if docs is None:
        docs = load_strategy_docs()

    pricing: dict[str, Any] = {
        "tiers": [],
        "credit_economy": {},
        "found_in": [],
    }

    all_text = "\n".join(docs.values())

    # Look for pricing tier mentions
    tier_patterns = [
        r"free\s+tier",
        r"\$\d+/month",
        r"active\s+job\s+seeker",
        r"career\s+accelerator",
    ]
    for pattern in tier_patterns:
        if re.search(pattern, all_text, re.IGNORECASE):
            pricing["tiers"].append(pattern)

    # Credit economy
    credit_patterns = {
        "earn_actions": r"earn:?\s*(.+?)(?:\n|$)",
        "spend_actions": r"spend:?\s*(.+?)(?:\n|$)",
        "buy_rate": r"\$1\s*=\s*(\d+)\s*credits",
        "expiry": r"(\d+).month\s*expir",
    }
    for key, pattern in credit_patterns.items():
        match = re.search(pattern, all_text, re.IGNORECASE)
        if match:
            pricing["credit_economy"][key] = match.group(1).strip()

    pricing["found_in"] = list(docs.keys())
    return pricing


def extract_competitive_info(docs: dict[str, str] | None = None) -> dict[str, Any]:
    """Extract competitive landscape information."""
    if docs is None:
        docs = load_strategy_docs()

    all_text = "\n".join(docs.values())

    competitors_mentioned = []
    from gtm_team.shared.config import TRACKED_COMPETITORS
    for comp in TRACKED_COMPETITORS:
        if comp.lower() in all_text.lower():
            competitors_mentioned.append(comp)

    return {
        "competitors_mentioned": competitors_mentioned,
        "total_tracked": len(TRACKED_COMPETITORS),
        "coverage_ratio": len(competitors_mentioned) / max(1, len(TRACKED_COMPETITORS)),
        "has_positioning": bool(re.search(r"differentiator|positioning|competitive\s+advantage", all_text, re.IGNORECASE)),
        "has_market_sizing": bool(re.search(r"TAM|SAM|SOM|total\s+addressable", all_text, re.IGNORECASE)),
    }


def extract_personas(docs: dict[str, str] | None = None) -> dict[str, Any]:
    """Extract user persona information."""
    if docs is None:
        docs = load_strategy_docs()

    all_text = "\n".join(docs.values())

    return {
        "has_job_seeker_persona": bool(re.search(r"job\s+seeker|demand\s+side", all_text, re.IGNORECASE)),
        "has_network_holder_persona": bool(re.search(r"network\s+holder|supply\s+side", all_text, re.IGNORECASE)),
        "has_bootcamp_persona": bool(re.search(r"bootcamp|career\s+changer", all_text, re.IGNORECASE)),
        "has_coach_persona": bool(re.search(r"career\s+coach|white.?label", all_text, re.IGNORECASE)),
    }


def extract_geographic_strategy(docs: dict[str, str] | None = None) -> dict[str, Any]:
    """Extract geographic expansion strategy."""
    if docs is None:
        docs = load_strategy_docs()

    all_text = "\n".join(docs.values())

    markets = {
        "singapore": bool(re.search(r"singapore", all_text, re.IGNORECASE)),
        "us": bool(re.search(r"united\s+states|US\s+market|\bUS\b", all_text)),
        "sea": bool(re.search(r"southeast\s+asia|SEA|APAC", all_text, re.IGNORECASE)),
        "india": bool(re.search(r"\bindia\b", all_text, re.IGNORECASE)),
        "anz": bool(re.search(r"australia|new\s+zealand|ANZ", all_text, re.IGNORECASE)),
    }

    return {
        "markets_mentioned": {k: v for k, v in markets.items() if v},
        "has_entry_sequence": bool(re.search(r"entry\s+sequence|market\s+entry|expansion", all_text, re.IGNORECASE)),
        "has_regulatory_notes": bool(re.search(r"PDPA|GDPR|CCPA|regulatory", all_text, re.IGNORECASE)),
    }


def extract_privacy_constraints(docs: dict[str, str] | None = None) -> dict[str, Any]:
    """Extract privacy constraints relevant to GTM marketing."""
    if docs is None:
        docs = load_strategy_docs()

    all_text = "\n".join(docs.values())

    return {
        "has_vault_model": bool(re.search(r"private\s+vault|vault\s+boundary", all_text, re.IGNORECASE)),
        "has_anonymization": bool(re.search(r"anonymi[sz]ed|marketplace\s+index", all_text, re.IGNORECASE)),
        "has_suppression_list": bool(re.search(r"suppression\s+list", all_text, re.IGNORECASE)),
        "has_consent_gates": bool(re.search(r"consent\s+gate|opt.in", all_text, re.IGNORECASE)),
        "has_gdpr": bool(re.search(r"GDPR", all_text)),
        "has_pdpa": bool(re.search(r"PDPA", all_text)),
        "has_ccpa": bool(re.search(r"CCPA", all_text)),
    }


def check_alignment(recommendation: str, strategy_section: str) -> list[str]:
    """Check if a recommendation aligns with strategy docs. Returns divergence list."""
    divergences: list[str] = []

    rec_lower = recommendation.lower()
    strat_lower = strategy_section.lower()

    # Check for pricing contradictions
    if "free" in rec_lower and "paid" in strat_lower:
        divergences.append("Recommendation suggests free access where strategy docs specify paid tier")

    # Check for geographic contradictions
    if "us first" in rec_lower and "singapore" in strat_lower:
        divergences.append("Recommendation suggests US-first but strategy docs specify Singapore as home base")

    return divergences
