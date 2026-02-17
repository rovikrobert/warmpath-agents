"""External intelligence for data team — marketplace benchmarks, ML research, job market data.

Provides `DataIntelligence` with 10 data-specific intelligence categories,
per-agent relevance filtering, urgency tracking, adoption workflow,
per-category TTL staleness, and research agenda generation.

Same pattern as agents/shared/intelligence.py but with data-team-specific
categories and independent cache at data_team/shared/intel_cache.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from data_team.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DataIntelItem:
    """A piece of data-team-specific intelligence."""

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
# Intelligence categories (10 data-specific)
# ---------------------------------------------------------------------------

DATA_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    "marketplace_benchmarks": {
        "refresh_hours": 168,
        "agents": ["analyst", "data_lead"],
        "source": "Industry reports — Uber, Airbnb, LinkedIn marketplace KPIs",
        "description": "Two-sided marketplace KPI benchmarks (liquidity, take rate, supply/demand ratios)",
    },
    "job_market_data": {
        "refresh_hours": 168,
        "agents": ["analyst", "model_engineer"],
        "source": "BLS, LinkedIn Economic Graph, Greenhouse benchmarks",
        "description": "Job market trends, referral conversion rates, hiring velocity by sector",
    },
    "ml_research": {
        "refresh_hours": 336,
        "agents": ["model_engineer"],
        "source": "arXiv, Papers with Code — recommendation systems, NLP matching",
        "description": "Recommendation systems, NLP for matching, warm score ML approaches",
    },
    "competitor_intel": {
        "refresh_hours": 168,
        "agents": ["data_lead", "analyst"],
        "source": "Crunchbase, product blogs — Blind, Lunchclub, Teamable, Refer.me",
        "description": "Competitor analytics approaches and feature launches",
    },
    "privacy_regulations": {
        "refresh_hours": 336,
        "agents": ["pipeline", "data_lead"],
        "source": "GDPR/CCPA/PDPA regulatory updates, EDPB guidelines",
        "description": "Data privacy regulation changes, differential privacy techniques",
    },
    "referral_science": {
        "refresh_hours": 336,
        "agents": ["model_engineer", "analyst"],
        "source": "Academic papers, HR industry reports",
        "description": "Referral effectiveness research, social network analysis, tie strength theory",
    },
    "data_infrastructure": {
        "refresh_hours": 168,
        "agents": ["pipeline", "data_lead"],
        "source": "PostgreSQL, SQLAlchemy, dbt, Airflow release notes",
        "description": "Data infrastructure tooling updates and best practices",
    },
    "ab_testing_methods": {
        "refresh_hours": 336,
        "agents": ["model_engineer", "analyst"],
        "source": "Statsig, Eppo, academic papers on causal inference",
        "description": "A/B testing methodologies, sequential testing, causal inference for marketplaces",
    },
    "matching_algorithms": {
        "refresh_hours": 336,
        "agents": ["model_engineer"],
        "source": "RecSys conference, Netflix/Spotify/LinkedIn engineering blogs",
        "description": "Matching algorithm improvements, embedding models, hybrid recommenders",
    },
    "analytics_patterns": {
        "refresh_hours": 168,
        "agents": ["analyst", "data_lead"],
        "source": "dbt blog, Amplitude, Mixpanel product analytics resources",
        "description": "Product analytics best practices, funnel analysis, cohort methods",
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
# DataIntelligence class
# ---------------------------------------------------------------------------


class DataIntelligence:
    """Structured intelligence system for data team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "data_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: DataIntelItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[DataIntelItem]:
        """Return all items for a given category."""
        result = []
        for raw in self._get_items():
            if raw.get("category") == category:
                result.append(DataIntelItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[DataIntelItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[DataIntelItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(DataIntelItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[DataIntelItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(DataIntelItem(**raw))
        return result

    def get_all(self) -> list[DataIntelItem]:
        """Return all intelligence items."""
        return [DataIntelItem(**raw) for raw in self._get_items()]

    def get_urgent(self) -> list[DataIntelItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(DataIntelItem(**raw))
        return result

    def get_unadopted(self) -> list[DataIntelItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(DataIntelItem(**raw))
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
        for category, meta in DATA_INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritized research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = DATA_INTEL_CATEGORIES.get(category, {})
                priority = "high"
                if category in ("marketplace_benchmarks", "job_market_data", "competitor_intel"):
                    priority = "high"
                elif category in ("privacy_regulations", "data_infrastructure"):
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
            "categories_total": len(DATA_INTEL_CATEGORIES),
            "items_by_category": by_category,
            "freshness": freshness,
        }
