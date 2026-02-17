"""External intelligence for product team — UX research, competitor features, design trends.

Provides `ProductIntelligence` with 12 product-specific intelligence categories,
per-agent relevance filtering, urgency tracking, adoption workflow,
per-category TTL staleness, and research agenda generation.

Same pattern as data_team/shared/intelligence.py but with product-team-specific
categories and independent cache at product_team/shared/intel_cache.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from product_team.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProductIntelItem:
    """A piece of product-team-specific intelligence."""

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
# Intelligence categories (12 product-specific)
# ---------------------------------------------------------------------------

PRODUCT_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    # UserResearcher categories (6)
    "user_forums": {
        "refresh_hours": 168,
        "agents": ["user_researcher", "product_lead"],
        "source": "Reddit r/cscareerquestions, Blind, Hacker News — job search frustrations",
        "description": "Job seeker pain points, referral-seeking behavior, competitor complaints",
    },
    "career_platforms": {
        "refresh_hours": 168,
        "agents": ["user_researcher", "product_manager"],
        "source": "LinkedIn, Glassdoor, Levels.fyi — career platform trends",
        "description": "How job seekers currently navigate referrals and networking",
    },
    "referral_culture": {
        "refresh_hours": 336,
        "agents": ["user_researcher"],
        "source": "HR blogs, LinkedIn articles, recruiter communities",
        "description": "Referral bonus trends, cultural attitudes toward networking by region",
    },
    "research_methods": {
        "refresh_hours": 336,
        "agents": ["user_researcher", "product_lead"],
        "source": "Nielsen Norman Group, Baymard Institute, UX research publications",
        "description": "UX research methodologies, survey design, interview techniques",
    },
    "persona_evolution": {
        "refresh_hours": 336,
        "agents": ["user_researcher", "product_manager"],
        "source": "Job market reports, demographic data, tech industry surveys",
        "description": "How target personas are evolving (remote work, AI impact, market shifts)",
    },
    "competitor_features": {
        "refresh_hours": 168,
        "agents": ["user_researcher", "product_manager", "product_lead"],
        "source": "Product Hunt, TechCrunch, competitor changelogs — Blind, Lunchclub, Teamable, Refer.me",
        "description": "Competitor feature launches, pricing changes, positioning shifts",
    },
    # DesignLead categories (2)
    "design_systems": {
        "refresh_hours": 336,
        "agents": ["design_lead"],
        "source": "Tailwind blog, Figma community, design system showcases",
        "description": "Design system best practices, Tailwind patterns, component libraries",
    },
    "design_trends": {
        "refresh_hours": 336,
        "agents": ["design_lead", "ux_lead"],
        "source": "Dribbble, Behance, Awwwards — SaaS/marketplace design trends",
        "description": "Visual design trends for B2B/marketplace products",
    },
    # UXLead categories (2)
    "accessibility_standards": {
        "refresh_hours": 336,
        "agents": ["ux_lead"],
        "source": "WCAG updates, WebAIM, Deque — accessibility compliance",
        "description": "WCAG guideline updates, accessibility testing tools, legal requirements",
    },
    "ux_patterns": {
        "refresh_hours": 168,
        "agents": ["ux_lead", "design_lead"],
        "source": "Nielsen Norman Group, Smashing Magazine, UX Collective",
        "description": "UX patterns for marketplaces, onboarding flows, trust-building UI",
    },
    # ProductManager categories (2)
    "pm_frameworks": {
        "refresh_hours": 336,
        "agents": ["product_manager", "product_lead"],
        "source": "Lenny's Newsletter, Reforge, Product School",
        "description": "Product management frameworks, prioritization methods, metrics best practices",
    },
    "marketplace_dynamics": {
        "refresh_hours": 168,
        "agents": ["product_manager", "product_lead"],
        "source": "a16z marketplace guides, NFX network effects, marketplace research",
        "description": "Two-sided marketplace tactics: liquidity, chicken-and-egg, pricing",
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
# ProductIntelligence class
# ---------------------------------------------------------------------------


class ProductIntelligence:
    """Structured intelligence system for product team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "product_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: ProductIntelItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[ProductIntelItem]:
        """Return all items for a given category."""
        result = []
        for raw in self._get_items():
            if raw.get("category") == category:
                result.append(ProductIntelItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[ProductIntelItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[ProductIntelItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(ProductIntelItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[ProductIntelItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(ProductIntelItem(**raw))
        return result

    def get_all(self) -> list[ProductIntelItem]:
        """Return all intelligence items."""
        return [ProductIntelItem(**raw) for raw in self._get_items()]

    def get_urgent(self) -> list[ProductIntelItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(ProductIntelItem(**raw))
        return result

    def get_unadopted(self) -> list[ProductIntelItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(ProductIntelItem(**raw))
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
        for category, meta in PRODUCT_INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritized research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = PRODUCT_INTEL_CATEGORIES.get(category, {})
                if category in ("competitor_features", "user_forums", "marketplace_dynamics"):
                    priority = "high"
                elif category in ("accessibility_standards", "ux_patterns", "career_platforms"):
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
            "categories_total": len(PRODUCT_INTEL_CATEGORIES),
            "items_by_category": by_category,
            "freshness": freshness,
        }
