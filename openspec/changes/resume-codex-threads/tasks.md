# Tasks

- [x] Add OpenSpec deltas for Codex thread resume behavior and command-surface compatibility.
- [x] Run `openspec validate resume-codex-threads --strict`.
- [x] Run `ai-decision-review` on the OpenSpec change before implementation.
- [x] Add failing tests for resume candidate selection and dry-run safety.
- [x] Add failing tests for successful/failed resume attempts and Evidence recording.
- [x] Add CLI tests for `/codex resume`, `--dry-run`, targeted thread id, and unavailable client.
- [x] Add bounded watch test for `/sync watch --resume`.
- [x] Implement Codex resume service and injectable client interface.
- [x] Wire `/codex resume` and `/sync watch --resume` into the CLI.
- [x] Update help/completion text and README.
- [x] Run targeted tests and full unittest discovery.
