"""Credits manager agent -- credit economy integrity auditor.

Scans app/services/credits.py, app/api/credits.py, and app/api/marketplace.py
to verify the credit economy is correctly implemented:
  - All expected earn/spend actions are wired
  - Credits are non-transferable (no transfer function, no money-transmitter signals)
  - 12-month expiry logic is present
  - Duplicate/idempotency detection prevents double-earning
  - Balance uses a SUM query (not a cached counter)
  - Abuse prevention: rate limiting, negative balance guards, bulk earn caps
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from finance_team.shared.config import (
    API_DIR,
    MODELS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    SERVICES_DIR,
    EXPECTED_CREDIT_EARN_ACTIONS,
    EXPECTED_CREDIT_SPEND_ACTIONS,
)
from finance_team.shared.learning import FinanceLearningState
from finance_team.shared.ledger import (
    CREDIT_EXPIRY_MONTHS,
    MONEY_TRANSMITTER_RISK_SIGNALS,
    SAFE_CREDIT_PATTERNS,
)
from finance_team.shared.report import FinancialFinding, FinanceTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "credits_manager"

# Source file paths scanned by this agent
_CREDITS_SVC_PATH = SERVICES_DIR / "credits.py"
_CREDITS_API_PATH = API_DIR / "credits.py"
_MARKETPLACE_API_PATH = API_DIR / "marketplace.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("credits_manager: could not read %s: %s", path, exc)
        return ""


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT, falling back to the absolute string."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check 1: Earn and spend rules
# ---------------------------------------------------------------------------


def _check_earn_spend_rules(
    combined: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Verify every expected earn and spend action is referenced in the combined source."""
    earn_found: list[str] = []
    earn_missing: list[str] = []

    for action in EXPECTED_CREDIT_EARN_ACTIONS:
        # Match the action string as a substring (quoted or unquoted, underscores or hyphens)
        pattern = re.compile(re.escape(action).replace(r"\_", "[_-]?"), re.IGNORECASE)
        if pattern.search(combined):
            earn_found.append(action)
        else:
            earn_missing.append(action)

    metrics["earn_actions_found"] = len(earn_found)
    metrics["earn_actions_expected"] = len(EXPECTED_CREDIT_EARN_ACTIONS)
    metrics["earn_actions_missing"] = earn_missing

    if earn_missing:
        severity = "high" if len(earn_missing) > 2 else "medium"
        findings.append(Finding(
            id="cm-earn-001",
            severity=severity,
            category="credit_economy",
            title=f"Credit economy missing {len(earn_missing)} earn action(s)",
            detail=f"Missing earn triggers: {', '.join(earn_missing)}",
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Implement missing earn triggers in app/services/credits.py and ensure "
                "they are called from the appropriate API endpoints."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-earn-001",
            category="credit_economy",
            severity=severity,
            title=f"Missing earn actions: {', '.join(earn_missing)}",
            file=_relative(_CREDITS_SVC_PATH),
            detail=(
                f"Found {len(earn_found)}/{len(EXPECTED_CREDIT_EARN_ACTIONS)} expected earn reasons. "
                f"Network holders need all earn incentives to stay engaged."
            ),
            recommendation="Wire missing earn actions through earn_credits() calls.",
        ))

    spend_found: list[str] = []
    spend_missing: list[str] = []

    for action in EXPECTED_CREDIT_SPEND_ACTIONS:
        pattern = re.compile(re.escape(action).replace(r"\_", "[_-]?"), re.IGNORECASE)
        if pattern.search(combined):
            spend_found.append(action)
        else:
            spend_missing.append(action)

    metrics["spend_actions_found"] = len(spend_found)
    metrics["spend_actions_expected"] = len(EXPECTED_CREDIT_SPEND_ACTIONS)
    metrics["spend_actions_missing"] = spend_missing

    if spend_missing:
        severity = "high" if len(spend_missing) > 2 else "medium"
        findings.append(Finding(
            id="cm-spend-001",
            severity=severity,
            category="credit_economy",
            title=f"Credit economy missing {len(spend_missing)} spend action(s)",
            detail=f"Missing spend triggers: {', '.join(spend_missing)}",
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Ensure all credit-consuming actions call spend_credits() with the "
                "correct reason string."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-spend-001",
            category="credit_economy",
            severity=severity,
            title=f"Missing spend actions: {', '.join(spend_missing)}",
            file=_relative(_CREDITS_SVC_PATH),
            detail=(
                f"Found {len(spend_found)}/{len(EXPECTED_CREDIT_SPEND_ACTIONS)} expected spend reasons."
            ),
            recommendation="Wire missing spend actions through spend_credits() in the API layer.",
        ))

    # Compute a combined economy coverage ratio for KPI tracking
    total_expected = len(EXPECTED_CREDIT_EARN_ACTIONS) + len(EXPECTED_CREDIT_SPEND_ACTIONS)
    total_found = len(earn_found) + len(spend_found)
    metrics["credit_economy_coverage"] = round(total_found / max(1, total_expected), 3)


# ---------------------------------------------------------------------------
# Check 2: Non-transferability and money transmitter risk signals
# ---------------------------------------------------------------------------


def _check_non_transferability(
    combined: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Ensure no transfer_credits function exists and no money-transmitter risk signals appear."""
    has_transfer = bool(re.search(r"def\s+transfer_credits", combined))
    metrics["has_transfer_function"] = has_transfer

    if has_transfer:
        findings.append(Finding(
            id="cm-transfer-001",
            severity="high",
            category="credit_economy",
            title="transfer_credits function found — credits must be non-transferable",
            detail=(
                "A transfer_credits function was detected. Non-transferability is critical "
                "to keep WarmPath outside FinCEN money transmitter and Singapore PSA scope."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Remove transfer_credits. Credits must behave like airline miles (loyalty program), "
                "not a payment instrument."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-transfer-001",
            category="credit_economy",
            severity="high",
            title="Credit transfer function violates non-transferability requirement",
            file=_relative(_CREDITS_SVC_PATH),
            detail="Non-transferable credits avoid FinCEN/PSA classification as virtual currency.",
            recommendation="Delete transfer_credits and any supporting endpoints.",
        ))

    # Scan for money transmitter risk signals from the ledger module
    risk_signals_found: list[str] = []
    for signal in MONEY_TRANSMITTER_RISK_SIGNALS:
        if re.search(re.escape(signal), combined, re.IGNORECASE):
            risk_signals_found.append(signal)

    metrics["money_transmitter_risk_signals_found"] = risk_signals_found

    if risk_signals_found:
        findings.append(Finding(
            id="cm-transmitter-001",
            severity="high",
            category="credit_economy",
            title=f"Money transmitter risk signals detected: {', '.join(risk_signals_found)}",
            detail=(
                "These patterns may expose WarmPath to FinCEN (USA) or Singapore Payment Services "
                f"Act classification: {', '.join(risk_signals_found)}"
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Review and remove money transmitter patterns. Credits must remain non-transferable, "
                "non-cashable functional accounting units."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-transmitter-001",
            category="credit_economy",
            severity="high",
            title=f"Regulatory risk: money transmitter signals in credit code",
            file=_relative(_CREDITS_SVC_PATH),
            detail=f"Risk signals detected: {', '.join(risk_signals_found)}",
            recommendation="Legal review required before launch if any signal persists.",
        ))

    # Positive check: safe credit patterns should be present
    safe_patterns_found: list[str] = []
    for pattern in SAFE_CREDIT_PATTERNS:
        if re.search(re.escape(pattern), combined, re.IGNORECASE):
            safe_patterns_found.append(pattern)

    metrics["safe_credit_patterns_found"] = safe_patterns_found
    metrics["safe_credit_patterns_expected"] = len(SAFE_CREDIT_PATTERNS)


# ---------------------------------------------------------------------------
# Check 3: Expiry implementation
# ---------------------------------------------------------------------------


def _check_expiry_implementation(
    credits_svc_source: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Verify credit expiry logic is present in app/services/credits.py."""
    has_expiry_function = bool(
        re.search(r"expire_stale_credits|expired", credits_svc_source, re.IGNORECASE)
    )
    has_expires_at_field = "expires_at" in credits_svc_source

    metrics["has_expiry_function"] = has_expiry_function
    metrics["has_expires_at_field"] = has_expires_at_field
    metrics["credit_expiry_months"] = CREDIT_EXPIRY_MONTHS

    if not has_expiry_function:
        findings.append(Finding(
            id="cm-expiry-001",
            severity="high",
            category="credit_economy",
            title="Credit expiry function not found in credits service",
            detail=(
                f"Neither expire_stale_credits nor 'expired' transaction type found in "
                f"app/services/credits.py. Credits must expire after {CREDIT_EXPIRY_MONTHS} months "
                f"per CLAUDE.md to avoid liability accrual."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                f"Add expire_stale_credits() to mark or purge credit_transactions older than "
                f"{CREDIT_EXPIRY_MONTHS} months. Schedule it as a periodic Celery task."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-expiry-001",
            category="credit_economy",
            severity="high",
            title="Missing credit expiry — liability accrual risk",
            file=_relative(_CREDITS_SVC_PATH),
            detail=(
                f"Without expiry, credits accumulate indefinitely, creating an open-ended "
                f"liability. {CREDIT_EXPIRY_MONTHS}-month expiry keeps WarmPath in loyalty-program territory."
            ),
            recommendation=(
                "Implement expiry and schedule the sweep via Celery beat."
            ),
        ))

    if not has_expires_at_field:
        findings.append(Finding(
            id="cm-expiry-002",
            severity="high",
            category="credit_economy",
            title="expires_at field not referenced in credits service",
            detail=(
                "Credit transactions should carry an expires_at timestamp so the balance "
                "calculation can exclude expired credits."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Set expires_at = now + timedelta(days=365) on all earned credit transactions. "
                "Exclude expired rows in get_balance() SUM query."
            ),
        ))


# ---------------------------------------------------------------------------
# Check 4: Duplicate detection
# ---------------------------------------------------------------------------


def _check_duplicate_detection(
    combined: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Look for idempotency/dedup patterns near credit earn endpoints."""
    dedup_patterns = [
        re.compile(r"already[_\s]?earned", re.IGNORECASE),
        re.compile(r"duplicate", re.IGNORECASE),
        re.compile(r"idempotent", re.IGNORECASE),
        re.compile(r"\bexists\b.*credit|credit.*\bexists\b", re.IGNORECASE),
    ]

    dedup_signals_found: list[str] = []
    for pat in dedup_patterns:
        m = pat.search(combined)
        if m:
            dedup_signals_found.append(pat.pattern)

    has_dedup = len(dedup_signals_found) > 0
    metrics["has_duplicate_detection"] = has_dedup
    metrics["dedup_signals_found"] = len(dedup_signals_found)

    if not has_dedup:
        findings.append(Finding(
            id="cm-dedup-001",
            severity="medium",
            category="credit_economy",
            title="No duplicate/idempotency detection found near credit earn operations",
            detail=(
                "Without dedup checks, users may earn credits multiple times for the same "
                "action (e.g., re-uploading the same CSV). Patterns searched: "
                "already_earned, duplicate, idempotent, exists+credit."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Add an idempotency check before earn_credits(). For CSV uploads, hash the "
                "file or record the upload event and gate earning on first-time-only."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-dedup-001",
            category="credit_economy",
            severity="medium",
            title="Missing duplicate detection — credit abuse vector",
            file=_relative(_CREDITS_SVC_PATH),
            detail="Users could trigger repeated earn events and accumulate credits unfairly.",
            recommendation="Implement idempotency keys or action-per-user uniqueness constraints.",
        ))


# ---------------------------------------------------------------------------
# Check 5: Balance integrity
# ---------------------------------------------------------------------------


def _check_balance_integrity(
    credits_svc_source: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Verify get_balance and get_credit_summary exist and use a SUM query."""
    has_get_balance = "get_balance" in credits_svc_source
    has_get_summary = "get_credit_summary" in credits_svc_source
    has_sum_query = bool(re.search(r"\bSUM\b|func\.sum|sum\(", credits_svc_source, re.IGNORECASE))

    metrics["has_get_balance"] = has_get_balance
    metrics["has_get_credit_summary"] = has_get_summary
    metrics["has_sum_query"] = has_sum_query

    if not has_get_balance:
        findings.append(Finding(
            id="cm-balance-001",
            severity="high",
            category="credit_economy",
            title="get_balance function not found in credits service",
            detail=(
                "The core balance primitive is missing from app/services/credits.py. "
                "Balance must be computed as SUM(amount) on non-expired, non-spent transactions."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Add async get_balance(db, user_id) that returns "
                "SELECT SUM(amount) FROM credit_transactions WHERE user_id=? AND expires_at > now()."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-balance-001",
            category="credit_economy",
            severity="high",
            title="Missing get_balance — no credit accounting primitive",
            file=_relative(_CREDITS_SVC_PATH),
            detail="Without get_balance, all spend gates and UI displays are broken.",
            recommendation="Implement get_balance as a SUM query — never cache a running counter.",
        ))

    if not has_get_summary:
        findings.append(Finding(
            id="cm-balance-002",
            severity="high",
            category="credit_economy",
            title="get_credit_summary function not found in credits service",
            detail=(
                "get_credit_summary provides the breakdown (earned, spent, expiring soon) "
                "that the frontend credit widget and CoS cost tracker depend on."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Add get_credit_summary(db, user_id) returning balance, total_earned, "
                "total_spent, and expiring_soon fields."
            ),
        ))

    if has_get_balance and not has_sum_query:
        findings.append(Finding(
            id="cm-balance-003",
            severity="medium",
            category="credit_economy",
            title="Balance calculation does not appear to use a SUM query",
            detail=(
                "get_balance exists but no SUM / func.sum pattern was detected. "
                "Using a cached counter risks balance drift on failed transactions."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Compute balance as SUM(amount) from credit_transactions each time — "
                "never store a running counter on the user row."
            ),
        ))


# ---------------------------------------------------------------------------
# Check 6: Abuse prevention
# ---------------------------------------------------------------------------


def _check_abuse_prevention(
    combined: str,
    findings: list[Finding],
    fin_findings: list[FinancialFinding],
    metrics: dict,
) -> None:
    """Check for rate limiting on credit endpoints, negative balance prevention, and bulk earn caps."""

    # Rate limiting signals
    rate_limit_patterns = [
        re.compile(r"rate_limit|RateLimit|limiter|throttle", re.IGNORECASE),
    ]
    has_rate_limit = any(p.search(combined) for p in rate_limit_patterns)
    metrics["has_rate_limiting"] = has_rate_limit

    # Negative balance prevention
    negative_balance_patterns = [
        re.compile(r"insufficient|negative|balance\s*[<=>]+\s*0|balance\s*<=\s*0", re.IGNORECASE),
    ]
    has_negative_guard = any(p.search(combined) for p in negative_balance_patterns)
    metrics["has_negative_balance_guard"] = has_negative_guard

    # Bulk earn caps
    bulk_cap_patterns = [
        re.compile(r"max.*earn|earn.*max|earn.*cap|cap.*earn|MAX_EARN|bulk.*limit", re.IGNORECASE),
    ]
    has_bulk_cap = any(p.search(combined) for p in bulk_cap_patterns)
    metrics["has_bulk_earn_cap"] = has_bulk_cap

    missing_safeguards: list[str] = []
    if not has_rate_limit:
        missing_safeguards.append("rate_limiting")
    if not has_negative_guard:
        missing_safeguards.append("negative_balance_guard")
    if not has_bulk_cap:
        missing_safeguards.append("bulk_earn_cap")

    metrics["abuse_prevention_score"] = round(
        (3 - len(missing_safeguards)) / 3, 3
    )

    if not has_rate_limit:
        findings.append(Finding(
            id="cm-abuse-001",
            severity="medium",
            category="credit_economy",
            title="No rate limiting detected on credit endpoints",
            detail=(
                "Credit earn endpoints (CSV upload, intro facilitation) should be rate-limited "
                "to prevent abuse. Patterns searched: rate_limit, RateLimit, limiter, throttle."
            ),
            file=_relative(_CREDITS_API_PATH),
            recommendation=(
                "Apply the existing IP rate limiter from app/middleware/ to POST /credits/earn "
                "and related endpoints."
            ),
        ))

    if not has_negative_guard:
        findings.append(Finding(
            id="cm-abuse-002",
            severity="medium",
            category="credit_economy",
            title="No negative balance guard detected in credits service",
            detail=(
                "spend_credits() must check that the user has sufficient balance before "
                "deducting. Patterns searched: insufficient, negative, balance<=0."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Before inserting a spend transaction, call get_balance() and raise "
                "InsufficientCreditsError if balance < amount."
            ),
        ))
        fin_findings.append(FinancialFinding(
            id="cm-fin-abuse-001",
            category="credit_economy",
            severity="medium",
            title="Missing insufficient-balance guard — overdraft risk",
            file=_relative(_CREDITS_SVC_PATH),
            detail="Without a guard, users could spend more credits than they hold.",
            recommendation="Add a pre-spend balance check with an explicit error response.",
        ))

    if not has_bulk_cap:
        findings.append(Finding(
            id="cm-abuse-003",
            severity="medium",
            category="credit_economy",
            title="No bulk earn cap detected",
            detail=(
                "Without a per-user earn cap, a user could upload many CSVs rapidly "
                "to accumulate large credit balances artificially."
            ),
            file=_relative(_CREDITS_SVC_PATH),
            recommendation=(
                "Define a MAX_EARN_PER_DAY constant and gate earn_credits() calls when the "
                "daily earn total exceeds it."
            ),
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> FinanceTeamReport:
    """Run all credit economy integrity checks and return a FinanceTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    fin_findings: list[FinancialFinding] = []
    metrics: dict = {}

    # --- Read source files ---------------------------------------------------

    credits_svc_source = _read_safe(_CREDITS_SVC_PATH)
    credits_api_source = _read_safe(_CREDITS_API_PATH)
    marketplace_api_source = _read_safe(_MARKETPLACE_API_PATH)

    files_scanned = sum(
        1 for s in [credits_svc_source, credits_api_source, marketplace_api_source] if s
    )
    metrics["files_scanned"] = files_scanned
    metrics["files_expected"] = 3

    if not credits_svc_source:
        findings.append(Finding(
            id="cm-io-001",
            severity="high",
            category="credit_economy",
            title="Could not read app/services/credits.py",
            detail=f"Expected at {_relative(_CREDITS_SVC_PATH)}",
            file=_relative(_CREDITS_SVC_PATH),
            recommendation="Ensure app/services/credits.py exists — it is the core credit accounting module.",
        ))

    if not credits_api_source:
        findings.append(Finding(
            id="cm-io-002",
            severity="medium",
            category="credit_economy",
            title="Could not read app/api/credits.py",
            detail=f"Expected at {_relative(_CREDITS_API_PATH)}",
            file=_relative(_CREDITS_API_PATH),
            recommendation="Ensure app/api/credits.py exists for credit purchase and balance endpoints.",
        ))

    if not marketplace_api_source:
        findings.append(Finding(
            id="cm-io-003",
            severity="medium",
            category="credit_economy",
            title="Could not read app/api/marketplace.py",
            detail=f"Expected at {_relative(_MARKETPLACE_API_PATH)}",
            file=_relative(_MARKETPLACE_API_PATH),
            recommendation="Ensure app/api/marketplace.py exists — it triggers cross-network spend actions.",
        ))

    # Combined source for checks that span all three files
    combined = credits_svc_source + "\n" + credits_api_source + "\n" + marketplace_api_source

    # --- Run checks ----------------------------------------------------------

    _check_earn_spend_rules(combined, findings, fin_findings, metrics)
    _check_non_transferability(combined, findings, fin_findings, metrics)
    _check_expiry_implementation(credits_svc_source, findings, fin_findings, metrics)
    _check_duplicate_detection(combined, findings, fin_findings, metrics)
    _check_balance_integrity(credits_svc_source, findings, fin_findings, metrics)
    _check_abuse_prevention(combined, findings, fin_findings, metrics)

    # --- Compute overall credit economy integrity score ----------------------

    integrity_components = [
        metrics.get("credit_economy_coverage", 0.0),
        0.0 if metrics.get("has_transfer_function") else 1.0,
        0.0 if metrics.get("money_transmitter_risk_signals_found") else 1.0,
        1.0 if metrics.get("has_expiry_function") else 0.0,
        1.0 if metrics.get("has_expires_at_field") else 0.0,
        1.0 if metrics.get("has_duplicate_detection") else 0.0,
        1.0 if metrics.get("has_get_balance") else 0.0,
        1.0 if metrics.get("has_get_credit_summary") else 0.0,
        metrics.get("abuse_prevention_score", 0.0),
    ]
    credit_economy_integrity = round(
        sum(integrity_components) / max(1, len(integrity_components)), 3
    )
    metrics["credit_economy_integrity"] = credit_economy_integrity

    duration = time.time() - start

    # --- Learning state ------------------------------------------------------

    ls = FinanceLearningState(AGENT_NAME)
    ls.record_scan(metrics)

    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding({
            "id": f.id,
            "severity": f.severity,
            "category": f.category,
            "title": f.title,
            "file": f.file,
        })
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1

    for ff in fin_findings:
        ls.record_finding({
            "id": ff.id,
            "severity": ff.severity,
            "category": ff.category,
            "title": ff.title,
            "file": ff.file,
        })

    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot — penalise by finding severity
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # KPI tracking
    ls.track_kpi("credit_economy_integrity", credit_economy_integrity)
    ls.track_kpi("credit_economy_coverage", metrics.get("credit_economy_coverage", 0.0))
    ls.track_kpi("earn_actions_found", metrics.get("earn_actions_found", 0))
    ls.track_kpi("spend_actions_found", metrics.get("spend_actions_found", 0))
    ls.track_kpi("abuse_prevention_score", metrics.get("abuse_prevention_score", 0.0))

    # Learning updates for CoS consumption
    learning_updates: list[str] = [
        (
            f"Scanned {files_scanned}/{metrics['files_expected']} credit files, "
            f"integrity={credit_economy_integrity:.1%}"
        ),
        (
            f"Earn actions: {metrics.get('earn_actions_found', 0)}/{metrics.get('earn_actions_expected', 0)}, "
            f"spend actions: {metrics.get('spend_actions_found', 0)}/{metrics.get('spend_actions_expected', 0)}"
        ),
    ]

    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    patterns = ls.state.get("recurring_patterns", {})
    escalated = [k for k, v in patterns.items() if v.get("auto_escalated")]
    if escalated:
        learning_updates.append(f"Escalated recurring patterns: {len(escalated)}")

    risk_signals = metrics.get("money_transmitter_risk_signals_found", [])
    if risk_signals:
        learning_updates.append(
            f"ALERT: money transmitter risk signals detected: {', '.join(risk_signals)}"
        )

    return FinanceTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        financial_findings=fin_findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: FinanceTeamReport) -> Path:
    """Save report to finance_team/reports/credits_manager_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("credits_manager: report saved to %s", path)
    return path
