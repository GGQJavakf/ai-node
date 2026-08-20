"""Run the scoped AgentRetro McCabe regression gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "agentretro_complexity_targets.txt"
SOURCE_ROOT = (ROOT / "src" / "agent_retro").resolve()


def load_targets() -> tuple[Path, ...]:
    targets: list[Path] = []
    seen: set[Path] = set()
    for raw_line in MANIFEST.read_text(encoding="utf-8").splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        target = (ROOT / value).resolve()
        if target.suffix != ".py" or SOURCE_ROOT not in target.parents:
            raise ValueError(f"complexity target is outside AgentRetro: {value}")
        if target in seen:
            raise ValueError(f"duplicate complexity target: {value}")
        if not target.is_file():
            raise FileNotFoundError(f"complexity target is missing: {value}")
        seen.add(target)
        targets.append(target)
    if not targets:
        raise ValueError("AgentRetro complexity manifest is empty")
    return tuple(targets)


def main() -> int:
    targets = load_targets()
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        *(str(target.relative_to(ROOT)) for target in targets),
        "--select",
        "C901",
        "--config",
        "lint.mccabe.max-complexity=15",
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
