"""External intelligence for ops team — job market, referral practices, marketplace economics.

Provides `OpsIntelligence` with 12 ops-specific intelligence categories,
per-agent relevance filtering, urgency tracking, adoption workflow,
per-category TTL staleness, and research agenda generation.

Same pattern as product_team/shared/intelligence.py but with ops-team-specific
categories and independent cache at ops_team/shared/intel_cache.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ops_team.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OpsIntelItem:
    """A piece of ops-team-specific intelligence."""

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
# Intelligence categories (12 ops-specific)
# ---------------------------------------------------------------------------

OPS_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    # Keevs categories
    "job_market_trends": {
        "refresh_hours": 168,
        "agents": ["keevs", "ops_lead"],
        "source": "LinkedIn Economic Graph, Indeed Hiring Lab, BLS jobs reports",
        "description": "Job market trends affecting coaching advice quality",
    },
    "referral_best_practices": {
        "refresh_hours": 336,
        "agents": ["keevs"],
        "source": "Career coaching blogs, referral success studies, HR research",
        "description": "Best practices for referral requests, cold-to-warm techniques",
    },
    "cultural_communication": {
        "refresh_hours": 336,
        "agents": ["keevs"],
        "source": "Cross-cultural communication research, regional business norms",
        "description": "Cultural communication norms for referral messaging by region",
    },
    "competitor_ux": {
        "refresh_hours": 168,
        "agents": ["keevs", "naiv"],
        "source": "Lunchclub, Blind, Teamable, Refer.me — UX teardowns",
        "description": "Competitor user experience and coaching feature comparison",
    },
    # Treb categories
    "referral_bonus_benchmarks": {
        "refresh_hours": 336,
        "agents": ["treb"],
        "source": "Glassdoor, Levels.fyi, HR surveys — referral bonus data",
        "description": "Referral bonus amounts by company/role for NH activation messaging",
    },
    "employee_engagement": {
        "refresh_hours": 336,
        "agents": ["treb"],
        "source": "Gallup, SHRM, employee engagement surveys",
        "description": "Employee engagement patterns affecting willingness to refer",
    },
    "marketplace_retention": {
        "refresh_hours": 336,
        "agents": ["treb", "marsh"],
        "source": "Marketplace platform case studies, supplier retention research",
        "description": "Supply-side retention strategies for two-sided marketplaces",
    },
    "company_hiring_signals": {
        "refresh_hours": 168,
        "agents": ["treb", "marsh"],
        "source": "Job boards, LinkedIn hiring signals, company news",
        "description": "Companies actively hiring — signals for marketplace supply targeting",
    },
    # Naiv categories
    "nps_benchmarks": {
        "refresh_hours": 336,
        "agents": ["naiv"],
        "source": "Delighted, Wootric, SaaS NPS benchmarks",
        "description": "NPS benchmarks for marketplace/SaaS products",
    },
    "survey_design": {
        "refresh_hours": 336,
        "agents": ["naiv", "ops_lead"],
        "source": "Qualtrics, SurveyMonkey research, UX survey best practices",
        "description": "Survey design and feedback collection best practices",
    },
    # Marsh categories
    "marketplace_economics": {
        "refresh_hours": 336,
        "agents": ["marsh", "ops_lead"],
        "source": "a16z marketplace guides, NFX, marketplace economics research",
        "description": "Marketplace economics: take rates, liquidity, pricing strategies",
    },
    "credit_economy_benchmarks": {
        "refresh_hours": 336,
        "agents": ["marsh"],
        "source": "Loyalty program research, virtual currency case studies",
        "description": "Credit/loyalty economy benchmarks and compliance frameworks",
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
# OpsIntelligence class
# ---------------------------------------------------------------------------


class OpsIntelligence:
    """Structured intelligence system for ops team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "ops_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: OpsIntelItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[OpsIntelItem]:
        """Return all items for a given category."""
        result = []
        for raw in self._get_items():
            if raw.get("category") == category:
                result.append(OpsIntelItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[OpsIntelItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[OpsIntelItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(OpsIntelItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[OpsIntelItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(OpsIntelItem(**raw))
        return result

    def get_all(self) -> list[OpsIntelItem]:
        """Return all intelligence items."""
        return [OpsIntelItem(**raw) for raw in self._get_items()]

    def get_urgent(self) -> list[OpsIntelItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(OpsIntelItem(**raw))
        return result

    def get_unadopted(self) -> list[OpsIntelItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(OpsIntelItem(**raw))
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
        for category, meta in OPS_INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritized research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = OPS_INTEL_CATEGORIES.get(category, {})
                if category in (
                    "job_market_trends",
                    "competitor_ux",
                    "company_hiring_signals",
                ):
                    priority = "high"
                elif category in (
                    "marketplace_economics",
                    "referral_best_practices",
                    "nps_benchmarks",
                ):
                    priority = "medium"
                else:
                    priority = "medium"

                agenda.append(
                    {
                        "category": category,
                        "question": f"What are the latest updates for: {meta.get('description', category)}?",
                        "source": meta.get("source", "unknown"),
                        "relevant_agents": meta.get("agents", []),
                        "priority": priority,
                    }
                )

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
            "categories_total": len(OPS_INTEL_CATEGORIES),
            "items_by_category": by_category,
            "freshness": freshness,
        }
