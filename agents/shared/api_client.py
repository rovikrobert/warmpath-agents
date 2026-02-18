"""Internal WarmPath API client for agents that need live production data.

Provides:
- check_health(): Hit /health endpoint, return status + response time
- get_api_response(path, token): GET any API endpoint with optional auth

Used by Marsh (marketplace health) and other agents that need production data.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://web-production-b3a4a.up.railway.app"
REQUEST_TIMEOUT = 10


@dataclass
class HealthStatus:
    healthy: bool
    status_code: int
    response_ms: float


def _get_base_url() -> str:
    """Get base URL from env or default to Railway production."""
    return os.environ.get("WARMPATH_API_URL", _DEFAULT_BASE_URL)


def check_health() -> HealthStatus:
    """Hit /health endpoint and return status.

    Returns HealthStatus with healthy=False on any error.
    """
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(f"{_get_base_url()}/health")
            return HealthStatus(
                healthy=resp.status_code == 200,
                status_code=resp.status_code,
                response_ms=resp.elapsed.total_seconds() * 1000,
            )
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        return HealthStatus(healthy=False, status_code=0, response_ms=0)


def get_api_response(path: str, token: str | None = None) -> dict | None:
    """GET an API endpoint with optional bearer token auth.

    Returns parsed JSON on success, None on error.
    """
    try:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(f"{_get_base_url()}{path}", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("API %s returned %d", path, resp.status_code)
            return None
    except Exception as exc:
        logger.warning("API request failed for '%s': %s", path, exc)
        return None
