"""Auto-repair pipeline for agent scan findings.

Runs safe auto-repairs (ruff lint + format) on findings marked
auto_fixable=True. Gates on pytest before committing.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.shared.report import Finding

logger = logging.getLogger(__name__)

# Marker file prevents multiple repair attempts per day
_MARKER_DIR = Path(__file__).resolve().parent.parent / "reports"


@dataclass
class RepairResult:
    fixed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    pr_url: str | None = None
    errors: list[str] = field(default_factory=list)
    fixed_ids: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    ci_minutes_estimated: float = 0.0


def _already_attempted_today() -> bool:
    """Check if a repair attempt was already made today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    marker = _MARKER_DIR / f"repair-{today}.marker"
    return marker.exists()


def _mark_attempted() -> bool:
    """Atomically claim today's repair slot.

    Returns True if this process won the race (marker created).
    Returns False if another process already claimed it.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = _MARKER_DIR / f"repair-{today}.marker"
    try:
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"claimed at {datetime.now(timezone.utc).isoformat()}\n".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with timeout."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=cwd)


def _emit_repair_event(
    *, action: str, fixed_count: int = 0, detail: str = "", pr_url: str = ""
) -> None:
    """Emit repair outcome to cto:events Redis Stream (best-effort)."""
    try:
        import redis
        from agents.shared.event_stream import STREAM_KEY

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return
        r = redis.from_url(redis_url)
        r.xadd(
            STREAM_KEY,
            {
                "team": "engineering",
                "agent": "repair_pipeline",
                "action": action,
                "fixed_count": str(fixed_count),
                "detail": detail[:500],
                "pr_url": pr_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        logger.debug("Failed to emit repair event: %s", exc)


def _collect_recommendations(findings: list[Finding]) -> list[str]:
    """Extract actionable recommendations from high/critical non-auto-fixable findings."""
    recs: list[str] = []
    for f in sorted(findings, key=lambda x: x.sort_key):
        if f.auto_fixable or f.severity not in ("critical", "high"):
            continue
        if f.recommendation:
            rec = f.recommendation
        else:
            # Auto-generate from finding fields
            rec = f"{f.title}"
            if f.file:
                rec += f" in {f.file}"
            if f.detail:
                rec += f" — {f.detail[:100]}"
        recs.append(rec)
    return recs[:5]  # Cap at 5 recommendations


def evaluate_fix_quality(
    diff: str,
    finding_title: str,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Evaluate whether an auto-fix actually improves the codebase.

    Returns {"score": 1-5, "assessment": str, "needs_human_review": bool}.
    In mock mode (default), uses deterministic heuristic.
    """
    lines = diff.strip().split("\n") if diff.strip() else []
    diff_size = len(lines)

    if not use_llm:
        is_trivial = diff_size < 50 and any(
            kw in finding_title.lower()
            for kw in ("lint", "format", "style", "import", "whitespace", "indent")
        )
        score = 4 if is_trivial else 3
        return {
            "score": score,
            "assessment": f"Auto-evaluated: {'trivial fix' if is_trivial else 'non-trivial fix'} "
            f"({diff_size} lines changed)",
            "needs_human_review": score < 3,
        }

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Rate this auto-fix on a 1-5 scale. "
                        f"Finding: {finding_title}\n\nDiff:\n```\n{diff[:2000]}\n```\n\n"
                        f"Respond with ONLY a JSON object: "
                        f'{{"score": N, "assessment": "one sentence"}}'
                    ),
                }
            ],
        )
        import json as _json

        result = _json.loads(response.content[0].text)
        result["needs_human_review"] = result.get("score", 3) < 3
        return result
    except Exception as exc:
        logger.warning("LLM evaluation failed, falling back to heuristic: %s", exc)
        return evaluate_fix_quality(diff, finding_title, use_llm=False)


def repair_auto_fixable(findings: list[Finding]) -> RepairResult:
    """Execute safe auto-repairs for findings marked auto_fixable=True.

    Safety guardrails:
    - Only runs ruff check --fix and ruff format (no arbitrary commands)
    - pytest must pass before committing
    - Creates branch + PR for human review (never merges)
    - Max 1 attempt per day (marker file dedup)
    - Reverts on test failure
    """
    result = RepairResult()

    # Always collect recommendations (even if repair is skipped)
    result.recommendations = _collect_recommendations(findings)

    fixable = [f for f in findings if f.auto_fixable and f.repair_status == "pending"]
    not_fixable = [f for f in findings if not f.auto_fixable]
    result.skipped_count = len(not_fixable)

    if not fixable:
        logger.info("No auto-fixable findings to repair")
        return result

    # Daily dedup guard — atomic claim
    if _already_attempted_today():
        logger.info("Repair already attempted today — skipping")
        for f in fixable:
            f.repair_status = "skipped"
        result.skipped_count += len(fixable)
        return result

    if not _mark_attempted():
        logger.info("Another process claimed today's repair slot — skipping")
        for f in fixable:
            f.repair_status = "skipped"
        result.skipped_count += len(fixable)
        return result

    logger.info("Attempting auto-repair for %d findings", len(fixable))

    # Stash any uncommitted changes so repair only commits ruff fixes
    _run(["git", "stash", "push", "-m", "agent-repair-stash"])

    # Step 1: Run ruff fixes
    try:
        _run(["ruff", "check", "--fix", "."])
        _run(["ruff", "format", "."])
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("Ruff command failed: %s", exc)
        result.errors.append(f"Ruff failed: {exc}")
        result.failed_count = len(fixable)
        for f in fixable:
            f.repair_status = "failed"
        return result

    # Step 2: Check if ruff made any changes
    diff_result = _run(["git", "diff", "--stat"])
    if not diff_result.stdout.strip():
        logger.info("Ruff made no changes — nothing to commit")
        result.skipped_count += len(fixable)
        for f in fixable:
            f.repair_status = "skipped"
        return result

    # Step 3: Run pytest to verify no regressions
    try:
        test_result = _run(["pytest", "-n", "auto", "--timeout=120", "-q"])
        tests_passed = test_result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("pytest timed out during repair verification")
        tests_passed = False

    if not tests_passed:
        # Revert all changes
        logger.warning("Tests failed after repair — reverting")
        _run(["git", "checkout", "."])
        _run(["git", "stash", "pop"])
        result.failed_count = len(fixable)
        result.errors.append("Tests failed after ruff fixes — reverted")
        for f in fixable:
            f.repair_status = "failed"
        _emit_repair_event(
            action="repair_failure",
            detail="Tests failed after ruff fixes — reverted",
        )
        return result

    # Step 4: Evaluate fix quality (LLM-as-judge)
    full_diff_result = _run(["git", "diff"])
    full_diff = full_diff_result.stdout.strip()[:10000]  # Cap to avoid large memory
    quality = evaluate_fix_quality(
        diff=full_diff,
        finding_title=", ".join(f.title for f in fixable[:3]),
        use_llm=True,
    )
    logger.info("Fix quality score: %d/5 — %s", quality["score"], quality["assessment"])

    if quality.get("needs_human_review"):
        logger.warning("Quality score < 3 — flagging for human review")

    # Step 5: Create branch, commit, push, create PR
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branch = f"fix/agent-auto-repair-{today}"
    try:
        _run(["git", "checkout", "-b", branch])
        _run(
            ["git", "add", "-u"]
        )  # Only tracked files — prevents bundling unrelated files
        _run(
            [
                "git",
                "commit",
                "-m",
                f"fix: agent auto-repair (ruff lint + format) {today}",
            ]
        )
        push_result = _run(["git", "push", "-u", "origin", branch])

        if push_result.returncode == 0:
            # Build PR body with quality score
            quality_line = (
                f"\n### Quality Review\n"
                f"Score: **{quality['score']}/5** — {quality['assessment']}\n"
            )
            if quality.get("needs_human_review"):
                quality_line += "⚠️ **Flagged for human review** (score < 3)\n"

            # Create PR via gh CLI
            pr_result = _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    f"fix: agent auto-repair {today}",
                    "--body",
                    "Auto-generated by agent repair pipeline.\n\n"
                    "### Findings fixed\n"
                    + "".join(
                        f"- **[{f.id}]** {f.title}"
                        + (f" (`{f.file}`)" if f.file else "")
                        + "\n"
                        for f in fixable
                    )
                    + f"\nTotal: {len(fixable)} findings. Tests passed before commit."
                    + quality_line,
                    "--base",
                    "master",
                ]
            )
            if pr_result.returncode == 0:
                result.pr_url = pr_result.stdout.strip()

        # Return to original branch
        _run(["git", "checkout", "-"])
        _run(["git", "stash", "pop"])

        result.fixed_count = len(fixable)
        result.fixed_ids = [f.id for f in fixable]
        result.ci_minutes_estimated = 3.0
        for f in fixable:
            f.repair_status = "fixed"
        _emit_repair_event(
            action="repair_success",
            fixed_count=result.fixed_count,
            pr_url=result.pr_url or "",
        )

    except Exception as exc:
        logger.error("Git/PR creation failed: %s", exc)
        result.errors.append(f"Git/PR failed: {exc}")
        result.failed_count = len(fixable)
        _emit_repair_event(action="repair_failure", detail=f"Git/PR failed: {exc}")
        _run(["git", "checkout", "."])
        with contextlib.suppress(Exception):
            _run(["git", "checkout", "-"])
        with contextlib.suppress(Exception):
            _run(["git", "stash", "pop"])

    return result
