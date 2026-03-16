"""Marketing Manager agent — SEO readiness, content infrastructure, landing page
optimization, brand messaging consistency, privacy compliance in marketing, onboarding
conversion analysis.

Scans frontend/index.html, frontend/src/pages/*.jsx, and CLAUDE.md for marketing
readiness signals.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from agents.shared.web_tools import web_fetch, web_search
from gtm_team.shared.config import (
    FRONTEND_SRC,
    PAGES_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
)
from gtm_team.shared.learning import GTMLearningState
from gtm_team.shared.report import (
    ComplianceReviewItem,
    GTMTeamReport,
    MarketInsight,
)
from gtm_team.shared.strategy_context import (
    extract_privacy_constraints,
    get_strategy_doc,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "marketing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read file, returning empty string on failure."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    """Return path relative to project root."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _find_jsx_files() -> list[Path]:
    """Return all .jsx/.tsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted([*PAGES_DIR.glob("*.jsx"), *PAGES_DIR.glob("*.tsx")])


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_seo_basics(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan frontend/index.html and JSX pages for meta tags, title tags, heading hierarchy."""
    index_html = FRONTEND_SRC.parent / "index.html"
    index_content = _read_safe(index_html)

    # Check index.html for essential SEO elements
    has_title = bool(re.search(r"<title\b[^>]*>", index_content))
    has_meta_desc = bool(
        re.search(r'<meta\s+[^>]*name=["\']description["\']', index_content)
    )
    has_og_tags = bool(re.search(r'<meta\s+[^>]*property=["\']og:', index_content))
    has_viewport = bool(
        re.search(r'<meta\s+[^>]*name=["\']viewport["\']', index_content)
    )
    has_charset = bool(re.search(r"<meta\s+[^>]*charset=", index_content))
    has_favicon = bool(re.search(r'<link\s+[^>]*rel=["\']icon["\']', index_content))

    seo_score = sum(
        [has_title, has_meta_desc, has_og_tags, has_viewport, has_charset, has_favicon]
    )
    metrics["seo_index_score"] = seo_score
    metrics["seo_has_title"] = has_title
    metrics["seo_has_meta_description"] = has_meta_desc
    metrics["seo_has_og_tags"] = has_og_tags

    if not has_title:
        findings.append(
            Finding(
                id="mkt-seo-001",
                severity="medium",
                category="seo",
                title="Missing <title> tag in index.html",
                detail="index.html has no <title> tag — critical for SEO and browser tab display",
                file=_relative(index_html),
                recommendation="Add a descriptive <title> tag with primary keyword",
            )
        )

    if not has_meta_desc:
        findings.append(
            Finding(
                id="mkt-seo-002",
                severity="medium",
                category="seo",
                title="Missing meta description in index.html",
                detail='No <meta name="description"> — search engines will auto-generate a snippet',
                file=_relative(index_html),
                recommendation="Add a 150-160 character meta description with value proposition",
            )
        )

    if not has_og_tags:
        findings.append(
            Finding(
                id="mkt-seo-003",
                severity="medium",
                category="seo",
                title="Missing OpenGraph tags in index.html",
                detail="No og: meta tags — social media shares will lack rich preview",
                file=_relative(index_html),
                recommendation="Add og:title, og:description, og:image, og:url meta tags",
            )
        )

    # Check JSX pages for heading hierarchy
    pages_with_h1 = 0
    pages_with_headings = 0
    heading_issues: list[str] = []

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue

        has_h1 = bool(re.search(r"<h1\b", source))
        has_h2 = bool(re.search(r"<h2\b", source))
        has_any_heading = has_h1 or has_h2

        if has_h1:
            pages_with_h1 += 1
        if has_any_heading:
            pages_with_headings += 1

        # Check for heading hierarchy violations (h3 before h2, etc.)
        h_tags = re.findall(r"<h(\d)\b", source)
        if h_tags:
            levels = [int(h) for h in h_tags]
            for i in range(1, len(levels)):
                if levels[i] > levels[i - 1] + 1:
                    heading_issues.append(path.name)
                    break

    h1_pct = pages_with_h1 / max(1, len(jsx_files))
    metrics["seo_pages_with_h1"] = pages_with_h1
    metrics["seo_h1_coverage"] = round(h1_pct, 2)
    metrics["seo_heading_hierarchy_issues"] = len(heading_issues)

    if h1_pct < 0.3:
        findings.append(
            Finding(
                id="mkt-seo-004",
                severity="medium",
                category="seo",
                title=f"Low h1 tag coverage ({h1_pct:.0%})",
                detail=f"Only {pages_with_h1}/{len(jsx_files)} pages have <h1> tags",
                recommendation="Add semantic h1 headings to all pages for SEO and accessibility",
            )
        )


def _check_landing_page_readiness(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check for homepage value proposition, CTA buttons, social proof elements."""
    # Look for the main Coach / landing page
    landing_candidates = [
        "CoachPage.jsx",
        "LandingPage.jsx",
        "HomePage.jsx",
        "AuthPage.jsx",
    ]
    landing_content = ""

    for candidate in landing_candidates:
        for path in jsx_files:
            if path.name == candidate:
                landing_content = _read_safe(path)
                _relative(path)
                break
        if landing_content:
            break

    # Also check all pages collectively
    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path)

    # CTAs across all pages
    cta_patterns = re.compile(
        r"(?:Get\s+Started|Sign\s+Up|Start\s+Free|Try\s+Free|Join\s+Now|Upload|Get\s+Referred|Find\s+Referrals)",
        re.IGNORECASE,
    )
    cta_count = len(cta_patterns.findall(all_content))
    metrics["cta_count"] = cta_count

    # Value proposition keywords
    value_prop_patterns = re.compile(
        r"(?:referral|warm\s+introduction|employee\s+referral|get\s+referred|network|connection)",
        re.IGNORECASE,
    )
    value_prop_mentions = len(value_prop_patterns.findall(all_content))
    metrics["value_prop_mentions"] = value_prop_mentions

    # Social proof patterns
    social_proof_patterns = re.compile(
        r"(?:testimonial|success\s+stor|review|rating|\d+\s*(?:users?|referrals?|connections?|companies)|trusted\s+by)",
        re.IGNORECASE,
    )
    social_proof_count = len(social_proof_patterns.findall(all_content))
    metrics["social_proof_elements"] = social_proof_count

    # Button elements
    button_count = len(re.findall(r"<button\b", all_content))
    metrics["total_buttons"] = button_count

    if cta_count == 0:
        findings.append(
            Finding(
                id="mkt-lp-001",
                severity="high",
                category="landing_page",
                title="No clear call-to-action found across pages",
                detail="No CTA patterns (Get Started, Sign Up, etc.) detected in any page",
                recommendation="Add prominent CTA buttons on landing/dashboard pages",
            )
        )

    if social_proof_count == 0:
        insights.append(
            MarketInsight(
                id="mkt-lp-insight-001",
                category="channel",
                title="No social proof elements detected",
                evidence="No testimonials, success stories, or usage stats found in JSX pages",
                strategic_impact="Landing page conversion likely below benchmark without social proof",
                recommended_response="Add testimonials, user counts, or success metrics to key pages",
                urgency="this_month",
                confidence="high",
            )
        )

    if value_prop_mentions < 3:
        findings.append(
            Finding(
                id="mkt-lp-002",
                severity="medium",
                category="landing_page",
                title="Weak value proposition visibility",
                detail=f"Only {value_prop_mentions} referral/network value prop mentions across all pages",
                recommendation="Reinforce the core value prop (referrals > cold applications) on key pages",
            )
        )


def _check_brand_messaging(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan JSX pages for messaging consistency with CLAUDE.md key phrases."""
    get_strategy_doc("CLAUDE.md")

    # Key brand phrases that should appear in the frontend
    brand_phrases = {
        "referral": re.compile(r"\breferral\b", re.IGNORECASE),
        "warm_score": re.compile(r"warm\s*score", re.IGNORECASE),
        "cold_application": re.compile(r"cold\s*(?:application|apply)", re.IGNORECASE),
        "privacy_vault": re.compile(r"(?:private|privacy)\s*vault", re.IGNORECASE),
        "marketplace": re.compile(r"\bmarketplace\b", re.IGNORECASE),
        "network_holder": re.compile(r"network\s*holder", re.IGNORECASE),
        "anonymous": re.compile(r"\banonymous|anonymi[sz]ed\b", re.IGNORECASE),
        "credits": re.compile(r"\bcredits?\b", re.IGNORECASE),
    }

    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path) + "\n"

    phrase_coverage: dict[str, bool] = {}
    for phrase_name, pattern in brand_phrases.items():
        found = bool(pattern.search(all_content))
        phrase_coverage[phrase_name] = found

    covered = sum(1 for v in phrase_coverage.values() if v)
    total = len(phrase_coverage)
    coverage_ratio = covered / max(1, total)

    metrics["brand_phrase_coverage"] = round(coverage_ratio, 2)
    metrics["brand_phrases_found"] = covered
    metrics["brand_phrases_total"] = total
    metrics["brand_phrase_detail"] = {k: v for k, v in phrase_coverage.items()}

    missing = [k for k, v in phrase_coverage.items() if not v]
    if missing and coverage_ratio < 0.6:
        findings.append(
            Finding(
                id="mkt-brand-001",
                severity="medium",
                category="brand_messaging",
                title=f"Brand messaging gaps — {len(missing)} key phrases missing",
                detail=f"Missing: {', '.join(missing)}. Coverage: {coverage_ratio:.0%}",
                recommendation="Ensure core brand language from CLAUDE.md appears in user-facing pages",
            )
        )

    # Check for off-brand messaging
    off_brand_patterns = [
        (
            r"apply\s+(?:to\s+)?(?:hundreds|thousands)\s+of\s+jobs",
            "Mass-apply messaging contradicts referral focus",
        ),
        (r"we\s+guarantee", "Guarantee claims are risky for a marketplace"),
        (r"instant\s+(?:job|hire|referral)", "Instant promises set wrong expectations"),
    ]
    for pattern, reason in off_brand_patterns:
        if re.search(pattern, all_content, re.IGNORECASE):
            findings.append(
                Finding(
                    id=f"mkt-brand-off-{hash(pattern) % 1000:03d}",
                    severity="medium",
                    category="brand_messaging",
                    title="Potentially off-brand messaging detected",
                    detail=reason,
                    recommendation="Review and align with CLAUDE.md positioning",
                )
            )


def _check_privacy_compliance_in_marketing(
    jsx_files: list[Path],
    findings: list[Finding],
    compliance_reviews: list[ComplianceReviewItem],
    metrics: dict,
) -> None:
    """Scan for privacy-related text in JSX and verify claims match architecture."""
    privacy_constraints = extract_privacy_constraints()

    # Pages that should have privacy messaging
    privacy_pages = ["PrivacyPage.jsx", "OnboardingPage.jsx"]
    privacy_page_content: dict[str, str] = {}

    for path in jsx_files:
        if path.name in privacy_pages:
            privacy_page_content[path.name] = _read_safe(path)

    has_privacy_page = "PrivacyPage.jsx" in privacy_page_content
    has_onboarding_privacy = False

    if "OnboardingPage.jsx" in privacy_page_content:
        onboarding = privacy_page_content["OnboardingPage.jsx"]
        has_onboarding_privacy = bool(
            re.search(
                r"(?:privacy|vault|anonymous|consent|your\s+data)",
                onboarding,
                re.IGNORECASE,
            )
        )

    metrics["has_privacy_page"] = has_privacy_page
    metrics["has_onboarding_privacy"] = has_onboarding_privacy

    if not has_privacy_page:
        findings.append(
            Finding(
                id="mkt-priv-001",
                severity="medium",
                category="privacy_compliance",
                title="No dedicated privacy page found",
                detail="PrivacyPage.jsx not found — users need a visible privacy policy page",
                recommendation="Create or verify PrivacyPage.jsx exists with privacy architecture details",
            )
        )

    if not has_onboarding_privacy:
        findings.append(
            Finding(
                id="mkt-priv-002",
                severity="medium",
                category="privacy_compliance",
                title="Onboarding lacks privacy messaging",
                detail="OnboardingPage.jsx does not mention privacy/vault/consent",
                recommendation="Add privacy explainer step to onboarding per CLAUDE.md architecture (P16)",
            )
        )

    # Check for dangerous marketing claims in all pages
    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path) + "\n"

    dangerous_claims = [
        (
            r"100%\s*(?:private|secure|safe)",
            "Absolute privacy/security claims are risky",
        ),
        (
            r"we\s+never\s+(?:share|sell|see)\s+your\s+data",
            "Overbroad data handling claim — we do process data",
        ),
        (
            r"military.grade\s+(?:encryption|security)",
            "Military-grade is a marketing red flag",
        ),
    ]

    for pattern, reason in dangerous_claims:
        if re.search(pattern, all_content, re.IGNORECASE):
            compliance_reviews.append(
                ComplianceReviewItem(
                    id=f"mkt-compl-{hash(pattern) % 1000:03d}",
                    asset_type="landing_page",
                    description=reason,
                    jurisdiction="global",
                    reviewer="privy_agent",
                    status="pending",
                    changes_required=f"Review claim: {reason}",
                )
            )

    # Verify privacy architecture claims align with CLAUDE.md
    if has_privacy_page:
        privacy_content = privacy_page_content.get("PrivacyPage.jsx", "")
        vault_mentioned = bool(re.search(r"vault", privacy_content, re.IGNORECASE))
        anon_mentioned = bool(re.search(r"anonym", privacy_content, re.IGNORECASE))
        consent_mentioned = bool(re.search(r"consent", privacy_content, re.IGNORECASE))

        arch_alignment = sum([vault_mentioned, anon_mentioned, consent_mentioned])
        metrics["privacy_architecture_alignment"] = arch_alignment

        if arch_alignment < 2 and privacy_constraints.get("has_vault_model"):
            findings.append(
                Finding(
                    id="mkt-priv-003",
                    severity="medium",
                    category="privacy_compliance",
                    title="Privacy page under-represents architecture",
                    detail=f"Privacy page mentions {arch_alignment}/3 key architecture features (vault, anon, consent)",
                    recommendation="Ensure privacy page covers Private Vault, anonymization, and consent gates",
                )
            )


def _check_onboarding_conversion(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check OnboardingPage.jsx for conversion optimization signals."""
    onboarding_content = ""
    onboarding_file = ""

    for path in jsx_files:
        if path.name == "OnboardingPage.jsx":
            onboarding_content = _read_safe(path)
            onboarding_file = _relative(path)
            break

    if not onboarding_content:
        findings.append(
            Finding(
                id="mkt-onb-001",
                severity="medium",
                category="onboarding",
                title="No OnboardingPage.jsx found",
                detail="Onboarding flow is critical for activation — no page detected",
                recommendation="Create onboarding flow with step-by-step guidance",
            )
        )
        return

    # Progress indicators
    has_progress = bool(
        re.search(
            r"(?:step|progress|stage|phase|\d\s*(?:of|/)\s*\d|stepper|wizard)",
            onboarding_content,
            re.IGNORECASE,
        )
    )
    metrics["onboarding_has_progress"] = has_progress

    # Value communication
    has_value_comm = bool(
        re.search(
            r"(?:referral|warm|connect|network|get\s+referred|employee)",
            onboarding_content,
            re.IGNORECASE,
        )
    )
    metrics["onboarding_has_value_comm"] = has_value_comm

    # Upload/action prompt
    has_action = bool(
        re.search(
            r"(?:upload|import|csv|get\s+started|connect|add\s+contacts)",
            onboarding_content,
            re.IGNORECASE,
        )
    )
    metrics["onboarding_has_action_prompt"] = has_action

    # Skip option (reduces friction)
    has_skip = bool(
        re.search(
            r"(?:skip|later|not\s+now|maybe\s+later)", onboarding_content, re.IGNORECASE
        )
    )
    metrics["onboarding_has_skip_option"] = has_skip

    conversion_signals = sum([has_progress, has_value_comm, has_action, has_skip])
    metrics["onboarding_conversion_score"] = conversion_signals

    if not has_progress:
        findings.append(
            Finding(
                id="mkt-onb-002",
                severity="medium",
                category="onboarding",
                title="Onboarding lacks progress indicator",
                detail="No step/progress/wizard pattern detected in OnboardingPage.jsx",
                file=onboarding_file,
                recommendation="Add step counter or progress bar to reduce abandonment",
            )
        )

    if not has_value_comm:
        findings.append(
            Finding(
                id="mkt-onb-003",
                severity="medium",
                category="onboarding",
                title="Onboarding lacks value communication",
                detail="No referral/network value messaging found in onboarding flow",
                file=onboarding_file,
                recommendation="Reinforce why referrals matter before asking users to take action",
            )
        )

    if conversion_signals >= 3:
        insights.append(
            MarketInsight(
                id="mkt-onb-insight-001",
                category="channel",
                title="Onboarding has solid conversion foundations",
                evidence=f"{conversion_signals}/4 conversion signals present",
                strategic_impact="Good activation funnel structure",
                recommended_response="A/B test copy variants to optimize conversion rate",
                urgency="this_month",
                confidence="medium",
            )
        )


def _scan_competitor_marketing(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Search for competitor landing pages and marketing approaches."""
    competitor_queries = [
        "employee referral platform landing page",
        "get referred to jobs site",
        "referral marketplace for job seekers",
    ]
    total_results = 0
    competitor_pages: list[str] = []

    for query in competitor_queries:
        results = web_search(query, max_results=3)
        total_results += len(results)
        for r in results:
            competitor_pages.append(f"{r.title} ({r.url[:60]})")

    metrics["web_marketing_results"] = total_results
    metrics["web_marketing_queries"] = len(competitor_queries)

    # Fetch top result for messaging analysis if available
    if total_results > 0:
        all_results = []
        for query in competitor_queries:
            all_results.extend(web_search(query, max_results=1))

        top_url = all_results[0].url if all_results else None
        messaging_sample = ""
        if top_url:
            content = web_fetch(top_url, max_chars=3000)
            # Extract first 500 chars of meaningful content for analysis
            messaging_sample = content[:500] if content else ""

        metrics["competitor_messaging_sample_length"] = len(messaging_sample)

        insights.append(
            MarketInsight(
                id="mkt-web-insight-001",
                category="competitive",
                title=f"Competitor marketing scan: {total_results} results",
                evidence="; ".join(competitor_pages[:4]),
                strategic_impact="Competitor messaging reveals positioning gaps and differentiation opportunities",
                recommended_response="Compare WarmPath's messaging against competitor landing pages",
                urgency="this_month",
                confidence="medium",
            )
        )
    else:
        insights.append(
            MarketInsight(
                id="mkt-web-insight-001",
                category="competitive",
                title="Competitor marketing scan: no results (network may be unavailable)",
                evidence="Web search returned 0 results",
                strategic_impact="Cannot benchmark marketing against competitors without web access",
                urgency="monitor",
                confidence="low",
            )
        )


def _check_content_infrastructure(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check for blog/content infrastructure (blog routes, content pages)."""
    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path) + "\n"

    # Check for blog/content routes
    has_blog_route = bool(
        re.search(
            r"(?:/blog|/articles?|/resources?|/guides?)", all_content, re.IGNORECASE
        )
    )
    metrics["has_blog_route"] = has_blog_route

    # Check for content page files
    content_page_names = [
        "BlogPage.jsx",
        "ResourcesPage.jsx",
        "GuidesPage.jsx",
        "ArticlePage.jsx",
    ]
    content_pages_found = []
    for path in jsx_files:
        if path.name in content_page_names:
            content_pages_found.append(path.name)

    metrics["content_pages_found"] = len(content_pages_found)
    metrics["content_page_names"] = content_pages_found

    # Check for sitemap references
    index_html = FRONTEND_SRC.parent / "index.html"
    index_content = _read_safe(index_html)
    has_sitemap_ref = bool(re.search(r"sitemap", index_content, re.IGNORECASE))
    metrics["has_sitemap_reference"] = has_sitemap_ref

    # Check for robots.txt reference
    robots_path = FRONTEND_SRC.parent / "public" / "robots.txt"
    has_robots = robots_path.exists()
    metrics["has_robots_txt"] = has_robots

    if not has_blog_route and not content_pages_found:
        findings.append(
            Finding(
                id="mkt-content-001",
                severity="info",
                category="content_infrastructure",
                title="No blog/content infrastructure detected",
                detail="No blog routes, resource pages, or article pages found",
                recommendation="Build content infrastructure for SEO — blog with referral tips, company guides",
            )
        )

        insights.append(
            MarketInsight(
                id="mkt-content-insight-001",
                category="channel",
                title="Content marketing infrastructure not yet built",
                evidence="No blog routes or content pages detected in frontend",
                strategic_impact="SEO-driven acquisition channel is blocked until content infrastructure exists",
                recommended_response="Prioritize /blog route with 5-10 seed articles targeting referral keywords",
                urgency="this_month",
                confidence="high",
            )
        )


FUNNEL_EVENTS = [
    "signup_completed",
    "email_verified",
    "csv_uploaded",
    "search_performed",
    "intro_requested",
    "intro_approved",
]


def _check_analytics_integration(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan frontend source files for PostHog integration."""
    # Check both .jsx and .tsx (project uses TypeScript)
    src_dir = PROJECT_ROOT / "frontend" / "src"
    main_candidates = [src_dir / "main.jsx", src_dir / "main.tsx"]
    analytics_candidates = [
        src_dir / "utils" / "analytics.js",
        src_dir / "utils" / "analytics.ts",
    ]

    has_posthog_init = False
    has_analytics_util = any(p.exists() for p in analytics_candidates)

    for main_path in main_candidates:
        if main_path.exists():
            content = _read_safe(main_path)
            has_posthog_init = "posthog" in content.lower()
            break

    # Count trackEvent calls across all JSX/TSX files
    track_count = 0
    pages_dir = src_dir / "pages"
    if pages_dir.exists():
        for ext in ("*.jsx", "*.tsx"):
            for page_file in pages_dir.rglob(ext):
                if "trackEvent" in _read_safe(page_file):
                    track_count += 1

    metrics["posthog_initialized"] = has_posthog_init
    metrics["analytics_util_exists"] = has_analytics_util
    metrics["pages_with_tracking"] = track_count

    if not has_posthog_init:
        findings.append(
            Finding(
                id="MKT-NO-ANALYTICS",
                severity="high",
                category="analytics",
                title="PostHog analytics not initialized",
                detail="frontend/src/main.jsx does not initialize PostHog",
                recommendation="Add PostHog initialization with VITE_POSTHOG_KEY",
                effort_hours=0.5,
            )
        )

    insights.append(
        MarketInsight(
            id="mkt-insight-analytics",
            category="channel",
            title=f"Analytics: PostHog {'active' if has_posthog_init else 'not configured'}, {track_count} pages tracked",
            evidence=f"PostHog init: {has_posthog_init}, analytics.js: {has_analytics_util}, tracked pages: {track_count}",
            strategic_impact="Analytics coverage determines funnel visibility",
            recommended_response="Ensure all key funnel steps have trackEvent calls"
            if track_count < 5
            else "Good coverage",
            urgency="this_week" if not has_posthog_init else "monitor",
            confidence="high",
        )
    )


def _check_conversion_funnel(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check that key funnel events are tracked in frontend code."""
    tracked_events: set[str] = set()
    src_dir = PROJECT_ROOT / "frontend" / "src"
    if src_dir.exists():
        for jsx in src_dir.rglob("*.jsx"):
            content = _read_safe(jsx)
            for event in FUNNEL_EVENTS:
                if event in content:
                    tracked_events.add(event)

    missing = set(FUNNEL_EVENTS) - tracked_events
    metrics["funnel_events_tracked"] = len(tracked_events)
    metrics["funnel_events_missing"] = list(missing)

    if missing:
        findings.append(
            Finding(
                id="MKT-FUNNEL-GAPS",
                severity="medium",
                category="analytics",
                title=f"Conversion funnel: {len(missing)} events not tracked",
                detail=f"Missing events: {', '.join(sorted(missing))}",
                recommendation="Add trackEvent() calls for missing funnel steps",
                effort_hours=1.0,
            )
        )

    insights.append(
        MarketInsight(
            id="mkt-insight-funnel",
            category="channel",
            title=f"Funnel tracking: {len(tracked_events)}/{len(FUNNEL_EVENTS)} events instrumented",
            evidence=f"Tracked: {', '.join(sorted(tracked_events))}. Missing: {', '.join(sorted(missing)) if missing else 'none'}.",
            strategic_impact="Funnel visibility enables conversion optimization",
            recommended_response="Instrument remaining events"
            if missing
            else "Full funnel coverage achieved",
            urgency="this_week" if len(missing) > 2 else "monitor",
            confidence="high",
        )
    )


def _check_seo_readiness(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Extended SEO check: structured data, canonical URLs, and sitemap."""
    index_html = PROJECT_ROOT / "frontend" / "index.html"
    content = _read_safe(index_html) if index_html.exists() else ""

    seo_signals = {
        "has_meta_description": 'meta name="description"' in content.lower(),
        "has_og_tags": 'property="og:' in content.lower(),
        "has_canonical": 'rel="canonical"' in content.lower(),
        "has_robots_txt": (
            PROJECT_ROOT / "frontend" / "public" / "robots.txt"
        ).exists(),
        "has_sitemap": (PROJECT_ROOT / "frontend" / "public" / "sitemap.xml").exists(),
    }

    metrics["seo_signals"] = seo_signals
    metrics["seo_score"] = sum(seo_signals.values()) / len(seo_signals) * 100

    missing_seo = [k.replace("has_", "") for k, v in seo_signals.items() if not v]
    if missing_seo:
        findings.append(
            Finding(
                id="MKT-SEO-GAPS",
                severity="medium",
                category="seo",
                title=f"SEO: {len(missing_seo)} signals missing",
                detail=f"Missing: {', '.join(missing_seo)}",
                recommendation="Add missing SEO elements for search visibility",
                effort_hours=1.5,
            )
        )

    insights.append(
        MarketInsight(
            id="mkt-insight-seo",
            category="channel",
            title=f"SEO readiness: {metrics['seo_score']:.0f}% ({len(seo_signals) - len(missing_seo)}/{len(seo_signals)} signals)",
            evidence=f"Present: {', '.join(k.replace('has_', '') for k, v in seo_signals.items() if v)}",
            strategic_impact="SEO signals affect organic search visibility",
            recommended_response="Add missing signals for better search rankings",
            urgency="this_month" if missing_seo else "monitor",
            confidence="high",
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> GTMTeamReport:
    """Run all marketing checks and return a GTMTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[MarketInsight] = []
    compliance_reviews: list[ComplianceReviewItem] = []
    metrics: dict = {}

    jsx_files = _find_jsx_files()
    metrics["total_jsx_pages"] = len(jsx_files)

    if not jsx_files:
        findings.append(
            Finding(
                id="mkt-000",
                severity="info",
                category="marketing",
                title="No JSX page files found in frontend/src/pages/",
                detail="Frontend may not be initialized yet",
                recommendation="Initialize React frontend under frontend/src/pages/",
            )
        )
    else:
        _check_seo_basics(jsx_files, findings, insights, metrics)
        _check_landing_page_readiness(jsx_files, findings, insights, metrics)
        _check_brand_messaging(jsx_files, findings, insights, metrics)
        _check_privacy_compliance_in_marketing(
            jsx_files, findings, compliance_reviews, metrics
        )
        _check_onboarding_conversion(jsx_files, findings, insights, metrics)
        _check_content_infrastructure(jsx_files, findings, insights, metrics)

    # Analytics, funnel, and SEO checks
    _check_analytics_integration(findings, insights, metrics)
    _check_conversion_funnel(findings, insights, metrics)
    _check_seo_readiness(findings, insights, metrics)

    # Live competitor marketing intelligence
    _scan_competitor_marketing(findings, insights, metrics)

    # Compute marketing readiness score
    score_components = {
        "seo": min(1.0, metrics.get("seo_index_score", 0) / 6),
        "cta": min(1.0, metrics.get("cta_count", 0) / 3),
        "value_prop": min(1.0, metrics.get("value_prop_mentions", 0) / 5),
        "brand_coverage": metrics.get("brand_phrase_coverage", 0),
        "privacy_page": 1.0 if metrics.get("has_privacy_page") else 0.0,
        "onboarding": min(1.0, metrics.get("onboarding_conversion_score", 0) / 4),
    }
    weights = {
        "seo": 0.20,
        "cta": 0.20,
        "value_prop": 0.15,
        "brand_coverage": 0.15,
        "privacy_page": 0.15,
        "onboarding": 0.15,
    }

    weighted_sum = sum(score_components.get(k, 0) * weights.get(k, 0) for k in weights)
    total_weight = sum(weights.values())
    readiness_score = round(weighted_sum / max(0.01, total_weight) * 100, 1)
    metrics["marketing_readiness_score"] = readiness_score

    duration = time.time() - start

    # Learning — record scan, findings, health snapshot
    ls = GTMLearningState(AGENT_NAME)
    ls.record_scan(metrics)

    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding(
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "file": f.file,
            }
        )
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("marketing_readiness_score", readiness_score)
    ls.track_kpi("total_jsx_pages", len(jsx_files))

    learning_updates = [f"Scanned {len(jsx_files)} pages, readiness={readiness_score}"]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return GTMTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        market_insights=insights,
        compliance_reviews=compliance_reviews,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: GTMTeamReport) -> Path:
    """Save report to gtm_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
