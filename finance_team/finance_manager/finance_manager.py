"""finance_manager agent — financial health scanner.

Scans the codebase for financial health signals:
  1. Stripe webhook handler coverage (expected events vs. implemented handlers)
  2. Credit purchase endpoint presence and Stripe integration
  3. Subscription model coverage (model classes, service management)
  4. Agent team run costs (aggregated from all team report directories)
  5. Billing instrumentation (audit trail, usage tracking, completeness)
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from finance_team.shared.config import (
    API_DIR,
    EXPECTED_STRIPE_EVENTS,
    MODELS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    SERVICES_DIR,
)
from finance_team.shared.learning import FinanceLearningState
from finance_team.shared.report import CostSnapshot, FinancialFinding, FinanceTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "finance_manager"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read file, returning empty string on any error."""
    try:
        return path.read_text(errors="replace")
    except OSError as exc:
        logger.warning("finance_manager: could not read %s: %s", path, exc)
        return ""


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT for cleaner report output."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check 1: Stripe webhook handlers
# ---------------------------------------------------------------------------


def _check_stripe_webhook_handlers(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Read app/api/webhooks.py and check EXPECTED_STRIPE_EVENTS coverage.

    Verifies:
    - stripe.Webhook.construct_event or manual HMAC verification is present
    - Each expected event type string appears in the handler source
    """
    webhooks_path = API_DIR / "webhooks.py"
    source = _read_safe(webhooks_path)
    rel_path = _relative(webhooks_path)

    if not source:
        findings.append(
            Finding(
                id="finmgr-webhook-000",
                severity="critical",
                category="stripe_integration",
                title="Stripe webhook handler file not found",
                detail=f"Could not read {rel_path}",
                file=rel_path,
                recommendation="Create app/api/webhooks.py with a Stripe webhook endpoint",
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-webhook-000",
                category="stripe_integration",
                severity="critical",
                title="Stripe webhook file missing — no payment events can be processed",
                file=rel_path,
                detail="Without a webhook handler, Stripe events (payments, subscriptions) are silently dropped",
                recommendation="Implement app/api/webhooks.py with verified Stripe event handling",
            )
        )
        metrics["webhook_events_found"] = 0
        metrics["webhook_events_expected"] = len(EXPECTED_STRIPE_EVENTS)
        metrics["webhook_event_coverage"] = 0.0
        metrics["has_signature_verification"] = False
        return

    # Check for signature verification — accept either Stripe library or manual HMAC
    has_signature_verification = bool(
        re.search(
            r"(?:stripe\.Webhook\.construct_event|_verify_stripe_signature|hmac\.new|hmac\.compare_digest"
            r"|STRIPE_WEBHOOK_SECRET|stripe-signature)",
            source,
            re.IGNORECASE,
        )
    )
    metrics["has_signature_verification"] = has_signature_verification

    if not has_signature_verification:
        findings.append(
            Finding(
                id="finmgr-webhook-001",
                severity="critical",
                category="stripe_integration",
                title="Stripe webhook signature verification not found",
                detail="stripe.Webhook.construct_event or manual HMAC verification absent",
                file=rel_path,
                recommendation=(
                    "Add Stripe signature verification to prevent fake payment events from "
                    "granting free credits (critical security + financial integrity requirement)"
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-webhook-001",
                category="stripe_integration",
                severity="critical",
                title="Webhook accepts unsigned events — payment fraud risk",
                file=rel_path,
                detail="Attackers can POST fake checkout.session.completed events to grant unlimited credits",
                recommendation="Verify HMAC-SHA256 signature on every incoming webhook request",
            )
        )

    # Check for each expected Stripe event type
    events_found: list[str] = []
    events_missing: list[str] = []

    for event in EXPECTED_STRIPE_EVENTS:
        # Look for the event string in source (quoted or in condition)
        if re.search(re.escape(event), source):
            events_found.append(event)
        else:
            events_missing.append(event)

    metrics["webhook_events_found"] = len(events_found)
    metrics["webhook_events_expected"] = len(EXPECTED_STRIPE_EVENTS)
    coverage = len(events_found) / max(1, len(EXPECTED_STRIPE_EVENTS))
    metrics["webhook_event_coverage"] = round(coverage, 2)

    if events_missing:
        # Subscription lifecycle events are especially important for revenue
        subscription_missing = [e for e in events_missing if "subscription" in e]
        payment_missing = [
            e for e in events_missing if "payment" in e or "invoice" in e
        ]

        if subscription_missing or payment_missing:
            severity = "high"
        else:
            severity = "medium"

        findings.append(
            Finding(
                id="finmgr-webhook-002",
                severity=severity,
                category="stripe_integration",
                title=f"Stripe webhook missing {len(events_missing)}/{len(EXPECTED_STRIPE_EVENTS)} expected event handlers",
                detail=f"Missing: {', '.join(events_missing)}",
                file=rel_path,
                recommendation=(
                    "Add event-specific handlers for all expected Stripe events. "
                    "checkout.session.completed grants credits; subscription events manage access."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-webhook-002",
                category="stripe_integration",
                severity=severity,
                title=f"Unhandled Stripe events: {', '.join(events_missing)}",
                file=rel_path,
                detail=(
                    f"Event coverage: {coverage:.0%}. "
                    f"Missing handlers mean payment failures go undetected and subscription changes are ignored."
                ),
                recommendation="Implement all 6 expected Stripe event handlers for full billing lifecycle coverage",
            )
        )

    if events_found and not events_missing:
        # Full coverage — positive signal
        logger.info(
            "finance_manager: Stripe webhook has full event coverage (%s events)",
            len(events_found),
        )


# ---------------------------------------------------------------------------
# Check 2: Credit purchase endpoint
# ---------------------------------------------------------------------------


def _check_credit_purchase_endpoint(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Read app/api/credits.py and verify purchase endpoint + Stripe integration."""
    credits_api_path = API_DIR / "credits.py"
    source = _read_safe(credits_api_path)
    rel_path = _relative(credits_api_path)

    if not source:
        findings.append(
            Finding(
                id="finmgr-purchase-000",
                severity="high",
                category="billing",
                title="Credits API file not found",
                detail=f"Could not read {rel_path}",
                file=rel_path,
                recommendation="Create app/api/credits.py with credit balance, history, and purchase endpoints",
            )
        )
        metrics["has_purchase_endpoint"] = False
        metrics["purchase_has_stripe_ref"] = False
        return

    # Look for purchase/buy/checkout endpoint patterns
    has_purchase = bool(
        re.search(
            r'(?:def\s+purchase_credits|@router\.post.*["\'].*(?:purchase|buy|checkout))',
            source,
            re.IGNORECASE,
        )
    )
    metrics["has_purchase_endpoint"] = has_purchase

    if not has_purchase:
        findings.append(
            Finding(
                id="finmgr-purchase-001",
                severity="high",
                category="billing",
                title="Credit purchase endpoint not found in app/api/credits.py",
                detail="No purchase, buy, or checkout route detected",
                file=rel_path,
                recommendation=(
                    "Implement POST /credits/purchase for direct credit purchase. "
                    "Required for job seeker revenue ($1 = 5 credits)."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-purchase-001",
                category="billing",
                severity="high",
                title="No credit purchase endpoint — job seekers cannot buy credits",
                file=rel_path,
                detail="Without a purchase endpoint, the demand-side revenue model ($20-30/month) cannot function",
                recommendation="Implement POST /credits/purchase with Stripe Checkout integration",
            )
        )

    # Check for Stripe integration reference
    has_stripe_ref = bool(
        re.search(
            r"(?:stripe|checkout\.session|payment_intent|Stripe)",
            source,
            re.IGNORECASE,
        )
    )
    metrics["purchase_has_stripe_ref"] = has_stripe_ref

    if not has_stripe_ref:
        findings.append(
            Finding(
                id="finmgr-purchase-002",
                severity="medium",
                category="billing",
                title="Credits API has no Stripe integration reference",
                detail="No stripe, checkout.session, or payment_intent found in credits API",
                file=rel_path,
                recommendation=(
                    "Wire credits purchase to Stripe Checkout. "
                    "Production billing requires Stripe — current stub grants credits directly."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-purchase-002",
                category="billing",
                severity="medium",
                title="Credits purchase not wired to Stripe — revenue not captured",
                file=rel_path,
                detail=(
                    "MVP direct-grant stub is present but Stripe Checkout must be wired "
                    "before real money can be collected from job seekers."
                ),
                recommendation="Integrate stripe.checkout.Session.create() into the purchase endpoint",
            )
        )


# ---------------------------------------------------------------------------
# Check 3: Subscription model
# ---------------------------------------------------------------------------


def _check_subscription_model(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Scan app/models/ and app/services/ for subscription model coverage.

    Looks for:
    - Subscription class in models
    - subscription_tier column on User
    - stripe_subscription_id column
    - Subscription management in services
    """
    # Scan all model files
    model_files = list(MODELS_DIR.glob("*.py"))
    combined_model_source = ""
    for mf in model_files:
        combined_model_source += _read_safe(mf)

    # Scan all service files
    service_files = list(SERVICES_DIR.glob("*.py"))
    combined_service_source = ""
    for sf in service_files:
        combined_service_source += _read_safe(sf)

    has_subscription_class = bool(
        re.search(r"class\s+Subscription\b", combined_model_source)
    )
    has_subscription_tier = bool(
        re.search(r"\bsubscription_tier\b", combined_model_source)
    )
    has_stripe_subscription_id = bool(
        re.search(r"\bstripe_subscription_id\b", combined_model_source)
    )
    has_subscription_service = bool(
        re.search(
            r"(?:def\s+\w*subscription\w*|subscription_service|manage_subscription)",
            combined_service_source,
            re.IGNORECASE,
        )
    )

    metrics["has_subscription_class"] = has_subscription_class
    metrics["has_subscription_tier"] = has_subscription_tier
    metrics["has_stripe_subscription_id"] = has_stripe_subscription_id
    metrics["has_subscription_service"] = has_subscription_service

    subscription_signals = sum(
        [
            has_subscription_class,
            has_subscription_tier,
            has_stripe_subscription_id,
            has_subscription_service,
        ]
    )
    metrics["subscription_signals_found"] = subscription_signals
    metrics["subscription_signals_expected"] = 4

    if not has_subscription_class:
        findings.append(
            Finding(
                id="finmgr-sub-001",
                severity="medium",
                category="billing",
                title="No Subscription model class found in app/models/",
                detail="class Subscription not found across all model files",
                recommendation=(
                    "Add a Subscription model for tracking recurring billing state "
                    "(plan tier, billing period, Stripe subscription ID, status)."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-sub-001",
                category="billing",
                severity="medium",
                title="Missing Subscription model — recurring revenue state is untracked",
                detail=(
                    "Without a Subscription model, we cannot track which users have active $20-30/month plans, "
                    "handle plan upgrades/downgrades, or enforce access based on subscription status."
                ),
                recommendation="Add app/models/subscription.py with Stripe subscription lifecycle fields",
            )
        )

    if not has_subscription_tier:
        findings.append(
            Finding(
                id="finmgr-sub-002",
                severity="medium",
                category="billing",
                title="subscription_tier column not found on User model",
                detail="subscription_tier field not detected in any model file",
                recommendation=(
                    "Add subscription_tier to the User model (free/job_seeker/network_holder) "
                    "to gate marketplace access features."
                ),
            )
        )

    if not has_stripe_subscription_id:
        findings.append(
            Finding(
                id="finmgr-sub-003",
                severity="low",
                category="billing",
                title="stripe_subscription_id column not found in models",
                detail="stripe_subscription_id not found across model files",
                recommendation=(
                    "Store stripe_subscription_id on the subscription or user model "
                    "to enable cancellation, upgrade, and webhook reconciliation."
                ),
            )
        )

    if not has_subscription_service:
        findings.append(
            Finding(
                id="finmgr-sub-004",
                severity="low",
                category="billing",
                title="No subscription management service found",
                detail="No subscription-related functions detected in app/services/",
                recommendation=(
                    "Create app/services/subscription.py to manage Stripe subscription "
                    "lifecycle (create, cancel, upgrade, downgrade, webhook sync)."
                ),
            )
        )

    if subscription_signals == 4:
        logger.info("finance_manager: Full subscription model coverage detected")
    elif subscription_signals == 0:
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-sub-000",
                category="billing",
                severity="high",
                title="No subscription infrastructure found — recurring revenue model not implemented",
                detail=(
                    "Zero subscription signals detected across models and services. "
                    "The $20-30/month job seeker plan cannot be enforced without subscription tracking."
                ),
                recommendation=(
                    "Implement subscription model, tier field, Stripe ID storage, "
                    "and a management service before monetization launch."
                ),
            )
        )


# ---------------------------------------------------------------------------
# Check 4: Agent team costs
# ---------------------------------------------------------------------------

_TEAM_REPORT_DIRS: dict[str, str] = {
    "engineering": "agents/reports",
    "data": "data_team/reports",
    "product": "product_team/reports",
    "ops": "ops_team/reports",
    "finance": "finance_team/reports",
}

# Rough token/cost estimation: agent scans are Claude API calls.
# We use duration as a proxy since actual token counts aren't logged in reports.
# 1 second of scan time ≈ 500 tokens (conservative estimate).
_TOKENS_PER_SECOND = 500
# Claude Sonnet 4.5 input price: $3/M tokens (output at $15/M; use blended $5/M)
_COST_PER_TOKEN_USD = 5.0 / 1_000_000


def _check_agent_team_costs(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
    cost_snapshots: list[CostSnapshot],
) -> None:
    """Scan agent team report directories for *_latest.json files.

    Aggregates scan_duration_seconds from each to produce CostSnapshot entries.
    Flags teams with no recent reports.
    """
    total_duration = 0.0
    total_estimated_tokens = 0
    total_estimated_cost = 0.0
    teams_scanned = 0
    teams_missing = []

    for team_name, rel_dir in _TEAM_REPORT_DIRS.items():
        report_dir = PROJECT_ROOT / rel_dir
        if not report_dir.is_dir():
            teams_missing.append(team_name)
            continue

        latest_files = sorted(report_dir.glob("*_latest.json"))
        if not latest_files:
            teams_missing.append(team_name)
            continue

        team_duration = 0.0
        agent_count = 0

        for report_file in latest_files:
            try:
                data = json.loads(report_file.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "finance_manager: could not parse %s: %s", report_file, exc
                )
                continue

            duration = data.get("scan_duration_seconds", 0.0)
            if isinstance(duration, (int, float)):
                team_duration += float(duration)
            agent_count += 1

        if agent_count == 0:
            teams_missing.append(team_name)
            continue

        estimated_tokens = int(team_duration * _TOKENS_PER_SECOND)
        estimated_cost = team_duration * _TOKENS_PER_SECOND * _COST_PER_TOKEN_USD

        snapshot = CostSnapshot(
            team=team_name,
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=round(estimated_cost, 6),
            duration_seconds=round(team_duration, 3),
        )
        cost_snapshots.append(snapshot)

        total_duration += team_duration
        total_estimated_tokens += estimated_tokens
        total_estimated_cost += estimated_cost
        teams_scanned += 1

        logger.debug(
            "finance_manager: team=%s agents=%s duration=%.2fs tokens=%d cost=$%.6f",
            team_name,
            agent_count,
            team_duration,
            estimated_tokens,
            estimated_cost,
        )

    metrics["teams_with_reports"] = teams_scanned
    metrics["teams_missing_reports"] = len(teams_missing)
    metrics["total_agent_scan_duration_seconds"] = round(total_duration, 3)
    metrics["total_estimated_tokens"] = total_estimated_tokens
    metrics["total_estimated_cost_usd"] = round(total_estimated_cost, 6)

    if teams_missing:
        findings.append(
            Finding(
                id="finmgr-cost-001",
                severity="info",
                category="cost_tracking",
                title=f"{len(teams_missing)} agent team(s) have no report files",
                detail=f"Teams without reports: {', '.join(teams_missing)}",
                recommendation=(
                    "Run all agent teams at least once to establish cost baselines. "
                    "Missing reports cannot be included in aggregate cost tracking."
                ),
            )
        )

    if total_estimated_cost > 1.0:
        # Flag if daily agent run cost exceeds $1 (unusual for codebase scanning)
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-cost-001",
                category="cost_tracking",
                severity="medium",
                title=f"High estimated agent team cost: ${total_estimated_cost:.4f}/day",
                detail=(
                    f"Total scan duration: {total_duration:.1f}s across {teams_scanned} teams. "
                    f"Estimated {total_estimated_tokens:,} tokens at blended $5/M rate."
                ),
                recommendation="Review agent scan frequency and optimize prompt length to reduce AI costs",
            )
        )


# ---------------------------------------------------------------------------
# Check 5: Billing instrumentation
# ---------------------------------------------------------------------------


def _check_billing_instrumentation(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Check app/services/credits.py and app/api/credits.py for billing completeness.

    Looks for:
    - Audit trail (log_event, audit_log) in API layer
    - UsageLog / usage tracking references
    - earn/spend functions wired to credit_transactions table
    - expires_at / expiry logic
    - Non-transferability (no transfer_credits function)
    """
    credits_svc_path = SERVICES_DIR / "credits.py"
    credits_api_path = API_DIR / "credits.py"

    svc_source = _read_safe(credits_svc_path)
    api_source = _read_safe(credits_api_path)
    combined = svc_source + "\n" + api_source

    svc_rel = _relative(credits_svc_path)
    api_rel = _relative(credits_api_path)

    # -- Audit trail --
    has_audit_log = bool(
        re.search(
            r"(?:log_event|audit_log|audit_logger|AuditLog)", combined, re.IGNORECASE
        )
    )
    metrics["billing_has_audit_trail"] = has_audit_log

    if not has_audit_log:
        findings.append(
            Finding(
                id="finmgr-billing-001",
                severity="high",
                category="billing",
                title="Billing audit trail not found in credits service or API",
                detail="log_event / audit_log / AuditLog not referenced in credits files",
                file=api_rel,
                recommendation=(
                    "All credit purchases and admin grants must log to audit_logs table "
                    "(immutable, append-only) for financial integrity and dispute resolution."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-billing-001",
                category="billing",
                severity="high",
                title="No billing audit trail — credit transactions are unauditable",
                file=api_rel,
                detail=(
                    "Without audit logging, credit grants and purchases cannot be investigated "
                    "during payment disputes or regulatory review."
                ),
                recommendation="Emit audit_logs entries for every earn, spend, and purchase event",
            )
        )

    # -- Usage tracking --
    has_usage_log = bool(
        re.search(
            r"(?:UsageLog|usage_log|usage_logs|log_usage)", combined, re.IGNORECASE
        )
    )
    metrics["billing_has_usage_tracking"] = has_usage_log

    if not has_usage_log:
        findings.append(
            Finding(
                id="finmgr-billing-002",
                severity="medium",
                category="billing",
                title="Usage tracking (UsageLog) not found in credits files",
                detail="UsageLog or usage_log references absent from credits service and API",
                file=svc_rel,
                recommendation=(
                    "Link credit spend actions to UsageLog rows for metered billing analytics "
                    "and rate limiting (CLAUDE.md architecture decision #9)."
                ),
            )
        )

    # -- earn/spend transaction recording --
    has_earn = bool(
        re.search(r"def\s+(?:earn_credits|add_credits|credit_earn)", combined)
    )
    has_spend = bool(
        re.search(r"def\s+(?:spend_credits|deduct_credits|credit_spend)", combined)
    )
    has_credit_transaction = bool(
        re.search(
            r"(?:CreditTransaction|credit_transaction|credit_transactions)", combined
        )
    )
    metrics["billing_has_earn_function"] = has_earn
    metrics["billing_has_spend_function"] = has_spend
    metrics["billing_has_credit_transaction_ref"] = has_credit_transaction

    if not has_earn:
        findings.append(
            Finding(
                id="finmgr-billing-003",
                severity="medium",
                category="billing",
                title="earn_credits / add_credits function not found in credits service",
                detail="No earn-side credit function detected in app/services/credits.py",
                file=svc_rel,
                recommendation=(
                    "Implement earn_credits(user_id, amount, reason, expires_at) "
                    "to record CreditTransaction rows for all earn actions."
                ),
            )
        )

    if not has_spend:
        findings.append(
            Finding(
                id="finmgr-billing-004",
                severity="medium",
                category="billing",
                title="spend_credits / deduct_credits function not found in credits service",
                detail="No spend-side credit function detected in app/services/credits.py",
                file=svc_rel,
                recommendation=(
                    "Implement spend_credits(user_id, amount, reason) "
                    "with pre-check on get_balance() before deduction."
                ),
            )
        )

    if not has_credit_transaction:
        findings.append(
            Finding(
                id="finmgr-billing-005",
                severity="high",
                category="billing",
                title="CreditTransaction model not referenced in credits files",
                detail="credit_transaction or CreditTransaction not found in credits service/API",
                file=svc_rel,
                recommendation=(
                    "All earn/spend actions must write to credit_transactions table. "
                    "Balance = SUM query on non-expired rows (CLAUDE.md arch decision #14)."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-billing-005",
                category="billing",
                severity="high",
                title="credit_transactions table not referenced — credit economy may be unrecorded",
                file=svc_rel,
                detail=(
                    "Without CreditTransaction writes, credit balance is computed incorrectly "
                    "and the 12-month expiry cannot be enforced."
                ),
                recommendation="Wire every earn/spend path through CreditTransaction inserts",
            )
        )

    # -- Expiry logic --
    has_expiry = bool(
        re.search(
            r"(?:expire_stale_credits|expires_at|expiry|expired)",
            combined,
            re.IGNORECASE,
        )
    )
    metrics["billing_has_expiry_logic"] = has_expiry

    if not has_expiry:
        findings.append(
            Finding(
                id="finmgr-billing-006",
                severity="high",
                category="billing",
                title="Credit expiry logic not found in credits service or API",
                detail="expires_at / expire_stale_credits / expired not found",
                file=svc_rel,
                recommendation=(
                    "Credits expire after 12 months per CLAUDE.md to avoid balance-sheet liability. "
                    "Implement expire_stale_credits() and set expires_at on every earn transaction."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-billing-006",
                category="billing",
                severity="high",
                title="No credit expiry — outstanding balances create growing liability",
                file=svc_rel,
                detail=(
                    "Unexpired credits accumulate as a liability on the balance sheet. "
                    "12-month expiry keeps WarmPath in airline-miles territory, not money-transmitter."
                ),
                recommendation="Add expires_at column, set on earn, exclude from balance SUM after expiry",
            )
        )

    # -- Non-transferability --
    has_transfer = bool(re.search(r"def\s+transfer_credits", combined))
    metrics["billing_has_transfer_function"] = has_transfer

    if has_transfer:
        findings.append(
            Finding(
                id="finmgr-billing-007",
                severity="high",
                category="billing",
                title="transfer_credits function found — credits must be non-transferable",
                detail="A transfer function violates the non-transferability requirement from CLAUDE.md",
                file=svc_rel,
                recommendation=(
                    "Remove transfer_credits to stay in loyalty-program territory. "
                    "Tradeable credits require FinCEN/Singapore PSA money transmitter licensing."
                ),
            )
        )
        financial_findings.append(
            FinancialFinding(
                id="finmgr-ff-billing-007",
                category="billing",
                severity="high",
                title="Credit transfer function creates regulatory exposure (FinCEN/PSA)",
                file=svc_rel,
                detail=(
                    "Transferable credits may be classified as stored value — triggering "
                    "money transmitter requirements under FinCEN and Singapore Payment Services Act."
                ),
                recommendation="Remove transfer_credits; revisit post-Series A with legal counsel",
            )
        )

    # -- Billing completeness score --
    checks_passed = sum(
        [
            has_audit_log,
            has_usage_log,
            has_earn,
            has_spend,
            has_credit_transaction,
            has_expiry,
            not has_transfer,  # passing means no transfer function found
        ]
    )
    total_checks = 7
    billing_score = round(checks_passed / total_checks, 2)
    metrics["billing_completeness_score"] = billing_score
    metrics["billing_checks_passed"] = checks_passed
    metrics["billing_checks_total"] = total_checks


# ---------------------------------------------------------------------------
# Cash runway forecasting (CoS audit gap fix)
# ---------------------------------------------------------------------------


def _check_cash_runway(
    findings: list[Finding],
    financial_findings: list[FinancialFinding],
    metrics: dict,
    cost_snapshots: list[CostSnapshot],
) -> None:
    """Estimate monthly burn rate and cash runway."""
    from finance_team.shared.config import CASH_ON_HAND, MONTHLY_FIXED_COSTS

    # Fixed costs
    fixed_monthly = sum(MONTHLY_FIXED_COSTS.values())
    metrics["monthly_fixed_costs"] = round(fixed_monthly, 2)

    # Agent operation costs (from cost_snapshots already computed)
    agent_monthly = 0.0
    for snap in cost_snapshots:
        # Extrapolate: assume agents run ~30 times/month
        cost = (
            getattr(snap, "estimated_cost_usd", 0.0)
            if hasattr(snap, "estimated_cost_usd")
            else 0.0
        )
        agent_monthly += cost * 30

    metrics["monthly_agent_costs"] = round(agent_monthly, 4)

    # Revenue (try Stripe client)
    monthly_revenue = 0.0
    try:
        from finance_team.shared.stripe_client import get_stripe_client

        client = get_stripe_client()
        if client.is_available():
            import time as _time

            thirty_days_ago = int(_time.time()) - (30 * 86400)
            charges = client.list_charges(limit=100, created_after=thirty_days_ago)
            if charges and "data" in charges:
                for charge in charges["data"]:
                    if charge.get("paid") and not charge.get("refunded"):
                        monthly_revenue += charge.get("amount", 0) / 100.0
    except Exception:
        pass

    metrics["monthly_revenue"] = round(monthly_revenue, 2)

    # Burn rate
    monthly_burn = fixed_monthly + agent_monthly - monthly_revenue
    metrics["monthly_burn_rate"] = round(monthly_burn, 2)

    # Runway
    if CASH_ON_HAND > 0 and monthly_burn > 0:
        runway_months = CASH_ON_HAND / monthly_burn
        metrics["cash_runway_months"] = round(runway_months, 1)

        from finance_team.shared.config import KPI_TARGETS

        target = KPI_TARGETS.get("cash_runway_months", {}).get("target", 6)
        if runway_months < target:
            financial_findings.append(
                FinancialFinding(
                    id="finmgr-runway-001",
                    category="cash_runway",
                    severity="high" if runway_months < 3 else "medium",
                    title=f"Cash runway: {runway_months:.1f} months (target: {target})",
                    detail=f"Burn: ${monthly_burn:.2f}/mo, Cash: ${CASH_ON_HAND:.2f}",
                    recommendation="Reduce burn or accelerate revenue to extend runway.",
                )
            )
    else:
        metrics["cash_runway_months"] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> FinanceTeamReport:
    """Run all financial health checks and return a FinanceTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    financial_findings: list[FinancialFinding] = []
    cost_snapshots: list[CostSnapshot] = []
    metrics: dict = {}

    # Run checks
    _check_stripe_webhook_handlers(findings, financial_findings, metrics)
    _check_credit_purchase_endpoint(findings, financial_findings, metrics)
    _check_subscription_model(findings, financial_findings, metrics)
    _check_agent_team_costs(findings, financial_findings, metrics, cost_snapshots)
    _check_billing_instrumentation(findings, financial_findings, metrics)
    _check_cash_runway(findings, financial_findings, metrics, cost_snapshots)

    duration = time.time() - start

    # -- Learning state -------------------------------------------------------

    ls = FinanceLearningState(AGENT_NAME)
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

    for ff in financial_findings:
        ls.record_finding(
            {
                "id": ff.id,
                "severity": ff.severity,
                "category": ff.category,
                "title": ff.title,
                "file": ff.file,
            }
        )
        if ff.file:
            file_findings[ff.file] = file_findings.get(ff.file, 0) + 1

    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    for ff in financial_findings:
        ls.record_severity_calibration(ff.severity)

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    penalty += sum(severity_penalty.get(ff.severity, 0) for ff in financial_findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1

    ls.record_health_snapshot(health, finding_counts)

    # KPI tracking
    ls.track_kpi("webhook_event_coverage", metrics.get("webhook_event_coverage", 0.0))
    ls.track_kpi(
        "billing_completeness_score", metrics.get("billing_completeness_score", 0.0)
    )
    ls.track_kpi(
        "total_estimated_cost_usd", metrics.get("total_estimated_cost_usd", 0.0)
    )
    ls.track_kpi(
        "subscription_signals_found", metrics.get("subscription_signals_found", 0)
    )
    ls.track_kpi(
        "has_signature_verification",
        int(metrics.get("has_signature_verification", False)),
    )

    # Learning summary
    high_critical = sum(
        1 for f in findings if f.severity in ("critical", "high")
    ) + sum(1 for ff in financial_findings if ff.severity in ("critical", "high"))
    billing_score = metrics.get("billing_completeness_score", 0.0)
    webhook_coverage = metrics.get("webhook_event_coverage", 0.0)
    total_cost = metrics.get("total_estimated_cost_usd", 0.0)

    learning_updates: list[str] = [
        (
            f"Stripe webhook coverage: {webhook_coverage:.0%} "
            f"({metrics.get('webhook_events_found', 0)}/{metrics.get('webhook_events_expected', 0)} events)"
        ),
        f"Billing completeness: {billing_score:.0%} ({metrics.get('billing_checks_passed', 0)}/{metrics.get('billing_checks_total', 0)} checks)",
        (
            f"Agent team cost estimate: ${total_cost:.4f}/run "
            f"({metrics.get('teams_with_reports', 0)} teams, "
            f"{metrics.get('total_agent_scan_duration_seconds', 0.0):.1f}s total)"
        ),
        f"Subscription model signals: {metrics.get('subscription_signals_found', 0)}/4",
    ]

    if high_critical > 0:
        learning_updates.append(
            f"Action required: {high_critical} high/critical financial findings"
        )

    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    patterns = ls.state.get("recurring_patterns", {})
    escalated = [k for k, v in patterns.items() if v.get("auto_escalated")]
    if escalated:
        learning_updates.append(f"Escalated recurring patterns: {len(escalated)}")

    return FinanceTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        financial_findings=financial_findings,
        cost_snapshots=cost_snapshots,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: FinanceTeamReport) -> Path:
    """Save report JSON to finance_team/reports/finance_manager_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("finance_manager: report saved to %s", path)
    return path
