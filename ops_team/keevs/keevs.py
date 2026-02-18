"""Keevs agent -- job seeker coach quality auditor.

Scans coach_service.py, app/api/coach.py, and frontend JSX pages to verify
coaching service quality: system prompt coverage, context assembly completeness,
mock handler coverage, job seeker journey steps, streaming robustness.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from ops_team.shared.config import (
    API_DIR,
    COACH_JOURNEY_STEPS,
    COACH_KEYWORD_COVERAGE_TARGET,
    FRONTEND_SRC,
    PAGES_DIR,
)
from ops_team.shared.learning import OpsLearningState
from ops_team.shared.report import OpsInsight, OpsTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "keevs"

# Path to the coaching service owned by this agent
_COACH_SERVICE_PATH = Path(__file__).resolve().parent / "coach_service.py"
_COACH_API_PATH = API_DIR / "coach.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_jsx_files() -> list[Path]:
    """Return all .jsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted(PAGES_DIR.rglob("*.jsx"))


def _read_safe(path: Path) -> str:
    """Read file, returning empty string on failure."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    """Return path relative to project root."""
    try:
        return str(path.relative_to(FRONTEND_SRC.parent.parent))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_system_prompt_coverage(
    source: str,
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Verify _KEEVS_SYSTEM_PROMPT covers all expected coaching rules."""
    expected_rules: dict[str, re.Pattern] = {
        "referrals": re.compile(r"referral", re.IGNORECASE),
        "privacy_no_names": re.compile(
            r"(?:do\s+not\s+name|don.t\s+name|never\s+name|no\s+naming)", re.IGNORECASE
        ),
        "link_formatting": re.compile(r"markdown\s+link|\[.*\]\(/", re.IGNORECASE),
        "no_filler": re.compile(
            r"(?:no\s+filler|never\s+use.*filler|hope\s+this\s+finds)", re.IGNORECASE
        ),
        "actionable": re.compile(r"action(?:able|\.)", re.IGNORECASE),
        "briefing_format": re.compile(r"briefing", re.IGNORECASE),
        "chat_format": re.compile(r"chat", re.IGNORECASE),
        "data_reference": re.compile(
            r"(?:specific\s+data|reference.*data|never\s+generic)", re.IGNORECASE
        ),
    }

    # Extract the system prompt block (between the triple-quoted string markers)
    prompt_match = re.search(
        r'_KEEVS_SYSTEM_PROMPT\s*=\s*"""(.*?)"""', source, re.DOTALL
    )
    if not prompt_match:
        prompt_match = re.search(
            r"_KEEVS_SYSTEM_PROMPT\s*=\s*'''(.*?)'''", source, re.DOTALL
        )

    if not prompt_match:
        findings.append(
            Finding(
                id="keevs-prompt-001",
                severity="high",
                category="coaching_quality",
                title="System prompt not found in coach_service.py",
                detail="_KEEVS_SYSTEM_PROMPT variable not detected",
                file=_relative(_COACH_SERVICE_PATH),
                recommendation="Ensure _KEEVS_SYSTEM_PROMPT is defined as a triple-quoted string",
            )
        )
        metrics["prompt_rules_found"] = 0
        metrics["prompt_rules_expected"] = len(expected_rules)
        metrics["prompt_rule_coverage"] = 0.0
        return

    prompt_text = prompt_match.group(1)
    rules_found = 0
    missing_rules: list[str] = []

    for rule_name, pattern in expected_rules.items():
        if pattern.search(prompt_text):
            rules_found += 1
        else:
            missing_rules.append(rule_name)

    coverage = rules_found / max(1, len(expected_rules))
    metrics["prompt_rules_found"] = rules_found
    metrics["prompt_rules_expected"] = len(expected_rules)
    metrics["prompt_rule_coverage"] = round(coverage, 2)

    if missing_rules:
        severity = "high" if len(missing_rules) > 3 else "medium"
        findings.append(
            Finding(
                id="keevs-prompt-002",
                severity=severity,
                category="coaching_quality",
                title=f"System prompt missing {len(missing_rules)} coaching rules",
                detail=f"Missing rules: {', '.join(missing_rules)}",
                file=_relative(_COACH_SERVICE_PATH),
                recommendation="Add missing rule coverage to _KEEVS_SYSTEM_PROMPT",
            )
        )

    if coverage >= 0.75:
        insights.append(
            OpsInsight(
                id="keevs-insight-prompt",
                category="coaching",
                title=f"System prompt covers {coverage:.0%} of expected rules",
                evidence=f"{rules_found}/{len(expected_rules)} rules detected in prompt",
                impact="Coaching responses will be consistent with platform guidelines",
                recommendation="Maintain rule coverage as new scenarios are added",
                confidence=0.85,
                persona="job_seeker",
            )
        )


def _check_context_assembly(
    source: str,
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Verify _assemble_context pulls all expected data sources."""
    expected_sources: dict[str, re.Pattern] = {
        "user_profile": re.compile(
            r"(?:user\.full_name|user\.email|current_user|user_id)", re.IGNORECASE
        ),
        "preferences": re.compile(
            r"(?:UserJobPreferences|job_preferences|preferences)", re.IGNORECASE
        ),
        "network": re.compile(
            r"(?:network_analysis|_get_network_analysis|ConnectorProfile|contacts)",
            re.IGNORECASE,
        ),
        "pipeline": re.compile(r"(?:Application|applications|pipeline)", re.IGNORECASE),
        "searches": re.compile(
            r"(?:SearchRequest|search_request|searches)", re.IGNORECASE
        ),
        "credits": re.compile(r"(?:get_balance|credit|credits)", re.IGNORECASE),
        "market_trends": re.compile(
            r"(?:market_trends|_get_job_market_trends|market)", re.IGNORECASE
        ),
    }

    # Find the _assemble_context function body
    ctx_match = re.search(
        r"(?:async\s+)?def\s+_assemble_context\s*\(.*?\).*?(?=\n(?:async\s+)?def\s|\Z)",
        source,
        re.DOTALL,
    )
    search_text = ctx_match.group(0) if ctx_match else source

    sources_found = 0
    missing_sources: list[str] = []

    for source_name, pattern in expected_sources.items():
        if pattern.search(search_text):
            sources_found += 1
        else:
            missing_sources.append(source_name)

    metrics["context_sources_found"] = sources_found
    metrics["context_sources_expected"] = len(expected_sources)

    if missing_sources:
        findings.append(
            Finding(
                id="keevs-ctx-001",
                severity="high",
                category="coaching_quality",
                title=f"Context assembly missing {len(missing_sources)} data sources",
                detail=f"Missing sources: {', '.join(missing_sources)}",
                file=_relative(_COACH_SERVICE_PATH),
                recommendation="Add missing data sources to _assemble_context for richer coaching",
            )
        )

    if sources_found == len(expected_sources):
        insights.append(
            OpsInsight(
                id="keevs-insight-ctx",
                category="coaching",
                title="Context assembly pulls all expected data sources",
                evidence=f"{sources_found}/{len(expected_sources)} sources detected",
                impact="Coaching responses can reference full user context",
                recommendation="Keep context assembly in sync as new models are added",
                confidence=0.90,
                persona="job_seeker",
            )
        )


def _check_mock_handler_coverage(
    source: str,
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Check _mock_chat_response keyword handler coverage."""
    expected_keywords: list[str] = [
        "follow-up",
        "network",
        "company",
        "credit",
        "start",
        "pipeline",
    ]

    # Find the mock chat response function body
    mock_match = re.search(
        r"(?:async\s+)?def\s+_mock_chat_response\s*\(.*?\).*?(?=\n(?:async\s+)?def\s|\Z)",
        source,
        re.DOTALL,
    )

    if not mock_match:
        findings.append(
            Finding(
                id="keevs-mock-001",
                severity="medium",
                category="coaching_quality",
                title="_mock_chat_response function not found",
                detail="Mock mode handler missing from coach_service.py",
                file=_relative(_COACH_SERVICE_PATH),
                recommendation="Ensure _mock_chat_response exists for AI_MOCK_MODE=true",
            )
        )
        metrics["mock_handlers_found"] = 0
        metrics["mock_handlers_expected"] = len(expected_keywords)
        metrics["mock_handler_coverage"] = 0.0
        return

    mock_body = mock_match.group(0).lower()
    handlers_found = 0
    missing_handlers: list[str] = []

    for keyword in expected_keywords:
        # Match keyword in string literals or condition checks
        pattern = re.compile(
            rf'["\'].*?{re.escape(keyword)}.*?["\']|{re.escape(keyword)}', re.IGNORECASE
        )
        if pattern.search(mock_body):
            handlers_found += 1
        else:
            missing_handlers.append(keyword)

    coverage = handlers_found / max(1, len(expected_keywords))
    metrics["mock_handlers_found"] = handlers_found
    metrics["mock_handlers_expected"] = len(expected_keywords)
    metrics["mock_handler_coverage"] = round(coverage, 2)

    if coverage < COACH_KEYWORD_COVERAGE_TARGET:
        findings.append(
            Finding(
                id="keevs-mock-002",
                severity="medium",
                category="coaching_quality",
                title=f"Mock handler coverage ({coverage:.0%}) below target ({COACH_KEYWORD_COVERAGE_TARGET:.0%})",
                detail=f"Missing handlers: {', '.join(missing_handlers)}",
                file=_relative(_COACH_SERVICE_PATH),
                recommendation="Add keyword handlers for missing job seeker scenarios in mock mode",
            )
        )
    else:
        insights.append(
            OpsInsight(
                id="keevs-insight-mock",
                category="coaching",
                title=f"Mock handler coverage meets target ({coverage:.0%})",
                evidence=f"{handlers_found}/{len(expected_keywords)} keyword handlers present",
                impact="AI_MOCK_MODE=true returns meaningful responses for all common queries",
                recommendation="Add handlers for new scenarios as they emerge",
                confidence=0.80,
                persona="job_seeker",
            )
        )


def _check_journey_coverage(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Verify frontend pages reference each job seeker journey step."""
    # Map journey steps to search patterns in JSX
    step_patterns: dict[str, re.Pattern] = {
        "signup": re.compile(
            r"(?:sign\s*up|register|create\s*account|onboarding|Login|Auth)",
            re.IGNORECASE,
        ),
        "upload": re.compile(r"(?:upload|csv|import|contacts|file)", re.IGNORECASE),
        "search": re.compile(r"(?:search|find|referral|match|discover)", re.IGNORECASE),
        "message": re.compile(
            r"(?:message|intro|draft|outreach|connect|facilitat)", re.IGNORECASE
        ),
        "track": re.compile(
            r"(?:track|application|pipeline|status|progress|dashboard)", re.IGNORECASE
        ),
        "interview": re.compile(
            r"(?:interview|prep|prepare|coach|briefing|practice)", re.IGNORECASE
        ),
    }

    # Pre-read all JSX content once
    jsx_contents: dict[str, str] = {}
    for path in jsx_files:
        content = _read_safe(path)
        if content:
            jsx_contents[_relative(path)] = content

    covered_steps: list[str] = []
    missing_steps: list[str] = []

    for step in COACH_JOURNEY_STEPS:
        pattern = step_patterns.get(step)
        if not pattern:
            missing_steps.append(step)
            continue

        found = False
        for _rel_path, content in jsx_contents.items():
            if pattern.search(content):
                found = True
                break

        if found:
            covered_steps.append(step)
        else:
            missing_steps.append(step)

    coverage = len(covered_steps) / max(1, len(COACH_JOURNEY_STEPS))
    metrics["journey_steps_covered"] = len(covered_steps)
    metrics["journey_steps_total"] = len(COACH_JOURNEY_STEPS)
    metrics["journey_coverage"] = round(coverage, 2)
    metrics["journey_covered_list"] = covered_steps
    metrics["journey_missing_list"] = missing_steps

    if missing_steps:
        findings.append(
            Finding(
                id="keevs-journey-001",
                severity="medium",
                category="coaching_quality",
                title=f"Job seeker journey missing {len(missing_steps)} steps in frontend",
                detail=f"Missing steps: {', '.join(missing_steps)}",
                recommendation="Add frontend pages or components covering missing journey steps",
            )
        )

    if coverage >= 0.80:
        insights.append(
            OpsInsight(
                id="keevs-insight-journey",
                category="coaching",
                title=f"Job seeker journey coverage at {coverage:.0%}",
                evidence=f"Covered: {', '.join(covered_steps)}",
                impact="Most journey steps have corresponding frontend touchpoints",
                recommendation="Fill remaining gaps to complete the end-to-end experience",
                confidence=0.75,
                persona="job_seeker",
            )
        )


def _check_streaming_robustness(
    api_source: str,
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Verify SSE streaming in app/api/coach.py handles timeout, concurrency, sanitisation."""
    checks: dict[str, re.Pattern] = {
        "sse_timeout": re.compile(
            r"(?:SSE_TIMEOUT|timeout|wait_for|asyncio\.timeout)", re.IGNORECASE
        ),
        "concurrent_limit": re.compile(
            r"(?:MAX_CONCURRENT|_active_streams|concurrent|stream.*limit)",
            re.IGNORECASE,
        ),
        "sanitisation": re.compile(
            r"(?:sanitiz|escap|strip|clean|replace.*<|html)", re.IGNORECASE
        ),
        "cancelled_error": re.compile(
            r"(?:CancelledError|asyncio\.CancelledError|cancel)", re.IGNORECASE
        ),
    }

    passed = 0
    failed_checks: list[str] = []

    for check_name, pattern in checks.items():
        if pattern.search(api_source):
            passed += 1
        else:
            failed_checks.append(check_name)

    metrics["streaming_checks_passed"] = passed
    metrics["streaming_checks_total"] = len(checks)

    if failed_checks:
        findings.append(
            Finding(
                id="keevs-stream-001",
                severity="high",
                category="streaming_robustness",
                title=f"SSE streaming missing {len(failed_checks)} safety checks",
                detail=f"Missing: {', '.join(failed_checks)}",
                file=_relative(_COACH_API_PATH),
                recommendation="Add missing SSE safety checks to app/api/coach.py",
            )
        )


def _check_frontend_integration(
    jsx_files: list[Path],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check JSX pages for coaching API calls and imports."""
    coach_api_pattern = re.compile(
        r"(?:/coach|/briefing|/api/v1/coach|coach_briefing|coaching)", re.IGNORECASE
    )
    coaching_import_pattern = re.compile(
        r"(?:import.*coach|from.*coach|useCoach|CoachChat|Briefing)", re.IGNORECASE
    )

    files_with_api_calls = 0
    files_with_imports = 0

    for path in jsx_files:
        content = _read_safe(path)
        if not content:
            continue

        if coach_api_pattern.search(content):
            files_with_api_calls += 1
        if coaching_import_pattern.search(content):
            files_with_imports += 1

    metrics["frontend_coach_api_refs"] = files_with_api_calls
    metrics["frontend_coach_imports"] = files_with_imports

    if files_with_api_calls == 0:
        findings.append(
            Finding(
                id="keevs-frontend-001",
                severity="medium",
                category="coaching_quality",
                title="No frontend pages reference coaching API endpoints",
                detail="No JSX pages in frontend/src/pages/ call /coach or /briefing",
                recommendation="Integrate coaching API calls into relevant frontend pages",
            )
        )


def _check_live_coaching_quality(
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Test coach mock handler quality by running test scenarios."""
    try:
        from ops_team.keevs.coach_service import _mock_chat_response
    except ImportError:
        findings.append(
            Finding(
                id="keevs-live-001",
                severity="info",
                category="coaching_quality",
                title="Could not import coach_service for live quality testing",
                recommendation="Ensure ops_team/keevs/coach_service.py exists",
            )
        )
        return

    test_scenarios = [
        ("How should I follow up with my contact at Google?", "follow-up"),
        ("Which companies in my network are hiring?", "network"),
        ("How do I use my credits?", "credits"),
        ("Help me get started", "getting started"),
        ("What's my pipeline looking like?", "pipeline"),
    ]

    test_context = {
        "user": {"name": "Test User", "type": "job_seeker"},
        "preferences": {"target_role": "Software Engineer"},
        "network": {"total_contacts": 50, "top_companies": ["Google", "Meta"]},
        "pipeline": {"active": 3, "follow_ups_due": 1},
        "recent_searches": [],
        "credits": {"balance": 100},
        "market_trends": {},
    }

    passed = 0
    total_length = 0
    failures: list[str] = []

    for message, scenario_name in test_scenarios:
        try:
            response = _mock_chat_response(message, test_context)
            length = len(response)
            total_length += length
            if length >= 50:
                passed += 1
            else:
                failures.append(f"{scenario_name}: response too short ({length} chars)")
        except Exception as exc:
            failures.append(f"{scenario_name}: error — {exc}")

    tested = len(test_scenarios)
    pass_rate = passed / max(1, tested)
    avg_length = total_length / max(1, tested)

    metrics["live_coaching_scenarios_tested"] = tested
    metrics["live_coaching_test_pass_rate"] = round(pass_rate, 2)
    metrics["live_coaching_avg_response_length"] = round(avg_length, 0)

    if pass_rate < 0.8:
        findings.append(
            Finding(
                id="keevs-live-002",
                severity="high",
                category="coaching_quality",
                title=f"Coaching response quality below threshold ({pass_rate:.0%})",
                detail=f"Failures: {'; '.join(failures)}",
                recommendation="Review _mock_chat_response handlers for short/missing responses",
            )
        )
    else:
        insights.append(
            OpsInsight(
                id="keevs-live-ins-001",
                category="coaching",
                title=f"Live coaching quality test: {pass_rate:.0%} pass rate",
                evidence=f"{passed}/{tested} scenarios passed, avg length {avg_length:.0f} chars",
                impact="Mock coaching responses meet quality bar for test scenarios",
                recommendation="Expand test scenarios as new coaching features are added",
                confidence=0.85,
                persona="job_seeker",
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> OpsTeamReport:
    """Run all coaching quality checks and return an OpsTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[OpsInsight] = []
    metrics: dict = {}

    # --- Read source files ---------------------------------------------------

    coach_source = ""
    try:
        coach_source = _COACH_SERVICE_PATH.read_text(errors="replace")
    except OSError:
        findings.append(
            Finding(
                id="keevs-io-001",
                severity="high",
                category="coaching_quality",
                title="Could not read coach_service.py",
                detail=f"Expected at {_COACH_SERVICE_PATH}",
                recommendation="Ensure coach_service.py exists in ops_team/keevs/",
            )
        )

    api_source = ""
    try:
        api_source = _COACH_API_PATH.read_text(errors="replace")
    except OSError:
        findings.append(
            Finding(
                id="keevs-io-002",
                severity="medium",
                category="streaming_robustness",
                title="Could not read app/api/coach.py",
                detail=f"Expected at {_COACH_API_PATH}",
                recommendation="Ensure app/api/coach.py exists for SSE streaming checks",
            )
        )

    jsx_files = _find_jsx_files()
    metrics["total_jsx_pages"] = len(jsx_files)

    # --- Run checks ----------------------------------------------------------

    if coach_source:
        _check_system_prompt_coverage(coach_source, findings, insights, metrics)
        _check_context_assembly(coach_source, findings, insights, metrics)
        _check_mock_handler_coverage(coach_source, findings, insights, metrics)

    if jsx_files:
        _check_journey_coverage(jsx_files, findings, insights, metrics)
        _check_frontend_integration(jsx_files, findings, metrics)
    else:
        findings.append(
            Finding(
                id="keevs-jsx-001",
                severity="info",
                category="coaching_quality",
                title="No JSX page files found in frontend/src/pages/",
                detail="Frontend may not be initialised yet",
                recommendation="Initialise React frontend under frontend/src/pages/",
            )
        )

    if api_source:
        _check_streaming_robustness(api_source, findings, metrics)

    # --- Live coaching quality test -------------------------------------------
    _check_live_coaching_quality(findings, insights, metrics)

    # --- Compute coaching quality score --------------------------------------

    score_components = [
        metrics.get("prompt_rule_coverage", 0),
        (
            metrics.get("context_sources_found", 0)
            / max(1, metrics.get("context_sources_expected", 1))
        ),
        metrics.get("mock_handler_coverage", 0),
        metrics.get("journey_coverage", 0),
        (
            metrics.get("streaming_checks_passed", 0)
            / max(1, metrics.get("streaming_checks_total", 1))
        ),
    ]
    coaching_quality_score = round(
        sum(score_components) / max(1, len(score_components)) * 100, 1
    )
    metrics["coaching_quality_score"] = coaching_quality_score

    duration = time.time() - start

    # --- Learning state ------------------------------------------------------

    ls = OpsLearningState(AGENT_NAME)
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

    for ins in insights:
        ls.record_insight(
            {
                "id": ins.id,
                "category": ins.category,
                "title": ins.title,
                "confidence": ins.confidence,
            }
        )

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # KPI tracking
    ls.track_kpi("coaching_quality_score", coaching_quality_score)
    ls.track_kpi("prompt_rule_coverage", metrics.get("prompt_rule_coverage", 0))
    ls.track_kpi("context_sources_found", metrics.get("context_sources_found", 0))
    ls.track_kpi("mock_handler_coverage", metrics.get("mock_handler_coverage", 0))
    ls.track_kpi("journey_coverage", metrics.get("journey_coverage", 0))

    # Learning summary
    learning_updates = [
        f"Scanned coach_service.py + {len(jsx_files)} JSX pages, quality={coaching_quality_score}",
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return OpsTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        ops_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: OpsTeamReport) -> Path:
    """Save report to ops_team/reports/."""
    from ops_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
