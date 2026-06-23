# Design

## Overview

The implementation adds a local application service that turns the latest Codex task report into resume candidates. It does not parse Codex private storage and does not assume the current desktop runtime is available. A small `CodexThreadResumeClient` interface owns message delivery; the default client reports `unavailable`, while tests and later Codex app bridges can inject a working implementation.

## Candidate Contract

An entry is resume-eligible only when all of these are true:

- It comes from the latest report's `unfinished` bucket.
- It has a stable `thread_id` or `id`.
- It has a non-empty `resume_prompt` or `next_action`.
- It is explicitly marked safe by `resume_eligible: true`, or its normalized `status` / `classification` is one of `continueable`, `continuable`, `paused`, `ready`, `needs_action`, or `needs_resume`.

An entry is never resume-eligible when:

- It appears in `blocked` or `completed`.
- Its status/classification indicates `blocked`, `needs_user`, `needs_human`, `waiting_user`, `complete`, or `completed`.
- It lacks a thread id or continuation prompt.

## Command Surface

- `/codex resume --dry-run [thread-id]`
  - Lists candidates and skip reasons.
  - Does not call the resume client and writes no Evidence.
- `/codex resume [thread-id]`
  - Sends continuation prompts only for eligible candidates.
  - If a thread id is supplied, evaluates only that thread.
  - Records local Evidence for each attempted resume.
- `/sync watch --resume [interval-seconds] [path]`
  - Runs the existing sync trigger.
  - Then runs Codex resume for safe candidates.
  - Prints both sync and resume results for each trigger.

## Data and Persistence

No schema migration is required. Resume attempts use existing `WorkItem` and `Evidence` storage:

- Match WorkItems by source `codex` and source ref `thread_id`.
- If a matching WorkItem does not exist, create one from the report entry before recording attempt evidence.
- Evidence source is `codex`, command is `codex resume <thread-id>`, success reflects client outcome, and summary contains the attempt result.

## Safety

- Dry-run is read-only.
- Missing report, missing resume client, or unavailable client returns a local report and does not crash.
- The service never resumes blocked/completed/user-needed threads.
- The service never writes external systems other than the configured Codex thread client.

## Compatibility

Existing Codex report imports remain unchanged. `/codex tasks` still imports report entries into WorkItems; resume is an explicit command path and is not triggered by ordinary report ingestion.

## Test Strategy

- Unit test candidate selection and skip reasons from report entries.
- Unit test dry-run does not call the resume client or write Evidence.
- Unit test successful and failed resume attempts call the client, update WorkItems, and append Evidence.
- CLI test `/codex resume --dry-run`, `/codex resume`, targeted thread id, and unavailable-client output.
- CLI/watch test `--resume` runs sync then resume once with bounded execution.
