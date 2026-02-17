"""External intelligence for finance team — startup finance, credit economy, regulation.

Provides `FinanceIntelligence` with 7 finance-specific intelligence categories,
per-agent relevance filtering, urgency tracking, adoption workflow,
per-category TTL staleness, and research agenda generation.

Same pattern as ops_team/shared/intelligence.py but with finance-team-specific
categories and independent cache at finance_team/shared/intel_cache.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from finance_team.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FinanceIntelItem:
    """A piece of finance-team-specific intelligence."""

    id: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    source: str = ""
    severity: str = "info"  # critical | high | medium | low | info
    relevant_agents: list[str] = field(default_factory=list)
    fetched_at: str = ""
    adopted: bool = False
    adopted_by: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Intelligence categories (7 finance-specific)
# ---------------------------------------------------------------------------

FINANCE_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    "startup_finance": {
        "refresh_hours": 720,
        "agents": ["finance_manager", "investor_relations"],
        "source": "SaaS benchmarks (Bessemer, OpenView), startup cost data",
        "description": "Startup financial benchmarks and cost optimization strategies",
    },
    "credit_economy_patterns": {
        "refresh_hours": 720,
        "agents": ["credits_manager"],
        "source": "Game economy research, loyalty program benchmarks, marketplace economy studies",
        "description": "Credit/loyalty economy benchmarks and design patterns",
    },
    "regulatory_privacy": {
        "refresh_hours": 168,
        "agents": ["legal_compliance"],
        "source": "GDPR enforcement tracker, CCPA enforcement, PDPC (Singapore) decisions",
        "description": "Privacy regulation enforcement trends and changes",
    },
    "regulatory_financial": {
        "refresh_hours": 168,
        "agents": ["legal_compliance", "credits_manager"],
        "source": "FinCEN guidance, MAS (Singapore) notices, e-money regulation updates",
        "description": "Financial regulation affecting credit/token systems",
    },
    "vc_market": {
        "refresh_hours": 720,
        "agents": ["investor_relations"],
        "source": "Crunchbase, PitchBook summaries, fundraise benchmarks by stage",
        "description": "VC market conditions and fundraising benchmarks",
    },
    "ai_regulation": {
        "refresh_hours": 336,
        "agents": ["legal_compliance"],
        "source": "EU AI Act developments, Singapore AI governance, US AI EO updates",
        "description": "AI regulation affecting platform operations",
    },
    "competitor_pricing": {
        "refresh_hours": 720,
        "agents": ["finance_manager", "investor_relations"],
        "source": "The Swarm, LinkedIn, Indeed, Handshake pricing changes",
        "description": "Competitor pricing intelligence for referral platforms",
    },
}


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    if INTEL_CACHE.exists():
        try:
            return json.loads(INTEL_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(data: dict) -> None:
    INTEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    INTEL_CACHE.write_text(json.dumps(data, indent=2, default=str))


def _is_stale(cache: dict, key: str, ttl_hours: float | None = None) -> bool:
    entry = cache.get(key)
    if not entry or "fetched_at" not in entry:
        return True
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        ttl = ttl_hours if ttl_hours is not None else INTEL_CACHE_TTL_HOURS
        return hours > ttl
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# FinanceIntelligence class
# ---------------------------------------------------------------------------


class FinanceIntelligence:
    """Structured intelligence system for finance team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "finance_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: FinanceIntelItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[FinanceIntelItem]:
        """Return all items for a given category."""
        result = []
        for raw in self._get_items():
            if raw.get("category") == category:
                result.append(FinanceIntelItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[FinanceIntelItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[FinanceIntelItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(FinanceIntelItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[FinanceIntelItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(FinanceIntelItem(**raw))
        return result

    def get_all(self) -> list[FinanceIntelItem]:
        """Return all intelligence items."""
        return [FinanceIntelItem(**raw) for raw in self._get_items()]

    def get_urgent(self) -> list[FinanceIntelItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(FinanceIntelItem(**raw))
        return result

    def get_unadopted(self) -> list[FinanceIntelItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(FinanceIntelItem(**raw))
        return result

    def mark_adopted(self, item_id: str, agent_name: str) -> bool:
        """Mark an item as adopted by an agent. Returns True if found."""
        items = self._get_items()
        for raw in items:
            if raw.get("id") == item_id:
                raw["adopted"] = True
                raw["adopted_by"] = agent_name
                self._set_items(items)
                self._save()
                return True
        return False

    def check_freshness(self) -> dict[str, bool]:
        """Check staleness of each intelligence category."""
        result = {}
        for category, meta in FINANCE_INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritized research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = FINANCE_INTEL_CATEGORIES.get(category, {})
                if category in ("regulatory_privacy", "regulatory_financial", "competitor_pricing"):
                    priority = "high"
                elif category in ("startup_finance", "vc_market", "ai_regulation"):
                    priority = "medium"
                else:
                    priority = "medium"

                agenda.append({
                    "category": category,
                    "question": f"What are the latest updates for: {meta.get('description', category)}?",
                    "source": meta.get("source", "unknown"),
                    "relevant_agents": meta.get("agents", []),
                    "priority": priority,
                })

        priority_order = {"high": 0, "medium": 1, "low": 2}
        agenda.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
        return agenda

    def generate_intel_report(self) -> dict:
        """Generate a summary report of all intelligence state."""
        freshness = self.check_freshness()
        all_items = self.get_all()
        urgent = self.get_urgent()
        unadopted = self.get_unadopted()

        by_category: dict[str, int] = {}
        for item in all_items:
            by_category[item.category] = by_category.get(item.category, 0) + 1

        return {
            "total_items": len(all_items),
            "urgent_items": len(urgent),
            "unadopted_items": len(unadopted),
            "categories_fresh": sum(1 for v in freshness.values() if v),
            "categories_stale": sum(1 for v in freshness.values() if not v),
            "categories_total": len(FINANCE_INTEL_CATEGORIES),
            "items_by_category": by_category,
            "freshness": freshness,
        }
