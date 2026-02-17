"""ModelEngineer agent — warm score calibration, cultural context evaluation, A/B framework audit.

Scans warm_scorer.py, ai_matcher.py, and related code to assess model quality infrastructure.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from data_team.shared.config import MODELS_DIR, SERVICES_DIR
from data_team.shared.learning import DataLearningState
from data_team.shared.report import DataTeamReport, Insight

logger = logging.getLogger(__name__)

AGENT_NAME = "model_engineer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_file_safe(path: Path) -> str:
    """Read file contents or return empty string."""
    try:
        return path.read_text()
    except (OSError, FileNotFoundError):
        return ""


def _extract_warm_score_weights(source: str) -> dict[str, float]:
    """Extract WEIGHT_* constants from warm_scorer.py."""
    weights: dict[str, float] = {}
    for match in re.finditer(r'WEIGHT_(\w+)\s*=\s*([\d.]+)', source):
        weights[match.group(1).lower()] = float(match.group(2))
    return weights


def _count_score_factors(source: str) -> int:
    """Count distinct scoring factors/bonuses in warm_scorer."""
    factors = set()
    # Look for numeric bonuses/penalties
    for match in re.finditer(r'[+-]=?\s*(\d+).*?#.*?(bonus|penalty|score|weight)', source, re.IGNORECASE):
        factors.add(match.group(0)[:50])
    # Look for score component assignments
    for match in re.finditer(r'(\w+_score)\s*[=+]', source):
        factors.add(match.group(1))
    return len(factors)


def _check_warm_score_algorithm(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Analyze warm score algorithm for calibration readiness."""
    scorer_path = SERVICES_DIR / "warm_scorer.py"
    source = _read_file_safe(scorer_path)
    if not source:
        findings.append(Finding(
            id="model-001",
            severity="high",
            category="model_calibration",
            title="Warm scorer service not found",
            detail="app/services/warm_scorer.py missing",
            recommendation="Warm score is the core ranking signal — verify it exists",
        ))
        return

    # Extract weights
    weights = _extract_warm_score_weights(source)
    metrics["warm_score_weights"] = weights
    metrics["warm_score_features_count"] = _count_score_factors(source)

    # Verify weights sum to ~1.0
    weight_sum = sum(weights.values())
    if weights and abs(weight_sum - 1.0) > 0.01:
        findings.append(Finding(
            id="model-002",
            severity="medium",
            category="model_calibration",
            title=f"Warm score weights sum to {weight_sum:.2f}, not 1.0",
            detail=f"Weights: {weights}",
            file=str(scorer_path),
            recommendation="Normalize weights to sum to 1.0 for interpretability",
        ))

    # Check for algorithm version
    if "ALGORITHM_VERSION" not in source:
        findings.append(Finding(
            id="model-003",
            severity="low",
            category="model_calibration",
            title="No ALGORITHM_VERSION constant in warm scorer",
            detail="Version tracking helps with A/B testing and calibration history",
            file=str(scorer_path),
            recommendation="Add ALGORITHM_VERSION for audit trail",
        ))

    # Check for referral_likelihood thresholds
    if "referral_likelihood" in source or "high" in source:
        metrics["referral_likelihood_defined"] = True
    else:
        metrics["referral_likelihood_defined"] = False
        findings.append(Finding(
            id="model-004",
            severity="medium",
            category="model_calibration",
            title="Referral likelihood thresholds not found",
            detail="Expected high/medium/low bucketing based on warm_score",
            file=str(scorer_path),
            recommendation="Define referral_likelihood thresholds for outcome tracking",
        ))

    insights.append(Insight(
        id="model-insight-001",
        category="model",
        title="Warm score algorithm assessment",
        evidence=f"4-component model: {list(weights.keys())}, {metrics['warm_score_features_count']} scoring factors",
        impact="Score accuracy directly affects referral success rate for job seekers",
        recommendation="Add outcome feedback loop — correlate warm_score with intro approval rate",
        confidence=0.8,
        sample_size=0,
        actionable_by="model_engineer",
    ))


def _check_outcome_tracking(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check if outcome data can be correlated with warm_score."""
    # Check warm_scores table for calibration-ready columns
    match_model = MODELS_DIR / "match_result.py"
    source = _read_file_safe(match_model)

    if not source:
        return

    # Check for user_feedback column
    has_feedback = "user_feedback" in source
    metrics["outcome_feedback_column"] = has_feedback

    if not has_feedback:
        findings.append(Finding(
            id="model-005",
            severity="high",
            category="model_calibration",
            title="No user_feedback column in match_results",
            detail="Cannot correlate warm_score predictions with actual outcomes",
            file=str(match_model),
            recommendation="Add user_feedback column to enable calibration loop",
        ))

    # Check for score_factors JSONB
    has_score_factors = "score_factors" in source
    metrics["score_factors_stored"] = has_score_factors

    # Check warm_scores table
    warm_score_in_match = "warm_score" in source or "WarmScore" in source
    metrics["warm_score_in_match_model"] = warm_score_in_match


def _check_cultural_context(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Analyze cultural context engine."""
    matcher_path = SERVICES_DIR / "ai_matcher.py"
    source = _read_file_safe(matcher_path)

    if not source:
        findings.append(Finding(
            id="model-006",
            severity="medium",
            category="model_calibration",
            title="AI matcher service not found",
            detail="app/services/ai_matcher.py missing",
            recommendation="Cultural context is a key differentiator — verify it exists",
        ))
        return

    # Count cultural context variants
    approach_styles = set(re.findall(r'["\'](\w+(?:-\w+)*)["\']', source))
    cultural_keywords = {"direct", "formal", "casual", "relationship-first", "formal-indirect"}
    found_styles = approach_styles & cultural_keywords
    metrics["cultural_context_variants"] = len(found_styles)

    # Check for cultural_context JSONB field
    has_cultural_context = "cultural_context" in source
    metrics["cultural_context_in_matcher"] = has_cultural_context

    if has_cultural_context:
        insights.append(Insight(
            id="model-insight-002",
            category="model",
            title="Cultural context engine assessment",
            evidence=f"Found {len(found_styles)} approach styles in AI matcher",
            impact="Cultural adaptation is a differentiator — needs effectiveness tracking",
            recommendation="Track which approach_style leads to highest response rate",
            confidence=0.7,
            sample_size=0,
            actionable_by="model_engineer",
        ))


def _check_ai_token_usage(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Estimate AI token usage patterns from matcher/drafter code."""
    for service_name in ["ai_matcher.py", "intro_drafter.py"]:
        path = SERVICES_DIR / service_name
        source = _read_file_safe(path)
        if not source:
            continue

        # Check for token counting or cost awareness
        has_token_tracking = any(
            kw in source.lower()
            for kw in ["token", "max_tokens", "usage", "cost"]
        )
        metrics[f"{service_name}_token_aware"] = has_token_tracking

        # Check for AI_MOCK_MODE awareness
        has_mock_mode = "AI_MOCK_MODE" in source or "mock" in source.lower()
        metrics[f"{service_name}_mock_mode"] = has_mock_mode

    # Check for prompt length
    matcher_source = _read_file_safe(SERVICES_DIR / "ai_matcher.py")
    prompt_blocks = re.findall(r'""".*?"""', matcher_source, re.DOTALL)
    total_prompt_chars = sum(len(p) for p in prompt_blocks)
    metrics["ai_prompt_total_chars"] = total_prompt_chars

    if total_prompt_chars > 5000:
        findings.append(Finding(
            id="model-007",
            severity="low",
            category="model_calibration",
            title=f"AI prompts total {total_prompt_chars} chars — consider optimization",
            detail="Large prompts increase token cost per user",
            recommendation="Review prompts for redundancy; consider caching common patterns",
        ))


def _check_ab_testing_readiness(
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check if A/B testing infrastructure exists or can be built."""
    # Look for experiment-related tables or columns
    models_source = ""
    for path in MODELS_DIR.glob("*.py"):
        models_source += _read_file_safe(path)

    has_experiment_table = "experiment" in models_source.lower()
    has_variant_column = "variant" in models_source.lower() or "bucket" in models_source.lower()
    metrics["ab_testing_table"] = has_experiment_table
    metrics["ab_testing_variant_col"] = has_variant_column
    metrics["outcome_tracking_ready"] = has_experiment_table or has_variant_column

    if not has_experiment_table:
        findings.append(Finding(
            id="model-008",
            severity="low",
            category="model_calibration",
            title="No A/B experiment table found",
            detail="Cannot run controlled experiments on warm score algorithm or message variants",
            recommendation="Add experiment/variant table for warm score v2 calibration",
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> DataTeamReport:
    """Run all model engineer checks and return a DataTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[Insight] = []
    metrics: dict = {}

    _check_warm_score_algorithm(findings, insights, metrics)
    _check_outcome_tracking(findings, metrics)
    _check_cultural_context(findings, insights, metrics)
    _check_ai_token_usage(findings, metrics)
    _check_ab_testing_readiness(findings, metrics)

    duration = time.time() - start

    # Learning
    ls = DataLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    for f in findings:
        ls.record_finding({"id": f.id, "severity": f.severity, "category": f.category, "title": f.title})

    return DataTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        insights=insights,
        metrics=metrics,
        learning_updates=[f"Analyzed warm score ({metrics.get('warm_score_features_count', 0)} features), "
                         f"cultural context ({metrics.get('cultural_context_variants', 0)} styles)"],
    )


def save_report(report: DataTeamReport) -> Path:
    """Save report to data_team/reports/."""
    from data_team.shared.config import REPORTS_DIR
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
