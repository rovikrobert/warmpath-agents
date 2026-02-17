"""External intelligence for GTM team — competitive, pricing, SEO, partnerships, APAC.

Provides `GTMIntelligence` with 16 GTM-specific intelligence categories,
per-agent relevance filtering, urgency tracking, adoption workflow,
per-category TTL staleness, and research agenda generation.

Same pattern as ops_team/shared/intelligence.py but with GTM-specific
categories and independent cache at gtm_team/shared/intel_cache.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from gtm_team.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GTMIntelItem:
    """A piece of GTM-team-specific intelligence."""

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
# Intelligence categories (16 GTM-specific)
# ---------------------------------------------------------------------------

GTM_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    # Competitive landscape
    "competitor_products": {
        "refresh_hours": 24,
        "agents": ["stratops", "gtm_lead"],
        "source": "Product Hunt, G2, Capterra, App Store",
        "description": "Competitor feature launches, product changes, new entrants",
    },
    "competitor_funding": {
        "refresh_hours": 168,
        "agents": ["stratops", "gtm_lead"],
        "source": "Crunchbase, PitchBook, TechCrunch, Tech in Asia",
        "description": "Competitor funding rounds, new entrants, market valuations",
    },
    "competitor_pricing": {
        "refresh_hours": 168,
        "agents": ["monetization", "stratops"],
        "source": "Competitor pricing pages, G2 pricing data",
        "description": "Competitor pricing changes, tier structures, free tier limits",
    },
    "competitor_hiring": {
        "refresh_hours": 168,
        "agents": ["stratops"],
        "source": "LinkedIn job postings for tracked competitors",
        "description": "Competitor hiring patterns as strategy signals",
    },
    # Market data
    "job_market_stats": {
        "refresh_hours": 720,
        "agents": ["stratops", "gtm_lead"],
        "source": "BLS, Singapore MOM, LinkedIn Workforce Report",
        "description": "Job market statistics affecting demand-side positioning",
    },
    "referral_effectiveness": {
        "refresh_hours": 720,
        "agents": ["marketing", "stratops"],
        "source": "Jobvite recruiting surveys, LinkedIn talent insights, academic papers",
        "description": "Referral conversion data, effectiveness research for content",
    },
    # Pricing benchmarks
    "saas_pricing_benchmarks": {
        "refresh_hours": 2160,
        "agents": ["monetization"],
        "source": "ProfitWell/Paddle, OpenView, KeyBanc SaaS survey",
        "description": "SaaS pricing benchmarks, conversion rates, LTV/CAC ratios",
    },
    "marketplace_economics": {
        "refresh_hours": 720,
        "agents": ["monetization", "stratops"],
        "source": "a16z marketplace research, Lenny's Newsletter, NFX essays",
        "description": "Marketplace economics: take rates, liquidity, pricing evolution",
    },
    # Channel performance
    "seo_trends": {
        "refresh_hours": 168,
        "agents": ["marketing"],
        "source": "Google Trends, Ahrefs blog, Search Engine Journal",
        "description": "SEO trends, keyword opportunities, algorithm changes",
    },
    "content_benchmarks": {
        "refresh_hours": 720,
        "agents": ["marketing"],
        "source": "HubSpot research, Orbit Media surveys, Content Marketing Institute",
        "description": "Content marketing benchmarks, format effectiveness",
    },
    # Community & partnerships
    "community_building": {
        "refresh_hours": 720,
        "agents": ["partnerships"],
        "source": "CMX Hub, Community Club, Lenny's community research",
        "description": "Community building strategies, engagement patterns",
    },
    "bootcamp_market": {
        "refresh_hours": 720,
        "agents": ["partnerships"],
        "source": "Course Report, SwitchUp, Career Karma",
        "description": "Bootcamp market landscape, placement rates, partnership models",
    },
    "university_career_services": {
        "refresh_hours": 2160,
        "agents": ["partnerships"],
        "source": "NACE surveys, university career center blogs",
        "description": "University career services trends, partnership opportunities",
    },
    # APAC market
    "sea_tech_ecosystem": {
        "refresh_hours": 168,
        "agents": ["stratops", "partnerships"],
        "source": "Tech in Asia, e27, DealStreetAsia, The Ken",
        "description": "Southeast Asia tech ecosystem dynamics, startup hiring",
    },
    "sea_job_market": {
        "refresh_hours": 720,
        "agents": ["stratops", "marketing"],
        "source": "JobStreet reports, Michael Page salary surveys, Hays Asia reports",
        "description": "SEA job market trends, salary benchmarks, hiring patterns",
    },
    # Marketing compliance
    "marketing_regulations": {
        "refresh_hours": 720,
        "agents": ["marketing", "gtm_lead"],
        "source": "FTC guidance, PDPC Singapore enforcement, ICO UK/EU marketing guidance",
        "description": "Marketing regulatory updates across operating jurisdictions",
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
# GTMIntelligence class
# ---------------------------------------------------------------------------


class GTMIntelligence:
    """Structured intelligence system for GTM team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "gtm_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: GTMIntelItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[GTMIntelItem]:
        """Return all items for a given category."""
        result = []
        for raw in self._get_items():
            if raw.get("category") == category:
                result.append(GTMIntelItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[GTMIntelItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[GTMIntelItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(GTMIntelItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[GTMIntelItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(GTMIntelItem(**raw))
        return result

    def get_all(self) -> list[GTMIntelItem]:
        """Return all intelligence items."""
        return [GTMIntelItem(**raw) for raw in self._get_items()]

    def get_urgent(self) -> list[GTMIntelItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(GTMIntelItem(**raw))
        return result

    def get_unadopted(self) -> list[GTMIntelItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(GTMIntelItem(**raw))
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
        for category, meta in GTM_INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritised research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = GTM_INTEL_CATEGORIES.get(category, {})
                if category in ("competitor_products", "competitor_pricing", "seo_trends"):
                    priority = "high"
                elif category in ("marketplace_economics", "referral_effectiveness", "marketing_regulations"):
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
            "categories_total": len(GTM_INTEL_CATEGORIES),
            "items_by_category": by_category,
            "freshness": freshness,
        }
