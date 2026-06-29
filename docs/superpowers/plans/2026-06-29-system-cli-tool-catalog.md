# System CLI Tool Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first OpenSpec-backed slice of system CLI support: a read-only command catalog, `/system` CLI entry, and `run_system_cli` tool call with tests.

**Architecture:** Add a small `application.system_cli` package that owns command catalog, policy checks, output summarization, and execution service. Keep shell execution in the existing infrastructure `CommandRunner`, expose only catalog keys to slash commands and LLM tool calls, and keep `/system` as an advanced command so the daily command surface stays focused.

**Tech Stack:** Python 3.10+, Pydantic v2, unittest, existing `CommandRunner`, existing `TodoCLI`, existing OpenAI-compatible tool definitions.

---

## File Structure

- Create `openspec/changes/add-system-cli-tool-catalog/proposal.md`: why and scope for the OpenSpec change.
- Create `openspec/changes/add-system-cli-tool-catalog/design.md`: architecture and safety decisions.
- Create `openspec/changes/add-system-cli-tool-catalog/specs/system-cli-tool-catalog/spec.md`: acceptance requirements.
- Create `openspec/changes/add-system-cli-tool-catalog/tasks.md`: implementation checklist.
- Create `src/ai_todo_assistant/application/system_cli/__init__.py`: public exports for system CLI application services.
- Create `src/ai_todo_assistant/application/system_cli/models.py`: `CommandSpec`, `CommandExecutionRecord`, and related constants.
- Create `src/ai_todo_assistant/application/system_cli/catalog.py`: read-only command catalog and argument validation.
- Create `src/ai_todo_assistant/application/system_cli/service.py`: policy checks, command execution, redaction, truncation, and summary formatting.
- Modify `src/ai_todo_assistant/application/agent/tool_models.py`: add `RunSystemCliArgs` and register `run_system_cli`.
- Modify `src/ai_todo_assistant/application/agent/tool_definitions.py`: add description for `run_system_cli`.
- Modify `src/ai_todo_assistant/application/agent/tool_executor.py`: dispatch `run_system_cli` to `SystemCliService`.
- Modify `src/ai_todo_assistant/presentation/cli.py`: add `/system list`, `/system run <key> [--cwd <path>]`, `/system policy`, completion, and help topic.
- Create `tests/test_system_cli_service.py`: service, catalog, policy, redaction, truncation, and fallback behavior tests.
- Create `tests/test_system_cli_tool_call.py`: tool validation and tool executor tests.
- Create `tests/test_system_cli_cli.py`: slash command tests.

## Task 1: OpenSpec Artifacts

**Files:**
- Create: `openspec/changes/add-system-cli-tool-catalog/proposal.md`
- Create: `openspec/changes/add-system-cli-tool-catalog/design.md`
- Create: `openspec/changes/add-system-cli-tool-catalog/specs/system-cli-tool-catalog/spec.md`
- Create: `openspec/changes/add-system-cli-tool-catalog/tasks.md`

- [ ] **Step 1: Write OpenSpec proposal**

Create a proposal that limits the first slice to read-only catalog commands, `/system` advanced CLI entry, and `run_system_cli` tool calls. State explicitly that arbitrary shell and external writes are out of scope.

- [ ] **Step 2: Write OpenSpec design**

Document catalog-key execution, cwd policy, output redaction/truncation/summarization, and fallback behavior when parsing fails.

- [ ] **Step 3: Write OpenSpec spec**

Write requirements for read-only command catalog, slash command behavior, tool-call behavior, output safety, and help surface compatibility.

- [ ] **Step 4: Write task checklist**

Create a tasks file with tests-first implementation steps and validation commands.

- [ ] **Step 5: Validate OpenSpec**

Run: `openspec validate add-system-cli-tool-catalog --strict`
Expected: validation succeeds. Treat OpenSpec telemetry noise as non-blocking only if the command returns success.

## Task 2: System CLI Service

**Files:**
- Create: `src/ai_todo_assistant/application/system_cli/__init__.py`
- Create: `src/ai_todo_assistant/application/system_cli/models.py`
- Create: `src/ai_todo_assistant/application/system_cli/catalog.py`
- Create: `src/ai_todo_assistant/application/system_cli/service.py`
- Test: `tests/test_system_cli_service.py`

- [ ] **Step 1: Write failing service tests**

Add tests for:
- listing `git.status` and `git.branch`
- rejecting unknown command keys
- rejecting cwd outside allowed roots
- returning missing command records
- redacting secrets before returning excerpts
- truncating long output

- [ ] **Step 2: Run service tests to verify failure**

Run: `python -m unittest tests.test_system_cli_service`
Expected: import or assertion failures because service does not exist yet.

- [ ] **Step 3: Implement models and catalog**

Add immutable dataclasses for command specs and execution records. Add read-only specs for `git.branch`, `git.status`, and `git.diff_stat`.

- [ ] **Step 4: Implement service**

Implement `SystemCliService.list_commands()`, `run(command_key, cwd=None)`, cwd allowlist checks, redaction, truncation, and tool-result formatting.

- [ ] **Step 5: Run service tests to verify pass**

Run: `python -m unittest tests.test_system_cli_service`
Expected: all tests pass.

## Task 3: Tool Call Integration

**Files:**
- Modify: `src/ai_todo_assistant/application/agent/tool_models.py`
- Modify: `src/ai_todo_assistant/application/agent/tool_definitions.py`
- Modify: `src/ai_todo_assistant/application/agent/tool_executor.py`
- Test: `tests/test_system_cli_tool_call.py`

- [ ] **Step 1: Write failing tool-call tests**

Add tests that `validate_tool_call` accepts `run_system_cli` with `git.status`, rejects blank command keys, and that `ToolExecutor.execute("run_system_cli", ...)` returns a system CLI summary.

- [ ] **Step 2: Run tool-call tests to verify failure**

Run: `python -m unittest tests.test_system_cli_tool_call`
Expected: failure because `run_system_cli` is not registered.

- [ ] **Step 3: Register tool args**

Add `RunSystemCliArgs` with `command_key`, `cwd`, and `reason`; strip optional cwd/reason and reject blank command keys.

- [ ] **Step 4: Add tool description and executor dispatch**

Add a concise description explaining that only read-only catalog keys are allowed. Dispatch to `SystemCliService`.

- [ ] **Step 5: Run tool-call tests to verify pass**

Run: `python -m unittest tests.test_system_cli_tool_call`
Expected: all tests pass.

## Task 4: Slash Command Integration

**Files:**
- Modify: `src/ai_todo_assistant/presentation/cli.py`
- Test: `tests/test_system_cli_cli.py`
- Modify as needed: `tests/test_command_surface.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests for `/system list`, `/system policy`, `/system run git.status`, unknown command rejection, and `/help system` showing system CLI commands without moving them into primary help.

- [ ] **Step 2: Run CLI tests to verify failure**

Run: `python -m unittest tests.test_system_cli_cli`
Expected: failure because `/system` dispatch does not exist.

- [ ] **Step 3: Add completion and dispatch**

Add `/system list`, `/system policy`, and `/system run` completions and dispatch.

- [ ] **Step 4: Add formatter helpers**

Add helpers that call `SystemCliService` and return compact text suitable for CLI output.

- [ ] **Step 5: Run CLI tests to verify pass**

Run: `python -m unittest tests.test_system_cli_cli`
Expected: all tests pass.

## Task 5: Validation

**Files:**
- Modify: `openspec/changes/add-system-cli-tool-catalog/tasks.md`
- Review: all changed files

- [ ] **Step 1: Run targeted tests**

Run:
```powershell
python -m unittest tests.test_system_cli_service tests.test_system_cli_tool_call tests.test_system_cli_cli tests.test_tool_validation tests.test_command_surface
```
Expected: all tests pass.

- [ ] **Step 2: Run full unittest suite**

Run: `python -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 3: Validate OpenSpec**

Run: `openspec validate add-system-cli-tool-catalog --strict`
Expected: validation succeeds.

- [ ] **Step 4: Mark OpenSpec tasks complete**

Update `openspec/changes/add-system-cli-tool-catalog/tasks.md` checkboxes for completed work.

- [ ] **Step 5: Review final diff**

Run: `git diff --stat` and inspect touched files. Confirm only the design doc, OpenSpec artifacts, system CLI implementation, and focused tests changed.

## Self-Review

- Spec coverage: The plan covers OpenSpec artifacts, read-only command catalog, `/system` CLI, `run_system_cli` tool-call integration, output safety, and tests.
- Placeholder scan: No `TBD`, `TODO`, `implement later`, or placeholder instructions are present.
- Type consistency: The plan consistently uses `SystemCliService`, `CommandSpec`, `CommandExecutionRecord`, `RunSystemCliArgs`, and `run_system_cli`.
