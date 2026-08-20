## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal describing optional system CLI Evidence recording.
- [x] 1.2 Create design describing compact derived Evidence fields and duplicate reuse.
- [x] 1.3 Create spec delta for CLI and tool-call Evidence behavior.

## 2. TDD Coverage

- [x] 2.1 Add failing CLI tests for `/system run ... --evidence <work-id>` and duplicate reuse.
- [x] 2.2 Add failing tool-call tests for `record_evidence`, required `work_item_id`, and Evidence fields.

## 3. Implementation

- [x] 3.1 Add a small system CLI Evidence helper that records only compact derived fields.
- [x] 3.2 Extend `RunSystemCliArgs` with `work_item_id` and `record_evidence` validation.
- [x] 3.3 Extend `ToolExecutor._run_system_cli` to optionally record/reuse Evidence.
- [x] 3.4 Extend `/system run` parsing and help text for `--evidence`.

## 4. Validation

- [x] 4.1 Run focused system CLI CLI/tool-call tests.
- [x] 4.2 Validate OpenSpec with `openspec validate record-system-cli-evidence --strict`.
- [x] 4.3 Run full unittest suite.
- [x] 4.4 Review final diff for unrelated changes.
