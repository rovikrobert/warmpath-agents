"""PyPI API client for dependency version and vulnerability checking.

Provides:
- get_latest_version(package): Get latest version info from PyPI JSON API
- check_package_updates(requirements_path): Check all pinned packages for updates

Uses httpx (already a production dependency). Results are cached via web_tools.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from agents.shared.config import PROJECT_ROOT
from agents.shared.web_tools import _cache_key, _read_cache, _write_cache

logger = logging.getLogger(__name__)

PYPI_API = "https://pypi.org/pypi"
REQUEST_TIMEOUT = 10


@dataclass
class PackageUpdate:
    name: str
    current: str
    latest: str
    is_major: bool
    summary: str


def get_latest_version(package: str) -> dict | None:
    """Get latest version info from PyPI.

    Returns dict with: name, version, summary, home_page, license, requires_python.
    Returns None if package not found or network error.
    """
    cache_key = _cache_key("pypi", package)
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(f"{PYPI_API}/{package}/json")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

        data = resp.json()
        info = data.get("info", {})
        result = {
            "name": info.get("name", package),
            "version": info.get("version", ""),
            "summary": info.get("summary", ""),
            "home_page": info.get("home_page", ""),
            "license": info.get("license", ""),
            "requires_python": info.get("requires_python", ""),
        }
        _write_cache(cache_key, result)
        return result
    except Exception as exc:
        logger.warning("PyPI lookup failed for '%s': %s", package, exc)
        return None


def check_package_updates(
    requirements_path: Path | None = None,
) -> list[PackageUpdate]:
    """Check all pinned packages in requirements.txt for available updates.

    Returns list of PackageUpdate for packages where PyPI has a newer version.
    """
    if requirements_path is None:
        requirements_path = PROJECT_ROOT / "requirements.txt"

    if not requirements_path.exists():
        return []

    updates: list[PackageUpdate] = []
    lines = requirements_path.read_text().splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Parse "package==version" or "package>=version"
        match = re.match(
            r"^([a-zA-Z0-9_.-]+(?:\[[^\]]+\])?)\s*[=<>!~]+\s*([0-9][0-9a-zA-Z.*-]*)",
            line,
        )
        if not match:
            continue

        name = match.group(1)
        current = match.group(2)
        # Strip extras for PyPI lookup
        base_name = re.sub(r"\[.*\]", "", name)

        info = get_latest_version(base_name)
        if not info or not info.get("version"):
            continue

        latest = info["version"]
        if latest != current:
            current_major = current.split(".")[0] if "." in current else current
            latest_major = latest.split(".")[0] if "." in latest else latest
            is_major = current_major != latest_major

            updates.append(
                PackageUpdate(
                    name=base_name,
                    current=current,
                    latest=latest,
                    is_major=is_major,
                    summary=info.get("summary", ""),
                )
            )

    return updates
