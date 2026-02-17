"""Legal compliance agent -- regulatory compliance scanner.

Scans the codebase for money transmitter risk signals, GDPR/CCPA/PDPA deletion
paths, consent gates, suppression list coverage, security compliance markers,
and breach notification infrastructure.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from finance_team.shared.config import (
    API_DIR,
    APP_DIR,
    MODELS_DIR,
    PRIVACY_DELETION_PATHS,
    PROJECT_ROOT,
    REPORTS_DIR,
    SERVICES_DIR,
)
from finance_team.shared.learning import FinanceLearningState
from finance_team.shared.ledger import (
    MONEY_TRANSMITTER_RISK_SIGNALS,
    REGULATORY_FRAMEWORKS,
    SAFE_CREDIT_PATTERNS,
)
from finance_team.shared.report import ComplianceFinding, FinanceTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "legal_compliance"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("legal_compliance: could not read %s: %s", path, exc)
        return ""


def _relative(path: Path) -> str:
    """Return path relative to project root, falling back to absolute string."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check 1: Money transmitter risk
# ---------------------------------------------------------------------------


def _check_money_transmitter_risk(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Scan app/services/ and app/api/ for money transmitter risk signals.

    Flags any occurrence of MONEY_TRANSMITTER_RISK_SIGNALS as HIGH/CRITICAL.
    Notes SAFE_CREDIT_PATTERNS as positive compliance evidence.
    """
    # Collect all .py files under services and api
    service_files = sorted(SERVICES_DIR.glob("*.py")) if SERVICES_DIR.is_dir() else []
    api_files = sorted(API_DIR.glob("*.py")) if API_DIR.is_dir() else []
    all_files = service_files + api_files

    combined_source = ""
    files_scanned = 0
    for fp in all_files:
        src = _read_safe(fp)
        if src:
            combined_source += "\n" + src
            files_scanned += 1

    metrics["money_transmitter_files_scanned"] = files_scanned

    # Check for risk signals
    risk_signals_found: list[str] = []
    for signal in MONEY_TRANSMITTER_RISK_SIGNALS:
        pattern = re.compile(rf"\b{re.escape(signal)}\b", re.IGNORECASE)
        if pattern.search(combined_source):
            risk_signals_found.append(signal)

    metrics["money_transmitter_risk_signals_found"] = len(risk_signals_found)
    metrics["money_transmitter_risk_signals_checked"] = len(MONEY_TRANSMITTER_RISK_SIGNALS)

    if risk_signals_found:
        severity = "critical" if any(
            s in risk_signals_found for s in ("transfer_credits", "cash_out", "peer_to_peer")
        ) else "high"
        findings.append(Finding(
            id="lc-mtr-001",
            severity=severity,
            category="money_transmitter",
            title=f"Money transmitter risk signals found: {', '.join(risk_signals_found)}",
            detail=(
                f"Detected {len(risk_signals_found)} risk signal(s) across app/services/ and app/api/. "
                f"Signals: {', '.join(risk_signals_found)}"
            ),
            recommendation=(
                "Remove or rename functions that imply transferability, cash conversion, or "
                "withdrawal. Credits must remain non-transferable to stay outside FinCEN/PSA scope."
            ),
        ))
        for signal in risk_signals_found:
            compliance_findings.append(ComplianceFinding(
                id=f"lc-mtr-{signal[:8]}",
                category="money_transmitter",
                severity=severity,
                title=f"Risk signal '{signal}' detected in codebase",
                detail=f"Matches pattern '{signal}' in combined app/services + app/api source",
                regulation="FinCEN" if signal in ("transfer_credits", "cash_out", "exchange_rate",
                                                   "convert_to_cash", "withdraw") else "PSA",
                recommendation=(
                    "Credits must be non-transferable loyalty points, not virtual currency. "
                    "Consult CLAUDE.md section on credit economy and money transmitter regulations."
                ),
            ))
    else:
        metrics["money_transmitter_clean"] = True

    # Check for safe patterns (positive compliance evidence)
    safe_patterns_found: list[str] = []
    for pattern_str in SAFE_CREDIT_PATTERNS:
        pat = re.compile(rf"\b{re.escape(pattern_str)}\b", re.IGNORECASE)
        if pat.search(combined_source):
            safe_patterns_found.append(pattern_str)

    metrics["safe_credit_patterns_found"] = len(safe_patterns_found)
    metrics["safe_credit_patterns_checked"] = len(SAFE_CREDIT_PATTERNS)

    if safe_patterns_found:
        compliance_findings.append(ComplianceFinding(
            id="lc-mtr-safe-001",
            category="money_transmitter",
            severity="info",
            title=f"Safe credit patterns present: {', '.join(safe_patterns_found)}",
            detail=(
                f"Found {len(safe_patterns_found)}/{len(SAFE_CREDIT_PATTERNS)} safe patterns: "
                f"{', '.join(safe_patterns_found)}"
            ),
            regulation="FinCEN",
            recommendation="Maintain these patterns to keep credits in loyalty-program territory.",
        ))

    if not safe_patterns_found:
        findings.append(Finding(
            id="lc-mtr-002",
            severity="medium",
            category="money_transmitter",
            title="No safe credit patterns found in services/API source",
            detail=(
                f"Expected one or more of: {', '.join(SAFE_CREDIT_PATTERNS)}. "
                "Missing patterns weaken FinCEN/PSA defense."
            ),
            recommendation=(
                "Add non_transferable, expires_at, or loyalty_program markers "
                "to credits service to reinforce compliance posture."
            ),
        ))


# ---------------------------------------------------------------------------
# Check 2: GDPR deletion paths
# ---------------------------------------------------------------------------


def _check_gdpr_deletion_paths(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Verify GDPR deletion/erasure infrastructure exists.

    Checks:
    - app/models/privacy.py exists with suppression_list, DataRequest, data_requests
    - app/services/ has deletion/purge logic
    - PRIVACY_DELETION_PATHS config references are present
    """
    privacy_model_path = MODELS_DIR / "privacy.py"
    privacy_source = _read_safe(privacy_model_path)

    # --- Privacy model checks ---
    privacy_model_exists = bool(privacy_source)
    metrics["gdpr_privacy_model_exists"] = privacy_model_exists

    if not privacy_model_exists:
        findings.append(Finding(
            id="lc-gdpr-001",
            severity="critical",
            category="gdpr",
            title="app/models/privacy.py not found",
            detail="GDPR compliance requires a privacy model with suppression and data request tables",
            file=_relative(privacy_model_path),
            recommendation="Create app/models/privacy.py with SuppressionList, DataRequest models",
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-gdpr-c001",
            category="gdpr",
            severity="critical",
            title="Privacy model missing — GDPR right to erasure cannot be fulfilled",
            file=_relative(privacy_model_path),
            regulation="GDPR",
            recommendation="app/models/privacy.py is required for GDPR/CCPA/PDPA deletion rights",
        ))
    else:
        # Check for required table/class references
        required_privacy_refs = {
            "suppression_list": re.compile(r"\bsuppression_list\b", re.IGNORECASE),
            "DataRequest": re.compile(r"\bDataRequest\b"),
            "data_requests": re.compile(r"\bdata_requests\b", re.IGNORECASE),
        }
        missing_refs: list[str] = []
        found_refs: list[str] = []
        for ref_name, pat in required_privacy_refs.items():
            if pat.search(privacy_source):
                found_refs.append(ref_name)
            else:
                missing_refs.append(ref_name)

        metrics["gdpr_privacy_model_refs_found"] = len(found_refs)
        metrics["gdpr_privacy_model_refs_expected"] = len(required_privacy_refs)

        if missing_refs:
            severity = "high" if "suppression_list" in missing_refs else "medium"
            findings.append(Finding(
                id="lc-gdpr-002",
                severity=severity,
                category="gdpr",
                title=f"Privacy model missing {len(missing_refs)} required reference(s)",
                detail=f"Missing: {', '.join(missing_refs)}. Found: {', '.join(found_refs)}",
                file=_relative(privacy_model_path),
                recommendation=(
                    "Ensure app/models/privacy.py defines suppression_list table, "
                    "DataRequest model, and data_requests relationship."
                ),
            ))
            compliance_findings.append(ComplianceFinding(
                id="lc-gdpr-c002",
                category="gdpr",
                severity=severity,
                title=f"GDPR deletion infrastructure incomplete: missing {', '.join(missing_refs)}",
                file=_relative(privacy_model_path),
                regulation="GDPR",
                recommendation="All three references required for GDPR/CCPA/PDPA right to erasure",
            ))

    # --- Services deletion/purge logic ---
    deletion_patterns = {
        "delete_user_data": re.compile(r"\bdelete_user_data\b", re.IGNORECASE),
        "purge": re.compile(r"\bpurge\b", re.IGNORECASE),
        "anonymize": re.compile(r"\banonymiz[e]?\b", re.IGNORECASE),
    }
    service_files = sorted(SERVICES_DIR.glob("*.py")) if SERVICES_DIR.is_dir() else []
    combined_services = ""
    for fp in service_files:
        src = _read_safe(fp)
        combined_services += "\n" + src

    deletion_found: list[str] = []
    deletion_missing: list[str] = []
    for name, pat in deletion_patterns.items():
        if pat.search(combined_services):
            deletion_found.append(name)
        else:
            deletion_missing.append(name)

    metrics["gdpr_deletion_functions_found"] = len(deletion_found)
    metrics["gdpr_deletion_functions_expected"] = len(deletion_patterns)

    if deletion_missing:
        severity = "high" if "delete_user_data" in deletion_missing else "medium"
        findings.append(Finding(
            id="lc-gdpr-003",
            severity=severity,
            category="gdpr",
            title=f"GDPR deletion logic missing: {', '.join(deletion_missing)}",
            detail=(
                f"Expected in app/services/: {', '.join(deletion_patterns.keys())}. "
                f"Missing: {', '.join(deletion_missing)}"
            ),
            recommendation=(
                "Implement delete_user_data, purge, and anonymize functions in app/services/ "
                "to fulfill GDPR/CCPA/PDPA right to erasure."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-gdpr-c003",
            category="gdpr",
            severity=severity,
            title=f"Deletion service functions missing: {', '.join(deletion_missing)}",
            regulation="GDPR",
            recommendation="GDPR Article 17 requires erasure capability across all user data",
        ))

    # --- PRIVACY_DELETION_PATHS config references ---
    deletion_path_refs_found: list[str] = []
    deletion_path_refs_missing: list[str] = []
    combined_all = combined_services + "\n" + privacy_source
    for path_ref in PRIVACY_DELETION_PATHS:
        pat = re.compile(rf"\b{re.escape(path_ref)}\b", re.IGNORECASE)
        if pat.search(combined_all):
            deletion_path_refs_found.append(path_ref)
        else:
            deletion_path_refs_missing.append(path_ref)

    metrics["gdpr_deletion_paths_found"] = len(deletion_path_refs_found)
    metrics["gdpr_deletion_paths_expected"] = len(PRIVACY_DELETION_PATHS)

    if deletion_path_refs_missing:
        compliance_findings.append(ComplianceFinding(
            id="lc-gdpr-c004",
            category="gdpr",
            severity="medium",
            title=f"PRIVACY_DELETION_PATHS not all referenced: missing {', '.join(deletion_path_refs_missing)}",
            detail=(
                f"Config defines: {', '.join(PRIVACY_DELETION_PATHS)}. "
                f"Missing from code: {', '.join(deletion_path_refs_missing)}"
            ),
            regulation="GDPR",
            recommendation=(
                "Ensure all PRIVACY_DELETION_PATHS (suppression_list, data_requests, "
                "archived_credit_transactions) are swept during deletion flows."
            ),
        ))


# ---------------------------------------------------------------------------
# Check 3: Consent gates
# ---------------------------------------------------------------------------


def _check_consent_gates(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Check marketplace model and API for consent-gate patterns.

    Expected: opt_in, consent, approve, consent_records, ConsentRecord, email_verified.
    """
    marketplace_model_path = MODELS_DIR / "marketplace.py"
    marketplace_api_path = API_DIR / "marketplace.py"

    model_source = _read_safe(marketplace_model_path)
    api_source = _read_safe(marketplace_api_path)
    combined = model_source + "\n" + api_source

    consent_patterns: dict[str, re.Pattern] = {
        "opt_in": re.compile(r"\bopt_in\b", re.IGNORECASE),
        "consent": re.compile(r"\bconsent\b", re.IGNORECASE),
        "approve": re.compile(r"\bapprove\b", re.IGNORECASE),
        "consent_records": re.compile(r"\bconsent_records\b", re.IGNORECASE),
        "ConsentRecord": re.compile(r"\bConsentRecord\b"),
    }

    consent_found: list[str] = []
    consent_missing: list[str] = []
    for name, pat in consent_patterns.items():
        if pat.search(combined):
            consent_found.append(name)
        else:
            consent_missing.append(name)

    metrics["consent_gates_found"] = len(consent_found)
    metrics["consent_gates_expected"] = len(consent_patterns)

    if consent_missing:
        severity = "high" if any(
            c in consent_missing for c in ("opt_in", "consent", "approve")
        ) else "medium"
        findings.append(Finding(
            id="lc-consent-001",
            severity=severity,
            category="consent",
            title=f"Consent gate patterns missing: {', '.join(consent_missing)}",
            detail=(
                f"Checked app/models/marketplace.py + app/api/marketplace.py. "
                f"Found: {', '.join(consent_found)}. Missing: {', '.join(consent_missing)}"
            ),
            recommendation=(
                "Privacy architecture requires explicit consent gates: opt_in toggle, "
                "approve/decline actions, and ConsentRecord model for audit trail."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-consent-c001",
            category="consent",
            severity=severity,
            title=f"Consent infrastructure incomplete: missing {', '.join(consent_missing)}",
            file=_relative(marketplace_model_path),
            regulation="GDPR",
            recommendation=(
                "GDPR requires consent records. PDPA requires valid consent for data collection. "
                "All marketplace contact disclosures must flow through explicit NH approval."
            ),
        ))

    # --- email_verified check (separate — auth layer) ---
    auth_api_path = API_DIR / "auth.py"
    user_model_path = MODELS_DIR / "user.py"
    auth_source = _read_safe(auth_api_path)
    user_source = _read_safe(user_model_path)
    email_verified_source = auth_source + "\n" + user_source

    has_email_verified = bool(
        re.search(r"\bemail_verified\b", email_verified_source, re.IGNORECASE)
    )
    metrics["has_email_verified"] = has_email_verified

    if not has_email_verified:
        findings.append(Finding(
            id="lc-consent-002",
            severity="high",
            category="consent",
            title="email_verified field not found in auth/user layer",
            detail="CLAUDE.md requires email verification before marketplace access",
            recommendation=(
                "Add email_verified to user model and enforce verification check "
                "before granting marketplace search and intro request access."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-consent-c002",
            category="consent",
            severity="high",
            title="Email verification gate missing — unverified users may access marketplace",
            file=_relative(auth_api_path),
            regulation="PDPA",
            recommendation=(
                "Singapore PDPA requires verified identity for services handling third-party contacts. "
                "Email verification is a minimum identity assurance step."
            ),
        ))


# ---------------------------------------------------------------------------
# Check 4: Suppression list
# ---------------------------------------------------------------------------


def _check_suppression_list(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Verify suppression list model, hash utility, and import-time sweep exist."""
    privacy_model_path = MODELS_DIR / "privacy.py"
    privacy_source = _read_safe(privacy_model_path)

    # --- SuppressionList model ---
    has_suppression_model = bool(
        re.search(r"\bSuppressionList\b", privacy_source)
        or re.search(r"\bsuppression_list\b", privacy_source, re.IGNORECASE)
    )
    metrics["has_suppression_model"] = has_suppression_model

    if not has_suppression_model:
        findings.append(Finding(
            id="lc-supp-001",
            severity="high",
            category="suppression",
            title="SuppressionList model not found in app/models/privacy.py",
            detail="The suppression list table/model is missing",
            file=_relative(privacy_model_path),
            recommendation=(
                "Define SuppressionList model with SHA-256 hashed email and name+company "
                "for cross-vault suppression sweep."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-supp-c001",
            category="suppression",
            severity="high",
            title="SuppressionList model absent — deletion requests cannot be fulfilled",
            file=_relative(privacy_model_path),
            regulation="GDPR",
            recommendation=(
                "GDPR/CCPA/PDPA require a mechanism for contacts to opt out of all vaults. "
                "The SuppressionList is that mechanism."
            ),
        ))

    # --- hash_for_suppression utility ---
    service_files = sorted(SERVICES_DIR.glob("*.py")) if SERVICES_DIR.is_dir() else []
    api_files = sorted(API_DIR.glob("*.py")) if API_DIR.is_dir() else []

    hash_util_found = False
    hash_util_location = ""
    for fp in list(service_files) + list(api_files):
        src = _read_safe(fp)
        if re.search(r"\bhash_for_suppression\b", src):
            hash_util_found = True
            hash_util_location = _relative(fp)
            break

    metrics["has_hash_for_suppression"] = hash_util_found

    if not hash_util_found:
        findings.append(Finding(
            id="lc-supp-002",
            severity="high",
            category="suppression",
            title="hash_for_suppression utility not found in services or API",
            detail="SHA-256 hashing utility for suppression matching not detected",
            recommendation=(
                "Implement hash_for_suppression(value) -> str using SHA-256 on normalized "
                "(lowercased, trimmed) inputs per CLAUDE.md PII hashing conventions."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-supp-c002",
            category="suppression",
            severity="high",
            title="SHA-256 suppression hash utility absent — vault boundary cannot be protected",
            regulation="GDPR",
            recommendation=(
                "The hash utility prevents PII from crossing vault boundaries while still "
                "allowing suppression checks. Required for privacy architecture compliance."
            ),
        ))

    # --- Import-time suppression sweep ---
    csv_parser_path = SERVICES_DIR / "csv_parser.py"
    csv_source = _read_safe(csv_parser_path)
    suppression_svc_path = SERVICES_DIR / "suppression.py"
    suppression_svc_source = _read_safe(suppression_svc_path)

    has_import_check = bool(
        re.search(r"\bsuppression\b", csv_source, re.IGNORECASE)
        or re.search(r"\bsuppression\b", suppression_svc_source, re.IGNORECASE)
    )
    metrics["has_import_time_suppression_check"] = has_import_check

    if not has_import_check:
        findings.append(Finding(
            id="lc-supp-003",
            severity="high",
            category="suppression",
            title="Suppression check not found at CSV import time",
            detail=(
                "Neither app/services/csv_parser.py nor app/services/suppression.py "
                "references suppression list at import time"
            ),
            file=_relative(csv_parser_path),
            recommendation=(
                "Per CLAUDE.md: suppression list must be checked at every CSV import. "
                "Add suppression sweep to csv_parser.py or call from Celery CSV task."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-supp-c003",
            category="suppression",
            severity="high",
            title="Suppression not enforced at CSV upload — contacts in suppression list may be stored",
            file=_relative(csv_parser_path),
            regulation="GDPR",
            recommendation=(
                "GDPR erasure requests must prevent re-ingestion of suppressed contacts. "
                "The import-time sweep is the primary enforcement point."
            ),
        ))

    # --- Suppression sweep in services ---
    has_sweep = bool(
        re.search(r"\bsuppression.*sweep\b|\bsweep.*suppression\b|\bcheck_suppression\b|\bsuppress\b",
                  suppression_svc_source, re.IGNORECASE)
        or re.search(r"\bsuppression\b", suppression_svc_source, re.IGNORECASE)
    )
    metrics["has_suppression_sweep_service"] = has_sweep

    if suppression_svc_source and has_sweep:
        compliance_findings.append(ComplianceFinding(
            id="lc-supp-c004",
            category="suppression",
            severity="info",
            title="Suppression service found and references suppression logic",
            file=_relative(suppression_svc_path),
            detail="app/services/suppression.py is present and contains suppression references",
            regulation="GDPR",
            recommendation="Verify periodic sweep covers all network holder vaults, not just new uploads.",
        ))


# ---------------------------------------------------------------------------
# Check 5: Security compliance
# ---------------------------------------------------------------------------


def _check_security_compliance(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Audit security compliance markers required by CLAUDE.md.

    Checks:
    - JWT token versioning (token_version on User model)
    - Account lockout (locked_until, failed_login_attempts on User model)
    - Security headers middleware
    - CORS configuration
    - audit_logs model
    """
    user_model_path = MODELS_DIR / "user.py"
    user_source = _read_safe(user_model_path)

    audit_model_path = MODELS_DIR / "audit.py"
    audit_source = _read_safe(audit_model_path)

    middleware_security_path = APP_DIR / "middleware" / "security_headers.py"
    middleware_source = _read_safe(middleware_security_path)

    # Look for CORS config in main.py or a cors middleware file
    main_path = APP_DIR / "main.py"
    main_source = _read_safe(main_path)
    cors_source = main_source + "\n" + middleware_source

    security_checks: dict[str, tuple[bool, str, str]] = {}

    # token_version
    has_token_version = bool(re.search(r"\btoken_version\b", user_source))
    security_checks["token_version"] = (
        has_token_version,
        _relative(user_model_path),
        "JWT token versioning prevents reuse after password/email change",
    )
    metrics["has_token_version"] = has_token_version

    # locked_until
    has_locked_until = bool(re.search(r"\blocked_until\b", user_source))
    security_checks["locked_until"] = (
        has_locked_until,
        _relative(user_model_path),
        "Account lockout (locked_until) prevents brute-force attacks",
    )
    metrics["has_locked_until"] = has_locked_until

    # failed_login_attempts
    has_failed_attempts = bool(re.search(r"\bfailed_login_attempts\b", user_source))
    security_checks["failed_login_attempts"] = (
        has_failed_attempts,
        _relative(user_model_path),
        "failed_login_attempts counter drives account lockout logic",
    )
    metrics["has_failed_login_attempts"] = has_failed_attempts

    # Security headers middleware
    has_security_headers = bool(
        re.search(r"\bsecurity.?headers\b|\bSecurityHeaders\b|\bhsts\b|\bX.Frame.Options\b",
                  middleware_source, re.IGNORECASE)
        or middleware_source  # file exists at all is a signal
    )
    security_checks["security_headers_middleware"] = (
        has_security_headers,
        _relative(middleware_security_path),
        "Security headers middleware (HSTS, X-Frame-Options, CSP) required on all responses",
    )
    metrics["has_security_headers_middleware"] = has_security_headers

    # CORS configuration
    has_cors = bool(
        re.search(r"\bCORSMiddleware\b|\bcors\b|\bCORS_ORIGINS\b", cors_source, re.IGNORECASE)
    )
    security_checks["cors_configuration"] = (
        has_cors,
        _relative(main_path),
        "CORS must be locked to explicit frontend origin — no wildcards",
    )
    metrics["has_cors_configuration"] = has_cors

    # audit_logs model
    has_audit_logs = bool(
        re.search(r"\baudit_logs\b|\bAuditLog\b", audit_source)
        or re.search(r"\baudit_logs\b|\bAuditLog\b", user_source)
    )
    security_checks["audit_logs"] = (
        has_audit_logs,
        _relative(audit_model_path),
        "Immutable audit_logs table required for sensitive operation logging",
    )
    metrics["has_audit_logs"] = has_audit_logs

    # Tally
    security_passed = sum(1 for ok, _, _ in security_checks.values() if ok)
    security_total = len(security_checks)
    security_score = round(security_passed / max(1, security_total), 2)
    metrics["security_compliance_score"] = security_score
    metrics["security_checks_passed"] = security_passed
    metrics["security_checks_total"] = security_total

    # Report failures
    for check_name, (passed, file_hint, rationale) in security_checks.items():
        if not passed:
            severity = "critical" if check_name in ("token_version", "audit_logs") else "high"
            findings.append(Finding(
                id=f"lc-sec-{check_name[:12]}",
                severity=severity,
                category="security_compliance",
                title=f"Security check failed: {check_name}",
                detail=rationale,
                file=file_hint,
                recommendation=(
                    f"Add or restore {check_name} per CLAUDE.md security architecture. "
                    f"See Security Architecture section for full context."
                ),
            ))
            compliance_findings.append(ComplianceFinding(
                id=f"lc-sec-c-{check_name[:10]}",
                category="security_compliance",
                severity=severity,
                title=f"Security compliance gap: {check_name} missing",
                file=file_hint,
                detail=rationale,
                regulation="GDPR",
                recommendation=(
                    "GDPR Article 32 requires appropriate technical security measures. "
                    f"{check_name} is part of the defense-in-depth architecture."
                ),
            ))


# ---------------------------------------------------------------------------
# Check 6: Breach notification
# ---------------------------------------------------------------------------


def _check_breach_notification(
    findings: list[Finding],
    compliance_findings: list[ComplianceFinding],
    metrics: dict,
) -> None:
    """Check for breach notification infrastructure in services and utils.

    Patterns: breach_notification, notify_breach, BreachNotification.
    Also checks CLAUDE.md for breach_notification mention.
    """
    breach_patterns: dict[str, re.Pattern] = {
        "breach_notification": re.compile(r"\bbreach_notification\b", re.IGNORECASE),
        "notify_breach": re.compile(r"\bnotify_breach\b", re.IGNORECASE),
        "BreachNotification": re.compile(r"\bBreachNotification\b"),
    }

    # Scan services and utils
    service_files = sorted(SERVICES_DIR.glob("*.py")) if SERVICES_DIR.is_dir() else []
    utils_dir = APP_DIR / "utils"
    utils_files = sorted(utils_dir.glob("*.py")) if utils_dir.is_dir() else []
    all_target_files = service_files + utils_files

    breach_found: dict[str, str] = {}  # pattern_name -> file where found
    for fp in all_target_files:
        src = _read_safe(fp)
        for pattern_name, pat in breach_patterns.items():
            if pattern_name not in breach_found and pat.search(src):
                breach_found[pattern_name] = _relative(fp)

    metrics["breach_notification_patterns_found"] = len(breach_found)
    metrics["breach_notification_patterns_checked"] = len(breach_patterns)

    # Check CLAUDE.md for breach_notification mention
    claude_md_path = PROJECT_ROOT / "CLAUDE.md"
    claude_md_source = _read_safe(claude_md_path)
    claude_md_mentions_breach = bool(
        re.search(r"breach.?notification", claude_md_source, re.IGNORECASE)
    )
    metrics["claude_md_documents_breach_notification"] = claude_md_mentions_breach

    if not breach_found:
        severity = "high"
        findings.append(Finding(
            id="lc-breach-001",
            severity=severity,
            category="breach_notification",
            title="Breach notification infrastructure not found",
            detail=(
                "No breach_notification, notify_breach, or BreachNotification "
                "patterns found in app/services/ or app/utils/"
            ),
            recommendation=(
                "Implement breach notification service (app/services/breach_notification.py) "
                "per GDPR Article 33 (72-hour regulator notification) and Article 34 "
                "(data subject notification for high-risk breaches)."
            ),
        ))
        compliance_findings.append(ComplianceFinding(
            id="lc-breach-c001",
            category="breach_notification",
            severity=severity,
            title="Breach notification service absent — GDPR Article 33 compliance gap",
            regulation="GDPR",
            recommendation=(
                "GDPR requires notification to supervisory authority within 72 hours of a breach. "
                "PDPA (Singapore) requires notification to PDPC within 3 days for significant breaches. "
                "Implement breach_notification.py with email alerts and regulator notification flow."
            ),
        ))
    else:
        patterns_missing = [p for p in breach_patterns if p not in breach_found]
        if patterns_missing:
            compliance_findings.append(ComplianceFinding(
                id="lc-breach-c002",
                category="breach_notification",
                severity="medium",
                title=f"Partial breach notification coverage: missing {', '.join(patterns_missing)}",
                detail=(
                    f"Found: {', '.join(f'{k} in {v}' for k, v in breach_found.items())}. "
                    f"Missing patterns: {', '.join(patterns_missing)}"
                ),
                regulation="GDPR",
                recommendation=(
                    "Ensure breach notification covers both regulator notification (notify_breach) "
                    "and data subject notification (BreachNotification model/record)."
                ),
            ))
        else:
            compliance_findings.append(ComplianceFinding(
                id="lc-breach-c003",
                category="breach_notification",
                severity="info",
                title="Breach notification infrastructure present",
                detail=(
                    f"All {len(breach_found)} patterns found: "
                    + ", ".join(f"{k} in {v}" for k, v in breach_found.items())
                ),
                regulation="GDPR",
                recommendation="Review notification flow covers 72-hour GDPR and 3-day PDPA deadlines.",
            ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> FinanceTeamReport:
    """Run all regulatory compliance checks and return a FinanceTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    compliance_findings: list[ComplianceFinding] = []
    metrics: dict = {}

    # Count files available
    service_py_count = len(list(SERVICES_DIR.glob("*.py"))) if SERVICES_DIR.is_dir() else 0
    api_py_count = len(list(API_DIR.glob("*.py"))) if API_DIR.is_dir() else 0
    model_py_count = len(list(MODELS_DIR.glob("*.py"))) if MODELS_DIR.is_dir() else 0
    metrics["services_files_available"] = service_py_count
    metrics["api_files_available"] = api_py_count
    metrics["model_files_available"] = model_py_count
    metrics["regulatory_frameworks_tracked"] = len(REGULATORY_FRAMEWORKS)

    # --- Run checks ---

    _check_money_transmitter_risk(findings, compliance_findings, metrics)
    _check_gdpr_deletion_paths(findings, compliance_findings, metrics)
    _check_consent_gates(findings, compliance_findings, metrics)
    _check_suppression_list(findings, compliance_findings, metrics)
    _check_security_compliance(findings, compliance_findings, metrics)
    _check_breach_notification(findings, compliance_findings, metrics)

    # --- Overall compliance score ---
    severity_penalty = {"critical": 25, "high": 15, "medium": 5, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    compliance_score = max(0.0, round(100.0 - penalty, 1))
    metrics["compliance_score"] = compliance_score

    critical_count = sum(1 for f in findings if f.severity == "critical")
    high_count = sum(1 for f in findings if f.severity == "high")
    metrics["critical_findings"] = critical_count
    metrics["high_findings"] = high_count
    metrics["total_findings"] = len(findings)
    metrics["compliance_findings_total"] = len(compliance_findings)

    duration = time.time() - start

    # --- Learning state ---

    ls = FinanceLearningState(AGENT_NAME)
    ls.record_scan(metrics)

    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding({
            "id": f.id,
            "severity": f.severity,
            "category": f.category,
            "title": f.title,
            "file": getattr(f, "file", None) or "",
        })
        file_hint = getattr(f, "file", None) or ""
        if file_hint:
            file_findings[file_hint] = file_findings.get(file_hint, 0) + 1

    for cf in compliance_findings:
        ls.record_finding({
            "id": cf.id,
            "severity": cf.severity,
            "category": cf.category,
            "title": cf.title,
            "file": cf.file or "",
        })

    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    # Health snapshot
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(compliance_score, finding_counts)

    # KPI tracking
    ls.track_kpi("compliance_score", compliance_score)
    ls.track_kpi("money_transmitter_risk_signals_found",
                 metrics.get("money_transmitter_risk_signals_found", 0))
    ls.track_kpi("gdpr_deletion_functions_found",
                 metrics.get("gdpr_deletion_functions_found", 0))
    ls.track_kpi("consent_gates_found", metrics.get("consent_gates_found", 0))
    ls.track_kpi("security_compliance_score", metrics.get("security_compliance_score", 0.0))
    ls.track_kpi("breach_notification_patterns_found",
                 metrics.get("breach_notification_patterns_found", 0))

    # Learning updates
    learning_updates: list[str] = [
        (
            f"Scanned {service_py_count} services + {api_py_count} API + "
            f"{model_py_count} model files; compliance_score={compliance_score}"
        ),
        f"Findings: {critical_count} critical, {high_count} high, {len(findings)} total",
        f"Security checks passed: {metrics.get('security_checks_passed', '?')}/{metrics.get('security_checks_total', '?')}",
        f"Consent gates found: {metrics.get('consent_gates_found', 0)}/{metrics.get('consent_gates_expected', 0)}",
        f"Money transmitter risk signals: {metrics.get('money_transmitter_risk_signals_found', 0)} found",
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

    return FinanceTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        compliance_findings=compliance_findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: FinanceTeamReport) -> Path:
    """Save report to finance_team/reports/legal_compliance_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    logger.info("legal_compliance: report saved to %s", path)
    return path
