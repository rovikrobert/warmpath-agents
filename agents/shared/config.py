"""Agent system configuration — paths, thresholds, severity weights."""

from pathlib import Path

# Auto-detect project root (git root)
_this = Path(__file__).resolve()
PROJECT_ROOT = _this.parent.parent.parent  # agents/shared/config.py → project root
AGENTS_DIR = PROJECT_ROOT / "agents"
REPORTS_DIR = AGENTS_DIR / "reports"
INTEL_CACHE = AGENTS_DIR / "shared" / "intel_cache.json"

# Scan targets by category
SCAN_TARGETS = {
    "backend": PROJECT_ROOT / "app",
    "tests": PROJECT_ROOT / "tests",
    "frontend": PROJECT_ROOT / "frontend" / "src",
    "migrations": PROJECT_ROOT / "alembic",
    "config": [
        PROJECT_ROOT / "CLAUDE.md",
        PROJECT_ROOT / "ARCHITECTURE.md",
        PROJECT_ROOT / "warmpath_privacy_policy.docx",
    ],
}

# Severity weights for prioritisation scoring
SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 5,
    "medium": 2,
    "low": 1,
    "info": 0,
}

# Lead agent caps the daily brief to the top N findings
MAX_FINDINGS_PER_BRIEF = 10

# Thresholds
COVERAGE_WARN_THRESHOLD = 80        # % line coverage below which we warn
COVERAGE_CRITICAL_MODULES = 90      # % for high-risk modules
FILE_SIZE_WARN_LINES = 300          # flag files larger than this
FUNCTION_SIZE_WARN_LINES = 30       # flag functions longer than this
TEST_SLOW_THRESHOLD_SECONDS = 2.0   # flag slow tests
QUERIES_PER_REQUEST_WARN = 5        # potential N+1
DEP_STALE_DAYS = 365                # flag deps not released in this many days

# Skip directories during scanning
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".mypy_cache", ".pytest_cache"}

# Intelligence cache TTL
INTEL_CACHE_TTL_HOURS = 24

# Agent names (canonical)
AGENT_NAMES = [
    "architect",
    "test_engineer",
    "perf_monitor",
    "deps_manager",
    "doc_keeper",
    "security",
    "privy",
]
