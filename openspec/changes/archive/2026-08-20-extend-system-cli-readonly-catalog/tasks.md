## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal for extending the read-only catalog with OpenSpec listing.
- [x] 1.2 Create design describing why only fixed `openspec.list` is included.
- [x] 1.3 Create spec delta for OpenSpec list catalog behavior.

## 2. TDD Coverage

- [x] 2.1 Add failing service tests for listing and running `openspec.list`.
- [x] 2.2 Add failing CLI test showing `/system list` includes `openspec.list`.

## 3. Implementation

- [x] 3.1 Add `openspec.list` to the read-only command catalog with fixed argv.

## 4. Validation

- [x] 4.1 Run focused System CLI service and CLI tests.
- [x] 4.2 Validate OpenSpec with `openspec validate extend-system-cli-readonly-catalog --strict`.
- [x] 4.3 Run full unittest suite.
- [x] 4.4 Review final diff for unrelated changes.
