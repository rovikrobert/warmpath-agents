"""Read-only Stripe API client for finance agents.

Uses httpx (already a dependency) to call Stripe REST API directly.
No ``stripe`` pip package needed. All methods are read-only — agents
never create charges, customers, or mutations.

Gracefully degrades when STRIPE_SECRET_KEY is not set.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_STRIPE_BASE = "https://api.stripe.com/v1"


class StripeClient:
    """Read-only Stripe API client."""

    def __init__(self) -> None:
        self._api_key: str | None = os.environ.get("STRIPE_SECRET_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict | None:
        """GET request to Stripe API. Returns parsed JSON or None on failure."""
        if not self._api_key:
            return None

        try:
            import httpx

            resp = httpx.get(
                f"{_STRIPE_BASE}{path}",
                params=params or {},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Stripe API error (%s): %s", path, exc)
            return None

    def get_balance(self) -> dict | None:
        """Get current Stripe account balance."""
        return self._get("/balance")

    def list_charges(
        self, limit: int = 25, created_after: int | None = None
    ) -> dict | None:
        """List recent charges."""
        params: dict[str, Any] = {"limit": limit}
        if created_after:
            params["created[gte]"] = created_after
        return self._get("/charges", params)

    def list_subscriptions(self, status: str = "active") -> dict | None:
        """List subscriptions by status."""
        return self._get("/subscriptions", {"status": status, "limit": 25})

    def list_disputes(self) -> dict | None:
        """List open disputes."""
        return self._get("/disputes", {"limit": 25})

    def get_customer(self, customer_id: str) -> dict | None:
        """Get a single customer by ID."""
        if not customer_id:
            return None
        return self._get(f"/customers/{customer_id}")


_client: StripeClient | None = None


def get_stripe_client() -> StripeClient:
    """Return module-level StripeClient singleton."""
    global _client
    if _client is None:
        _client = StripeClient()
    return _client
