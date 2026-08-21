"""Run the declared and full-source ai-todo McCabe regression gates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "ai_todo_complexity_targets.txt"
SOURCE_ROOT = (ROOT / "src" / "ai_todo_assistant").resolve()
TARGET_MAX_COMPLEXITY = 10
PACKAGE_MAX_COMPLEXITY = 15


def load_targets() -> tuple[Path, ...]:
    targets: list[Path] = []
    seen: set[Path] = set()
    for raw_line in MANIFEST.read_text(encoding="utf-8").splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        target = (ROOT / value).resolve()
        if target.suffix != ".py" or SOURCE_ROOT not in target.parents:
            raise ValueError(f"complexity target is outside ai-todo: {value}")
        if target in seen:
            raise ValueError(f"duplicate complexity target: {value}")
        if not target.is_file():
            raise FileNotFoundError(f"complexity target is missing: {value}")
        seen.add(target)
        targets.append(target)
    if not targets:
        raise ValueError("ai-todo complexity manifest is empty")
    return tuple(targets)


def main() -> int:
    targets = load_targets()
    command_prefix = [sys.executable, "-m", "ruff", "check"]
    command_suffix = [
        "--select",
        "C901",
        "--ignore-noqa",
    ]
    manifest_result = subprocess.run(
        [
            *command_prefix,
            *(str(target.relative_to(ROOT)) for target in targets),
            *command_suffix,
            "--config",
            f"lint.mccabe.max-complexity={TARGET_MAX_COMPLEXITY}",
        ],
        cwd=ROOT,
        check=False,
    )
    if manifest_result.returncode:
        return manifest_result.returncode
    return subprocess.run(
        [
            *command_prefix,
            str(SOURCE_ROOT.relative_to(ROOT)),
            *command_suffix,
            "--config",
            f"lint.mccabe.max-complexity={PACKAGE_MAX_COMPLEXITY}",
        ],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
