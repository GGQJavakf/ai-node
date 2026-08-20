## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal describing read-only system CLI catalog scope.
- [x] 1.2 Create design describing catalog execution, policy checks, and output safety.
- [x] 1.3 Create system-cli-tool-catalog spec with slash-command, tool-call, and safety requirements.
- [x] 1.4 Validate OpenSpec with `openspec validate add-system-cli-tool-catalog --strict`.

## 2. System CLI Service

- [x] 2.1 Add failing tests for command listing, unknown command rejection, cwd policy, missing command handling, redaction, and truncation.
- [x] 2.2 Implement system CLI models, catalog, and service.
- [x] 2.3 Verify service tests pass.

## 3. Tool Call Integration

- [x] 3.1 Add failing tests for `run_system_cli` validation and execution.
- [x] 3.2 Register `RunSystemCliArgs`, tool description, and executor dispatch.
- [x] 3.3 Verify tool-call tests pass.

## 4. Slash Command Integration

- [x] 4.1 Add failing tests for `/system list`, `/system policy`, `/system run`, and `/help system`.
- [x] 4.2 Add `/system` completion, dispatch, and formatter helpers.
- [x] 4.3 Verify CLI tests pass.

## 5. Validation

- [x] 5.1 Run targeted system CLI, tool validation, and command surface tests.
- [x] 5.2 Run full unittest suite with `python -m unittest discover -s tests`.
- [x] 5.3 Validate OpenSpec after implementation.
- [x] 5.4 Review final diff for unrelated changes.
