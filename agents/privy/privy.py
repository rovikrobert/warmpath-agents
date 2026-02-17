"""Privy agent — wraps scripts/privacy_scan.py to output AgentReport."""

from __future__ import annotations

import logging
import time

from agents.shared.report import AgentReport, Finding
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "privy"

# Severity mapping: scripts use uppercase, AgentReport uses lowercase
_SEV_MAP = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "INFO": "info",
}


def _convert_findings(raw: list[dict]) -> list[Finding]:
    """Convert the scripts/privacy_scan.py findings dicts to Finding objects."""
    results: list[Finding] = []
    seen_ids: set[str] = set()

    for i, f in enumerate(raw):
        severity = _SEV_MAP.get(f.get("severity", ""), "medium")
        category = f.get("category", "unknown")
        message = f.get("message", "")
        file_path = f.get("file", "") or None
        line = f.get("line", 0) or None

        # Generate a stable ID
        base_id = f"PRIV-{category.upper().replace('_', '-')}"
        if file_path and line:
            candidate = f"{base_id}-{file_path.replace('/', '-')}:{line}"
        else:
            candidate = f"{base_id}-{i}"

        # Deduplicate
        if candidate in seen_ids:
            candidate = f"{candidate}-{i}"
        seen_ids.add(candidate)

        results.append(
            Finding(
                id=candidate,
                severity=severity,
                category=category,
                title=message[:120],
                detail=message,
                file=file_path,
                line=line,
            )
        )

    return results


def scan() -> AgentReport:
    """Run the privacy scanner and return an AgentReport."""
    start = time.time()

    # Import the script module and reset its state
    import scripts.privacy_scan as priv

    priv.findings.clear()

    # Run all check phases
    try:
        priv.check_encryption()
    except Exception as exc:
        logger.warning("Encryption check failed: %s", exc)

    try:
        priv.check_suppression()
    except Exception as exc:
        logger.warning("Suppression check failed: %s", exc)

    try:
        priv.check_consent()
    except Exception as exc:
        logger.warning("Consent check failed: %s", exc)

    try:
        priv.check_data_retention()
    except Exception as exc:
        logger.warning("Data retention check failed: %s", exc)

    try:
        priv.check_dsar()
    except Exception as exc:
        logger.warning("DSAR check failed: %s", exc)

    try:
        priv.check_pii_leaks()
    except Exception as exc:
        logger.warning("PII leak check failed: %s", exc)

    try:
        priv.check_vault_isolation()
    except Exception as exc:
        logger.warning("Vault isolation check failed: %s", exc)

    try:
        priv.check_marketplace_anonymization()
    except Exception as exc:
        logger.warning("Marketplace anonymization check failed: %s", exc)

    try:
        priv.check_privacy_policy()
    except Exception as exc:
        logger.warning("Privacy policy check failed: %s", exc)

    try:
        priv.check_info_leaks()
    except Exception as exc:
        logger.warning("Info leak check failed: %s", exc)

    # Convert findings
    findings = _convert_findings(priv.findings)

    # Metrics
    sev_counts: dict[str, int] = {}
    for f in findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    metrics = {
        "total_findings": len(findings),
        "checks_run": 10,
        **{f"{k}_count": v for k, v in sev_counts.items()},
    }

    # Self-learning
    learning_updates: list[str] = []
    try:
        file_counts: dict[str, int] = {}
        for f in findings:
            learning.record_finding(
                AGENT_NAME,
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "file": f.file,
                    "line": f.line,
                    "title": f.title,
                },
            )
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1

        if file_counts:
            learning.update_attention_weights(AGENT_NAME, file_counts)

        # Recurrence enrichment
        for f in findings:
            prev = learning.get_recurrence_count(AGENT_NAME, f.category, f.file)
            if prev > 0:
                f.recurrence_count = prev + 1

        learning.record_scan(
            AGENT_NAME,
            {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
        )
        learning_updates.append(
            f"Recorded scan #{learning.get_total_scans(AGENT_NAME)}"
        )
    except Exception as exc:
        logger.warning("Learning update failed: %s", exc)

    elapsed = time.time() - start
    report = AgentReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )

    logger.info("Privy scan complete: %d findings in %.1fs", len(findings), elapsed)
    return report


# CLI
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    report = scan()
    print(report.to_markdown())
    sev = {}
    for f in report.findings:
        sev[f.severity] = sev.get(f.severity, 0) + 1
    print(
        f"\nTotal: {len(report.findings)} findings ({', '.join(f'{v} {k}' for k, v in sorted(sev.items())) or 'clean'})"
    )
    if sev.get("critical", 0) or sev.get("high", 0):
        sys.exit(1)
