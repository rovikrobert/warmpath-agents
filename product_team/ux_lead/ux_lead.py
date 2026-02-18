"""UXLead agent — accessibility audit, flow analysis, error/loading/empty state checks, heuristic eval.

Scans frontend/src/**/*.jsx for UX quality signals.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from agents.shared.report import Finding
from product_team.shared.config import (
    COMPONENTS_DIR,
    FRONTEND_SRC,
    PAGES_DIR,
    UX_HEURISTIC_WEIGHTS,
)
from product_team.shared.learning import ProductLearningState
from product_team.shared.report import ProductTeamReport, UXFinding

logger = logging.getLogger(__name__)

AGENT_NAME = "ux_lead"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_jsx_files() -> list[Path]:
    """Return all .jsx files under frontend/src/."""
    if not FRONTEND_SRC.is_dir():
        return []
    return sorted(FRONTEND_SRC.rglob("*.jsx"))


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


def _check_accessibility(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for aria-*, role, alt text, button labels."""
    total_files = len(jsx_files)
    files_with_aria = 0
    files_with_role = 0
    files_with_alt = 0
    missing_aria_files = []

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue

        has_aria = bool(re.search(r"aria-\w+", source))
        has_role = bool(re.search(r"role\s*=", source))
        has_alt = bool(re.search(r"alt\s*=", source))

        if has_aria:
            files_with_aria += 1
        if has_role:
            files_with_role += 1
        if has_alt:
            files_with_alt += 1

        # Check for buttons without accessible labels
        button_count = len(re.findall(r"<button\b", source))
        labeled_buttons = len(re.findall(r"<button\b[^>]*(?:aria-label|title)", source))
        text_buttons = len(re.findall(r"<button\b[^>]*>[^<]+</button>", source))

        if button_count > 0 and (labeled_buttons + text_buttons) < button_count:
            missing_aria_files.append(_relative(path))
            ux_findings.append(
                UXFinding(
                    id=f"ux-a11y-{path.stem}",
                    category="accessibility",
                    severity="medium",
                    title=f"Buttons may lack accessible labels in {path.name}",
                    file=_relative(path),
                    detail=f"{button_count} buttons found, {labeled_buttons + text_buttons} with text/aria-label",
                    heuristic="Accessibility — button labeling",
                    recommendation="Add aria-label or visible text to all buttons",
                )
            )

        # Check for images without alt text
        img_count = len(re.findall(r"<img\b", source))
        img_with_alt = len(re.findall(r"<img\b[^>]*alt\s*=", source))
        if img_count > img_with_alt:
            ux_findings.append(
                UXFinding(
                    id=f"ux-alt-{path.stem}",
                    category="accessibility",
                    severity="medium",
                    title=f"Images missing alt text in {path.name}",
                    file=_relative(path),
                    detail=f"{img_count} images, {img_with_alt} with alt text",
                    heuristic="Accessibility — image alt text",
                    recommendation="Add alt attributes to all <img> tags",
                )
            )

    aria_pct = files_with_aria / max(1, total_files)
    metrics["accessibility_aria_coverage"] = round(aria_pct, 2)
    metrics["accessibility_role_files"] = files_with_role
    metrics["accessibility_alt_files"] = files_with_alt

    if aria_pct < 0.3:
        findings.append(
            Finding(
                id="ux-001",
                severity="high",
                category="ux_quality",
                title=f"Low ARIA attribute coverage ({aria_pct:.0%})",
                detail=f"Only {files_with_aria}/{total_files} JSX files use aria-* attributes",
                recommendation="Add ARIA labels to interactive elements for screen reader support",
            )
        )


def _check_loading_states(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for loading state patterns (spinners, skeletons)."""
    total_pages = 0
    pages_with_loading = 0
    loading_patterns = re.compile(
        r"(?:loading|isLoading|spinner|skeleton|Spinner|Loading|CircularProgress)",
        re.IGNORECASE,
    )

    for path in jsx_files:
        if "pages/" not in str(path):
            continue
        total_pages += 1
        source = _read_safe(path)
        if loading_patterns.search(source):
            pages_with_loading += 1
        else:
            ux_findings.append(
                UXFinding(
                    id=f"ux-load-{path.stem}",
                    category="loading_state",
                    severity="medium",
                    title=f"No loading state detected in {path.name}",
                    file=_relative(path),
                    detail="Page may show blank content during data fetching",
                    heuristic="Visibility of system status",
                    recommendation="Add loading spinner or skeleton screen",
                )
            )

    coverage = pages_with_loading / max(1, total_pages)
    metrics["loading_state_coverage"] = round(coverage, 2)
    metrics["pages_total"] = total_pages
    metrics["pages_with_loading"] = pages_with_loading


def _check_error_states(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for error handling and display patterns."""
    total_pages = 0
    pages_with_errors = 0
    error_patterns = re.compile(
        r"(?:error|Error|catch\b|\.catch\(|onError|errorMessage|isError|err\b)",
    )

    for path in jsx_files:
        if "pages/" not in str(path):
            continue
        total_pages += 1
        source = _read_safe(path)
        if error_patterns.search(source):
            pages_with_errors += 1
        else:
            ux_findings.append(
                UXFinding(
                    id=f"ux-err-{path.stem}",
                    category="error_state",
                    severity="medium",
                    title=f"No error handling detected in {path.name}",
                    file=_relative(path),
                    detail="Page may fail silently without user feedback",
                    heuristic="Error prevention & recovery",
                    recommendation="Add try/catch, error state display, or error boundary",
                )
            )

    coverage = pages_with_errors / max(1, total_pages)
    metrics["error_state_coverage"] = round(coverage, 2)
    metrics["pages_with_error_handling"] = pages_with_errors


def _check_empty_states(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    metrics: dict,
) -> None:
    """Check for empty state / no-data messaging."""
    total_pages = 0
    pages_with_empty = 0
    empty_patterns = re.compile(
        r"(?:no\s+(?:data|results|contacts|items|applications)|empty|nothing\s+(?:here|to\s+show|found)|\.length\s*===?\s*0)",
        re.IGNORECASE,
    )

    for path in jsx_files:
        if "pages/" not in str(path):
            continue
        total_pages += 1
        source = _read_safe(path)
        if empty_patterns.search(source):
            pages_with_empty += 1

    coverage = pages_with_empty / max(1, total_pages)
    metrics["empty_state_coverage"] = round(coverage, 2)
    metrics["pages_with_empty_state"] = pages_with_empty


def _check_form_validation(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    metrics: dict,
) -> None:
    """Check for inline form validation patterns."""
    files_with_forms = 0
    files_with_validation = 0
    form_pattern = re.compile(r"<form\b|onSubmit|handleSubmit")
    validation_pattern = re.compile(
        r"(?:required|pattern=|validate|validation|setError|formError|invalid)",
        re.IGNORECASE,
    )

    for path in jsx_files:
        source = _read_safe(path)
        if form_pattern.search(source):
            files_with_forms += 1
            if validation_pattern.search(source):
                files_with_validation += 1
            else:
                ux_findings.append(
                    UXFinding(
                        id=f"ux-form-{path.stem}",
                        category="form_validation",
                        severity="low",
                        title=f"Form without inline validation in {path.name}",
                        file=_relative(path),
                        detail="Form may lack client-side validation feedback",
                        heuristic="Error prevention",
                        recommendation="Add inline validation for required fields",
                    )
                )

    metrics["forms_total"] = files_with_forms
    metrics["forms_with_validation"] = files_with_validation


def _check_responsive(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    metrics: dict,
) -> None:
    """Check for Tailwind responsive prefixes (sm:, md:, lg:, xl:)."""
    total_files = len(jsx_files)
    files_with_responsive = 0
    responsive_pattern = re.compile(r"\b(?:sm:|md:|lg:|xl:|2xl:)\w")

    for path in jsx_files:
        source = _read_safe(path)
        if responsive_pattern.search(source):
            files_with_responsive += 1

    coverage = files_with_responsive / max(1, total_files)
    metrics["responsive_coverage"] = round(coverage, 2)
    metrics["files_with_responsive"] = files_with_responsive


def _check_privacy_indicators(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    metrics: dict,
) -> None:
    """Check for privacy-related UI references (vault, private, anonymous, consent)."""
    privacy_pattern = re.compile(
        r"(?:vault|private|anonymous|consent|privacy|confidential|encrypted|secure)",
        re.IGNORECASE,
    )
    files_with_privacy = 0

    for path in jsx_files:
        source = _read_safe(path)
        if privacy_pattern.search(source):
            files_with_privacy += 1

    metrics["privacy_indicator_files"] = files_with_privacy


def _check_flow_efficiency(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    metrics: dict,
) -> None:
    """Estimate clicks to complete critical paths by counting page transitions."""
    # Count pages and navigation patterns
    page_files = [p for p in jsx_files if "pages/" in str(p)]
    nav_pattern = re.compile(r"(?:navigate\(|useNavigate|Link\s+to=|href=)")

    total_nav_links = 0
    for path in page_files:
        source = _read_safe(path)
        total_nav_links += len(nav_pattern.findall(source))

    metrics["page_count"] = len(page_files)
    metrics["total_nav_links"] = total_nav_links
    if page_files:
        metrics["avg_nav_per_page"] = round(total_nav_links / len(page_files), 1)


def _run_accessibility_audit(
    ux_findings: list[UXFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Run pa11y for WCAG 2.1 AA accessibility testing. Falls back if unavailable."""
    try:
        result = subprocess.run(
            ["npx", "pa11y", "--version"],
            capture_output=True, text=True, timeout=15,
            cwd=str(FRONTEND_SRC.parent),
        )
        if result.returncode != 0:
            raise FileNotFoundError("pa11y not available")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        metrics["pa11y_available"] = False
        findings.append(
            Finding(
                id="ux-pa11y-unavailable",
                severity="info",
                category="accessibility",
                title="pa11y not available — using static analysis only",
                detail="Install pa11y: npm install -D pa11y (in frontend/)",
                recommendation="Install pa11y for WCAG 2.1 AA compliance testing",
            )
        )
        return

    metrics["pa11y_available"] = True
    target = "http://localhost:3000"
    try:
        result = subprocess.run(
            ["npx", "pa11y", target, "--reporter", "json", "--standard", "WCAG2AA"],
            capture_output=True, text=True, timeout=30,
            cwd=str(FRONTEND_SRC.parent),
        )
        if result.stdout.strip():
            import json as _json
            try:
                issues = _json.loads(result.stdout)
            except _json.JSONDecodeError:
                issues = []
            metrics["pa11y_issues"] = len(issues)
            errors = [i for i in issues if i.get("type") == "error"]
            warnings = [i for i in issues if i.get("type") == "warning"]
            metrics["pa11y_errors"] = len(errors)
            metrics["pa11y_warnings"] = len(warnings)
            for issue in errors[:10]:
                ux_findings.append(
                    UXFinding(
                        id=f"ux-pa11y-{issue.get('code', 'unknown')[:30]}",
                        category="accessibility",
                        severity="high" if issue.get("type") == "error" else "medium",
                        title=f"WCAG: {issue.get('message', 'Unknown issue')[:80]}",
                        file=target,
                        detail=f"Rule: {issue.get('code', '?')} | Element: {issue.get('selector', '?')}",
                        heuristic="WCAG 2.1 AA",
                        recommendation=f"Fix: {issue.get('context', '')[:100]}",
                    )
                )
        else:
            metrics["pa11y_issues"] = 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        metrics["pa11y_issues"] = -1
        logger.warning("pa11y scan failed: %s", exc)


def _analyze_user_flows(
    jsx_files: list[Path],
    ux_findings: list[UXFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Build page transition graph and validate against persona journeys."""
    from product_team.shared.config import PERSONA_JOURNEYS

    graph: dict[str, set[str]] = {}
    page_files = [p for p in jsx_files if "pages/" in str(p)]

    # Parse App.jsx for route definitions
    app_jsx = FRONTEND_SRC / "App.jsx"
    route_to_page: dict[str, str] = {}
    if app_jsx.exists():
        app_source = _read_safe(app_jsx)
        route_pattern = re.compile(
            r'path\s*=\s*["\']([^"\']+)["\']\s*[^>]*element\s*=\s*\{?\s*<\s*(\w+)',
        )
        for match in route_pattern.finditer(app_source):
            route_to_page[match.group(1)] = match.group(2)

    nav_patterns = [
        re.compile(r'navigate\s*\(\s*["\']([^"\']+)["\']'),
        re.compile(r'<Link\s+to\s*=\s*["\']([^"\']+)["\']'),
        re.compile(r'href\s*=\s*["\'](/[^"\']+)["\']'),
    ]

    for page_path in page_files:
        page_name = page_path.stem
        source = _read_safe(page_path)
        targets: set[str] = set()
        for pattern in nav_patterns:
            for match in pattern.finditer(source):
                target_path = match.group(1)
                target_page = route_to_page.get(target_path)
                if target_page:
                    targets.add(target_page)
        graph[page_name] = targets

    metrics["flow_graph_nodes"] = len(graph)
    metrics["flow_graph_edges"] = sum(len(v) for v in graph.values())

    dead_ends = [page for page, targets in graph.items() if not targets]
    metrics["dead_end_pages"] = len(dead_ends)

    if dead_ends:
        ux_findings.append(
            UXFinding(
                id="ux-flow-deadends",
                category="flow_analysis",
                severity="medium",
                title=f"{len(dead_ends)} pages are dead ends (no outgoing navigation)",
                file="",
                detail=f"Pages: {', '.join(sorted(dead_ends)[:10])}",
                heuristic="User control & freedom",
                recommendation="Add navigation options (back, home, next step) to dead-end pages",
            )
        )

    all_pages = set(graph.keys())
    for persona_id, journeys in PERSONA_JOURNEYS.items():
        reachable_count = 0
        total_steps = 0
        for journey in journeys:
            for i in range(len(journey) - 1):
                total_steps += 1
                source_page = journey[i]
                target_page = journey[i + 1]
                if source_page in graph and target_page in graph.get(source_page, set()):
                    reachable_count += 1
        coverage = reachable_count / max(1, total_steps)
        metrics[f"journey_coverage_{persona_id}"] = round(coverage, 2)
        if coverage < 0.5:
            findings.append(
                Finding(
                    id=f"ux-flow-{persona_id}",
                    severity="high",
                    category="flow_analysis",
                    title=f"{persona_id} journey coverage: {coverage:.0%} — critical navigation gaps",
                    detail=f"Only {reachable_count}/{total_steps} journey steps have direct navigation links",
                    recommendation=f"Add navigation paths to complete the {persona_id} user flow",
                )
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> ProductTeamReport:
    """Run all UX checks and return a ProductTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    ux_findings: list[UXFinding] = []
    metrics: dict = {}

    jsx_files = _find_jsx_files()
    metrics["total_jsx_files"] = len(jsx_files)

    if not jsx_files:
        findings.append(
            Finding(
                id="ux-000",
                severity="info",
                category="ux_quality",
                title="No JSX files found in frontend/src/",
                detail="Frontend may not be initialized yet",
                recommendation="Initialize React frontend under frontend/src/",
            )
        )
    else:
        _check_accessibility(jsx_files, ux_findings, findings, metrics)
        _run_accessibility_audit(ux_findings, findings, metrics)
        _check_loading_states(jsx_files, ux_findings, findings, metrics)
        _check_error_states(jsx_files, ux_findings, findings, metrics)
        _check_empty_states(jsx_files, ux_findings, metrics)
        _check_form_validation(jsx_files, ux_findings, metrics)
        _check_responsive(jsx_files, ux_findings, metrics)
        _check_privacy_indicators(jsx_files, ux_findings, metrics)
        _check_flow_efficiency(jsx_files, ux_findings, metrics)
        _analyze_user_flows(jsx_files, ux_findings, findings, metrics)

    # Compute UX health score
    score_components = {
        "accessibility": metrics.get("accessibility_aria_coverage", 0),
        "loading_states": metrics.get("loading_state_coverage", 0),
        "error_states": metrics.get("error_state_coverage", 0),
        "empty_states": metrics.get("empty_state_coverage", 0),
        "responsive_design": metrics.get("responsive_coverage", 0),
    }
    weighted = sum(
        score_components.get(k, 0) * UX_HEURISTIC_WEIGHTS.get(k, 0)
        for k in score_components
    )
    total_weight = sum(UX_HEURISTIC_WEIGHTS.get(k, 0) for k in score_components)
    ux_score = round(weighted / max(0.01, total_weight) * 100, 1)
    metrics["ux_health_score"] = ux_score

    duration = time.time() - start

    # Learning — record scan, findings, health snapshot
    ls = ProductLearningState(AGENT_NAME)
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
    for uf in ux_findings:
        ls.record_finding(
            {
                "id": uf.id,
                "severity": uf.severity,
                "category": uf.category,
                "title": uf.title,
                "file": uf.file,
            }
        )
        if uf.file:
            file_findings[uf.file] = file_findings.get(uf.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)
    for uf in ux_findings:
        ls.record_severity_calibration(uf.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    penalty += sum(severity_penalty.get(uf.severity, 0) for uf in ux_findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    for uf in ux_findings:
        finding_counts[uf.severity] = finding_counts.get(uf.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("ux_health_score", ux_score)
    ls.track_kpi("total_jsx_files", len(jsx_files))

    learning_updates = [f"Scanned {len(jsx_files)} JSX files, UX score={ux_score}"]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return ProductTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        ux_findings=ux_findings,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: ProductTeamReport) -> Path:
    """Save report to product_team/reports/."""
    from product_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
