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
    for match in re.finditer(r"WEIGHT_(\w+)\s*=\s*([\d.]+)", source):
        weights[match.group(1).lower()] = float(match.group(2))
    return weights


def _count_score_factors(source: str) -> int:
    """Count distinct scoring factors/bonuses in warm_scorer."""
    factors = set()
    # Look for numeric bonuses/penalties
    for match in re.finditer(
        r"[+-]=?\s*(\d+).*?#.*?(bonus|penalty|score|weight)", source, re.IGNORECASE
    ):
        factors.add(match.group(0)[:50])
    # Look for score component assignments
    for match in re.finditer(r"(\w+_score)\s*[=+]", source):
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
        findings.append(
            Finding(
                id="model-001",
                severity="high",
                category="model_calibration",
                title="Warm scorer service not found",
                detail="app/services/warm_scorer.py missing",
                recommendation="Warm score is the core ranking signal — verify it exists",
            )
        )
        return

    # Extract weights
    weights = _extract_warm_score_weights(source)
    metrics["warm_score_weights"] = weights
    metrics["warm_score_features_count"] = _count_score_factors(source)

    # Verify weights sum to ~1.0
    weight_sum = sum(weights.values())
    if weights and abs(weight_sum - 1.0) > 0.01:
        findings.append(
            Finding(
                id="model-002",
                severity="medium",
                category="model_calibration",
                title=f"Warm score weights sum to {weight_sum:.2f}, not 1.0",
                detail=f"Weights: {weights}",
                file=str(scorer_path),
                recommendation="Normalize weights to sum to 1.0 for interpretability",
            )
        )

    # Check for algorithm version
    if "ALGORITHM_VERSION" not in source:
        findings.append(
            Finding(
                id="model-003",
                severity="low",
                category="model_calibration",
                title="No ALGORITHM_VERSION constant in warm scorer",
                detail="Version tracking helps with A/B testing and calibration history",
                file=str(scorer_path),
                recommendation="Add ALGORITHM_VERSION for audit trail",
            )
        )

    # Check for referral_likelihood thresholds
    if "referral_likelihood" in source or "high" in source:
        metrics["referral_likelihood_defined"] = True
    else:
        metrics["referral_likelihood_defined"] = False
        findings.append(
            Finding(
                id="model-004",
                severity="medium",
                category="model_calibration",
                title="Referral likelihood thresholds not found",
                detail="Expected high/medium/low bucketing based on warm_score",
                file=str(scorer_path),
                recommendation="Define referral_likelihood thresholds for outcome tracking",
            )
        )

    insights.append(
        Insight(
            id="model-insight-001",
            category="model",
            title="Warm score algorithm assessment",
            evidence=f"4-component model: {list(weights.keys())}, {metrics['warm_score_features_count']} scoring factors",
            impact="Score accuracy directly affects referral success rate for job seekers",
            recommendation="Add outcome feedback loop — correlate warm_score with intro approval rate",
            confidence=0.8,
            sample_size=0,
            actionable_by="model_engineer",
        )
    )


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
        findings.append(
            Finding(
                id="model-005",
                severity="high",
                category="model_calibration",
                title="No user_feedback column in match_results",
                detail="Cannot correlate warm_score predictions with actual outcomes",
                file=str(match_model),
                recommendation="Add user_feedback column to enable calibration loop",
            )
        )

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
        findings.append(
            Finding(
                id="model-006",
                severity="medium",
                category="model_calibration",
                title="AI matcher service not found",
                detail="app/services/ai_matcher.py missing",
                recommendation="Cultural context is a key differentiator — verify it exists",
            )
        )
        return

    # Count cultural context variants
    approach_styles = set(re.findall(r'["\'](\w+(?:-\w+)*)["\']', source))
    cultural_keywords = {
        "direct",
        "formal",
        "casual",
        "relationship-first",
        "formal-indirect",
    }
    found_styles = approach_styles & cultural_keywords
    metrics["cultural_context_variants"] = len(found_styles)

    # Check for cultural_context JSONB field
    has_cultural_context = "cultural_context" in source
    metrics["cultural_context_in_matcher"] = has_cultural_context

    if has_cultural_context:
        insights.append(
            Insight(
                id="model-insight-002",
                category="model",
                title="Cultural context engine assessment",
                evidence=f"Found {len(found_styles)} approach styles in AI matcher",
                impact="Cultural adaptation is a differentiator — needs effectiveness tracking",
                recommendation="Track which approach_style leads to highest response rate",
                confidence=0.7,
                sample_size=0,
                actionable_by="model_engineer",
            )
        )


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
            kw in source.lower() for kw in ["token", "max_tokens", "usage", "cost"]
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
        findings.append(
            Finding(
                id="model-007",
                severity="low",
                category="model_calibration",
                title=f"AI prompts total {total_prompt_chars} chars — consider optimization",
                detail="Large prompts increase token cost per user",
                recommendation="Review prompts for redundancy; consider caching common patterns",
            )
        )


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
    has_variant_column = (
        "variant" in models_source.lower() or "bucket" in models_source.lower()
    )
    metrics["ab_testing_table"] = has_experiment_table
    metrics["ab_testing_variant_col"] = has_variant_column
    metrics["outcome_tracking_ready"] = has_experiment_table or has_variant_column

    if not has_experiment_table:
        findings.append(
            Finding(
                id="model-008",
                severity="low",
                category="model_calibration",
                title="No A/B experiment table found",
                detail="Cannot run controlled experiments on warm score algorithm or message variants",
                recommendation="Add experiment/variant table for warm score v2 calibration",
            )
        )


# ---------------------------------------------------------------------------
# Live model analytics (requires DATABASE_URL)
# ---------------------------------------------------------------------------


def _scan_warm_score_calibration(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Correlate warm_score bands with actual intro approval rates.

    Runs WARM_SCORE_VS_OUTCOME template and checks whether higher scores
    correspond to higher approval rates (the fundamental assumption).
    """
    from data_team.shared.query_executor import get_executor

    qe = get_executor()
    if not qe.is_available():
        metrics["warm_score_calibration_available"] = False
        return

    metrics["warm_score_calibration_available"] = True

    # Run approval rate query — aggregated, no user_id filter needed
    approval_sql = """
    SELECT
        CASE
            WHEN ws.total_score >= 80 THEN 'high'
            WHEN ws.total_score >= 50 THEN 'medium'
            ELSE 'low'
        END AS score_band,
        COUNT(*) AS total_intros,
        COUNT(CASE WHEN inf.status = 'approved' THEN 1 END) AS approved
    FROM warm_scores ws
    JOIN intro_facilitations inf ON inf.contact_id = ws.contact_id
    GROUP BY score_band
    HAVING COUNT(*) >= 5
    """
    rows = qe.execute_sql(approval_sql, context="warm_score_calibration")

    if not rows:
        metrics["warm_score_sample_size"] = 0
        return

    total_sample = sum(r.get("total_intros", 0) for r in rows)
    metrics["warm_score_sample_size"] = total_sample

    # Build band → approval_rate map
    band_rates: dict[str, float] = {}
    for row in rows:
        band = row.get("score_band", "unknown")
        total = row.get("total_intros", 0) or 0
        approved = row.get("approved", 0) or 0
        if total > 0:
            band_rates[band] = round(approved / total, 3)

    metrics["warm_score_band_rates"] = band_rates

    # Core validation: high > medium > low
    high_rate = band_rates.get("high", 0)
    medium_rate = band_rates.get("medium", 0)
    low_rate = band_rates.get("low", 0)

    monotonic = high_rate >= medium_rate >= low_rate
    metrics["warm_score_monotonic"] = monotonic

    if not monotonic and total_sample >= 30:
        findings.append(
            Finding(
                id="model-009",
                severity="high",
                category="model_calibration",
                title="Warm score is miscalibrated — higher scores don't predict better outcomes",
                detail=(
                    f"Approval rates: high={high_rate:.0%}, "
                    f"medium={medium_rate:.0%}, low={low_rate:.0%} "
                    f"(n={total_sample})"
                ),
                recommendation=(
                    "Recalibrate warm_score weights. Consider: "
                    "1) Run regression on outcome data to find optimal weights, "
                    "2) Add outcome-based recency bias, "
                    "3) Test with/without cultural context"
                ),
            )
        )

    insights.append(
        Insight(
            id="model-insight-calibration",
            category="model",
            title="Warm score outcome correlation",
            evidence=(
                f"Bands: high={high_rate:.0%}, med={medium_rate:.0%}, "
                f"low={low_rate:.0%} | monotonic={monotonic} | n={total_sample}"
            ),
            impact="Miscalibrated scores waste job seeker credits on unlikely intros",
            recommendation=(
                "Target: high band ≥60% approval, low band ≤30%. "
                "Recalibrate if inverted."
            ),
            confidence=0.9 if total_sample >= 100 else 0.6,
            statistical_significance=total_sample >= 100,
            sample_size=total_sample,
            actionable_by="model_engineer",
        )
    )


def _scan_ab_test_analysis(
    findings: list[Finding],
    insights: list[Insight],
    metrics: dict,
) -> None:
    """Analyse A/B experiment results if experiment data exists.

    Runs CULTURAL_CONTEXT_EFFECTIVENESS to compare approach styles.
    """
    from data_team.shared.query_executor import get_executor

    qe = get_executor()
    if not qe.is_available():
        metrics["ab_test_analysis_available"] = False
        return

    metrics["ab_test_analysis_available"] = True

    # Cultural context as a natural experiment
    context_sql = """
    SELECT
        mr.cultural_context->>'approach_style' AS approach_style,
        COUNT(*) AS total_matches,
        AVG(CASE WHEN mr.user_feedback = 'positive' THEN 1.0 ELSE 0.0 END) AS positive_rate
    FROM match_results mr
    WHERE mr.cultural_context IS NOT NULL
        AND mr.user_feedback IS NOT NULL
    GROUP BY mr.cultural_context->>'approach_style'
    HAVING COUNT(*) >= 5
    """
    rows = qe.execute_sql(context_sql, context="ab_test:cultural_context")

    if not rows:
        metrics["ab_test_variants_tested"] = 0
        return

    metrics["ab_test_variants_tested"] = len(rows)
    total_matches = sum(r.get("total_matches", 0) for r in rows)
    metrics["ab_test_total_samples"] = total_matches

    # Find best and worst performing styles
    by_rate = sorted(rows, key=lambda r: r.get("positive_rate", 0), reverse=True)
    best = by_rate[0]
    worst = by_rate[-1]

    best_style = best.get("approach_style", "unknown")
    best_rate = best.get("positive_rate", 0)
    worst_style = worst.get("approach_style", "unknown")
    worst_rate = worst.get("positive_rate", 0)

    metrics["ab_test_best_style"] = best_style
    metrics["ab_test_best_rate"] = round(best_rate, 3)
    metrics["ab_test_worst_style"] = worst_style
    metrics["ab_test_worst_rate"] = round(worst_rate, 3)

    # Significant difference?
    rate_gap = best_rate - worst_rate
    if rate_gap > 0.15 and total_matches >= 50:
        findings.append(
            Finding(
                id="model-010",
                severity="medium",
                category="model_calibration",
                title=f"Cultural context '{best_style}' outperforms '{worst_style}' by {rate_gap:.0%}",
                detail=(
                    f"Best: {best_style} ({best_rate:.0%}), "
                    f"Worst: {worst_style} ({worst_rate:.0%}), "
                    f"n={total_matches}"
                ),
                recommendation=(
                    "Consider defaulting to the higher-performing approach style "
                    "or refining the lower-performing variant"
                ),
            )
        )

    insights.append(
        Insight(
            id="model-insight-ab",
            category="model",
            title="Cultural context effectiveness analysis",
            evidence=(
                f"{len(rows)} styles tested across {total_matches} matches. "
                f"Best: {best_style} ({best_rate:.0%}), "
                f"worst: {worst_style} ({worst_rate:.0%})"
            ),
            impact="Approach style directly affects response rate and user satisfaction",
            recommendation="Route users to highest-performing style for their context",
            confidence=0.8 if total_matches >= 100 else 0.5,
            statistical_significance=total_matches >= 100 and rate_gap > 0.10,
            sample_size=total_matches,
            actionable_by="model_engineer",
        )
    )


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
    _scan_warm_score_calibration(findings, insights, metrics)
    _scan_ab_test_analysis(findings, insights, metrics)

    duration = time.time() - start

    # Learning — record scan, findings, attention weights, health snapshot
    ls = DataLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding(
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "file": getattr(f, "file", None),
            }
        )
        if getattr(f, "file", None):
            file_findings[f.file] = file_findings.get(f.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # Track KPIs
    ls.track_kpi("warm_score_features", metrics.get("warm_score_features_count", 0))
    ls.track_kpi(
        "cultural_context_variants", metrics.get("cultural_context_variants", 0)
    )

    # Record insights
    for i in insights:
        ls.record_insight(
            {
                "id": i.id,
                "category": i.category,
                "title": i.title,
                "confidence": i.confidence,
            }
        )

    learning_updates = [
        f"Analyzed warm score ({metrics.get('warm_score_features_count', 0)} features), "
        f"cultural context ({metrics.get('cultural_context_variants', 0)} styles)"
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )
    trajectory = ls.get_health_trajectory()
    if trajectory != "insufficient_data":
        learning_updates.append(f"Health trajectory: {trajectory}")

    return DataTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: DataTeamReport) -> Path:
    """Save report to data_team/reports/."""
    from data_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
