"""Run the repository quality gate used before a release or migration cutover."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# The technical design fixes the branch-coverage floor at 85%.
COVERAGE_FLOOR = 85


def run(command: list[str]) -> int:
    print(f"\n> {' '.join(command)}")
    return subprocess.run(command, check=False).returncode


def main() -> int:
    checks = [
        [sys.executable, "-m", "compileall", "-q", "src", "migrations", "tests"],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--cov=src/app",
            "--cov-branch",
            "--cov-report=term-missing:skip-covered",
            f"--cov-fail-under={COVERAGE_FLOOR}",
        ],
    ]
    if os.environ.get("SKIP_DB_TESTS") == "1":
        print(
            "WARNING: SKIP_DB_TESTS=1 - database integration tests are skipped. "
            "This is not a full pass and must not be used to clear a release gate."
        )
    optional_tools = [
        ("ruff", ["ruff", "check", "src", "tests", "migrations", "scripts"]),
        ("mypy", ["mypy", "src"]),
        ("bandit", ["bandit", "-r", "src"]),
        ("pip-audit", ["pip-audit"]),
    ]
    for tool, command in optional_tools:
        if shutil.which(tool):
            checks.append(command)
        else:
            print(f"SKIP: {tool} is not installed; CI must install the dev/security toolchain.")
    for command in checks:
        if run(command) != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
