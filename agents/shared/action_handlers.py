"""Action handlers for Telegram-approved execution.

Each handler creates a branch + PR (never pushes to master).
AUTO_DO tier gets auto-merge label for zero-friction.
All handlers: record HEAD -> act -> test -> revert on failure.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.execution_engine import ExecutionTier
from agents.shared.report import Finding
from agents.shared.risk_classifier import PROTECTED_PATHS

logger = logging.getLogger(__name__)

HANDLER_TIMEOUT = 120  # seconds


@dataclass
class ActionResult:
    success: bool
    summary: str
    pr_url: str | None = None
    branch: str | None = None
    reverted: bool = False


def _run_subprocess(
    cmd: list[str], timeout: int = HANDLER_TIMEOUT, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with timeout and capture output."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, **kwargs
    )


def _touches_protected_path(finding: Finding) -> bool:
    """Check if finding targets a protected file."""
    if not finding.file:
        return False
    return any(finding.file.startswith(p) or finding.file == p for p in PROTECTED_PATHS)


def _get_head_sha() -> str:
    return _run_subprocess(["git", "rev-parse", "HEAD"]).stdout.strip()


def _get_current_branch() -> str:
    return _run_subprocess(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def _make_branch_name(finding: Finding) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", finding.id)[:40]
    return f"tg-approve/{safe_id}-{today}"


def _revert(head_sha: str, original_branch: str, new_branch: str | None) -> None:
    """Hard reset to recorded HEAD, return to original branch, clean up."""
    _run_subprocess(["git", "reset", "--hard", head_sha])
    if new_branch:
        _run_subprocess(["git", "checkout", original_branch])
        _run_subprocess(["git", "branch", "-D", new_branch])


def _create_pr(branch: str, title: str, body: str, tier: ExecutionTier) -> str | None:
    """Push branch and create PR. Returns PR URL or None."""
    push = _run_subprocess(["git", "push", "-u", "origin", branch])
    if push.returncode != 0:
        logger.error("git push failed: %s", push.stderr)
        return None

    pr = _run_subprocess(
        [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--base",
            "master",
        ]
    )
    pr_url = pr.stdout.strip() if pr.returncode == 0 else None

    if pr_url and tier == ExecutionTier.AUTO_DO:
        _run_subprocess(["gh", "pr", "edit", pr_url, "--add-label", "auto-merge"])

    return pr_url


def _run_tests() -> bool:
    """Run pytest fail-fast. Returns True if tests pass."""
    try:
        result = _run_subprocess(
            ["pytest", "-x", "-q", "--timeout=60"],
            timeout=HANDLER_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("pytest timed out during approval execution")
        return False


def _resolve_in_registry(finding: Finding) -> None:
    """Mark finding as resolved using existing learning.py function."""
    from agents.shared.learning import resolve_issue

    resolve_issue(
        finding.id,
        resolution_type="false_positive",
        reason=f"Approved via Telegram: {finding.title}",
        skip_days=None,  # permanent
    )


def _base_handler(
    finding: Finding,
    tier: ExecutionTier,
    action_fn,
    commit_msg: str,
) -> ActionResult:
    """Shared handler skeleton: branch -> act -> test -> PR or revert."""
    head_sha = _get_head_sha()
    original_branch = _get_current_branch()
    branch = _make_branch_name(finding)

    checkout = _run_subprocess(["git", "checkout", "-b", branch])
    if checkout.returncode != 0:
        return ActionResult(
            success=False,
            summary=f"Failed to create branch: {checkout.stderr[:200]}",
        )

    try:
        action_fn()

        # Check if anything changed
        diff = _run_subprocess(["git", "diff", "--stat"])
        if not diff.stdout.strip():
            _revert(head_sha, original_branch, branch)
            return ActionResult(success=False, summary="No changes produced")

        if not _run_tests():
            _revert(head_sha, original_branch, branch)
            return ActionResult(
                success=False,
                summary="Tests failed after changes — reverted",
                reverted=True,
            )

        _run_subprocess(["git", "add", "-u"])
        _run_subprocess(["git", "commit", "-m", commit_msg])

        pr_url = _create_pr(
            branch,
            commit_msg,
            f"Telegram-approved execution for finding `{finding.id}`.\n\n"
            f"**Category:** {finding.category}\n"
            f"**Detail:** {finding.detail}\n"
            f"**Recommendation:** {finding.recommendation}",
            tier,
        )

        _run_subprocess(["git", "checkout", original_branch])

        auto_note = " (auto-merge enabled)" if tier == ExecutionTier.AUTO_DO else ""
        return ActionResult(
            success=True,
            summary=f"PR opened{auto_note}: {commit_msg}",
            pr_url=pr_url,
            branch=branch,
        )

    except subprocess.TimeoutExpired:
        _revert(head_sha, original_branch, branch)
        return ActionResult(
            success=False, summary="Timed out — reverted", reverted=True
        )
    except Exception as exc:
        logger.exception("Action handler error: %s", exc)
        _revert(head_sha, original_branch, branch)
        return ActionResult(
            success=False,
            summary=f"Error: {str(exc)[:200]} — reverted",
            reverted=True,
        )


def handle_dependency_bump(finding: Finding, tier: ExecutionTier) -> ActionResult:
    """Bump a dependency version in requirements.txt."""
    req_path = Path("requirements.txt")

    def action():
        if not req_path.exists():
            raise FileNotFoundError("requirements.txt not found")
        content = req_path.read_text(encoding="utf-8")
        rec = finding.recommendation or finding.title
        match = re.search(r"(\w[\w-]*(?:>=|<=|==|~=|>|<)\S+)", rec)
        if match:
            spec = match.group(1)
            pkg = re.split(r"[><=~!]", spec)[0]
            pattern = re.compile(rf"^{re.escape(pkg)}[><=~!].*$", re.MULTILINE)
            if pattern.search(content):
                content = pattern.sub(spec, content)
            else:
                content += f"\n{spec}\n"
            req_path.write_text(content, encoding="utf-8")
        else:
            raise ValueError(f"Could not parse package spec from: {rec}")

    return _base_handler(
        finding, tier, action, f"fix(deps): {finding.title} [tg-approved]"
    )


def handle_lint_fix(finding: Finding, tier: ExecutionTier) -> ActionResult:
    """Run ruff check --fix and ruff format."""

    def action():
        _run_subprocess(["ruff", "check", "--fix", "."])
        _run_subprocess(["ruff", "format", "."])

    return _base_handler(
        finding, tier, action, f"fix(lint): {finding.title} [tg-approved]"
    )


def handle_resolve_false_positive(
    finding: Finding, tier: ExecutionTier
) -> ActionResult:
    """Add finding to resolved_registry.json via learning.resolve_issue."""

    def action():
        _resolve_in_registry(finding)

    return _base_handler(
        finding, tier, action, f"chore(registry): resolve {finding.id} [tg-approved]"
    )


def handle_generic_pr(finding: Finding, tier: ExecutionTier) -> ActionResult:
    """Create a context-only PR for manual investigation."""
    original_branch = _get_current_branch()
    branch = _make_branch_name(finding)

    checkout = _run_subprocess(["git", "checkout", "-b", branch])
    if checkout.returncode != 0:
        return ActionResult(
            success=False,
            summary=f"Failed to create branch: {checkout.stderr[:200]}",
        )

    _run_subprocess(
        [
            "git",
            "commit",
            "--allow-empty",
            "-m",
            f"chore: investigate {finding.id} [tg-approved]",
        ]
    )

    pr_url = _create_pr(
        branch,
        f"investigate: {finding.title} [tg-approved]",
        f"Telegram-approved investigation for `{finding.id}`.\n\n"
        f"**Severity:** {finding.severity}\n"
        f"**Category:** {finding.category}\n"
        f"**File:** {finding.file or 'N/A'}\n"
        f"**Detail:** {finding.detail}\n"
        f"**Recommendation:** {finding.recommendation}\n\n"
        f"Manual investigation needed.",
        tier,
    )

    _run_subprocess(["git", "checkout", original_branch])

    return ActionResult(
        success=True,
        summary=f"Investigation PR opened: {finding.title}",
        pr_url=pr_url,
        branch=branch,
    )


def dispatch_action(finding: Finding, tier: ExecutionTier) -> ActionResult:
    """Route a finding to the appropriate handler based on tier and category."""
    if _touches_protected_path(finding):
        return ActionResult(
            success=False,
            summary=f"Protected path ({finding.file}) — cannot auto-execute",
        )

    if tier == ExecutionTier.ESCALATE:
        return ActionResult(
            success=False,
            summary=f"Escalated: {finding.severity} finding on "
            f"{finding.file or 'unknown'}. Too risky for auto-execution.",
        )

    category = finding.category.lower()
    if category in ("dependency-update", "dependency-vulnerability"):
        return handle_dependency_bump(finding, tier)
    if category == "dependency-dead":
        return handle_generic_pr(finding, tier)
    if category in ("lint", "format"):
        return handle_lint_fix(finding, tier)
    if finding.auto_fixable:
        return handle_lint_fix(finding, tier)

    return handle_generic_pr(finding, tier)
