## Why

The repository currently has no automated pull-request checks, so the locally verified test, packaging, secret-safety, and command-line compatibility guarantees can regress without a visible merge gate. Add a deterministic, least-privilege CI baseline now so the AgentRetro and `ai-todo` mainline can be reviewed against the same reproducible evidence used locally.

## What Changes

- Add GitHub Actions checks for supported Python runtimes on Windows and Linux, including the full deterministic test suite and repository lint baseline.
- Make the repository's Python 3.10-compatible Ruff baseline explicit so local and hosted runs do not inherit tool-version defaults or workstation configuration.
- Add a read-only secret scan that covers the submitted Git content without receiving repository secrets or write permissions.
- Build distributable artifacts, validate their metadata and contents, install the wheel into an isolated environment, and smoke both installed console commands.
- Upload only non-sensitive distribution artifacts and keep job permissions, timeouts, concurrency, and dependency/action versions explicit.
- Remove the four existing unused example assignments that prevent a truthful repository-wide Ruff gate.
- Correct the reproduced cross-runtime baseline defects in Windows shim path resolution, invalid `/sync` project-path handling, Python-version-sensitive candidate-budget assertions, and localized timestamp formatting without weakening their intended safety guarantees.

## Capabilities

### New Capabilities

- `repository-ci-quality-gates`: Defines the required pull-request and mainline checks for tests, lint, secret scanning, package build validation, isolated wheel installation, and installed CLI smoke behavior.

### Modified Capabilities

None.

## Impact

- Adds repository-owned workflow and CI smoke files under `.github/` and `scripts/` plus a new OpenSpec capability.
- Adds CI-only tooling installation for pytest, Ruff, the declared setuptools build backend, build, and package metadata validation; runtime dependencies and public CLI contracts remain unchanged.
- GitHub pull requests and pushes to `main` gain observable automated checks. The workflow does not deploy, publish packages, read user configuration, use production credentials, or mutate application data.
- `pyproject.toml` owns the deterministic Ruff target and rule selection; `examples/demo.py` receives a non-functional lint-baseline cleanup only.
- The compatibility corrections preserve existing Windows and `/sync` contracts while making their tests deterministic on every supported CI runtime.
