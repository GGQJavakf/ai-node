## ADDED Requirements

### Requirement: CI runs on reviewable repository changes
The repository SHALL run its CI workflow for every pull request, every push to `main`, and an explicit manual dispatch. The workflow SHALL cancel superseded runs for the same pull request or ref without cancelling an unrelated change.

#### Scenario: Pull request receives CI evidence
- **WHEN** a pull request targets the repository
- **THEN** the current submitted commit receives quality, test, secret-scan, and package job results

#### Scenario: Superseded commit stops consuming runners
- **WHEN** a newer commit starts CI for the same pull request or ref
- **THEN** the older in-progress workflow is cancelled while workflows for other refs remain unaffected

### Requirement: Workflow authority is least privilege
The workflow MUST use read-only repository-content permission, MUST disable persisted checkout credentials, and MUST NOT receive reusable repository, model, deployment, or publishing secrets. It MUST NOT publish, deploy, release, change repository settings, or mutate external application state.

#### Scenario: Untrusted fork pull request runs safely
- **WHEN** CI evaluates code submitted from an untrusted fork
- **THEN** jobs can read the submitted Git content but receive no reusable secret and have no repository write permission

### Requirement: Full tests cover the supported runtime boundary
The CI test matrix SHALL run the complete deterministic pytest suite on Linux and Windows using both Python 3.10 and Python 3.14. Any failing test or unsupported matrix entry MUST fail its job, and one matrix failure MUST NOT hide results from the remaining entries.

#### Scenario: Minimum-version regression is visible
- **WHEN** code passes on the current Python runtime but fails on Python 3.10
- **THEN** at least the affected Python 3.10 matrix job fails and the pull request does not show a fully passing test gate

#### Scenario: Windows-only regression is visible
- **WHEN** subprocess, path, or console behavior fails only on Windows
- **THEN** the affected Windows matrix job fails even if Linux jobs pass

### Requirement: Static and specification baselines are truthful
CI SHALL run Ruff against the entire tracked repository, compile all source modules, and strictly validate every active OpenSpec change and main specification. The workflow MUST NOT exclude an existing source or example path merely to hide a baseline failure.

#### Scenario: Lint debt blocks the quality job
- **WHEN** any tracked Python file violates the configured Ruff baseline
- **THEN** the quality job fails with that file included in the check scope

#### Scenario: Invalid OpenSpec artifact blocks the quality job
- **WHEN** an active change or main specification fails strict OpenSpec validation
- **THEN** the quality job fails before the commit is considered fully verified

### Requirement: Secret scanning covers Git history without leaking findings
CI SHALL scan the full checked-out Git history with an immutable, checksum-verified Gitleaks binary. It MUST redact detected values completely, enforce a bounded scan timeout, persist no finding report, and fail before any distribution artifact is uploaded when a finding exists or scanner integrity cannot be verified.

#### Scenario: Submitted credential is detected
- **WHEN** the submitted Git content contains a value recognized as a secret
- **THEN** the secret-scan job fails, logs do not reveal the value, and package jobs do not upload artifacts

#### Scenario: Scanner download is tampered with
- **WHEN** the downloaded scanner archive does not match the pinned SHA-256
- **THEN** the secret-scan job fails before executing the archive

### Requirement: Distribution artifacts are validated and smoke tested
CI SHALL build both sdist and wheel, validate their package metadata, install the wheel into a fresh virtual environment on Linux and Windows, and exercise the installed `retro` and `ai-todo` entry points from outside the checkout. The smoke environment MUST remove `PYTHONPATH` and user/project AI configuration, redirect all home and application state into a temporary directory, and verify that the installed non-secret settings template is present.

#### Scenario: Wheel depends on checkout-only files
- **WHEN** an installed command succeeds from source but the built wheel omits a required module or data file
- **THEN** the isolated wheel smoke fails on at least one package job

#### Scenario: Installed commands use no user configuration
- **WHEN** the package smoke runs on a hosted runner
- **THEN** both commands complete their bounded non-network flows using only temporary state and no inherited AI or local-project configuration

### Requirement: CI dependencies and execution are bounded
All third-party Actions SHALL be pinned to a verified full commit SHA, CI-only Python and OpenSpec tools SHALL use explicit versions, and every job SHALL define a timeout. Uploaded distributions SHALL use a short retention period and fail the package job when the expected files are absent.

#### Scenario: Action tag moves upstream
- **WHEN** an upstream Action changes a mutable release tag
- **THEN** the workflow continues using the reviewed immutable commit until this repository explicitly updates the pin

#### Scenario: Job hangs
- **WHEN** a test, scanner, build, or smoke command does not finish
- **THEN** GitHub terminates the owning job at its configured timeout and reports failure
