"""Naiv agent — Customer Satisfaction Auditor.

Scans API endpoints, frontend pages, and middleware for signals that
affect customer satisfaction: error message quality, feedback collection
coverage, journey milestone celebrations, usage tracking completeness,
and empty state handling.

Produces an OpsTeamReport with satisfaction findings and metrics.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from agents.shared.report import Finding
from ops_team.shared.config import API_DIR, MIDDLEWARE_DIR, PAGES_DIR
from ops_team.shared.learning import OpsLearningState
from ops_team.shared.report import OpsTeamReport, SatisfactionFinding

logger = logging.getLogger(__name__)

AGENT_NAME = "naiv"

# ---------------------------------------------------------------------------
# Regex patterns used across checks
# ---------------------------------------------------------------------------

# Error handling patterns in Python API files
_HTTP_EXCEPTION_RE = re.compile(
    r"HTTPException\s*\(\s*status_code\s*=\s*(\d+)", re.MULTILINE
)
_RAISE_RE = re.compile(r"\braise\b", re.MULTILINE)
_GENERIC_500_RE = re.compile(
    r"(Internal\s+Server\s+Error|status_code\s*=\s*500)", re.IGNORECASE
)
_CUSTOM_ERROR_MSG_RE = re.compile(
    r"HTTPException\s*\([^)]*detail\s*=\s*[\"']", re.MULTILINE
)
_APP_ERROR_RE = re.compile(
    r"\b(AppError|NotFoundError|RateLimitError|ValidationError|AuthError)\b"
)

# Feedback-related patterns in JSX
_FEEDBACK_PATTERNS = re.compile(
    r"\b(rating|feedback|survey|nps|satisfaction|thumbs|review|poll|star[sS]core"
    r"|FeedbackForm|FeedbackModal|SurveyWidget|NpsPrompt)\b",
    re.IGNORECASE,
)

# Journey milestone / celebration patterns in JSX
_MILESTONE_PATTERNS = re.compile(
    r"\b(congratulat|success|welcome|milestone|achievement|complete[d]?"
    r"|well\s*done|great\s*job|toast|notification|celebrate|first.?upload"
    r"|first.?search|onboard)\b",
    re.IGNORECASE,
)

# Empty state patterns in JSX
_EMPTY_STATE_PATTERNS = re.compile(
    r"(no\s+results|no\s+contacts|get\s+started|empty|nothing\s+here"
    r"|no\s+data|no\s+items|you\s+haven.t|EmptyState|emptyState|empty-state"
    r"|no\s+applications|no\s+searches|no\s+credits|no\s+requests)",
    re.IGNORECASE,
)

# Usage tracking patterns
_USAGE_LOG_RE = re.compile(r"\bUsageLog\b")
_TRACKED_ACTION_RE = re.compile(r"action\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read file contents, returning empty string on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("Could not read file: %s", path)
        return ""


def _relative(path: Path) -> str:
    """Return a project-relative path string for reports."""
    try:
        root = API_DIR.parent.parent  # warmpath/
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _find_api_files() -> list[Path]:
    """Glob app/api/*.py, excluding __init__.py."""
    if not API_DIR.exists():
        logger.warning("API directory not found: %s", API_DIR)
        return []
    return sorted(p for p in API_DIR.glob("*.py") if p.name != "__init__.py")


def _find_jsx_files() -> list[Path]:
    """Glob frontend/src/pages/*.jsx and *.tsx.

    Returns an empty list when the frontend source directory is not available
    (e.g. backend-only Docker image on Railway).  Callers should treat an
    empty list from a missing directory differently from zero matches in an
    existing directory.
    """
    if not PAGES_DIR.exists():
        logger.warning(
            "Pages directory not found: %s — frontend source may not be present",
            PAGES_DIR,
        )
        return []
    return sorted([*PAGES_DIR.glob("*.jsx"), *PAGES_DIR.glob("*.tsx")])


# ---------------------------------------------------------------------------
# Check 1: Error Message Quality
# ---------------------------------------------------------------------------


def _check_error_message_quality(
    api_files: list[Path],
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Audit API files for user-friendly error handling."""
    files_with_custom_errors = 0
    files_with_generic_errors = 0
    total_endpoints = len(api_files)
    files_with_bare_500 = 0

    for path in api_files:
        source = _read_safe(path)
        if not source:
            continue

        rel = _relative(path)
        has_custom = bool(_CUSTOM_ERROR_MSG_RE.search(source)) or bool(
            _APP_ERROR_RE.search(source)
        )
        has_generic_500 = bool(_GENERIC_500_RE.search(source))
        has_any_raise = bool(_RAISE_RE.search(source))

        if has_custom:
            files_with_custom_errors += 1

        if has_generic_500:
            files_with_bare_500 += 1
            # Find the line number of the first occurrence
            line_num = 0
            for i, line in enumerate(source.split("\n"), 1):
                if _GENERIC_500_RE.search(line):
                    line_num = i
                    break

            finding_id = f"NAIV-ERR-500-{path.stem.upper()}"
            findings.append(
                Finding(
                    id=finding_id,
                    severity="medium",
                    category="error_quality",
                    title=f"Generic 500 error in {path.stem}.py",
                    detail=(
                        f"{rel} contains a generic 500/Internal Server Error response. "
                        "Users seeing this have no idea what went wrong or what to do next."
                    ),
                    file=rel,
                    line=line_num,
                    recommendation=(
                        "Replace generic 500 responses with descriptive error messages. "
                        "Use the AppError hierarchy for structured error responses."
                    ),
                    effort_hours=0.5,
                )
            )
            sat_findings.append(
                SatisfactionFinding(
                    id=finding_id,
                    category="error_quality",
                    severity="medium",
                    title=f"Generic 500 error in {path.stem}.py",
                    file=rel,
                    line=line_num,
                    detail="Raw 500 errors erode user trust and provide no recovery path.",
                    persona="both",
                    recommendation="Return structured errors with user-facing messages.",
                )
            )

        if has_any_raise and not has_custom:
            files_with_generic_errors += 1
            finding_id = f"NAIV-ERR-NOCUSTOM-{path.stem.upper()}"
            findings.append(
                Finding(
                    id=finding_id,
                    severity="medium",
                    category="error_quality",
                    title=f"No custom error messages in {path.stem}.py",
                    detail=(
                        f"{rel} raises exceptions but lacks custom HTTPException "
                        "detail messages. Errors may surface as generic to users."
                    ),
                    file=rel,
                    recommendation=(
                        "Add descriptive detail= strings to HTTPException calls. "
                        "Consider using AppError subclasses for consistent messaging."
                    ),
                    effort_hours=0.5,
                )
            )

    error_coverage = (
        round(files_with_custom_errors / total_endpoints, 2)
        if total_endpoints > 0
        else 0
    )
    metrics["error_handling_files_total"] = total_endpoints
    metrics["error_handling_files_with_custom"] = files_with_custom_errors
    metrics["error_handling_files_with_generic"] = files_with_generic_errors
    metrics["error_handling_files_with_bare_500"] = files_with_bare_500
    metrics["error_handling_coverage"] = error_coverage


# ---------------------------------------------------------------------------
# Check 2: Feedback Collection Points
# ---------------------------------------------------------------------------


def _check_feedback_collection(
    jsx_files: list[Path],
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Search JSX pages for feedback collection widgets."""
    pages_with_feedback = 0
    feedback_points: list[str] = []

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue

        matches = _FEEDBACK_PATTERNS.findall(source)
        if matches:
            pages_with_feedback += 1
            feedback_points.append(f"{path.stem}: {', '.join(set(matches))}")

    total_pages = len(jsx_files)
    metrics["feedback_collection_points"] = pages_with_feedback
    metrics["feedback_pages_total"] = total_pages
    metrics["feedback_details"] = feedback_points

    if pages_with_feedback == 0 and total_pages > 0:
        # Only flag when we actually scanned pages but found nothing.
        # When total_pages == 0, frontend source is likely unavailable (e.g. Railway).
        finding_id = "NAIV-FB-NONE"
        findings.append(
            Finding(
                id=finding_id,
                severity="high",
                category="feedback_collection",
                title="No feedback collection points found in any page",
                detail=(
                    f"Scanned {total_pages} JSX pages and found zero feedback "
                    "widgets (ratings, surveys, NPS, polls). Without feedback "
                    "collection, satisfaction cannot be measured directly."
                ),
                recommendation=(
                    "Add at least one feedback mechanism: post-intro NPS prompt, "
                    "search result helpfulness rating, or onboarding satisfaction survey. "
                    "Start with a simple thumbs-up/down on search results."
                ),
                effort_hours=4.0,
            )
        )
        sat_findings.append(
            SatisfactionFinding(
                id=finding_id,
                category="feedback_collection",
                severity="high",
                title="Zero feedback collection points across all pages",
                detail=(
                    "No rating, survey, NPS, or poll widgets detected. "
                    "User satisfaction is unmeasurable without direct feedback signals."
                ),
                persona="both",
                recommendation=(
                    "Prioritize adding NPS after intro facilitation and "
                    "helpfulness rating on search results."
                ),
            )
        )
    elif total_pages == 0:
        logger.info("No frontend pages found; skipping feedback collection check")


# ---------------------------------------------------------------------------
# Check 3: Journey Milestone Celebrations
# ---------------------------------------------------------------------------


def _check_journey_milestones(
    jsx_files: list[Path],
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Search JSX for celebration/acknowledgment patterns at milestones."""
    pages_with_milestones = 0
    milestone_details: list[str] = []

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue

        matches = _MILESTONE_PATTERNS.findall(source)
        if matches:
            pages_with_milestones += 1
            unique = sorted(set(m.lower().strip() for m in matches))
            milestone_details.append(f"{path.stem}: {', '.join(unique)}")

    total_pages = len(jsx_files)
    metrics["milestone_pages_with_celebration"] = pages_with_milestones
    metrics["milestone_pages_total"] = total_pages
    metrics["milestone_details"] = milestone_details

    # Check for critical first-time milestones
    all_source = ""
    for path in jsx_files:
        all_source += _read_safe(path)

    has_first_upload = bool(
        re.search(
            r"first.?upload|upload.*success|csv.*success", all_source, re.IGNORECASE
        )
    )
    has_first_search = bool(
        re.search(
            r"first.?search|search.*complete|results.*found", all_source, re.IGNORECASE
        )
    )

    if not has_first_upload:
        finding_id = "NAIV-MS-NOUPLOAD"
        findings.append(
            Finding(
                id=finding_id,
                severity="medium",
                category="journey_milestone",
                title="No first-upload celebration detected",
                detail=(
                    "Could not find a celebration or success acknowledgment for "
                    "the first CSV upload milestone. This is a critical activation "
                    "moment for both job seekers and network holders."
                ),
                recommendation=(
                    "Add a success toast or celebration screen after first CSV upload. "
                    "Include contact count, top companies found, and next step CTA."
                ),
                effort_hours=2.0,
            )
        )
        sat_findings.append(
            SatisfactionFinding(
                id=finding_id,
                category="journey_milestone",
                severity="medium",
                title="Missing first-upload celebration",
                detail="First CSV upload is a critical activation moment without celebration.",
                persona="both",
                recommendation="Add success toast with contact count and next step.",
            )
        )

    if not has_first_search:
        finding_id = "NAIV-MS-NOSEARCH"
        findings.append(
            Finding(
                id=finding_id,
                severity="medium",
                category="journey_milestone",
                title="No first-search milestone acknowledgment detected",
                detail=(
                    "Could not find a celebration or acknowledgment for the first "
                    "search milestone. First search is the 'aha moment' for job seekers."
                ),
                recommendation=(
                    "Add a success message after first search with match count, "
                    "warm score summary, and intro request CTA."
                ),
                effort_hours=2.0,
            )
        )
        sat_findings.append(
            SatisfactionFinding(
                id=finding_id,
                category="journey_milestone",
                severity="medium",
                title="Missing first-search milestone",
                detail="First search is the aha moment for job seekers without acknowledgment.",
                persona="job_seeker",
                recommendation="Add success message with match count and intro CTA.",
            )
        )

    metrics["has_first_upload_celebration"] = has_first_upload
    metrics["has_first_search_celebration"] = has_first_search


# ---------------------------------------------------------------------------
# Check 4: Usage Tracking Coverage
# ---------------------------------------------------------------------------


def _check_usage_tracking(
    api_files: list[Path],
    middleware_source: str,
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Check for UsageLog references and tracked action coverage."""
    # Extract tracked actions from middleware
    tracked_actions = set(_TRACKED_ACTION_RE.findall(middleware_source))

    files_with_tracking = 0
    files_without_tracking = 0
    untracked_files: list[str] = []

    for path in api_files:
        source = _read_safe(path)
        if not source:
            continue

        rel = _relative(path)
        has_usage_log = bool(_USAGE_LOG_RE.search(source))
        has_action_ref = bool(_TRACKED_ACTION_RE.search(source))

        if has_usage_log or has_action_ref:
            files_with_tracking += 1
        else:
            files_without_tracking += 1
            untracked_files.append(path.stem)

            finding_id = f"NAIV-TRK-{path.stem.upper()}"
            findings.append(
                Finding(
                    id=finding_id,
                    severity="low",
                    category="usage_tracking",
                    title=f"No usage tracking in {path.stem}.py",
                    detail=(
                        f"{rel} has no UsageLog references or tracked action strings. "
                        "Endpoints in this file are invisible to satisfaction correlation."
                    ),
                    file=rel,
                    recommendation=(
                        "Add UsageLog entries for key actions in this file, or add "
                        "the relevant action strings to the usage middleware configuration."
                    ),
                    effort_hours=0.5,
                )
            )

    total = len(api_files)
    tracking_coverage = round(files_with_tracking / total, 2) if total > 0 else 0
    metrics["usage_tracking_files_with"] = files_with_tracking
    metrics["usage_tracking_files_without"] = files_without_tracking
    metrics["usage_tracking_coverage"] = tracking_coverage
    metrics["usage_tracked_actions"] = sorted(tracked_actions)
    metrics["usage_untracked_files"] = untracked_files


# ---------------------------------------------------------------------------
# Check 5: Empty State Handling
# ---------------------------------------------------------------------------


def _check_empty_states(
    jsx_files: list[Path],
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Check JSX pages for empty state handling."""
    pages_with_empty_states = 0
    pages_without_empty_states = 0
    missing_pages: list[str] = []
    empty_state_details: list[str] = []

    # Pages that are likely to need empty states (data-driven pages)
    data_pages = {
        "ContactsPage",
        "ApplicationsPage",
        "CreditsPage",
        "CoachPage",
        "FindReferrals",
        "SearchResults",
        "ReferralResults",
        "MyRequests",
        "MarketplaceOverview",
    }

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue

        stem = path.stem
        has_empty_state = bool(_EMPTY_STATE_PATTERNS.search(source))

        if has_empty_state:
            pages_with_empty_states += 1
            matches = _EMPTY_STATE_PATTERNS.findall(source)
            unique = sorted(set(m.lower().strip() for m in matches))
            empty_state_details.append(f"{stem}: {', '.join(unique)}")
        elif stem in data_pages:
            pages_without_empty_states += 1
            missing_pages.append(stem)

            rel = _relative(path)
            finding_id = f"NAIV-EMPTY-{stem.upper()}"
            findings.append(
                Finding(
                    id=finding_id,
                    severity="medium",
                    category="empty_state",
                    title=f"No empty state handling in {stem}",
                    detail=(
                        f"{rel} is a data-driven page but has no empty state handling. "
                        "Users with no data will see a blank or confusing page."
                    ),
                    file=rel,
                    recommendation=(
                        f"Add an empty state component to {stem} with a helpful message "
                        "and a clear CTA (e.g., 'Upload your CSV to get started')."
                    ),
                    effort_hours=1.0,
                )
            )
            sat_findings.append(
                SatisfactionFinding(
                    id=finding_id,
                    category="empty_state",
                    severity="medium",
                    title=f"Missing empty state in {stem}",
                    file=rel,
                    detail="Data page without empty state leaves new users confused.",
                    persona="both",
                    recommendation=f"Add empty state with CTA to {stem}.",
                )
            )

    metrics["empty_state_pages_with"] = pages_with_empty_states
    metrics["empty_state_pages_missing"] = pages_without_empty_states
    metrics["empty_state_missing_pages"] = missing_pages
    metrics["empty_state_details"] = empty_state_details


# ---------------------------------------------------------------------------
# Check 6: Live User Satisfaction Data (CoS gap 3)
# ---------------------------------------------------------------------------


def _check_live_satisfaction(
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Query user_feedback table for actual NPS/rating data."""
    from ops_team.shared.db import get_session

    session = get_session()
    if session is None:
        logger.info("naiv: live satisfaction — no DB session, skipping")
        findings.append(
            Finding(
                id="naiv-live-sat-skip",
                severity="info",
                category="live_satisfaction",
                title="Live satisfaction data unavailable",
                detail="DATABASE_URL not set — cannot query user_feedback",
            )
        )
        return

    try:
        from sqlalchemy import func, select
        from app.models.enrichment import UserFeedback

        logger.info("naiv: live satisfaction — querying user_feedback table")
        total = (
            session.execute(select(func.count()).select_from(UserFeedback)).scalar()
            or 0
        )
        logger.info("naiv: live satisfaction — found %d feedback records", total)

        avg_rating = session.execute(select(func.avg(UserFeedback.rating))).scalar()

        feature_rows = session.execute(
            select(
                UserFeedback.feature,
                func.count().label("cnt"),
                func.avg(UserFeedback.rating).label("avg_r"),
            ).group_by(UserFeedback.feature)
        ).all()

        by_feature = {
            row[0]: {"count": row[1], "avg_rating": round(float(row[2]), 2)}
            for row in feature_rows
        }

        positive = (
            session.execute(
                select(func.count())
                .select_from(UserFeedback)
                .where(UserFeedback.rating == 1)
            ).scalar()
            or 0
        )
        negative = (
            session.execute(
                select(func.count())
                .select_from(UserFeedback)
                .where(UserFeedback.rating == -1)
            ).scalar()
            or 0
        )
        neutral = (
            session.execute(
                select(func.count())
                .select_from(UserFeedback)
                .where(UserFeedback.rating == 0)
            ).scalar()
            or 0
        )

        metrics["live_feedback_count"] = total
        metrics["live_feedback_avg_rating"] = (
            round(float(avg_rating), 2) if avg_rating is not None else None
        )
        metrics["live_feedback_by_feature"] = by_feature
        metrics["live_feedback_positive"] = positive
        metrics["live_feedback_negative"] = negative
        metrics["live_feedback_neutral"] = neutral

        # Wire into satisfaction_score for ops_lead scorecard (0-1 scale)
        if total > 0:
            nps_raw = (positive - negative) / total  # -1 to +1
            metrics["satisfaction_score"] = round((nps_raw + 1) / 2, 2)  # 0 to 1
        else:
            metrics["satisfaction_score"] = 0.5  # neutral when no data

        if total == 0:
            findings.append(
                Finding(
                    id="naiv-live-sat-000",
                    severity="info",
                    category="live_satisfaction",
                    title="No user feedback collected yet",
                    detail="user_feedback table is empty — pre-launch state",
                )
            )
        else:
            nps_like = round((positive - negative) / total, 2) if total > 0 else 0.0
            metrics["live_feedback_nps_score"] = nps_like

            if nps_like < 0:
                sat_findings.append(
                    SatisfactionFinding(
                        id="naiv-live-sat-001",
                        category="live_satisfaction",
                        severity="high",
                        title=f"Negative NPS score: {nps_like:.2f}",
                        detail=f"Positive: {positive}, Negative: {negative}, Neutral: {neutral}",
                        persona="both",
                        recommendation="Investigate top negative-feedback features for root cause",
                    )
                )
    except Exception as exc:
        logger.error("naiv: live satisfaction check failed: %s", exc)
        findings.append(
            Finding(
                id="naiv-live-sat-err",
                severity="info",
                category="live_satisfaction",
                title="Live satisfaction check error",
                detail=str(exc),
            )
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Check 7: Live Error Telemetry (CoS gap 5)
# ---------------------------------------------------------------------------


def _check_live_error_telemetry(
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Query usage_logs and audit_logs for error frequency and impact."""
    from ops_team.shared.db import get_session

    session = get_session()
    if session is None:
        logger.info("naiv: live error telemetry — no DB session, skipping")
        findings.append(
            Finding(
                id="naiv-live-err-skip",
                severity="info",
                category="error_telemetry",
                title="Live error telemetry unavailable",
                detail="DATABASE_URL not set — cannot query error logs",
            )
        )
        return

    try:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import func, select
        from app.models.enrichment import UsageLog
        from app.models.audit import AuditLog

        logger.info("naiv: live error telemetry — querying usage_logs + audit_logs")

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        error_actions = session.execute(
            select(
                UsageLog.action,
                func.count().label("cnt"),
            )
            .where(UsageLog.created_at >= cutoff)
            .group_by(UsageLog.action)
            .order_by(func.count().desc())
        ).all()

        total_actions_7d = sum(row[1] for row in error_actions)

        security_events = (
            session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.created_at >= cutoff)
            ).scalar()
            or 0
        )

        top_actions = {row[0]: row[1] for row in error_actions[:10]}

        metrics["live_error_total_actions_7d"] = total_actions_7d
        metrics["live_error_security_events_7d"] = security_events
        metrics["live_error_top_actions"] = top_actions

        if security_events > 50:
            sat_findings.append(
                SatisfactionFinding(
                    id="naiv-live-err-001",
                    category="error_telemetry",
                    severity="high",
                    title=f"High security event volume: {security_events} in 7 days",
                    detail="Elevated audit log entries may indicate attacks or config issues",
                    persona="both",
                    recommendation="Review audit_logs for patterns — brute force, unusual IPs",
                )
            )
    except Exception as exc:
        logger.error("naiv: live error telemetry failed: %s", exc)
        findings.append(
            Finding(
                id="naiv-live-err-err",
                severity="info",
                category="error_telemetry",
                title="Live error telemetry check error",
                detail=str(exc),
            )
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Check 8: Live Email Engagement Metrics (CoS gap 7)
# ---------------------------------------------------------------------------


def _check_live_email_engagement(
    findings: list[Finding],
    sat_findings: list[SatisfactionFinding],
    metrics: dict[str, Any],
) -> None:
    """Query email_campaign_logs for open/click rates by email type."""
    from ops_team.shared.db import get_session

    session = get_session()
    if session is None:
        logger.info("naiv: live email engagement — no DB session, skipping")
        findings.append(
            Finding(
                id="naiv-live-email-skip",
                severity="info",
                category="email_engagement",
                title="Live email engagement unavailable",
                detail="DATABASE_URL not set — cannot query email_campaign_logs",
            )
        )
        return

    try:
        from sqlalchemy import func, select
        from app.models.email_campaign import EmailCampaignLog

        logger.info("naiv: live email engagement — querying email_campaign_logs")
        total_sent = (
            session.execute(select(func.count()).select_from(EmailCampaignLog)).scalar()
            or 0
        )

        if total_sent == 0:
            findings.append(
                Finding(
                    id="naiv-live-email-000",
                    severity="info",
                    category="email_engagement",
                    title="No emails sent yet",
                    detail="email_campaign_logs is empty — pre-launch state",
                )
            )
            metrics["live_email_total_sent"] = 0
            return

        total_opened = (
            session.execute(
                select(func.count())
                .select_from(EmailCampaignLog)
                .where(EmailCampaignLog.opened_at.is_not(None))
            ).scalar()
            or 0
        )

        total_clicked = (
            session.execute(
                select(func.count())
                .select_from(EmailCampaignLog)
                .where(EmailCampaignLog.clicked_at.is_not(None))
            ).scalar()
            or 0
        )

        type_rows = session.execute(
            select(
                EmailCampaignLog.email_type,
                func.count().label("sent"),
                func.count(EmailCampaignLog.opened_at).label("opened"),
                func.count(EmailCampaignLog.clicked_at).label("clicked"),
            ).group_by(EmailCampaignLog.email_type)
        ).all()

        by_type = {}
        for row in type_rows:
            sent = row[1]
            by_type[row[0]] = {
                "sent": sent,
                "opened": row[2],
                "clicked": row[3],
                "open_rate": round(row[2] / sent, 2) if sent > 0 else 0.0,
                "click_rate": round(row[3] / sent, 2) if sent > 0 else 0.0,
            }

        open_rate = round(total_opened / total_sent, 2) if total_sent > 0 else 0.0
        click_rate = round(total_clicked / total_sent, 2) if total_sent > 0 else 0.0

        metrics["live_email_total_sent"] = total_sent
        metrics["live_email_open_rate"] = open_rate
        metrics["live_email_click_rate"] = click_rate
        metrics["live_email_by_type"] = by_type

        if open_rate < 0.15:
            sat_findings.append(
                SatisfactionFinding(
                    id="naiv-live-email-001",
                    category="email_engagement",
                    severity="medium",
                    title=f"Low email open rate: {open_rate:.0%}",
                    detail=f"{total_opened}/{total_sent} emails opened (target >=15%)",
                    persona="both",
                    recommendation="Review subject lines and send timing. Consider A/B testing.",
                )
            )
    except Exception as exc:
        logger.error("naiv: live email engagement failed: %s", exc)
        findings.append(
            Finding(
                id="naiv-live-email-err",
                severity="info",
                category="email_engagement",
                title="Live email engagement check error",
                detail=str(exc),
            )
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------


def scan() -> OpsTeamReport:
    """Run all satisfaction checks and return consolidated report."""
    start = time.time()

    findings: list[Finding] = []
    sat_findings: list[SatisfactionFinding] = []
    metrics: dict[str, Any] = {}
    learning_updates: list[str] = []

    # Discover files
    api_files = _find_api_files()
    jsx_files = _find_jsx_files()

    middleware_path = MIDDLEWARE_DIR / "usage.py"
    middleware_source = _read_safe(middleware_path)

    metrics["api_files_scanned"] = len(api_files)
    metrics["jsx_files_scanned"] = len(jsx_files)
    metrics["middleware_found"] = bool(middleware_source)

    # -- Run checks ----------------------------------------------------------

    try:
        _check_error_message_quality(api_files, findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Error message quality check failed: %s", exc)
        metrics["error_quality_check_error"] = str(exc)

    try:
        _check_feedback_collection(jsx_files, findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Feedback collection check failed: %s", exc)
        metrics["feedback_check_error"] = str(exc)

    try:
        _check_journey_milestones(jsx_files, findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Journey milestones check failed: %s", exc)
        metrics["milestones_check_error"] = str(exc)

    try:
        _check_usage_tracking(
            api_files, middleware_source, findings, sat_findings, metrics
        )
    except Exception as exc:
        logger.error("Usage tracking check failed: %s", exc)
        metrics["tracking_check_error"] = str(exc)

    try:
        _check_empty_states(jsx_files, findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Empty states check failed: %s", exc)
        metrics["empty_states_check_error"] = str(exc)

    try:
        _check_live_satisfaction(findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Live satisfaction check failed: %s", exc)
        metrics["live_satisfaction_check_error"] = str(exc)

    try:
        _check_live_error_telemetry(findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Live error telemetry check failed: %s", exc)
        metrics["live_error_telemetry_check_error"] = str(exc)

    try:
        _check_live_email_engagement(findings, sat_findings, metrics)
    except Exception as exc:
        logger.error("Live email engagement check failed: %s", exc)
        metrics["live_email_check_error"] = str(exc)

    # -- Self-learning -------------------------------------------------------

    try:
        learner = OpsLearningState(AGENT_NAME)

        # Record each finding
        for f in findings:
            learner.record_finding(
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "file": f.file,
                    "line": f.line,
                    "title": f.title,
                }
            )

        # Update attention weights based on findings per file
        file_counts: dict[str, int] = {}
        for f in findings:
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1
        if file_counts:
            learner.update_attention_weights(file_counts)

        # Track satisfaction KPIs
        if "error_handling_coverage" in metrics:
            learner.track_kpi(
                "error_handling_coverage", metrics["error_handling_coverage"]
            )
        if "feedback_collection_points" in metrics:
            learner.track_kpi(
                "feedback_collection_points", metrics["feedback_collection_points"]
            )
        if "usage_tracking_coverage" in metrics:
            learner.track_kpi(
                "usage_tracking_coverage", metrics["usage_tracking_coverage"]
            )

        # Record scan
        learner.record_scan(
            {
                "total_findings": len(findings),
                "satisfaction_findings": len(sat_findings),
                "error_handling_coverage": metrics.get("error_handling_coverage", 0),
                "feedback_points": metrics.get("feedback_collection_points", 0),
                "tracking_coverage": metrics.get("usage_tracking_coverage", 0),
                "empty_states_missing": metrics.get("empty_state_pages_missing", 0),
            }
        )

        # Record health snapshot
        sev_counts: dict[str, int] = {}
        for f in findings:
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

        score = max(
            0.0,
            100.0
            - sev_counts.get("critical", 0) * 20
            - sev_counts.get("high", 0) * 10
            - sev_counts.get("medium", 0) * 5
            - sev_counts.get("low", 0) * 1,
        )
        learner.record_health_snapshot(score, sev_counts)

        # Check trends for learning updates
        err_trend = learner.get_kpi_trend("error_handling_coverage")
        if err_trend == "improving":
            learning_updates.append(
                "Error handling coverage is IMPROVING across scans."
            )
        elif err_trend == "degrading":
            learning_updates.append(
                "Error handling coverage is DEGRADING — new endpoints may lack custom errors."
            )

        fb_trend = learner.get_kpi_trend("feedback_collection_points")
        if fb_trend == "improving":
            learning_updates.append("Feedback collection points are INCREASING.")

        health_traj = learner.get_health_trajectory()
        if health_traj != "insufficient_data":
            learning_updates.append(f"Satisfaction health trajectory: {health_traj}.")

        total_scans = learner.state.get("total_scans", 0)
        learning_updates.append(f"Total naiv scans completed: {total_scans}")

        learner.save()

    except Exception as exc:
        logger.error("Naiv learning update failed: %s", exc)
        learning_updates.append(f"Learning update error: {exc}")

    elapsed = time.time() - start

    return OpsTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        satisfaction_findings=sat_findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def save_report(report: OpsTeamReport) -> Path:
    """Save the latest report to ops_team/reports/naiv_latest.json."""
    reports_dir = Path(__file__).resolve().parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "naiv_latest.json"
    out_path.write_text(report.serialize(), encoding="utf-8")
    logger.info("Naiv report saved to %s", out_path)
    return out_path
