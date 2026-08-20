# Design

## Overview

The first implementation adds a local in-process watch loop. It does not create a daemon, OS scheduled task, or Codex app automation. The loop invokes the existing `TodoCLI._handle_sync_command()` path, then appends `ContinueService.recommend()` output so each trigger gives the user both synchronization evidence and the next action.

## Command Surface

- `/sync watch [interval-seconds] [path]`
  - Runs immediately once, then sleeps for the requested interval before the next trigger.
  - Defaults to a safe interval from configuration when no interval is supplied.
  - Prints each trigger result to the console.
  - Stops on `Ctrl+C`.

The watch mode is intentionally nested under `/sync` so it does not create a second synchronization command family.

## Configuration

Add `sync_watch_interval_seconds` to settings, with environment override `AI_SYNC_WATCH_INTERVAL_SECONDS`.

## Safety

The watch loop reuses existing `/sync` behavior:

- Codex report ingestion reads local JSON/Markdown report files.
- Project context synchronization uses existing read-only connectors.
- No external writeback, merge, push, publish, or deploy is performed.

## Test Strategy

- Unit test the formatter/runner with a bounded `max_runs` and fake sleep so tests never wait in real time.
- CLI test `/sync watch` dispatch with a single run and mocked sync service.
- Keep existing `/sync` tests passing to prove compatibility.
