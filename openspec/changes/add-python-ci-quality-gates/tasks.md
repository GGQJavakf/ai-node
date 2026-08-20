## 1. Establish the green baseline

- [x] 1.1 Add exact, CI-only Python tool versions without changing runtime dependencies.
- [x] 1.2 Remove the four unused `examples/demo.py` assignments and prove example behavior remains unchanged.
- [x] 1.3 Correct the four hosted-matrix portability failures without skipping platforms or weakening their intended invariants.

## 2. Implement repository CI gates

- [x] 2.1 Add the isolated installed-wheel smoke that verifies packaged data and both console entry points without inherited user configuration.
- [x] 2.2 Add the least-privilege workflow triggers, concurrency, timeouts, immutable Action pins, repository-wide quality checks, and Linux/Windows Python 3.10/3.14 test matrix.
- [x] 2.3 Add the full-history, checksum-verified, fully redacted Gitleaks CLI gate with no persistent report or reusable secret.
- [x] 2.4 Add Linux/Windows sdist and wheel build, metadata validation, secret-gated isolated smoke, and short-retention distribution upload.

## 3. Verify implementation and security boundaries

- [x] 3.1 Run the pinned Gitleaks release locally against full history and resolve only reproduced findings without exposing values.
- [x] 3.2 Run the full local pytest suite, repository-wide Ruff, source compile, and strict all-OpenSpec validation.
- [x] 3.3 Build sdist and wheel locally, run metadata checks, and pass the installed-wheel smoke from an unrelated directory.
- [x] 3.4 Validate workflow syntax and immutable pins, inspect the complete diff, and obtain a fresh independent review after fixes.

## 4. Deliver reviewable remote evidence

- [x] 4.1 Commit and push the isolated branch, then create a Draft PR targeting `main` with verification and rollback details.
- [ ] 4.2 Read back the remote PR head and every new CI job; keep the PR Draft until all jobs pass on the delivered commit.
