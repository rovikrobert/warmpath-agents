"""DesignLead agent — design system audit, color/spacing/typography consistency, Tailwind analysis.

Scans frontend/src/**/*.jsx and CSS config for design system compliance.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from product_team.shared.config import (
    DESIGN_SYSTEM_TARGETS,
    FRONTEND_DIR,
    FRONTEND_SRC,
)
from product_team.shared.learning import ProductLearningState
from product_team.shared.report import DesignFinding, ProductTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "design_lead"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_jsx_files() -> list[Path]:
    """Return all .jsx files under frontend/src/."""
    if not FRONTEND_SRC.is_dir():
        return []
    return sorted(FRONTEND_SRC.rglob("*.jsx"))


def _find_css_files() -> list[Path]:
    """Return all .css files under frontend/src/."""
    if not FRONTEND_SRC.is_dir():
        return []
    return sorted(FRONTEND_SRC.rglob("*.css"))


def _find_tailwind_config() -> Path | None:
    """Find tailwind config file."""
    for name in ("tailwind.config.js", "tailwind.config.ts", "tailwind.config.mjs"):
        path = FRONTEND_DIR / name
        if path.exists():
            return path
    return None


def _read_safe(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(FRONTEND_SRC.parent.parent))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_color_consistency(
    jsx_files: list[Path],
    css_files: list[Path],
    design_findings: list[DesignFinding],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Extract color values, check hardcoded hex vs Tailwind classes."""
    hardcoded_hex: set[str] = set()
    tailwind_color_classes: set[str] = set()
    inline_color_count = 0

    hex_pattern = re.compile(r"#(?:[0-9a-fA-F]{3,8})\b")
    tw_color_pattern = re.compile(
        r"\b(?:text|bg|border|ring|shadow|outline|accent|fill|stroke|from|via|to)-"
        r"(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
        r"teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black|"
        r"transparent|current|inherit)-?\d*(?:/\d+)?\b"
    )
    inline_style_color = re.compile(r"style\s*=\s*\{?\{[^}]*color\s*:", re.IGNORECASE)

    for path in jsx_files:
        source = _read_safe(path)
        for match in hex_pattern.finditer(source):
            hardcoded_hex.add(match.group().lower())
        for match in tw_color_pattern.finditer(source):
            tailwind_color_classes.add(match.group())
        inline_color_count += len(inline_style_color.findall(source))

    for path in css_files:
        source = _read_safe(path)
        for match in hex_pattern.finditer(source):
            hardcoded_hex.add(match.group().lower())

    metrics["unique_hardcoded_colors"] = len(hardcoded_hex)
    metrics["tailwind_color_classes"] = len(tailwind_color_classes)
    metrics["inline_color_styles"] = inline_color_count

    max_colors = DESIGN_SYSTEM_TARGETS.get("max_unique_colors", 12)
    if len(hardcoded_hex) > max_colors:
        design_findings.append(
            DesignFinding(
                id="ds-color-001",
                category="color",
                severity="medium",
                title=f"{len(hardcoded_hex)} unique hardcoded colors (target: <={max_colors})",
                detail=f"Colors: {', '.join(sorted(hardcoded_hex)[:10])}{'...' if len(hardcoded_hex) > 10 else ''}",
                recommendation="Consolidate to Tailwind color palette or CSS custom properties",
            )
        )

    if inline_color_count > 0:
        design_findings.append(
            DesignFinding(
                id="ds-color-002",
                category="color",
                severity="low",
                title=f"{inline_color_count} inline color styles found",
                detail="Inline styles bypass the design system",
                recommendation="Use Tailwind classes instead of inline color styles",
            )
        )


def _check_spacing_consistency(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Audit Tailwind spacing class usage patterns."""
    spacing_classes: dict[str, int] = {}
    spacing_pattern = re.compile(
        r"\b(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|space-[xy])-"
        r"(?:\d+(?:\.\d+)?|px|auto)\b"
    )

    for path in jsx_files:
        source = _read_safe(path)
        for match in spacing_pattern.finditer(source):
            cls = match.group()
            spacing_classes[cls] = spacing_classes.get(cls, 0) + 1

    metrics["unique_spacing_classes"] = len(spacing_classes)
    metrics["total_spacing_usages"] = sum(spacing_classes.values())

    # Identify off-scale spacing (non-standard values)
    standard_values = set(
        [
            "0",
            "0.5",
            "1",
            "1.5",
            "2",
            "2.5",
            "3",
            "3.5",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
            "14",
            "16",
            "20",
            "24",
            "28",
            "32",
            "36",
            "40",
            "44",
            "48",
            "52",
            "56",
            "60",
            "64",
            "72",
            "80",
            "96",
            "px",
            "auto",
        ]
    )
    off_scale = []
    for cls in spacing_classes:
        val = cls.rsplit("-", 1)[-1]
        if val not in standard_values:
            off_scale.append(cls)

    if off_scale:
        design_findings.append(
            DesignFinding(
                id="ds-spacing-001",
                category="spacing",
                severity="low",
                title=f"{len(off_scale)} non-standard spacing values",
                detail=f"Off-scale: {', '.join(off_scale[:8])}",
                recommendation="Use Tailwind's default spacing scale for consistency",
            )
        )


def _check_typography(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Count unique text sizes and weights."""
    text_sizes: set[str] = set()
    font_weights: set[str] = set()
    size_pattern = re.compile(
        r"\btext-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl)\b"
    )
    weight_pattern = re.compile(
        r"\bfont-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black)\b"
    )

    for path in jsx_files:
        source = _read_safe(path)
        for match in size_pattern.finditer(source):
            text_sizes.add(match.group())
        for match in weight_pattern.finditer(source):
            font_weights.add(match.group())

    metrics["unique_text_sizes"] = len(text_sizes)
    metrics["unique_font_weights"] = len(font_weights)

    max_sizes = DESIGN_SYSTEM_TARGETS.get("max_unique_text_sizes", 8)
    if len(text_sizes) > max_sizes:
        design_findings.append(
            DesignFinding(
                id="ds-type-001",
                category="typography",
                severity="low",
                title=f"{len(text_sizes)} unique text sizes (target: <={max_sizes})",
                detail=f"Sizes: {', '.join(sorted(text_sizes))}",
                recommendation="Consolidate to a type scale with fewer sizes",
            )
        )


def _check_component_patterns(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Audit button variants, card patterns, modal patterns."""
    button_variants: set[str] = set()
    card_count = 0
    modal_count = 0

    button_class_pattern = re.compile(r'<button\b[^>]*className\s*=\s*["\{]([^"}\n]+)')
    card_pattern = re.compile(
        r'(?:rounded|shadow|border)[^"]*(?:rounded|shadow|border)', re.IGNORECASE
    )
    modal_pattern = re.compile(
        r"(?:Modal|modal|Dialog|dialog|overlay|Overlay)", re.IGNORECASE
    )

    for path in jsx_files:
        source = _read_safe(path)
        for match in button_class_pattern.finditer(source):
            button_variants.add(match.group(1)[:60])
        card_count += len(card_pattern.findall(source))
        modal_count += len(modal_pattern.findall(source))

    metrics["button_variants"] = len(button_variants)
    metrics["card_patterns"] = card_count
    metrics["modal_patterns"] = modal_count


def _check_dark_mode(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Check for dark: prefixes (dark mode readiness)."""
    files_with_dark = 0
    dark_pattern = re.compile(r"\bdark:\w")

    for path in jsx_files:
        source = _read_safe(path)
        if dark_pattern.search(source):
            files_with_dark += 1

    coverage = files_with_dark / max(1, len(jsx_files))
    metrics["dark_mode_files"] = files_with_dark
    metrics["dark_mode_coverage"] = round(coverage, 2)


def _check_animations(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Count transition/animate class usage."""
    transition_count = 0
    animate_count = 0

    transition_pattern = re.compile(r"\btransition(?:-\w+)?\b")
    animate_pattern = re.compile(r"\banimate-\w+\b")

    for path in jsx_files:
        source = _read_safe(path)
        transition_count += len(transition_pattern.findall(source))
        animate_count += len(animate_pattern.findall(source))

    metrics["transition_usages"] = transition_count
    metrics["animate_usages"] = animate_count


def _compute_design_system_score(
    jsx_files: list[Path],
    metrics: dict,
) -> float:
    """Compute % of styling via Tailwind vs inline/hardcoded."""
    total_tw_classes = 0
    total_inline_styles = 0

    tw_class_pattern = re.compile(r"\bclassName\s*=")
    inline_pattern = re.compile(r"\bstyle\s*=\s*\{")

    for path in jsx_files:
        source = _read_safe(path)
        total_tw_classes += len(tw_class_pattern.findall(source))
        total_inline_styles += len(inline_pattern.findall(source))

    total = total_tw_classes + total_inline_styles
    if total == 0:
        score = 100.0
    else:
        score = round((total_tw_classes / total) * 100, 1)

    metrics["tailwind_class_usages"] = total_tw_classes
    metrics["inline_style_usages"] = total_inline_styles
    metrics["design_system_score"] = score
    return score


def _validate_against_design_tokens(
    jsx_files: list[Path],
    design_findings: list[DesignFinding],
    metrics: dict,
) -> None:
    """Validate code against design-tokens.json spec. Flag drift."""
    import json
    from product_team.shared.config import DESIGN_TOKENS_PATH

    if not DESIGN_TOKENS_PATH.exists():
        metrics["design_tokens_loaded"] = False
        design_findings.append(
            DesignFinding(
                id="ds-tokens-missing",
                category="design_system",
                severity="medium",
                title="No design-tokens.json found",
                detail=f"Expected at {DESIGN_TOKENS_PATH}",
                recommendation="Create frontend/design-tokens.json with canonical design values",
            )
        )
        return

    try:
        tokens = json.loads(DESIGN_TOKENS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        metrics["design_tokens_loaded"] = False
        return

    metrics["design_tokens_loaded"] = True

    allowed_colors: set[str] = set()
    for group_colors in tokens.get("colors", {}).values():
        allowed_colors.update(group_colors)

    tw_color_pattern = re.compile(
        r"\b(?:text|bg|border|ring|shadow|from|via|to)-"
        r"((?:slate|gray|zinc|red|orange|amber|yellow|green|emerald|blue|indigo|violet|purple|pink|rose|white|black|transparent)-?\d*)"
    )

    off_token_colors: set[str] = set()
    on_token_colors: set[str] = set()

    for path in jsx_files:
        source = _read_safe(path)
        for match in tw_color_pattern.finditer(source):
            color = match.group(1)
            if color in allowed_colors:
                on_token_colors.add(color)
            else:
                off_token_colors.add(color)

    total_colors = len(on_token_colors) + len(off_token_colors)
    compliance = len(on_token_colors) / max(1, total_colors)

    metrics["token_color_drift"] = len(off_token_colors)
    metrics["token_colors_compliant"] = len(on_token_colors)
    metrics["token_compliance_pct"] = round(compliance * 100, 1)

    if off_token_colors:
        design_findings.append(
            DesignFinding(
                id="ds-tokens-color-drift",
                category="color",
                severity="low" if len(off_token_colors) <= 5 else "medium",
                title=f"{len(off_token_colors)} color values not in design tokens",
                detail=f"Off-spec: {', '.join(sorted(off_token_colors)[:8])}{'...' if len(off_token_colors) > 8 else ''}",
                recommendation="Add to design-tokens.json or replace with approved colors",
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> ProductTeamReport:
    """Run all design checks and return a ProductTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    design_findings: list[DesignFinding] = []
    metrics: dict = {}

    jsx_files = _find_jsx_files()
    css_files = _find_css_files()
    metrics["total_jsx_files"] = len(jsx_files)
    metrics["total_css_files"] = len(css_files)

    tw_config = _find_tailwind_config()
    metrics["tailwind_config_exists"] = tw_config is not None

    if not jsx_files:
        findings.append(
            Finding(
                id="ds-000",
                severity="info",
                category="design_system",
                title="No JSX files found in frontend/src/",
                detail="Frontend may not be initialized yet",
                recommendation="Initialize React frontend under frontend/src/",
            )
        )
    else:
        _check_color_consistency(
            jsx_files, css_files, design_findings, findings, metrics
        )
        _check_spacing_consistency(jsx_files, design_findings, metrics)
        _check_typography(jsx_files, design_findings, metrics)
        _check_component_patterns(jsx_files, design_findings, metrics)
        _check_dark_mode(jsx_files, design_findings, metrics)
        _check_animations(jsx_files, design_findings, metrics)
        ds_score = _compute_design_system_score(jsx_files, metrics)
        _validate_against_design_tokens(jsx_files, design_findings, metrics)

    duration = time.time() - start

    # Learning
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
    for df in design_findings:
        ls.record_finding(
            {
                "id": df.id,
                "severity": df.severity,
                "category": df.category,
                "title": df.title,
                "file": df.file,
            }
        )
        if df.file:
            file_findings[df.file] = file_findings.get(df.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)
    for df in design_findings:
        ls.record_severity_calibration(df.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    penalty += sum(severity_penalty.get(df.severity, 0) for df in design_findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    for df in design_findings:
        finding_counts[df.severity] = finding_counts.get(df.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("design_system_score", metrics.get("design_system_score", 0))
    ls.track_kpi("unique_hardcoded_colors", metrics.get("unique_hardcoded_colors", 0))

    learning_updates = [f"Scanned {len(jsx_files)} JSX + {len(css_files)} CSS files"]
    if jsx_files:
        learning_updates.append(
            f"Design system score: {metrics.get('design_system_score', 0)}%"
        )
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return ProductTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        design_findings=design_findings,
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
