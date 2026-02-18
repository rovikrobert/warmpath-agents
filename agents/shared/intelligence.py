"""External intelligence fetcher — CVE feeds, changelogs, best practices.

Provides both the new `ExternalIntelligence` class and the original
module-level functions used by orchestrator.py.

Caches results locally so we don't re-fetch within INTEL_CACHE_TTL_HOURS.
Uses subprocess calls to pip-audit and parses requirements.txt for version data.
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.shared.config import (
    AGENT_NAMES,
    INTEL_CACHE,
    INTEL_CACHE_TTL_HOURS,
    PROJECT_ROOT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class IntelligenceItem:
    """A single piece of external intelligence."""

    id: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    source_url: str = ""
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
# Intelligence categories (13)
# ---------------------------------------------------------------------------

INTEL_CATEGORIES: dict[str, dict[str, Any]] = {
    "python_advisories": {
        "refresh_hours": 24,
        "agents": ["deps_manager", "security"],
        "source": "pip-audit against requirements.txt",
        "description": "Python package security advisories (CVEs)",
    },
    "dependency_versions": {
        "refresh_hours": 48,
        "agents": ["deps_manager"],
        "source": "pip show for installed packages",
        "description": "Installed vs latest package versions",
    },
    "api_status": {
        "refresh_hours": 12,
        "agents": ["architect", "deps_manager"],
        "source": "External API status pages",
        "description": "Health of APIs we depend on (Anthropic, Stripe, etc.)",
    },
    "framework_updates": {
        "refresh_hours": 48,
        "agents": ["architect", "deps_manager"],
        "source": "GitHub releases for FastAPI, SQLAlchemy, Pydantic, etc.",
        "description": "Major framework version updates and changelogs",
    },
    "security_best_practices": {
        "refresh_hours": 168,
        "agents": ["security", "privy"],
        "source": "OWASP, CWE feeds",
        "description": "Security best practices and common vulnerability patterns",
    },
    "python_ecosystem": {
        "refresh_hours": 168,
        "agents": ["architect", "deps_manager"],
        "source": "Python.org, PEP tracker",
        "description": "Python language updates, new PEPs, deprecations",
    },
    "testing_patterns": {
        "refresh_hours": 168,
        "agents": ["test_engineer"],
        "source": "pytest releases, testing blogs",
        "description": "New testing tools, patterns, and best practices",
    },
    "performance_patterns": {
        "refresh_hours": 168,
        "agents": ["perf_monitor"],
        "source": "Database and async performance research",
        "description": "SQLAlchemy, asyncio, and query optimization insights",
    },
    "privacy_regulations": {
        "refresh_hours": 336,
        "agents": ["privy"],
        "source": "GDPR, CCPA, PDPA regulatory updates",
        "description": "Data privacy regulation changes and guidance",
    },
    "docker_security": {
        "refresh_hours": 168,
        "agents": ["security", "deps_manager"],
        "source": "Docker Hub advisories, base image updates",
        "description": "Container security updates and base image patches",
    },
    "ai_sdk_updates": {
        "refresh_hours": 48,
        "agents": ["architect", "perf_monitor"],
        "source": "Anthropic SDK changelog",
        "description": "Claude API and SDK version updates",
    },
    "documentation_standards": {
        "refresh_hours": 336,
        "agents": ["doc_keeper"],
        "source": "OpenAPI spec updates, documentation tools",
        "description": "API documentation standards and tooling updates",
    },
    "infrastructure": {
        "refresh_hours": 168,
        "agents": ["architect", "security"],
        "source": "Railway, Redis, PostgreSQL release notes",
        "description": "Infrastructure platform updates and patches",
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
# ExternalIntelligence class
# ---------------------------------------------------------------------------


class ExternalIntelligence:
    """Structured intelligence system with per-agent filtering."""

    def __init__(self):
        self.cache = _load_cache()
        self._items_key = "intel_items"
        if self._items_key not in self.cache:
            self.cache[self._items_key] = []

    def _save(self) -> None:
        _save_cache(self.cache)

    def _get_items(self) -> list[dict]:
        return self.cache.get(self._items_key, [])

    def _set_items(self, items: list[dict]) -> None:
        self.cache[self._items_key] = items

    def add_item(self, item: IntelligenceItem) -> None:
        """Add an intelligence item to the store."""
        items = self._get_items()
        items.append(asdict(item))
        # Keep last 200 items
        self.cache[self._items_key] = items[-200:]
        self._save()

    def fetch_category(self, category: str) -> list[IntelligenceItem]:
        """Return all items for a given category."""
        items = self._get_items()
        result = []
        for raw in items:
            if raw.get("category") == category:
                result.append(IntelligenceItem(**raw))
        return result

    def fetch_all(self) -> dict[str, list[IntelligenceItem]]:
        """Return all items grouped by category."""
        result: dict[str, list[IntelligenceItem]] = {}
        for raw in self._get_items():
            cat = raw.get("category", "uncategorized")
            if cat not in result:
                result[cat] = []
            result[cat].append(IntelligenceItem(**raw))
        return result

    def get_for_agent(self, agent_name: str) -> list[IntelligenceItem]:
        """Return items relevant to a specific agent."""
        result = []
        for raw in self._get_items():
            agents = raw.get("relevant_agents", [])
            if agent_name in agents:
                result.append(IntelligenceItem(**raw))
        return result

    def get_urgent(self) -> list[IntelligenceItem]:
        """Return items with critical or high severity."""
        result = []
        for raw in self._get_items():
            if raw.get("severity") in ("critical", "high"):
                result.append(IntelligenceItem(**raw))
        return result

    def get_unadopted(self) -> list[IntelligenceItem]:
        """Return items that haven't been adopted yet."""
        result = []
        for raw in self._get_items():
            if not raw.get("adopted"):
                result.append(IntelligenceItem(**raw))
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
        for category, meta in INTEL_CATEGORIES.items():
            ttl = meta.get("refresh_hours", INTEL_CACHE_TTL_HOURS)
            result[category] = not _is_stale(self.cache, category, ttl)
        return result

    def generate_research_agenda(self) -> list[dict]:
        """Generate prioritized research questions based on stale/missing intel."""
        agenda = []
        freshness = self.check_freshness()

        for category, is_fresh in freshness.items():
            if not is_fresh:
                meta = INTEL_CATEGORIES.get(category, {})
                agenda.append(
                    {
                        "category": category,
                        "question": f"What are the latest updates for: {meta.get('description', category)}?",
                        "source": meta.get("source", "unknown"),
                        "relevant_agents": meta.get("agents", []),
                        "priority": "high"
                        if category in ("python_advisories", "api_status")
                        else "medium",
                    }
                )

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        agenda.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
        return agenda


# ---------------------------------------------------------------------------
# Original intelligence fetchers (unchanged for backward compat)
# ---------------------------------------------------------------------------


def fetch_python_advisories() -> list[dict]:
    """Run pip-audit against our requirements and return advisory list."""
    cache = _load_cache()
    if not _is_stale(cache, "python_advisories"):
        return cache["python_advisories"].get("data", [])

    advisories: list[dict] = []
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        return advisories

    try:
        result = subprocess.run(
            ["pip-audit", "-r", str(req_file), "--format=json", "--desc"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            for dep in data.get("dependencies", []):
                for vuln in dep.get("vulns", []):
                    advisories.append(
                        {
                            "package": dep.get("name"),
                            "installed": dep.get("version"),
                            "advisory_id": vuln.get("id"),
                            "description": vuln.get("description", "")[:200],
                            "fix_versions": vuln.get("fix_versions", []),
                        }
                    )
    except FileNotFoundError:
        logger.info("pip-audit not installed — skipping advisory check")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.warning("pip-audit failed: %s", e)

    cache["python_advisories"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": advisories,
    }
    _save_cache(cache)
    return advisories


def fetch_dependency_versions() -> dict[str, dict]:
    """Check installed vs. latest versions using pip index."""
    cache = _load_cache()
    if not _is_stale(cache, "dep_versions"):
        return cache["dep_versions"].get("data", {})

    versions: dict[str, dict] = {}
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        return versions

    # Parse requirements.txt for package names
    packages: list[str] = []
    for line in req_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract package name (before any version specifier)
        name = line.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip()
        if name:
            packages.append(name)

    # Check each package
    for pkg in packages:
        try:
            result = subprocess.run(
                ["pip", "show", pkg],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                info: dict[str, str] = {}
                for line in result.stdout.splitlines():
                    if ": " in line:
                        key, val = line.split(": ", 1)
                        info[key.strip().lower()] = val.strip()
                versions[pkg] = {
                    "installed": info.get("version", "unknown"),
                    "location": info.get("location", ""),
                }
        except (subprocess.TimeoutExpired, Exception):
            continue

    cache["dep_versions"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": versions,
    }
    _save_cache(cache)
    return versions


def fetch_api_status() -> dict[str, str]:
    """Quick health check summaries for external APIs we depend on.

    Returns a dict of API name -> status string.
    Since we can't make arbitrary HTTP calls in all environments,
    this returns a template that the agent prompt can expand on.
    """
    cache = _load_cache()
    if not _is_stale(cache, "api_status"):
        return cache["api_status"].get("data", {})

    # Static intelligence — agents will augment with web search when running in Claude Code
    status = {
        "anthropic": "Check https://status.anthropic.com and SDK changelog",
        "stripe": "Check https://stripe.com/docs/upgrades for API version deprecations",
        "greenhouse": "Check https://developers.greenhouse.io/harvest.html for API changes",
        "lever": "Check https://hire.lever.co/developer/documentation for API changes",
    }

    cache["api_status"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": status,
    }
    _save_cache(cache)
    return status


def fetch_framework_updates() -> list[str]:
    """Return notable framework updates to be aware of."""
    cache = _load_cache()
    if not _is_stale(cache, "framework_updates"):
        return cache["framework_updates"].get("data", [])

    updates = [
        "Check FastAPI releases: https://github.com/tiangolo/fastapi/releases",
        "Check SQLAlchemy releases: https://docs.sqlalchemy.org/en/20/changelog/",
        "Check Pydantic releases: https://github.com/pydantic/pydantic/releases",
        "Check anthropic SDK releases: https://github.com/anthropics/anthropic-sdk-python/releases",
    ]

    cache["framework_updates"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": updates,
    }
    _save_cache(cache)
    return updates


def get_all_intelligence() -> dict:
    """Fetch all intelligence sources, return combined dict."""
    return {
        "advisories": fetch_python_advisories(),
        "dep_versions": fetch_dependency_versions(),
        "api_status": fetch_api_status(),
        "framework_updates": fetch_framework_updates(),
    }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def get_agent_intel(agent_name: str) -> list[IntelligenceItem]:
    """Return intelligence items relevant to the given agent."""
    ei = ExternalIntelligence()
    return ei.get_for_agent(agent_name)
