# Tasks

- [x] Add OpenSpec deltas for Codex thread resume behavior and command-surface compatibility.
- [x] Run `openspec validate resume-codex-threads --strict`.
- [x] Run `ai-decision-review` on the OpenSpec change before implementation.
- [x] Add failing tests for resume candidate selection and dry-run safety.
- [x] Add failing tests for successful/failed resume attempts and Evidence recording.
- [x] Add CLI tests for `/r`, indexed targeting, bulk resume, and unavailable client.
- [x] Add bounded watch test for `/sync watch --resume`.
- [x] Implement Codex resume service and injectable client interface.
- [x] Wire `/r` and `/sync watch --resume` into the CLI.
- [x] Update help/completion text and README.
- [x] Run targeted tests and full unittest discovery.
- [x] Add persistent manual auto-resume exclusions and CLI skip/unskip/list commands.
- [x] Add tests for mixed continueable/user-input reports and excluded-thread auto-resume skips.
- [x] Move exclusion management behind an application service and keep JSON persistence as an infrastructure adapter.
- [x] Write exclusion JSON through same-directory temporary files and atomic replace.
- [x] Add Evidence-based success/failure idempotence for bulk/watch resume while preserving targeted manual repeat.
