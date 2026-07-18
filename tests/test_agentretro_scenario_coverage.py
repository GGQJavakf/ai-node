from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401
from agentretro_scenarios import SCENARIO_TESTS, scenario_verification_rows


CHANGE_ROOT = Path(__file__).parents[1] / "openspec" / "changes" / "add-agentretro-mvp"
SCENARIO_PATTERN = re.compile(
    r"^#### Scenario: \[(CR|KR|OS|BR)-(\d{2})\]", re.MULTILINE
)
EXPECTED_IDS = {
    *(f"CR-{number:02d}" for number in range(1, 23)),
    *(f"KR-{number:02d}" for number in range(1, 25)),
    *(f"OS-{number:02d}" for number in range(1, 25)),
    *(f"BR-{number:02d}" for number in range(1, 29)),
}


def _discovered_scenario_ids() -> list[str]:
    found: list[str] = []
    for spec in sorted((CHANGE_ROOT / "specs").glob("**/spec.md")):
        text = spec.read_text(encoding="utf-8")
        found.extend(
            f"{prefix}-{number}" for prefix, number in SCENARIO_PATTERN.findall(text)
        )
    return found


def _collected_node_ids() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=CHANGE_ROOT.parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }


def test_all_openspec_scenarios_have_exact_collected_pytest_evidence():
    discovered = _discovered_scenario_ids()
    verification_rows = scenario_verification_rows()
    verification_report = "\n".join(verification_rows)
    assert len(discovered) == 98
    assert len(set(discovered)) == 98, "duplicate OpenSpec scenario IDs found"
    assert set(discovered) == EXPECTED_IDS
    assert set(SCENARIO_TESTS) == set(discovered), verification_report
    assert all(SCENARIO_TESTS.values())

    mapped_nodes = {node for nodes in SCENARIO_TESTS.values() for node in nodes}
    assert all("::" in node for node in mapped_nodes), (
        "module-only mappings are forbidden"
    )
    collected = _collected_node_ids()
    assert mapped_nodes <= collected, (
        f"stale node IDs: {sorted(mapped_nodes - collected)}\n{verification_report}"
    )
    assert len(verification_rows) == 98
