"""DepsManager agent — dependency health checker."""

import json
import logging
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from agents.shared.config import PROJECT_ROOT, SKIP_DIRS
from agents.shared.report import Finding, AgentReport
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "deps_manager"

# Known package name -> import name mappings
_IMPORT_MAP: dict[str, str] = {
    "python-jose": "jose",
    "python-jose[cryptography]": "jose",
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
    "pydantic-settings": "pydantic_settings",
    "psycopg2-binary": "psycopg2",
    "email-validator": "email_validator",
    "uvicorn[standard]": "uvicorn",
    "passlib[bcrypt]": "passlib",
}

# Packages that are runtime drivers, CLI tools, or framework deps not directly imported
# in application code. These are expected to be in requirements.txt but not in imports.
_RUNTIME_DEPS: set[str] = {
    "asyncpg",  # SQLAlchemy async driver (loaded by connection string)
    "psycopg2-binary",  # SQLAlchemy sync driver (loaded by connection string)
    "bcrypt",  # passlib backend (loaded by passlib[bcrypt])
    "alembic",  # CLI migration tool (not imported in app/)
    "uvicorn",  # ASGI server (CLI entrypoint, not imported in app/)
    "redis",  # Celery broker backend (loaded by connection string)
    "email-validator",  # Pydantic EmailStr validator (loaded by pydantic at runtime)
    "python-multipart",  # FastAPI form/file upload support (loaded by fastapi at runtime)
    "python-dotenv",  # Loaded by pydantic-settings for .env files
}

# Import names that are provided by another declared dependency (transitive)
_TRANSITIVE_IMPORTS: set[str] = {
    "starlette",  # provided by fastapi
    "jose",  # provided by python-jose
    "multipart",  # provided by python-multipart
    "dotenv",  # provided by python-dotenv
}

# Standard-library modules that should never be flagged as missing deps
_STDLIB_MODULES: set[str] = {
    "abc",
    "asyncio",
    "base64",
    "binascii",
    "builtins",
    "calendar",
    "collections",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "csv",
    "ctypes",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "email",
    "enum",
    "errno",
    "fnmatch",
    "functools",
    "gc",
    "getpass",
    "glob",
    "gzip",
    "hashlib",
    "hmac",
    "html",
    "http",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "logging",
    "math",
    "mimetypes",
    "multiprocessing",
    "operator",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "pprint",
    "queue",
    "random",
    "re",
    "secrets",
    "shutil",
    "signal",
    "socket",
    "sqlite3",
    "ssl",
    "string",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "traceback",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uuid",
    "warnings",
    "weakref",
    "xml",
    "zipfile",
    "zlib",
    # typing extensions
    "typing_extensions",
    # __future__ is special
    "__future__",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_requirements(path: Path) -> list[dict]:
    """Parse requirements.txt into list of {name, raw, specifier, version_op}."""
    deps: list[dict] = []
    if not path.exists():
        return deps

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Match: package[extras]>=version, package==version, bare package
        m = re.match(
            r"^([A-Za-z0-9_\-]+(?:\[[^\]]+\])?)\s*(==|>=|<=|~=|!=|>|<)?\s*(.*)$", line
        )
        if m:
            name = m.group(1)
            op = m.group(2) or ""
            version = m.group(3).strip() if m.group(3) else ""
            deps.append(
                {
                    "name": name,
                    "raw": line,
                    "version_op": op,
                    "version": version,
                    "base_name": re.sub(r"\[.*\]", "", name),  # strip extras
                }
            )
    return deps


def _run_cmd(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a subprocess with timeout, capturing output."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _get_import_name(pkg_name: str) -> str:
    """Map a pip package name to its Python import name."""
    # Check explicit mappings first (including extras variants)
    if pkg_name in _IMPORT_MAP:
        return _IMPORT_MAP[pkg_name]
    # Strip extras for a second lookup
    base = re.sub(r"\[.*\]", "", pkg_name)
    if base in _IMPORT_MAP:
        return _IMPORT_MAP[base]
    # Default: replace hyphens with underscores
    return base.lower().replace("-", "_")


def _collect_imports(app_dir: Path) -> set[str]:
    """Scan all .py files under app_dir for top-level import names."""
    imports: set[str] = set()
    if not app_dir.is_dir():
        return imports

    for py_file in app_dir.rglob("*.py"):
        # Skip hidden / cache dirs
        parts = py_file.relative_to(app_dir).parts
        if any(p in SKIP_DIRS for p in parts):
            continue

        try:
            text = py_file.read_text(errors="replace")
        except OSError:
            continue

        for line in text.splitlines():
            stripped = line.strip()
            # import foo / import foo.bar
            m = re.match(r"^import\s+([\w]+)", stripped)
            if m:
                imports.add(m.group(1))
            # from foo import ... / from foo.bar import ...
            m = re.match(r"^from\s+([\w]+)", stripped)
            if m:
                imports.add(m.group(1))

    return imports


# ---------------------------------------------------------------------------
# Scan phases
# ---------------------------------------------------------------------------


def _check_pinning(deps: list[dict]) -> list[Finding]:
    """Flag unpinned and overly-strict-pinned dependencies."""
    findings: list[Finding] = []
    for dep in deps:
        if not dep["version_op"]:
            findings.append(
                Finding(
                    id=f"DEP-PIN-{dep['base_name'].upper()}",
                    severity="medium",
                    category="dependency-pinning",
                    title=f"Unpinned dependency: {dep['name']}",
                    detail=(
                        f"`{dep['raw']}` has no version specifier. "
                        "Builds are not reproducible — a new release could silently break things."
                    ),
                    file="requirements.txt",
                    recommendation=f"Pin to a minimum version: `{dep['name']}>=<current_version>`",
                    effort_hours=0.1,
                )
            )
        elif dep["version_op"] == "==" and dep["base_name"] != "bcrypt":
            # bcrypt is intentionally pinned due to passlib compat
            findings.append(
                Finding(
                    id=f"DEP-STRICT-{dep['base_name'].upper()}",
                    severity="low",
                    category="dependency-pinning",
                    title=f"Overly strict pin: {dep['name']}=={dep['version']}",
                    detail=(
                        f"`{dep['raw']}` uses exact pinning. This prevents automatic "
                        "patch/security updates unless manually bumped."
                    ),
                    file="requirements.txt",
                    recommendation=f"Consider `{dep['name']}>={dep['version']}` to allow patch updates.",
                    effort_hours=0.1,
                )
            )
    return findings


def _check_pip_audit(requirements_path: Path) -> list[Finding]:
    """Run pip-audit and return findings for each CVE."""
    findings: list[Finding] = []
    try:
        result = _run_cmd(
            ["pip-audit", "-r", str(requirements_path), "--format=json"],
            timeout=60,
        )
    except FileNotFoundError:
        findings.append(
            Finding(
                id="DEP-AUDIT-MISSING",
                severity="info",
                category="dependency-audit",
                title="pip-audit not installed",
                detail=(
                    "pip-audit is not available in this environment. "
                    "Cannot check for known vulnerabilities."
                ),
                recommendation="Install with: pip install pip-audit",
                effort_hours=0.1,
            )
        )
        return findings
    except subprocess.TimeoutExpired:
        findings.append(
            Finding(
                id="DEP-AUDIT-TIMEOUT",
                severity="info",
                category="dependency-audit",
                title="pip-audit timed out",
                detail="pip-audit did not complete within 60 seconds.",
                recommendation="Run pip-audit manually to investigate.",
                effort_hours=0.2,
            )
        )
        return findings
    except Exception as exc:
        logger.warning("pip-audit failed: %s", exc)
        findings.append(
            Finding(
                id="DEP-AUDIT-ERROR",
                severity="info",
                category="dependency-audit",
                title="pip-audit encountered an error",
                detail=str(exc),
                recommendation="Check pip-audit installation and try running manually.",
                effort_hours=0.2,
            )
        )
        return findings

    # Parse JSON output
    try:
        data = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError:
        # pip-audit may output non-JSON on some failures
        if result.returncode != 0 and result.stderr:
            findings.append(
                Finding(
                    id="DEP-AUDIT-PARSE",
                    severity="info",
                    category="dependency-audit",
                    title="pip-audit output could not be parsed",
                    detail=result.stderr[:500],
                    recommendation="Run pip-audit manually.",
                    effort_hours=0.2,
                )
            )
        return findings

    # pip-audit JSON has a "dependencies" key with vulnerability info
    vulnerabilities = data.get("dependencies", [])
    for dep_entry in vulnerabilities:
        pkg = dep_entry.get("name", "unknown")
        version = dep_entry.get("version", "?")
        vulns = dep_entry.get("vulns", [])
        for vuln in vulns:
            vuln_id = vuln.get("id", "UNKNOWN")
            fix_versions = vuln.get("fix_versions", [])
            fix_str = ", ".join(fix_versions) if fix_versions else "no fix available"
            description = vuln.get("description", "No description provided.")

            findings.append(
                Finding(
                    id=f"DEP-CVE-{vuln_id}",
                    severity="high",
                    category="dependency-vulnerability",
                    title=f"{vuln_id} in {pkg}=={version}",
                    detail=description[:500],
                    file="requirements.txt",
                    recommendation=f"Upgrade {pkg} to {fix_str}.",
                    effort_hours=0.5,
                )
            )

    return findings


def _check_stale_packages(deps: list[dict]) -> list[Finding]:
    """Check installed package metadata for staleness indicators."""
    findings: list[Finding] = []
    for dep in deps:
        pkg = dep["base_name"]
        try:
            result = _run_cmd(["pip", "show", pkg], timeout=30)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

        if result.returncode != 0:
            # Package not installed locally — skip
            continue

        # pip show doesn't give "last release date" directly, but we can
        # check the version for staleness indicators. For now, log that
        # we checked it. A more advanced version would query PyPI JSON API.
        # We parse what we can from pip show output.
        info: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ": " in line:
                key, _, value = line.partition(": ")
                info[key.strip()] = value.strip()

        installed_version = info.get("Version", "unknown")
        # Store for metrics
        dep["installed_version"] = installed_version

    return findings


def _check_imports(deps: list[dict], app_dir: Path) -> tuple[list[Finding], int, int]:
    """Cross-check requirements.txt against actual imports in app/."""
    findings: list[Finding] = []
    actual_imports = _collect_imports(app_dir)

    # Build set of import names from requirements.txt
    req_import_names: dict[str, str] = {}  # import_name -> pkg_name
    req_base_names: set[str] = set()
    for dep in deps:
        import_name = _get_import_name(dep["name"])
        req_import_names[import_name] = dep["name"]
        req_base_names.add(dep["base_name"])

    # Filter out stdlib and local app imports
    external_imports = {
        imp
        for imp in actual_imports
        if imp not in _STDLIB_MODULES and imp != "app" and imp != "agents"
    }

    # Missing from requirements (imported but not declared)
    missing_count = 0
    for imp in sorted(external_imports):
        if imp in _TRANSITIVE_IMPORTS:
            continue
        if imp not in req_import_names and imp not in req_base_names:
            # Double-check: maybe it's a sub-import of something declared
            # e.g. "celery" covers "celery.app", "celery.result" etc.
            if any(imp.startswith(name) for name in req_import_names):
                continue
            missing_count += 1
            findings.append(
                Finding(
                    id=f"DEP-MISSING-{imp.upper()}",
                    severity="medium",
                    category="dependency-missing",
                    title=f"Imported but not in requirements.txt: {imp}",
                    detail=(
                        f"`{imp}` is imported in app/ but not declared in requirements.txt. "
                        "This could break deployment if the package isn't transitively installed."
                    ),
                    file="requirements.txt",
                    recommendation=f"Add `{imp}` to requirements.txt if it's a direct dependency.",
                    effort_hours=0.1,
                )
            )

    # Dead deps (in requirements but never imported)
    dead_count = 0
    for import_name, pkg_name in sorted(req_import_names.items()):
        base = re.sub(r"\[.*\]", "", pkg_name)
        if base in _RUNTIME_DEPS:
            continue
        if import_name not in external_imports:
            dead_count += 1
            findings.append(
                Finding(
                    id=f"DEP-DEAD-{base.upper()}",
                    severity="low",
                    category="dependency-dead",
                    title=f"In requirements.txt but never imported: {pkg_name}",
                    detail=(
                        f"`{pkg_name}` is declared in requirements.txt but `{import_name}` "
                        "is not imported anywhere in app/. It may be a dead dependency."
                    ),
                    file="requirements.txt",
                    recommendation=(
                        f"Verify `{pkg_name}` is actually needed. "
                        "Remove if unused to shrink the dependency surface."
                    ),
                    effort_hours=0.1,
                )
            )

    return findings, missing_count, dead_count


def _check_dockerfile(dockerfile_path: Path) -> list[Finding]:
    """Check the Dockerfile for outdated base images."""
    findings: list[Finding] = []
    if not dockerfile_path.exists():
        findings.append(
            Finding(
                id="DEP-NO-DOCKERFILE",
                severity="info",
                category="environment",
                title="No Dockerfile found",
                detail="No Dockerfile at project root. Skipping base image check.",
            )
        )
        return findings

    try:
        content = dockerfile_path.read_text()
    except OSError as exc:
        logger.warning("Could not read Dockerfile: %s", exc)
        return findings

    # Find all FROM lines with python images
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("FROM"):
            continue

        # Match python version in FROM line
        m = re.search(r"python:(\d+)\.(\d+)", stripped, re.IGNORECASE)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2))
            if major < 3 or (major == 3 and minor < 11):
                findings.append(
                    Finding(
                        id="DEP-DOCKER-PYTHON",
                        severity="medium",
                        category="environment",
                        title=f"Dockerfile uses Python {major}.{minor} (< 3.11)",
                        detail=(
                            f"`{stripped}` uses Python {major}.{minor}. "
                            "The project targets Python 3.11+. "
                            "Older versions miss performance improvements and security patches."
                        ),
                        file="Dockerfile",
                        recommendation="Update the FROM line to use python:3.11-slim or newer.",
                        effort_hours=0.5,
                    )
                )

    return findings


def _check_licenses(deps: list[dict]) -> list[Finding]:
    """Check dependency licenses for GPL-incompatible packages."""
    findings: list[Finding] = []
    for dep in deps:
        pkg = dep["base_name"]
        try:
            result = _run_cmd(["pip", "show", pkg], timeout=30)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

        if result.returncode != 0:
            continue

        license_str = ""
        for line in result.stdout.splitlines():
            if line.startswith("License:"):
                license_str = line.partition(":")[2].strip()
                break

        if not license_str or license_str == "UNKNOWN":
            continue

        # Flag GPL (but not LGPL, which is permissive enough for SaaS)
        # Use word boundary to avoid matching LGPL
        if re.search(r"(?<![L])GPL", license_str, re.IGNORECASE):
            findings.append(
                Finding(
                    id=f"DEP-LICENSE-{pkg.upper()}",
                    severity="high",
                    category="license-compliance",
                    title=f"GPL-licensed dependency: {pkg}",
                    detail=(
                        f"`{pkg}` is licensed under '{license_str}'. "
                        "GPL is incompatible with proprietary SaaS distribution. "
                        "This could create legal obligations to open-source WarmPath."
                    ),
                    file="requirements.txt",
                    recommendation=f"Find a permissively-licensed alternative to `{pkg}`, or get legal review.",
                    effort_hours=2.0,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------


def scan() -> AgentReport:
    """Run all dependency health checks and return a unified report."""
    start = time.time()
    findings: list[Finding] = []

    requirements_path = PROJECT_ROOT / "requirements.txt"
    app_dir = PROJECT_ROOT / "app"
    dockerfile_path = PROJECT_ROOT / "Dockerfile"

    # -- Phase 1: Parse requirements ------------------------------------------
    deps = _parse_requirements(requirements_path)
    if not deps:
        findings.append(
            Finding(
                id="DEP-NO-REQS",
                severity="high",
                category="environment",
                title="No dependencies found in requirements.txt",
                detail="requirements.txt is empty or missing. Cannot perform dependency analysis.",
                file="requirements.txt",
                recommendation="Ensure requirements.txt exists and lists all project dependencies.",
                effort_hours=1.0,
            )
        )
        elapsed = time.time() - start
        return AgentReport(
            agent=AGENT_NAME,
            scan_duration_seconds=round(elapsed, 2),
            findings=findings,
            metrics={"total_deps": 0},
        )

    total_deps = len(deps)

    # -- Phase 2: Pinning analysis --------------------------------------------
    pinning_findings = _check_pinning(deps)
    findings.extend(pinning_findings)

    pinned_count = sum(
        1 for d in deps if d["version_op"] in ("==", ">=", "<=", "~=", ">", "<")
    )
    unpinned_count = sum(1 for d in deps if not d["version_op"])

    # -- Phase 3: pip-audit (CVE scan) ----------------------------------------
    audit_findings = _check_pip_audit(requirements_path)
    findings.extend(audit_findings)

    cve_count = sum(
        1 for f in audit_findings if f.category == "dependency-vulnerability"
    )

    # -- Phase 4: Stale package check -----------------------------------------
    stale_findings = _check_stale_packages(deps)
    findings.extend(stale_findings)

    # -- Phase 5: Import cross-check ------------------------------------------
    import_findings, missing_deps, dead_deps = _check_imports(deps, app_dir)
    findings.extend(import_findings)

    # -- Phase 6: Dockerfile check --------------------------------------------
    docker_findings = _check_dockerfile(dockerfile_path)
    findings.extend(docker_findings)

    # -- Phase 7: License compliance ------------------------------------------
    license_findings = _check_licenses(deps)
    findings.extend(license_findings)

    # -- Metrics --------------------------------------------------------------
    elapsed = time.time() - start
    metrics = {
        "total_deps": total_deps,
        "pinned_count": pinned_count,
        "unpinned_count": unpinned_count,
        "cve_count": cve_count,
        "missing_deps": missing_deps,
        "dead_deps": dead_deps,
        "license_issues": len(license_findings),
        "total_findings": len(findings),
    }

    # -- Self-learning --------------------------------------------------------
    try:
        for f in findings:
            f.recurrence_count = learning.get_recurrence_count(
                AGENT_NAME, f.category, f.file
            )
            learning.record_finding(AGENT_NAME, asdict(f))

        # Track which files generate findings (attention weights)
        file_counts: dict[str, int] = {}
        for f in findings:
            if f.file:
                file_counts[f.file] = file_counts.get(f.file, 0) + 1
        if file_counts:
            learning.update_attention_weights(AGENT_NAME, file_counts)

        learning.record_scan(AGENT_NAME, metrics)
    except Exception as exc:
        logger.warning("Learning update failed: %s", exc)

    return AgentReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(elapsed, 2),
        findings=findings,
        metrics=metrics,
        learning_updates=[
            f"Recorded {len(findings)} findings to history",
            f"Updated attention weights for {len(set(f.file for f in findings if f.file))} files",
        ],
    )
