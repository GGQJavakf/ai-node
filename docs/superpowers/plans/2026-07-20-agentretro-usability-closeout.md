# AgentRetro Usability Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the verified Windows GBK regression in the preserved `ai-todo` entry point and make AgentRetro's first-use path executable from the README.

**Architecture:** Keep AgentRetro and `ai-todo` independent. Reuse the existing encoding-aware `_display_response()` path for the legacy farewell instead of changing process-wide encoding, dependencies, or Todo/WorkItem behavior. Treat `retro doctor` as the single-command readiness check and document the explicit, preview-first workflow without introducing a new initializer.

**Tech Stack:** Python 3.10+, pytest subprocess tests, Rich, PowerShell documentation, OpenSpec.

## Global Constraints

- Preserve all existing Todo, WorkItem, command, configuration, and database semantics.
- Support Windows GBK and UTF-8 consoles without forcing a process-wide encoding.
- Do not write real Codex sessions, Obsidian content, global `AGENTS.md`, Codex native memory, or external systems during verification.
- Keep the compatibility patch separate from AgentRetro business behavior.

---

### Task 1: Lock the legacy GBK exit regression

**Files:**
- Modify: `tests/test_agentretro_subprocess.py`
- Modify: `src/ai_todo_assistant/presentation/cli.py`

**Interfaces:**
- Consumes: `TodoCLI.run()` and its existing `_display_response(response)` encoding fallback.
- Produces: A full-process GBK `/exit` regression test and an encoding-safe farewell path.

- [x] **Step 1: Write the failing subprocess test**

```python
def test_existing_ai_todo_noninteractive_exit_remains_gbk_safe(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "from ai_todo_assistant.presentation.cli import main; main()"],
        cwd=tmp_path,
        env=_isolated_environment(tmp_path, "gbk"),
        input="/exit\n".encode("gbk"),
        capture_output=True,
        check=False,
        timeout=20,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined.decode("gbk", errors="replace")
    assert b"UnicodeEncodeError" not in combined
    combined.decode("gbk", errors="strict")
```

- [x] **Step 2: Run the new test and verify RED**

Run: `python -m pytest tests/test_agentretro_subprocess.py::test_existing_ai_todo_noninteractive_exit_remains_gbk_safe -q`

Expected: FAIL because the direct Rich farewell attempts to encode `👋` as GBK.

- [x] **Step 3: Route the farewell through the existing safe renderer**

```python
self._display_response("\n👋 Goodbye!")
```

- [x] **Step 4: Run the focused subprocess suite and verify GREEN**

Run: `python -m pytest tests/test_agentretro_subprocess.py -q`

Expected: PASS with no `UnicodeEncodeError` under GBK or UTF-8.

### Task 2: Document the executable first-use workflow

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Existing `retro doctor`, `project map`, `capture`, `review`, `brief`, and preview-only `integrate codex` commands.
- Produces: A PowerShell quickstart that separates read-only diagnostics, local state writes, vault writes, and global guidance writes.

- [x] **Step 1: Add an ordered PowerShell quickstart**

Document installation, `retro doctor`, project mapping, explicit capture, review, accepted-knowledge inspection, task briefing, and Codex integration preview. State that `doctor` is read-only and that `review accept` may project accepted knowledge into the configured vault.

- [x] **Step 2: Verify every documented command against CLI help**

Run: `retro --help` plus focused subcommand `--help` checks for every quickstart command.

Expected: Every example parses or displays help without modifying real user state.

### Task 3: Close verification and traceability

**Files:**
- Modify: `openspec/changes/add-agentretro-mvp/tasks.md`

**Interfaces:**
- Consumes: The compatibility fix, quickstart, and existing 98-scenario registry.
- Produces: A checked follow-up task after complete verification.

- [x] **Step 1: Run focused and full verification**

Run the focused subprocess suite, full pytest suite, Ruff, Ruff format check, `openspec validate add-agentretro-mvp --strict`, `pip check`, and `git diff --check`.

- [x] **Step 2: Reproduce the installed CLI path**

Run the editable virtual-environment `ai-todo` entry point under default Windows GBK-compatible settings with `/exit`, and confirm exit code 0 without forcing `PYTHONUTF8=1`.

- [x] **Step 3: Mark the OpenSpec follow-up task complete and commit only scoped files**

Exclude `.playbook/`, real user data, generated coverage data, and unrelated worktree files from the commit.
