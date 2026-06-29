## 1. Tests

- [x] 1.1 Add service/catalog tests for `openspec.validate` and `playbook.workspace_status` command specs and fixed argv.
- [x] 1.2 Add CLI test showing `/system list` includes both new keys.
- [x] 1.3 Add tool-call test showing `run_system_cli` can execute `openspec.validate`.

## 2. Implementation

- [x] 2.1 Add `openspec.validate` to the read-only command catalog with fixed non-interactive JSON argv.
- [x] 2.2 Add `playbook.workspace_status` to the read-only command catalog with fixed workspace status argv.

## 3. Verification

- [x] 3.1 Run focused system CLI service, CLI, and tool-call tests.
- [x] 3.2 Run manual smoke for `/system run openspec.validate` and `/system run playbook.workspace_status`.
- [x] 3.3 Run full unittest suite and strict OpenSpec validation.
- [x] 3.4 Review final diff for scope and unrelated changes.
