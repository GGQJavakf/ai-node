from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401
from agentretro_scenarios import (
    HARDENING_SCENARIO_TESTS,
    SCENARIO_TESTS,
    scenario_verification_rows,
)


REPO_ROOT = Path(__file__).parents[1]


def _change_root(name: str) -> Path:
    active = REPO_ROOT / "openspec" / "changes" / name
    if active.is_dir():
        return active
    archived = sorted(
        (REPO_ROOT / "openspec" / "changes" / "archive").glob(f"*-{name}")
    )
    assert len(archived) == 1, f"expected one active or archived change for {name}"
    return archived[0]


CHANGE_ROOT = _change_root("add-agentretro-mvp")
HARDENING_CHANGE_ROOT = _change_root("harden-recent-session-capture")
VALUE_LOOP_CHANGE_ROOT = _change_root("improve-agentretro-value-loop")
SCENARIO_PATTERN = re.compile(
    r"^#### Scenario: \[(CR|KR|OS|BR)-(\d{2})\]", re.MULTILINE
)
EXPECTED_IDS = {
    *(f"CR-{number:02d}" for number in range(1, 29)),
    *(f"KR-{number:02d}" for number in range(1, 31)),
    *(f"OS-{number:02d}" for number in range(1, 30)),
    *(f"BR-{number:02d}" for number in range(1, 37)),
}


def _discovered_scenario_ids(change_root: Path) -> list[str]:
    found: list[str] = []
    for spec in sorted((change_root / "specs").glob("**/spec.md")):
        text = spec.read_text(encoding="utf-8")
        found.extend(
            f"{prefix}-{number}" for prefix, number in SCENARIO_PATTERN.findall(text)
        )
    return found


def _collected_node_ids() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=REPO_ROOT,
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
    base_discovered = _discovered_scenario_ids(CHANGE_ROOT)
    value_loop_discovered = _discovered_scenario_ids(VALUE_LOOP_CHANGE_ROOT)
    discovered = {*base_discovered, *value_loop_discovered}
    verification_rows = scenario_verification_rows()
    verification_report = "\n".join(verification_rows)
    assert len(base_discovered) == len(set(base_discovered)) == 103
    assert len(value_loop_discovered) == len(set(value_loop_discovered)) == 27
    assert discovered == EXPECTED_IDS
    assert set(SCENARIO_TESTS) == discovered, verification_report
    assert all(SCENARIO_TESTS.values())

    mapped_nodes = {node for nodes in SCENARIO_TESTS.values() for node in nodes}
    assert all("::" in node for node in mapped_nodes), (
        "module-only mappings are forbidden"
    )
    collected = _collected_node_ids()
    assert mapped_nodes <= collected, (
        f"stale node IDs: {sorted(mapped_nodes - collected)}\n{verification_report}"
    )
    assert len(verification_rows) == 123


def test_hardening_openspec_scenarios_have_exact_collected_pytest_evidence():
    pattern = re.compile(
        r"^#### Scenario: \[(WR|SF|IQ|RR)-(\d{2})\]", re.MULTILINE
    )
    discovered: list[str] = []
    for spec in sorted((HARDENING_CHANGE_ROOT / "specs").glob("**/spec.md")):
        discovered.extend(
            f"{prefix}-{number}"
            for prefix, number in pattern.findall(spec.read_text(encoding="utf-8"))
        )
    expected = {
        *(f"WR-{number:02d}" for number in range(1, 7)),
        *(f"SF-{number:02d}" for number in range(1, 7)),
        *(f"IQ-{number:02d}" for number in range(1, 7)),
        *(f"RR-{number:02d}" for number in range(1, 7)),
    }
    assert len(discovered) == len(set(discovered)) == 24
    assert set(discovered) == expected == set(HARDENING_SCENARIO_TESTS)
    mapped_nodes = {
        node for nodes in HARDENING_SCENARIO_TESTS.values() for node in nodes
    }
    assert all("::" in node for node in mapped_nodes)
    collected = _collected_node_ids()
    assert mapped_nodes <= collected, f"stale node IDs: {sorted(mapped_nodes - collected)}"
