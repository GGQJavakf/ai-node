## Context

`origin/main` has no `.github/workflows` entry. The Python distribution contains two console commands (`ai-todo` and `retro`), supports Python 3.10 and newer, includes Windows-sensitive subprocess and encoding behavior, and already has deterministic pytest coverage plus an installed-wheel configuration test. Those guarantees are currently evidenced only by local runs. The CI design must be safe for untrusted pull-request content, must not depend on workstation configuration or reusable credentials, and must keep package artifacts behind a secret-safety gate.

## Goals / Non-Goals

**Goals:**

- Make every pull request, push to `main`, and manual run produce reproducible test, lint, OpenSpec, secret-scan, and package evidence.
- Exercise the declared minimum Python (3.10) and the current stable Python (3.14) on both Linux and Windows.
- Prove that a built wheel works outside the repository and that both installed console commands start and exit safely with isolated homes and no AI credentials.
- Minimize workflow authority and supply-chain drift through read-only permissions, disabled checkout credentials, full-SHA Action pins, checksummed scanner binaries, bounded timeouts, and exact CI tool versions.

**Non-Goals:**

- Publishing to PyPI, creating releases, deploying, signing, or attesting artifacts.
- Reading local/user configuration, invoking a real model, capturing real Codex sessions, or contacting production systems.
- Introducing a type-check gate before the existing repository-wide mypy debt has a separately approved baseline.
- Rewriting Git history, rotating credentials, or accepting broad secret-scan exceptions if a real historical leak is found.

## Decisions

### One workflow with isolated jobs

Use one `.github/workflows/ci.yml` with separate `quality`, `tests`, `secret-scan`, and `package` jobs. The workflow runs for `pull_request`, pushes to `main`, and `workflow_dispatch`, has workflow-level `contents: read`, cancels superseded runs in the same ref/PR group, and gives every job a timeout. A single workflow keeps event, permission, pin, and concurrency policy visible in one reviewable place; separate jobs preserve failure attribution and parallelize independent checks.

### Supported-runtime matrix, not every Python minor

Run the full suite on Python 3.10 and 3.14 on both `ubuntu-latest` and `windows-latest`. The minimum catches compatibility regressions in the declared contract, while the current stable runtime catches ecosystem drift. Minor versions remain fixed while hosted runners provide current patch/security releases. Exact CI tool versions, including the declared setuptools build backend needed by the existing `--no-build-isolation` wheel regression, live in `requirements-ci.txt`; runtime dependencies continue to resolve from `pyproject.toml` because introducing a cross-platform application lock is a separate concern.

### Direct, checksummed Gitleaks CLI

Fetch Gitleaks 8.30.0 from its official GitHub release in the Linux `secret-scan` job, verify the `linux_x64` archive against the hard-coded SHA-256 published with that immutable release, and run `gitleaks git` against a full-history checkout with 100% redaction and a command timeout. This avoids the Gitleaks Action's license/token/commenting behavior, passes no repository secret to untrusted code, and scans past and present Git content. No scan report is uploaded because even redacted finding metadata is unnecessary persistence.

If the baseline contains a finding, classify it before adding any exception. A confirmed reusable secret requires separate authorization for rotation/history remediation; a demonstrable fixture false positive may receive only the narrowest path/rule exception with a regression test.

### Package gate installs the artifact, not the source tree

Build both sdist and wheel with `python -m build`, validate metadata with `twine check`, then use `scripts/ci_installed_smoke.py` to create a fresh virtual environment and install the produced wheel from an unrelated temporary working directory. The script removes project/user configuration variables, redirects home/Codex/AgentRetro state into the temporary directory, removes `PYTHONPATH`, verifies the packaged non-secret settings template, runs `retro --help` plus a JSON read command, and drives `ai-todo` through a non-interactive `/exit` flow. Package jobs run on Linux and Windows and depend on a successful secret scan. Only the Linux `dist/` is uploaded, with a short retention period and failure on missing files.

### Immutable Actions and explicit platform tools

Pin first-party Actions to full commits verified from their official repositories:

- `actions/checkout` v7.0.1: `3d3c42e5aac5ba805825da76410c181273ba90b1`
- `actions/setup-python` v7.0.0: `5fda3b95a4ea91299a34e894583c3862153e4b97`
- `actions/setup-node` v7.0.0: `820762786026740c76f36085b0efc47a31fe5020`
- `actions/upload-artifact` v7.0.1: `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`

Run OpenSpec 1.4.1 with Node 24 using an exact `npx` package version. All checkouts set `persist-credentials: false`; only the secret scan requests full history.

### Truthful repository-wide Ruff baseline

The quality job runs Ruff on the entire repository. `pyproject.toml` explicitly owns the Python 3.10 target and the established `E4`, `E7`, `E9`, and `F` rule set so a Ruff upgrade or workstation configuration cannot silently change the merge gate. Remove the four unused local assignments in `examples/demo.py` instead of weakening the check or excluding the examples tree. The demonstration calls and observable output remain unchanged.

### Repair reproduced compatibility failures instead of excluding them

The hosted matrix revealed four existing portability assumptions. Windows batch-shim resolution patched `os.name` in tests while retaining the host's POSIX path module, invalid `/sync` paths relied on platform-specific subprocess exceptions, a candidate-budget test counted internal `Path.stat()` calls that vary by Python version even though its actual invariant is the selected path set, and Windows Python 3.10 could not locale-encode Chinese characters embedded directly in a `strftime` format string. Use `ntpath` inside the Windows-only resolver, preflight `/sync` directories before connector execution, keep the candidate-set/no-old-candidate assertions while removing only the interpreter-internal call-count assertion, and assemble the localized timestamp from numeric fields plus Unicode literals without locale-dependent formatting. Do not skip platforms, mark expected failures, or shrink the matrix.

## Risks / Trade-offs

- **Historical scan finds a real credential** → Fail closed, redact output, do not upload packages, and stop for explicit credential/history-remediation authorization.
- **Generated or fixture text triggers a false positive** → Require a reproduced rule/path finding and a narrow documented allowlist; never blanket-ignore test or config trees.
- **Four full test combinations consume Actions minutes** → Cancel superseded runs, keep `fail-fast: false` for complete compatibility evidence, and revisit the matrix only with measured runtime data.
- **Hosted runner images and runtime dependencies still drift** → Pin Actions and CI tools, test minimum/current runtimes, and treat application dependency locking as a separate design decision.
- **Wheel smoke accidentally imports the checkout** → Run from an unrelated temp directory with `PYTHONPATH` removed and invoke the generated entry-point executables from the new virtual environment.
- **Distribution artifact contains sensitive content despite source scanning** → Make package jobs depend on `secret-scan`, verify wheel/template contents, and upload only `dist/*` for seven days.

## Migration Plan

1. Add the OpenSpec artifacts, CI workflow, exact CI tool requirements, installed-wheel smoke script, and example lint cleanup on an isolated branch from `origin/main`.
2. Run the scanner, repository tests/lint/OpenSpec checks, local build, isolated wheel smoke, workflow lint, and a fresh independent review locally.
3. Push a Draft PR and require the new remote workflow to pass on its own commit before marking it ready.
4. After authorized merge, branch protection can select the stable job names as required checks; changing repository protection is outside this change and requires separate permission.

Rollback is a normal revert of the CI commit. Removing the workflow stops future runs; no deployment, schema, user data, or published package must be rolled back.

## Open Questions

None for implementation. Making the checks mandatory in GitHub branch protection remains a separately authorized repository-permission change.
