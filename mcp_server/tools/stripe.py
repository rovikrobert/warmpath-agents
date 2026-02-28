"""Stripe tools — read-only payment data for finance agents."""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.server import mcp

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from finance_team.shared.stripe_client import get_stripe_client

        _client = get_stripe_client()
    return _client


def _unavailable_error() -> dict[str, str]:
    return {"error": "Stripe unavailable (STRIPE_SECRET_KEY not set)"}


@mcp.tool()
def stripe_balance() -> dict[str, Any]:
    """Get current Stripe account balance (available + pending)."""
    client = _get_client()
    if not client.is_available():
        return _unavailable_error()
    result = client.get_balance()
    return result or {"error": "Stripe API call failed"}


@mcp.tool()
def stripe_subscriptions(status: str = "active") -> dict[str, Any]:
    """List Stripe subscriptions by status (default: active)."""
    client = _get_client()
    if not client.is_available():
        return _unavailable_error()
    result = client.list_subscriptions(status=status)
    return result or {"error": "Stripe API call failed"}


@mcp.tool()
def stripe_charges(limit: int = 25, created_after: int | None = None) -> dict[str, Any]:
    """List recent Stripe charges. Optional: limit (default 25), created_after (unix timestamp)."""
    client = _get_client()
    if not client.is_available():
        return _unavailable_error()
    result = client.list_charges(limit=limit, created_after=created_after)
    return result or {"error": "Stripe API call failed"}


@mcp.tool()
def stripe_disputes() -> dict[str, Any]:
    """List open Stripe disputes."""
    client = _get_client()
    if not client.is_available():
        return _unavailable_error()
    result = client.list_disputes()
    return result or {"error": "Stripe API call failed"}
