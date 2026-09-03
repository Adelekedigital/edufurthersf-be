"""Run the repository quality gate used before a release or migration cutover."""

from __future__ import annotations

import shutil
import subprocess
import sys


def run(command: list[str]) -> int:
    print(f"\n> {' '.join(command)}")
    return subprocess.run(command, check=False).returncode


def main() -> int:
    checks = [
        [sys.executable, "-m", "compileall", "-q", "src", "migrations", "tests"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
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
