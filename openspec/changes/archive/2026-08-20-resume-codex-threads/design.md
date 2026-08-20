# Design

## Overview

The implementation adds a local application service that turns the latest Codex task report into resume candidates. It does not parse Codex private storage and does not assume the current desktop runtime is available. A small `CodexThreadResumeClient` interface owns message delivery; the default client reports `unavailable`, while tests and later Codex app bridges can inject a working implementation.

## Candidate Contract

An entry is resume-eligible only when all of these are true:

- It comes from the latest report's `unfinished` bucket.
- It has a stable `thread_id` or `id`.
- It has a non-empty `resume_prompt` or `next_action`.
- It is explicitly marked safe by `resume_eligible: true`, or its normalized `status` / `classification` is one of `continueable`, `continuable`, `paused`, `ready`, `needs_action`, or `needs_resume`.
- For backward compatibility with older Codex reports, a plain `unfinished` entry with a continuation prompt is normalized to `resume_eligible: true` / `continueable` when it has no blocked/user-needed status and the prompt does not contain manual-action markers such as `人工确认`, `等待用户`, `权限`, or `审批`.

An entry is never resume-eligible when:

- It appears in `blocked` or `completed`.
- Its status/classification indicates `blocked`, `needs_user`, `needs_human`, `waiting_user`, `complete`, or `completed`.
- It lacks a thread id or continuation prompt.

## Command Surface

- `/r` or `/resume`
  - Lists progress summary, resumeable tasks, and skipped tasks in fixed-width text tables with stable row indexes.
  - Shows each task's current progress and next direction so the user can see what remains and how to proceed.
  - Does not call the resume client and writes no Evidence.
- `/r <index>` or `/resume <index>`
  - Sends continuation prompts only for eligible candidates.
  - A supplied table index is a manual action and bypasses automatic-resume exclusions.
  - Records local Evidence for each attempted resume.
- `/r all`
  - Bulk resumes all eligible candidates.
- `/r skip <index> [reason]`
  - Persists a manual exclusion for bulk and watch auto-resume.
- `/r unskip <index>`
  - Removes a manual exclusion.
- `/r skips`
  - Lists manual exclusions.
- `/sync watch --resume [interval-seconds] [path]`
  - Runs the existing sync trigger.
  - Then runs Codex resume for safe candidates.
  - Prints both sync and resume results for each trigger.

## Data and Persistence

No database schema migration is required. Resume attempts use existing `WorkItem` and `Evidence` storage:

- Match WorkItems by source `codex` and source ref `thread_id`.
- If a matching WorkItem does not exist, create one from the report entry before recording attempt evidence.
- Evidence source is `codex`, command is `codex resume <thread-id>`, success reflects client outcome, and summary contains the attempt result.

Manual automatic-resume exclusions are stored in a small JSON file configured by `codex_resume_exclusions_file`, defaulting to `data/codex-resume-exclusions.json`. If that file cannot be read, automatic resume fails closed and sends no Codex prompts.

The CLI manages exclusions through an application-level `CodexResumeExclusionService`; the JSON file remains an infrastructure adapter behind the exclusion store port. Writes use a same-directory temporary file followed by atomic replacement to avoid partially written exclusion files after interrupted local writes.

Bulk and watch-triggered resume are idempotent for prior attempts: before sending a candidate, the service checks the matching Codex WorkItem Evidence for a prior `codex resume <thread-id>` entry containing the same `prompt_sha256` marker. Prior success is skipped as already resumed; prior failure is skipped as already failed for that prompt so watch does not append the same failure Evidence every interval. Evidence still includes a human-readable prompt excerpt, but idempotence uses the stable hash marker so long prompts with the same display prefix are not treated as the same prompt. Targeted `/r <index>` remains an explicit manual action and can repeat a prompt.

## Safety

- Dry-run is read-only.
- Missing report, missing resume client, or unavailable client returns a local report and does not crash.
- The service never resumes blocked/completed/user-needed threads.
- Bulk and watch auto-resume skip manually excluded threads until the exclusion is removed.
- The service never writes external systems other than the configured Codex thread client.

## Compatibility

Existing Codex report imports remain unchanged. `/codex tasks` still imports report entries into WorkItems; resume is an explicit command path and is not triggered by ordinary report ingestion.

## Test Strategy

- Unit test candidate selection and skip reasons from report entries.
- Unit test dry-run does not call the resume client or write Evidence.
- Unit test successful and failed resume attempts call the client, update WorkItems, and append Evidence.
- CLI test `/r`, `/r all`, targeted index, and unavailable-client output.
- CLI test manual skip/unskip/skips commands and excluded-thread skip behavior.
- Unit test exclusion management routes through the application service and JSON store round-trips with atomic replacement cleanup.
- Unit test bulk resume skips a previously successful or failed same prompt, does not skip a different long prompt with the same excerpt prefix, and targeted manual resume may repeat it.
- CLI/watch test `--resume` runs sync then resume once with bounded execution.
