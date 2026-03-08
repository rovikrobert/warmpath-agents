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
COVERAGE_WARN_THRESHOLD = 80  # % line coverage below which we warn
COVERAGE_CRITICAL_MODULES = 90  # % for high-risk modules
FILE_SIZE_WARN_LINES = 300  # flag files larger than this
FUNCTION_SIZE_WARN_LINES = 30  # flag functions longer than this
TEST_SLOW_THRESHOLD_SECONDS = 2.0  # flag slow tests
QUERIES_PER_REQUEST_WARN = 5  # potential N+1
DEP_STALE_DAYS = 365  # flag deps not released in this many days

# Skip directories during scanning
SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
}

# Intelligence cache TTL
INTEL_CACHE_TTL_HOURS = 24

# Self-learning thresholds
RECURRING_PATTERN_THRESHOLD = 5  # auto-escalate at 5+ occurrences
SYSTEMIC_PATTERN_THRESHOLD = 10  # flag as systemic at 10+
ATTENTION_WEIGHT_DECAY = 0.05  # per-day decay for quiet files
FIX_EFFECTIVENESS_WINDOW_DAYS = 30  # look-back for fix effectiveness
INTEL_REFRESH_ON_SCAN = True  # check intel freshness during --all

# Agent names (canonical)
AGENT_NAMES = [
    "architect",
    "test_engineer",
    "perf_monitor",
    "deps_manager",
    "doc_keeper",
    "security",
    "privy",
    "ux_lead",
    "design_lead",
]

# KPI targets — (agent, kpi_name) → {target, yellow (optional)}
KPI_TARGETS: dict[tuple[str, str], dict] = {
    ("architect", "lint_density"): {"target": 0.10, "yellow": 0.15},
    ("architect", "large_file_ratio"): {"target": 0.10, "yellow": 0.15},
    ("architect", "type_coverage"): {"target": 0.95, "yellow": 0.90},
    ("test_engineer", "test_count"): {"target": 750, "yellow": 700},
    ("test_engineer", "weak_test_ratio"): {"target": 0.30, "yellow": 0.40},
    ("test_engineer", "tests_per_file"): {"target": 25, "yellow": 20},
    ("perf_monitor", "n_plus_1_count"): {"target": 0},
    ("perf_monitor", "index_coverage"): {"target": 0.80, "yellow": 0.70},
    ("perf_monitor", "ai_cost_per_user"): {"target": 0.50, "yellow": 0.75},
    ("deps_manager", "cve_count"): {"target": 0},
    ("deps_manager", "pin_ratio"): {"target": 1.0, "yellow": 0.95},
    ("deps_manager", "dead_dep_count"): {"target": 0},
    ("doc_keeper", "doc_coverage"): {"target": 0.90, "yellow": 0.80},
    ("doc_keeper", "claims_accuracy"): {"target": 1.0, "yellow": 0.95},
    ("doc_keeper", "convention_violations"): {"target": 0},
    ("security", "critical_high"): {"target": 0},
    ("security", "medium_findings"): {"target": 5, "yellow": 10},
    ("privy", "critical_high"): {"target": 0},
    ("privy", "check_pass_rate"): {"target": 0.90, "yellow": 0.80},
    ("ux_lead", "a11y_violations"): {"target": 0},
    ("ux_lead", "lighthouse_score"): {"target": 90, "yellow": 80},
    ("design_lead", "token_violations"): {"target": 0},
    ("design_lead", "consistency_score"): {"target": 0.95, "yellow": 0.90},
}

# Health score weights per agent (total = 100)
HEALTH_WEIGHTS: dict[str, int] = {
    "security": 20,
    "privy": 15,
    "deps_manager": 15,
    "test_engineer": 15,
    "architect": 10,
    "perf_monitor": 10,
    "ux_lead": 5,
    "design_lead": 5,
    "doc_keeper": 5,
}
