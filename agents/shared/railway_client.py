"""Railway production environment client for agent scans.

Provides:
- get_railway_variables(): Fetch all env vars from Railway CLI
- get_production_config(): Structured config status (set/unset, no secrets)
- ConfigStatus dataclass with per-variable status

Used by Marsh (ops agent) to give CoS real production state awareness.
Requires: Railway CLI installed and linked (`railway link`).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Variables to check and their risk context
CRITICAL_VARS = {
    "RESEND_API_KEY": "Email delivery (verification, welcome, password reset)",
    "FRONTEND_URL": "Email link targets + CORS",
    "SECRET_KEY": "JWT signing (must not be default)",
    "ENCRYPTION_KEY": "PII encryption at rest",
    "DATABASE_URL": "PostgreSQL connection",
}

FEATURE_VARS = {
    "AI_MOCK_MODE": "AI features (true=mock heuristics, false=real Claude)",
    "ANTHROPIC_API_KEY": "Claude API for Keevs, matching, intro drafting",
    "STRIPE_WEBHOOK_SECRET": "Credit purchasing via Stripe",
    "LINKEDIN_CLIENT_ID": "LinkedIn OAuth login/signup",
    "LINKEDIN_CLIENT_SECRET": "LinkedIn OAuth login/signup",
    "RESEND_WEBHOOK_SECRET": "Email open/click tracking",
    "TWILIO_ACCOUNT_SID": "WhatsApp error alerts to founder",
}

INFRA_VARS = {
    "REDIS_URL": "Celery task queue + caching",
    "CORS_ORIGINS": "Allowed frontend origins",
    "SECURE_HEADERS": "Security headers (HSTS, CSP, etc.)",
    "SECURE_COOKIES": "HttpOnly + SameSite cookies",
    "VITE_BETA_MODE": "Beta feedback overlay for users",
}

# Cache to avoid repeated CLI calls during a single scan
_cache: dict[str, dict] = {}
_CACHE_FILE = Path(__file__).parent / ".web_cache" / "railway_vars.json"


@dataclass
class VarStatus:
    name: str
    is_set: bool
    category: str  # critical, feature, infra
    description: str
    value_hint: str = ""  # e.g. "true", "https://...", never full secrets


@dataclass
class ConfigStatus:
    reachable: bool
    variables: list[VarStatus] = field(default_factory=list)
    error: str = ""

    @property
    def critical_missing(self) -> list[VarStatus]:
        return [v for v in self.variables if v.category == "critical" and not v.is_set]

    @property
    def features_disabled(self) -> list[VarStatus]:
        return [v for v in self.variables if v.category == "feature" and not v.is_set]

    @property
    def all_critical_set(self) -> bool:
        return len(self.critical_missing) == 0

    def summary(self) -> str:
        """One-line summary for CoS briefs."""
        total = len(self.variables)
        set_count = sum(1 for v in self.variables if v.is_set)
        if not self.reachable:
            return f"Railway CLI unreachable: {self.error}"
        if self.all_critical_set:
            return f"Production config: {set_count}/{total} vars set, all critical OK"
        missing = ", ".join(v.name for v in self.critical_missing)
        return f"Production config: {set_count}/{total} vars set, MISSING CRITICAL: {missing}"


def _safe_hint(name: str, value: str) -> str:
    """Return a safe hint for the value — never expose full secrets."""
    if not value:
        return ""
    # Boolean-like values are safe to show
    if value.lower() in ("true", "false"):
        return value.lower()
    # URLs are safe (no secrets in them typically)
    if value.startswith("http://") or value.startswith("https://"):
        return value
    # Email-like FROM_EMAIL is safe
    if "@" in value and name == "FROM_EMAIL":
        return value
    # For secrets, show just that it's set
    if len(value) > 8:
        return f"{value[:4]}...({len(value)} chars)"
    return "***"


def get_railway_variables() -> dict[str, str] | None:
    """Fetch all env vars from Railway CLI.

    Returns dict of var_name -> value, or None if CLI is unavailable.
    Caches result for the duration of a scan.
    """
    if "vars" in _cache:
        return _cache["vars"]

    try:
        result = subprocess.run(
            ["railway", "variables", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            # --json flag may not exist in older CLI versions, try parsing text
            return _parse_text_output()

        data = json.loads(result.stdout)
        _cache["vars"] = data
        return data
    except FileNotFoundError:
        logger.warning("Railway CLI not found — install with `npm i -g @railway/cli`")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Railway CLI timed out")
        return None
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Railway variables fetch failed: %s", exc)
        return _parse_text_output()


def _parse_text_output() -> dict[str, str] | None:
    """Fallback: parse `railway variables` text output."""
    try:
        result = subprocess.run(
            ["railway", "variables"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("Railway CLI failed: %s", result.stderr.strip())
            return None

        variables: dict[str, str] = {}
        for line in result.stdout.splitlines():
            # Railway output format: ║ KEY │ VALUE ║
            line = line.strip().strip("║").strip()
            if "│" in line:
                parts = line.split("│", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if key and not key.startswith("─"):
                        variables[key] = val

        _cache["vars"] = variables
        return variables
    except Exception as exc:
        logger.warning("Railway text parse failed: %s", exc)
        return None


def get_production_config() -> ConfigStatus:
    """Get structured production config status.

    Returns ConfigStatus with per-variable status and safe hints.
    Never exposes full secret values.
    """
    raw = get_railway_variables()
    if raw is None:
        return ConfigStatus(
            reachable=False,
            error="Railway CLI unavailable or not linked to project",
        )

    variables: list[VarStatus] = []

    for name, desc in CRITICAL_VARS.items():
        val = raw.get(name, "")
        variables.append(VarStatus(
            name=name,
            is_set=bool(val),
            category="critical",
            description=desc,
            value_hint=_safe_hint(name, val),
        ))

    for name, desc in FEATURE_VARS.items():
        val = raw.get(name, "")
        variables.append(VarStatus(
            name=name,
            is_set=bool(val),
            category="feature",
            description=desc,
            value_hint=_safe_hint(name, val),
        ))

    for name, desc in INFRA_VARS.items():
        val = raw.get(name, "")
        variables.append(VarStatus(
            name=name,
            is_set=bool(val),
            category="infra",
            description=desc,
            value_hint=_safe_hint(name, val),
        ))

    return ConfigStatus(reachable=True, variables=variables)


def clear_cache() -> None:
    """Clear the in-memory cache (call between scans if needed)."""
    _cache.clear()
