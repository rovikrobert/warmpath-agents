"""Monitor agent — continuous production health checking.

Checks app health endpoint, worker queue depth, and Sentry errors.
Has a calibration mode (first 2 weeks: observe only, no actions).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MonitorConfig:
    """Configuration for the monitor agent."""

    health_url: str = "https://web-production-b3a4a.up.railway.app/health"
    health_check_interval_seconds: int = 300
    consecutive_failures_to_alert: int = 2
    error_rate_threshold: float = 0.05
    queue_depth_threshold: int = 100
    calibration_mode: bool = True
    sentry_org: str = ""
    sentry_project: str = ""
    sentry_auth_token: str = ""


@dataclass
class HealthStatus:
    """Result of a single health check."""

    healthy: bool
    source: str = ""
    detail: str = ""
    response_time_ms: float = 0.0
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MonitorReport:
    """Aggregated report across all health checks."""

    checks: list[HealthStatus] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_healthy(self) -> bool:
        if not self.checks:
            return True
        return all(c.healthy for c in self.checks)

    def add_check(self, status: HealthStatus) -> None:
        self.checks.append(status)

    def summary(self) -> str:
        total = len(self.checks)
        unhealthy = [c for c in self.checks if not c.healthy]
        if not unhealthy:
            return f"All {total} checks healthy"
        details = "; ".join(f"{c.source}: {c.detail}" for c in unhealthy)
        return f"{len(unhealthy)}/{total} unhealthy — {details}"


# ---------------------------------------------------------------------------
# Health check functions
# ---------------------------------------------------------------------------


def check_app_health(url: str, timeout: float = 10.0) -> HealthStatus:
    """HTTP GET the health endpoint and return status."""
    try:
        resp = httpx.get(url, timeout=timeout)
        response_time_ms = resp.elapsed.total_seconds() * 1000
        healthy = resp.status_code == 200
        detail = "" if healthy else f"HTTP {resp.status_code}"
        return HealthStatus(
            healthy=healthy,
            source="app",
            detail=detail,
            response_time_ms=response_time_ms,
        )
    except (ConnectionError, httpx.ConnectError, httpx.TimeoutException, OSError) as e:
        return HealthStatus(
            healthy=False,
            source="app",
            detail=f"Connection failed: {e}",
        )


def check_worker_health(
    redis_client,
    threshold: int = 100,
    queue_name: str = "celery",
) -> HealthStatus:
    """Check Celery worker queue depth via Redis LLEN."""
    try:
        depth = redis_client.llen(queue_name)
        healthy = depth <= threshold
        detail = "" if healthy else f"Queue depth {depth} exceeds threshold {threshold}"
        return HealthStatus(
            healthy=healthy,
            source="worker",
            detail=detail,
        )
    except Exception as e:
        return HealthStatus(
            healthy=False,
            source="worker",
            detail=f"Redis check failed: {e}",
        )


def check_sentry_errors(
    org: str = "",
    project: str = "",
    auth_token: str = "",
    threshold: float = 0.05,
) -> Optional[HealthStatus]:
    """Poll Sentry for recent error rate. Returns None if Sentry is not configured."""
    org = org or os.getenv("SENTRY_ORG", "")
    project = project or os.getenv("SENTRY_PROJECT", "")
    auth_token = auth_token or os.getenv("SENTRY_AUTH_TOKEN", "")

    if not all([org, project, auth_token]):
        logger.debug("Sentry not configured — skipping error rate check")
        return None

    try:
        url = f"https://sentry.io/api/0/projects/{org}/{project}/stats/"
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = httpx.get(
            url,
            headers=headers,
            timeout=10.0,
            params={"stat": "received", "resolution": "1h"},
        )
        if resp.status_code != 200:
            return HealthStatus(
                healthy=False,
                source="sentry",
                detail=f"Sentry API returned HTTP {resp.status_code}",
            )

        # Sentry stats endpoint returns list of [timestamp, count] pairs.
        # We check if the latest hour's count is abnormally high.
        data = resp.json()
        if data and len(data) >= 2:
            latest = data[-1][1]
            previous = data[-2][1]
            if previous > 0 and latest / previous > (1 + threshold):
                return HealthStatus(
                    healthy=False,
                    source="sentry",
                    detail=f"Error spike: {latest} vs {previous} previous hour",
                )

        return HealthStatus(healthy=True, source="sentry")
    except Exception as e:
        return HealthStatus(
            healthy=False,
            source="sentry",
            detail=f"Sentry check failed: {e}",
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_health_checks(config: Optional[MonitorConfig] = None) -> MonitorReport:
    """Run all configured health checks and return an aggregated report.

    In calibration mode, the report is generated but no alerts are triggered.
    """
    if config is None:
        config = MonitorConfig()

    report = MonitorReport()

    # 1. App health
    app_status = check_app_health(config.health_url)
    report.add_check(app_status)

    # 2. Worker health (only if Redis is reachable)
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis

            r = redis.from_url(redis_url)
            worker_status = check_worker_health(
                r, threshold=config.queue_depth_threshold
            )
            report.add_check(worker_status)
        except Exception as e:
            report.add_check(
                HealthStatus(
                    healthy=False, source="worker", detail=f"Redis connect failed: {e}"
                )
            )

    # 3. Sentry errors (graceful skip when not configured)
    sentry_status = check_sentry_errors(
        org=config.sentry_org,
        project=config.sentry_project,
        auth_token=config.sentry_auth_token,
        threshold=config.error_rate_threshold,
    )
    if sentry_status is not None:
        report.add_check(sentry_status)

    # Log results
    if config.calibration_mode:
        logger.info("[CALIBRATION] Monitor report: %s", report.summary())
    else:
        if not report.all_healthy:
            logger.warning("Monitor ALERT: %s", report.summary())
        else:
            logger.info("Monitor OK: %s", report.summary())

    return report
