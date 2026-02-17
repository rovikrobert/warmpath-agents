"""External intelligence for data team — marketplace benchmarks, ML research, job market data."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from data_team.shared.config import INTEL_CACHE

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
    severity: str = "info"
    relevant_agents: list[str] = field(default_factory=list)
    fetched_at: str = ""
    adopted: bool = False

    def __post_init__(self):
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Intelligence categories (5 data-specific)
# ---------------------------------------------------------------------------

DATA_INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    "marketplace_benchmarks": {
        "refresh_hours": 168,
        "agents": ["analyst", "data_lead"],
        "description": "Two-sided marketplace KPI benchmarks (Uber, Airbnb, LinkedIn)",
    },
    "job_market_data": {
        "refresh_hours": 168,
        "agents": ["analyst", "model_engineer"],
        "description": "Job market trends, referral conversion rates, hiring velocity",
    },
    "ml_research": {
        "refresh_hours": 336,
        "agents": ["model_engineer"],
        "description": "Recommendation systems, NLP for matching, warm score ML approaches",
    },
    "competitor_intel": {
        "refresh_hours": 168,
        "agents": ["data_lead", "analyst"],
        "description": "Competitor analytics approaches (Blind, Lunchclub, Teamable)",
    },
    "privacy_regulations": {
        "refresh_hours": 336,
        "agents": ["pipeline", "data_lead"],
        "description": "GDPR/CCPA/PDPA analytics compliance, differential privacy",
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


# ---------------------------------------------------------------------------
# DataIntelligence class
# ---------------------------------------------------------------------------


class DataIntelligence:
    """Intelligence system for data team agents."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._items_key = "data_intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def add_item(self, item: DataIntelItem) -> None:
        items = self._get_items()
        items.append(asdict(item))
        self.cache[self._items_key] = items[-100:]
        self._save()

    def get_for_agent(self, agent_name: str) -> list[DataIntelItem]:
        result = []
        for raw in self._get_items():
            if agent_name in raw.get("relevant_agents", []):
                result.append(DataIntelItem(**raw))
        return result

    def get_all(self) -> list[DataIntelItem]:
        return [DataIntelItem(**raw) for raw in self._get_items()]

    def check_freshness(self) -> dict[str, bool]:
        result = {}
        for category, meta in DATA_INTEL_CATEGORIES.items():
            entry = self.cache.get(category)
            if not entry or "fetched_at" not in entry:
                result[category] = False
                continue
            try:
                fetched = datetime.fromisoformat(entry["fetched_at"])
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=timezone.utc)
                hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
                result[category] = hours <= meta.get("refresh_hours", 168)
            except (ValueError, TypeError):
                result[category] = False
        return result

    def generate_research_agenda(self) -> list[dict]:
        agenda = []
        freshness = self.check_freshness()
        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = DATA_INTEL_CATEGORIES.get(category, {})
                agenda.append({
                    "category": category,
                    "question": f"What are the latest updates for: {meta.get('description', category)}?",
                    "relevant_agents": meta.get("agents", []),
                    "priority": "high" if category == "marketplace_benchmarks" else "medium",
                })
        agenda.sort(key=lambda x: 0 if x.get("priority") == "high" else 1)
        return agenda
