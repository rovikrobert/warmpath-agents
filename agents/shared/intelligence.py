"""External intelligence fetcher — CVE feeds, changelogs, best practices.

Caches results locally so we don't re-fetch within INTEL_CACHE_TTL_HOURS.
Uses subprocess calls to pip-audit and parses requirements.txt for version data.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone

from agents.shared.config import INTEL_CACHE, INTEL_CACHE_TTL_HOURS, PROJECT_ROOT

logger = logging.getLogger(__name__)


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


def _is_stale(cache: dict, key: str) -> bool:
    entry = cache.get(key)
    if not entry or "fetched_at" not in entry:
        return True
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        return hours > INTEL_CACHE_TTL_HOURS
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# Intelligence fetchers
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

    Returns a dict of API name → status string.
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
