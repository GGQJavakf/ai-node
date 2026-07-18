# AgentRetro MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `retro` CLI that turns explicitly selected completed Codex sessions into reviewed, evidence-backed SQLite knowledge, safely projects accepted knowledge to Obsidian, and supplies bounded context to later Codex tasks.

**Architecture:** Add a sibling `agent_retro` package with domain models, application services, infrastructure adapters, and an argparse CLI. SQLite is the authority for lifecycle and audit state; Obsidian is a journaled, hash-checked projection; all model reuse goes through one filtered read-only adapter to the existing configuration and LLM client.

**Tech Stack:** Python 3.10+, standard-library `argparse`, `dataclasses`, `sqlite3`, `pathlib`, `hashlib`, existing Pydantic 2, existing Rich, pytest over the repository's unittest-style tests.

**Revised:** 2026-07-18 after OpenSpec review `APPROVE`; this revision supersedes the earlier hard-delete, manual-only projection, mutable mapping, relevance, and global-guidance assumptions in this file.

## Global Constraints

- Preserve the existing `ai-todo` entry point, Todo/WorkItem behavior, configuration precedence, and `data/todos.db` content.
- Do not add an ORM, vector database, Web/GUI/MCP surface, hook, watcher, or background process.
- Capture only one explicitly selected completed local Codex session per command.
- Store no complete raw transcript and no unredacted credential value.
- Use `RULE >= 0.97`, `LESSON >= 0.93`, and `TASK_STATE >= 0.90` as fixed MVP automatic-acceptance thresholds.
- Secrets, insufficient evidence, unknown project, duplicate, conflict, speculation, unauthoritative rule, or unverified lesson always block automatic acceptance.
- Automatic Obsidian writes stay inside three aggregate files and explicit managed regions; deep merge and global Codex integration require preview plus explicit apply.
- Every committed projection-changing transition attempts one synchronous, idempotent Obsidian projection; failure preserves SQLite authority and records `sync_pending`.
- Ordinary removal archives. Sensitive purge requires an immutable plan, confirmation of every operation ID, cleanup of every known AgentRetro-owned copy including affected backups, and `purge_incomplete` on any unverifiable residual.
- Project mappings are audited SQLite state managed only through `retro project map/list/remove/reclassify`.
- Brief selection is local and deterministic: NFKC/case-folded CJK and Latin tokens, fixed configured weights, stable-ID tie-break, and no model or vector service.
- Global Codex integration targets only `<effective-codex-home>/AGENTS.md`, refuses apply/removal when `AGENTS.override.md` exists, and never modifies Codex native memory.
- Default `TASK_STATE` validity is 14 days; default brief budget is approximately 6000 tokens estimated as `ceil(UTF-8 byte length / 3)` with atomic item inclusion.
- Default limits are newest 1000 candidate session files, 10-second discovery, 128 MiB source session, filtered model timeout or 120 seconds, and 5-second local brief rendering; every limit is configurable and fail-closed.
- Automated tests use temporary home, Codex, database, backup, vault, and global-guidance paths.
- Every `CR-01..CR-22`, `KR-01..KR-24`, `OS-01..OS-24`, and `BR-01..BR-28` scenario maps to a passing automated test or an explicitly justified manual check.
- Follow `openspec/changes/add-agentretro-mvp/` as the normative behavior contract.

---

## Planned File Structure

| Path | Responsibility |
|---|---|
| `src/agent_retro/domain/models.py` | Enums and dataclasses for sessions, evidence, candidates, knowledge, conflicts, sync, and audit |
| `src/agent_retro/application/ports.py` | Typed protocols for repository, session source, reviewer, vault, and clock boundaries |
| `src/agent_retro/application/capture.py` | Explicit capture transaction and project-routing orchestration |
| `src/agent_retro/application/review.py` | Extraction, independent review, thresholds, hard gates, and manual review actions |
| `src/agent_retro/application/knowledge.py` | Conflict resolution, scope promotion, expiry, and ordinary archive |
| `src/agent_retro/application/purge.py` | Immutable sensitive-purge planning, exact confirmation, residual verification, and content-free tombstones |
| `src/agent_retro/application/sync.py` | Obsidian projection planning, transaction journal, retry, and reconciliation |
| `src/agent_retro/application/merge.py` | Hash-bound deep merge plans and explicit apply |
| `src/agent_retro/application/brief.py` | Accepted-knowledge selection and token-bounded rendering model |
| `src/agent_retro/application/doctor.py` | Readiness checks and recovery hints |
| `src/agent_retro/application/bootstrap.py` | Dependency construction without importing the Todo/WorkItem domain |
| `src/agent_retro/infrastructure/settings.py` | User-local AgentRetro configuration |
| `src/agent_retro/infrastructure/legacy_model.py` | Filtered read-only existing model configuration and client adapter |
| `src/agent_retro/infrastructure/sqlite_repository.py` | Versioned schema, transactions, queries, audit, and sync journal |
| `src/agent_retro/infrastructure/codex_sessions.py` | Effective Codex-home discovery and versioned JSONL parser |
| `src/agent_retro/infrastructure/redaction.py` | Deterministic secret redaction before model input and persistence |
| `src/agent_retro/infrastructure/project_mapping.py` | Git-root and normalized-remote project resolution |
| `src/agent_retro/infrastructure/llm_review.py` | Pydantic extraction/review schemas and LLM calls |
| `src/agent_retro/infrastructure/obsidian.py` | Aggregate-file rendering, managed blocks, containment, atomic replace, and backup |
| `src/agent_retro/infrastructure/codex_guidance.py` | Global guidance preview/apply/remove for one managed block |
| `src/agent_retro/presentation/output.py` | Unicode-safe Chinese human and stable JSON output |
| `src/agent_retro/presentation/cli.py` | Argparse command tree and application dispatch |
| `tests/test_agentretro_*.py` | Focused unit, integration, security, subprocess, and regression coverage |
| `tests/fixtures/agentretro/*.jsonl` | Synthetic completed, active, malformed, changed, and unknown-event sessions |
| `tests/agentretro_scenarios.py` | Stable scenario-ID to pytest-node mapping used by the coverage gate |
| `tests/test_agentretro_scenario_coverage.py` | Verifies all 98 OpenSpec scenarios are mapped with no orphan IDs |

## Core Public Interfaces

The following names are fixed across tasks:

```python
class KnowledgeType(str, Enum):
    RULE = "RULE"
    LESSON = "LESSON"
    TASK_STATE = "TASK_STATE"

class ReviewVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    REJECT = "REJECT"

class CandidateStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    AUTO_ACCEPTED = "auto_accepted"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"

class ProjectionStatus(str, Enum):
    SYNCED = "synced"
    SYNC_PENDING = "sync_pending"
    ROLLBACK_REQUIRED = "rollback_required"

class PurgeStatus(str, Enum):
    PLANNED = "planned"
    PURGE_INCOMPLETE = "purge_incomplete"
    PURGED = "purged"

@dataclass(frozen=True)
class SourceLocator:
    session_id: str
    event_id: str
    source_path: str
    content_hash: str

@dataclass(frozen=True)
class Evidence:
    id: str
    session_id: str
    kind: str
    locator: SourceLocator
    excerpt: str

@dataclass(frozen=True)
class NormalizedEvent:
    id: str
    kind: str
    content: str
    locator: SourceLocator

@dataclass(frozen=True)
class NormalizedSession:
    id: str
    source_session_id: str
    source_path: Path
    source_hash: str
    project_id: str
    completed: bool
    completed_at: datetime
    events: tuple[NormalizedEvent, ...]

@dataclass(frozen=True)
class Candidate:
    id: str
    knowledge_type: KnowledgeType
    project_id: str
    scope: str
    proposed_text: str
    evidence_ids: tuple[str, ...]
    status: CandidateStatus
    extraction_confidence: float

@dataclass(frozen=True)
class ReviewResult:
    verdict: ReviewVerdict
    confidence: float
    reason: str
    normalized_text: str
    duplicate_of: str | None
    conflict_with: str | None

@dataclass(frozen=True)
class Knowledge:
    id: str
    version: int
    candidate_id: str
    knowledge_type: KnowledgeType
    project_id: str
    scope: str
    text: str
    status: str
    confidence: float
    accepted_by: str
    evidence_ids: tuple[str, ...]
    valid_until: datetime | None
    updated_at: datetime

@dataclass(frozen=True)
class KnowledgeConflict:
    id: str
    active_knowledge_id: str
    candidate_id: str
    reason: str
    merge_text: str
    status: str

@dataclass(frozen=True)
class SyncJob:
    id: str
    project_id: str
    status: str
    plan_json: str
    backup_path: Path
    error: str = ""

@dataclass(frozen=True)
class ProjectMapping:
    id: str
    git_root: Path
    remote_identity: str
    obsidian_project: str
    active: bool = True

@dataclass(frozen=True)
class ReviewAttempt:
    id: str
    candidate_id: str
    input_hash: str
    status: str
    result_json: str
    error: str

@dataclass(frozen=True)
class PurgeOperation:
    id: str
    location_kind: str
    location: str
    expected_hash: str

@dataclass(frozen=True)
class PurgePlan:
    id: str
    knowledge_id: str
    operations: tuple[PurgeOperation, ...]
    status: PurgeStatus

@dataclass(frozen=True)
class AuditEntry:
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    before_hash: str
    after_hash: str
    detail_json: str
    created_at: datetime

@dataclass(frozen=True)
class BriefRequest:
    task: str
    project_id: str
    max_tokens: int = 6000
```

---

### Task 1: Independent CLI, Settings, and Legacy Model Boundary

**Files:**
- Modify: `pyproject.toml:17`
- Create: `src/agent_retro/__init__.py`
- Create: `src/agent_retro/domain/__init__.py`
- Create: `src/agent_retro/domain/models.py`
- Create: `src/agent_retro/application/__init__.py`
- Create: `src/agent_retro/application/bootstrap.py`
- Create: `src/agent_retro/infrastructure/__init__.py`
- Create: `src/agent_retro/infrastructure/settings.py`
- Create: `src/agent_retro/infrastructure/legacy_model.py`
- Create: `src/agent_retro/presentation/__init__.py`
- Create: `src/agent_retro/presentation/output.py`
- Create: `src/agent_retro/presentation/cli.py`
- Test: `tests/test_agentretro_foundation.py`

**Interfaces:**
- Produces: `RetroSettings`, `load_retro_settings()`, `effective_model_timeout()`, `load_legacy_model_config()`, `build_retro_llm_client()`, `build_parser()`, `main()`.
- Preserves: `ai_todo_assistant.presentation.cli:main` and the existing `ai-todo` script.
- Closes OpenSpec tasks: `1.1`, `1.2`, `1.4`, `1.5`, `1.6` after the focused and full tests pass.

- [ ] **Step 1: Write failing isolation and configuration tests**

```python
import json
from unittest.mock import patch

import _path  # noqa: F401
from agent_retro.infrastructure.settings import load_retro_settings
from agent_retro.infrastructure.legacy_model import load_legacy_model_config
from agent_retro.presentation.cli import build_parser


def test_settings_use_the_supplied_home(tmp_path):
    settings = load_retro_settings(home=tmp_path, env={})
    assert settings.state_dir == tmp_path / ".agentretro"
    assert settings.db_path == tmp_path / ".agentretro" / "retro.db"
    assert settings.brief_max_tokens == 6000
    assert settings.discovery_max_files == 1000
    assert settings.discovery_timeout_seconds == 10.0
    assert settings.session_max_bytes == 128 * 1024 * 1024
    assert settings.brief_timeout_seconds == 5.0


def test_settings_reject_state_children_outside_root(tmp_path):
    with pytest.raises(ValueError, match="AGENTRETRO_DB_PATH"):
        load_retro_settings(
            home=tmp_path,
            env={"AGENTRETRO_DB_PATH": str(tmp_path.parent / "outside.db")},
        )


def test_invalid_limit_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="AGENTRETRO_DISCOVERY_MAX_FILES"):
        load_retro_settings(
            home=tmp_path,
            env={"AGENTRETRO_DISCOVERY_MAX_FILES": "0"},
        )


@patch("agent_retro.infrastructure.legacy_model.load_settings")
def test_legacy_model_adapter_filters_unrelated_settings(load_settings):
    load_settings.return_value = {
        "auth_mode": "openai_api",
        "api_key": "secret-for-test",
        "api_base": "https://example.invalid/v1",
        "model": "test-model",
        "sqlite_path": "data/todos.db",
    }
    filtered = load_legacy_model_config()
    assert "sqlite_path" not in filtered
    assert set(filtered) == {"auth_mode", "api_key", "api_base", "model", "request_timeout", "api_retry_limit", "api_retry_backoff", "codex_command", "codex_timeout", "codex_request_timeout", "codex_use_app_server", "codex_app_server_timeout", "codex_app_server_start_timeout", "codex_app_server_fallback_to_exec", "codex_retry_limit", "codex_ignore_user_config", "codex_ignore_rules"}


def test_parser_has_independent_program_name():
    parser = build_parser()
    assert parser.prog == "retro"
```

- [ ] **Step 2: Run the focused test and verify the missing package failure**

Run: `python -m pytest tests/test_agentretro_foundation.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'agent_retro'`.

- [ ] **Step 3: Add the console entry and immutable settings model**

Add this script beside the existing entry in `pyproject.toml`:

```toml
[project.scripts]
ai-todo = "ai_todo_assistant.presentation.cli:main"
retro = "agent_retro.presentation.cli:main"
```

Implement this exact settings shape:

```python
@dataclass(frozen=True)
class RetroSettings:
    state_dir: Path
    db_path: Path
    backup_dir: Path
    obsidian_root: Path | None
    brief_max_tokens: int
    discovery_max_files: int
    discovery_timeout_seconds: float
    session_max_bytes: int
    model_timeout_seconds: int | None
    brief_timeout_seconds: float
    thresholds: Mapping[KnowledgeType, float]


def load_retro_settings(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RetroSettings:
    values = dict(os.environ if env is None else env)
    user_home = Path.home() if home is None else Path(home)
    state_dir = Path(values.get("AGENTRETRO_HOME", user_home / ".agentretro"))
    obsidian_value = values.get("AGENTRETRO_OBSIDIAN_ROOT", "").strip()
    settings = RetroSettings(
        state_dir=state_dir,
        db_path=Path(values.get("AGENTRETRO_DB_PATH", state_dir / "retro.db")),
        backup_dir=Path(values.get("AGENTRETRO_BACKUP_DIR", state_dir / "backups")),
        obsidian_root=Path(obsidian_value) if obsidian_value else None,
        brief_max_tokens=int(values.get("AGENTRETRO_BRIEF_MAX_TOKENS", "6000")),
        discovery_max_files=int(values.get("AGENTRETRO_DISCOVERY_MAX_FILES", "1000")),
        discovery_timeout_seconds=float(values.get("AGENTRETRO_DISCOVERY_TIMEOUT_SECONDS", "10")),
        session_max_bytes=int(values.get("AGENTRETRO_SESSION_MAX_BYTES", str(128 * 1024 * 1024))),
        model_timeout_seconds=(
            int(values["AGENTRETRO_MODEL_TIMEOUT_SECONDS"])
            if values.get("AGENTRETRO_MODEL_TIMEOUT_SECONDS")
            else None
        ),
        brief_timeout_seconds=float(values.get("AGENTRETRO_BRIEF_TIMEOUT_SECONDS", "5")),
        thresholds={
            KnowledgeType.RULE: 0.97,
            KnowledgeType.LESSON: 0.93,
            KnowledgeType.TASK_STATE: 0.90,
        },
    )
    _validate_settings(settings)
    return settings


def effective_model_timeout(settings: RetroSettings, legacy: Mapping[str, object]) -> int:
    return int(
        settings.model_timeout_seconds
        or legacy.get("request_timeout")
        or legacy.get("codex_request_timeout")
        or 120
    )
```

`_validate_settings()` resolves `state_dir`, `db_path`, and `backup_dir`, rejects a child path outside the state root (including symlink escape), and requires every numeric limit to be greater than zero. `obsidian_root` is validated later by vault preflight because it is intentionally outside AgentRetro state.

- [ ] **Step 4: Add the filtered legacy model adapter**

Use one allowlist constant and return a fresh dictionary. `build_retro_llm_client()` passes only that dictionary to `build_llm_client()` and never logs it.

```python
MODEL_CONFIG_KEYS = (
    "auth_mode", "api_key", "api_base", "model", "request_timeout",
    "api_retry_limit", "api_retry_backoff", "codex_command", "codex_timeout",
    "codex_request_timeout", "codex_use_app_server", "codex_app_server_timeout",
    "codex_app_server_start_timeout", "codex_app_server_fallback_to_exec",
    "codex_retry_limit", "codex_ignore_user_config", "codex_ignore_rules",
)


def load_legacy_model_config(project_root: str | None = None) -> dict[str, object]:
    source = load_settings(project_root)
    return {key: source.get(key) for key in MODEL_CONFIG_KEYS}


def build_retro_llm_client(project_root: str | None = None):
    return build_llm_client(load_legacy_model_config(project_root))
```

- [ ] **Step 5: Add Unicode-safe output and minimal argparse help**

`safe_text()` encodes and decodes with `errors="replace"` only when the active stream encoding cannot represent the text. `write_json()` always emits UTF-8-safe JSON with `ensure_ascii=False`. `main(argv)` returns integer exit codes and does not construct any Todo/WorkItem object.

```python
def safe_text(value: object, encoding: str | None = None) -> str:
    text = str(value)
    target = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(target, errors="replace").decode(target, errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retro", description="Codex 会话复盘与知识沉淀")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
```

- [ ] **Step 6: Run foundation tests and the original suite**

Run: `python -m pytest tests/test_agentretro_foundation.py -q`

Expected: all foundation tests pass.

Run: `python -m pytest -q`

Expected: the existing 161 tests plus new tests pass.

- [ ] **Step 7: Mark the covered OpenSpec tasks complete**

Change only `1.1`, `1.2`, `1.4`, `1.5`, and `1.6` from `[ ]` to `[x]` in `openspec/changes/add-agentretro-mvp/tasks.md`; leave `1.3` for Task 2.

- [ ] **Step 8: Commit the independent product boundary**

```bash
git add pyproject.toml src/agent_retro tests/test_agentretro_foundation.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Establish the independent AgentRetro product boundary"
```

---

### Task 2: SQLite Schema, Repository, and Migration Recovery

**Files:**
- Create: `src/agent_retro/application/ports.py`
- Create: `src/agent_retro/infrastructure/sqlite_repository.py`
- Modify: `src/agent_retro/domain/models.py`
- Modify: `src/agent_retro/application/bootstrap.py`
- Test: `tests/test_agentretro_persistence.py`

**Interfaces:**
- Produces: `RetroRepository`, `SQLiteRetroRepository`, `migrate()`, `transaction()`, and typed persistence methods for sessions, mappings, evidence, candidates, review attempts, knowledge, conflicts, projection events, sync jobs, purge jobs, managed-file hashes, and audit.
- Consumes: `RetroSettings.db_path`, domain dataclasses from Task 1.
- Closes OpenSpec task: `1.3` after migration, rollback, transaction, and audit tests pass.

- [ ] **Step 1: Write failing migration, rollback, and lifecycle tests**

```python
def test_repository_creates_schema_version_one(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    assert repo.schema_version() == 1
    assert set(repo.table_names()) >= {
        "sessions", "evidence", "candidates", "review_attempts", "knowledge",
        "conflicts", "projection_events", "sync_jobs", "project_mappings",
        "purge_jobs", "purge_operations", "managed_file_state", "audit_log",
    }


def test_failed_migration_restores_database(tmp_path, monkeypatch):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    repo.migrate()
    before = db_path.read_bytes()
    monkeypatch.setattr(repo, "_apply_migration", lambda connection, version: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError, match="injected"):
        repo.migrate(target_version=2)
    assert db_path.read_bytes() == before
```

- [ ] **Step 2: Run the persistence tests and verify missing repository failure**

Run: `python -m pytest tests/test_agentretro_persistence.py -q`

Expected: import fails because `SQLiteRetroRepository` does not exist.

- [ ] **Step 3: Add the version-one schema**

Create the following tables in one SQLite transaction with foreign keys enabled:

```sql
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, source_session_id TEXT NOT NULL, source_path TEXT NOT NULL, source_hash TEXT NOT NULL, project_id TEXT NOT NULL, status TEXT NOT NULL, completed_at TEXT NOT NULL, captured_at TEXT NOT NULL, UNIQUE(source_session_id, source_hash));
CREATE TABLE evidence (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), kind TEXT NOT NULL, event_id TEXT NOT NULL, content_hash TEXT NOT NULL, excerpt TEXT NOT NULL, UNIQUE(session_id, event_id, content_hash));
CREATE TABLE candidates (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), knowledge_type TEXT NOT NULL, project_id TEXT NOT NULL, scope TEXT NOT NULL, proposed_text TEXT NOT NULL, status TEXT NOT NULL, extraction_confidence REAL NOT NULL, review_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE candidate_evidence (candidate_id TEXT NOT NULL REFERENCES candidates(id), evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(candidate_id, evidence_id));
CREATE TABLE knowledge (id TEXT NOT NULL, version INTEGER NOT NULL, candidate_id TEXT NOT NULL, knowledge_type TEXT NOT NULL, project_id TEXT NOT NULL, scope TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, confidence REAL NOT NULL, accepted_by TEXT NOT NULL, valid_until TEXT, created_at TEXT NOT NULL, PRIMARY KEY(id, version));
CREATE TABLE knowledge_evidence (knowledge_id TEXT NOT NULL, knowledge_version INTEGER NOT NULL, evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(knowledge_id, knowledge_version, evidence_id));
CREATE TABLE conflicts (id TEXT PRIMARY KEY, active_knowledge_id TEXT NOT NULL, candidate_id TEXT NOT NULL, reason TEXT NOT NULL, merge_text TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
CREATE TABLE sync_jobs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, status TEXT NOT NULL, plan_json TEXT NOT NULL, backup_path TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE review_attempts (id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id), input_hash TEXT NOT NULL, attempt_no INTEGER NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(candidate_id, attempt_no));
CREATE TABLE project_mappings (id TEXT PRIMARY KEY, git_root TEXT NOT NULL, remote_identity TEXT NOT NULL, obsidian_project TEXT NOT NULL, active INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX uq_active_mapping_root ON project_mappings(git_root) WHERE active = 1;
CREATE UNIQUE INDEX uq_active_mapping_remote ON project_mappings(remote_identity) WHERE active = 1;
CREATE TABLE projection_events (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, cause TEXT NOT NULL, cause_entity_id TEXT NOT NULL, input_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(project_id, cause, cause_entity_id, input_hash));
CREATE TABLE managed_file_state (path TEXT PRIMARY KEY, project_id TEXT NOT NULL, managed_hash TEXT NOT NULL, full_hash TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE purge_jobs (id TEXT PRIMARY KEY, knowledge_id TEXT NOT NULL, plan_hash TEXT NOT NULL, status TEXT NOT NULL, tombstone_json TEXT NOT NULL, residual_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE purge_operations (id TEXT PRIMARY KEY, purge_job_id TEXT NOT NULL REFERENCES purge_jobs(id), location_kind TEXT NOT NULL, location TEXT NOT NULL, expected_hash TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL);
CREATE TABLE audit_log (id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, before_hash TEXT NOT NULL, after_hash TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
```

- [ ] **Step 4: Implement backup-first migrations and transaction semantics**

`migrate()` copies an existing database to `<backup-dir>/migration-<from>-to-<to>-<timestamp>.db` before opening the migration transaction. On any error, close the connection, replace the failed database with the backup, verify SHA-256 equality, and re-raise. The repository context manager commits on success and rolls back on exception.

- [ ] **Step 5: Implement exact repository methods used by later tasks**

```python
def find_session(self, source_session_id: str, source_hash: str) -> NormalizedSession | None
def save_capture(self, session: NormalizedSession, evidence: Sequence[Evidence]) -> None
def save_candidates(self, candidates: Sequence[Candidate]) -> None
def get_candidate(self, candidate_id: str) -> Candidate | None
def list_candidates(self, status: CandidateStatus) -> list[Candidate]
def save_review(self, candidate_id: str, result: ReviewResult) -> None
def begin_review_attempt(self, attempt: ReviewAttempt) -> ReviewAttempt
def finish_review_attempt(self, attempt_id: str, status: str, result_json: str = "", error: str = "") -> None
def accept_candidate(self, candidate_id: str, text: str, actor: str, confidence: float) -> Knowledge
def list_active_knowledge(self, project_id: str, at: datetime) -> list[Knowledge]
def save_conflict(self, conflict: KnowledgeConflict) -> None
def begin_sync(self, job: SyncJob) -> None
def finish_sync(self, job_id: str, status: str, error: str = "") -> None
def save_project_mapping(self, mapping: ProjectMapping, actor: str) -> None
def list_project_mappings(self, active_only: bool = True) -> list[ProjectMapping]
def deactivate_project_mapping(self, mapping_id: str, actor: str) -> None
def save_projection_event(self, event_id: str, project_id: str, cause: str, cause_entity_id: str, input_hash: str) -> str
def save_managed_file_state(self, project_id: str, path: Path, managed_hash: str, full_hash: str) -> None
def save_purge_plan(self, plan: PurgePlan, plan_hash: str, actor: str) -> None
def finish_purge(self, plan_id: str, status: PurgeStatus, tombstone_json: str, residual_json: str) -> None
def append_audit(self, entry: AuditEntry) -> None
```

Each public mutation receives domain objects or typed scalar arguments, runs in one transaction, and appends its audit record in that transaction.

- [ ] **Step 6: Run persistence and full regression tests**

Run: `python -m pytest tests/test_agentretro_persistence.py -q`

Expected: schema, rollback, lifecycle, and audit tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Mark the covered OpenSpec task complete**

Change only `1.3` to `[x]` in `openspec/changes/add-agentretro-mvp/tasks.md`.

- [ ] **Step 8: Commit the persistence foundation**

```bash
git add src/agent_retro tests/test_agentretro_persistence.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Make AgentRetro state versioned and recoverable"
```

---

### Task 3: Codex Session Parser, Project Routing, Redaction, and Capture

**Files:**
- Create: `src/agent_retro/infrastructure/codex_sessions.py`
- Create: `src/agent_retro/infrastructure/project_mapping.py`
- Create: `src/agent_retro/infrastructure/redaction.py`
- Create: `src/agent_retro/application/capture.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Create: `tests/fixtures/agentretro/completed.jsonl`
- Create: `tests/fixtures/agentretro/active.jsonl`
- Create: `tests/fixtures/agentretro/malformed.jsonl`
- Create: `tests/fixtures/agentretro/unknown-event.jsonl`
- Test: `tests/test_agentretro_capture.py`

**Interfaces:**
- Produces: `CodexSessionSource`, `Redactor`, `ProjectResolver`, `ProjectMappingService.map/list/remove/reclassify`, `CaptureService.capture_last()`, `CaptureService.capture_session()`.
- Consumes: `RetroRepository` from Task 2.
- Closes OpenSpec tasks: `2.1` through `2.9`; scenario trace task `2.10` remains for Task 10.

- [ ] **Step 1: Add synthetic JSONL fixtures and failing parser tests**

The completed fixture contains one session identity event, one user message, one assistant message, one command result, and one completion event. Use the literal credential `TOKEN_FOR_REDACTION_TEST` only in fixtures.

```python
def test_completed_session_is_normalized(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)
    session = source.load("session-completed")
    assert session.source_session_id == "session-completed"
    assert session.completed is True
    assert [event.kind for event in session.events] == ["user", "assistant", "command"]


def test_active_session_is_rejected(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)
    with pytest.raises(IncompleteSessionError):
        source.load("session-active")


def test_discovery_stops_at_configured_count(fixtures_dir, monotonic_clock):
    source = CodexSessionSource(
        fixtures_dir,
        max_candidates=2,
        discovery_timeout_seconds=10,
        max_session_bytes=128 * 1024 * 1024,
        monotonic=monotonic_clock,
    )
    source.latest_completed()
    assert source.last_discovery.inspected_count <= 2


def test_oversized_session_is_rejected_before_parse(fixtures_dir):
    source = CodexSessionSource(fixtures_dir, max_session_bytes=8)
    with pytest.raises(SessionSizeLimitError, match="8"):
        source.load("session-completed")
```

- [ ] **Step 2: Run capture tests and verify parser imports fail**

Run: `python -m pytest tests/test_agentretro_capture.py -q`

Expected: import fails for the missing session adapter.

- [ ] **Step 3: Implement completed-session discovery and normalization**

```python
class CodexSessionSource:
    def __init__(
        self,
        codex_home: Path,
        *,
        max_candidates: int = 1000,
        discovery_timeout_seconds: float = 10.0,
        max_session_bytes: int = 128 * 1024 * 1024,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.codex_home = codex_home
        self.max_candidates = max_candidates
        self.discovery_timeout_seconds = discovery_timeout_seconds
        self.max_session_bytes = max_session_bytes
        self.monotonic = monotonic

    def latest_completed(self) -> NormalizedSession:
        deadline = self.monotonic() + self.discovery_timeout_seconds
        for path in self._session_paths_newest_first()[: self.max_candidates]:
            if self.monotonic() >= deadline:
                raise SessionDiscoveryTimeout("会话发现超过配置时限")
            session = self._parse_bounded(path)
            if session.completed:
                return session
        raise SessionNotFoundError("未找到已完成的 Codex 会话")

    def load(self, session_id: str) -> NormalizedSession:
        session = self._parse(self._path_for(session_id))
        if not session.completed:
            raise IncompleteSessionError(f"Codex 会话仍在进行: {session_id}")
        return session
```

Parse JSONL line-by-line, derive deterministic event IDs from source line number and event identity, ignore unknown optional event kinds with warnings, and reject missing session ID, source locator, or completion state.

- [ ] **Step 4: Implement two-pass redaction and minimal evidence**

Use compiled patterns for bearer headers, key/value secrets, JSON secret fields, PEM private-key blocks, and connection strings. Preserve the key name and replace only the value with `[REDACTED]`. Call the same `Redactor.redact()` before LLM input and before repository/vault serialization.

```python
class Redactor:
    def redact(self, text: str) -> str:
        value = text
        for pattern, replacement in REDACTION_RULES:
            value = pattern.sub(replacement, value)
        return value

    def contains_sensitive_value(self, text: str) -> bool:
        return any(pattern.search(text) for pattern, _ in REDACTION_RULES)
```

- [ ] **Step 5: Implement project routing**

Normalize HTTPS and SSH Git remotes to `host/path-without-dot-git`. Resolve in this order: exact Git-root plus remote mapping, exact Git-root mapping, unique remote mapping. Return `ProjectResolution(status="unknown")` or `status="ambiguous"` rather than guessing.

`ProjectMappingService.map()` resolves the Git root, rejects path/symlink escape for the configured vault project, rejects an active root or remote mapped to an incompatible target, and persists `ProjectMapping`. `list()` returns no embedded remote credentials. `remove()` deactivates only the mapping. `reclassify()` updates an awaiting session to an existing mapping and calls review over stored redacted evidence without parsing the JSONL again.

```python
class ProjectMappingService:
    def map(self, git_root: Path, obsidian_project: str, actor: str = "user") -> ProjectMapping: ...
    def list(self) -> list[ProjectMapping]: ...
    def remove(self, mapping_id: str, actor: str = "user") -> None: ...
    def reclassify(self, session_id: str, mapping_id: str, actor: str = "user") -> None: ...
```

- [ ] **Step 6: Implement transactional capture and CLI commands**

`CaptureService` checks `find_session()` before writing. A known session ID with a changed hash raises `SourceIntegrityError`. A new capture constructs redacted evidence, saves session and evidence in one repository transaction, and returns a result with `captured`, `reused`, `warnings`, and `project_status`.

Add argparse subcommands with mutually exclusive `--last` and `--session`, plus `retro project map --root ... --vault-project ...`, `list`, `remove`, and `reclassify`. No capture command may create a hook or watcher. A parser or evidence error occurs before `save_capture()` commits anything.

- [ ] **Step 7: Run capture, security, idempotency, and regression tests**

Run: `python -m pytest tests/test_agentretro_capture.py -q`

Expected: completed, active, malformed, unknown-event, project-routing, redaction, idempotency, and integrity-conflict tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Mark covered OpenSpec tasks complete**

Change `2.1` through `2.9` to `[x]`; leave `2.10` open for the scenario coverage gate.

- [ ] **Step 9: Commit explicit evidence-backed capture**

```bash
git add src/agent_retro tests/test_agentretro_capture.py tests/fixtures/agentretro openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Capture completed Codex sessions with traceable evidence"
```

---

### Task 4: Two-Stage Review, Hard Gates, and Knowledge Lifecycle

**Files:**
- Create: `src/agent_retro/infrastructure/llm_review.py`
- Create: `src/agent_retro/application/review.py`
- Create: `src/agent_retro/application/knowledge.py`
- Modify: `src/agent_retro/domain/models.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Test: `tests/test_agentretro_review.py`

**Interfaces:**
- Produces: `ExtractionGateway`, `ReviewGateway`, `ReviewService.review_session/retry_candidate/retry_session`, `KnowledgeService`, `GateResult`.
- Consumes: captured evidence and repository methods from Tasks 2 and 3.
- Closes OpenSpec tasks: `3.1` through `3.9`; sensitive purge `3.10` is Task 9 and trace task `3.11` is Task 10.

- [ ] **Step 1: Write failing type-contract and threshold tests**

```python
@pytest.mark.parametrize(
    ("knowledge_type", "confidence", "expected"),
    [
        (KnowledgeType.RULE, 0.969, False),
        (KnowledgeType.RULE, 0.970, True),
        (KnowledgeType.LESSON, 0.929, False),
        (KnowledgeType.LESSON, 0.930, True),
        (KnowledgeType.TASK_STATE, 0.899, False),
        (KnowledgeType.TASK_STATE, 0.900, True),
    ],
)
def test_type_thresholds(knowledge_type, confidence, expected):
    assert threshold_passes(knowledge_type, confidence) is expected


def test_secret_gate_blocks_high_confidence(rule_candidate, secret_evidence):
    result = evaluate_gates(rule_candidate, ReviewResult(ReviewVerdict.ACCEPT, 1.0, "", rule_candidate.proposed_text, None, None), [secret_evidence])
    assert result.allowed is False
    assert "secret" in result.blockers


def test_retry_reuses_candidate_without_reextracting(review_service, reviewer, extractor, pending_candidate):
    reviewer.result = ReviewResult(ReviewVerdict.ACCEPT, 0.99, "ok", "normalized", None, None)
    first = review_service.retry_candidate(pending_candidate.id)
    second = review_service.retry_candidate(pending_candidate.id)
    assert first == second
    assert extractor.calls == 0
    assert reviewer.calls == 1
    assert review_service.repository.accepted_count(pending_candidate.id) == 1
```

- [ ] **Step 2: Run review tests and verify missing service failure**

Run: `python -m pytest tests/test_agentretro_review.py -q`

Expected: import fails for the missing review service.

- [ ] **Step 3: Add strict Pydantic model responses**

```python
class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    knowledge_type: Literal["RULE", "LESSON", "TASK_STATE"]
    proposed_text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verdict: Literal["ACCEPT", "EDIT", "REJECT"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    duplicate_of: str | None = None
    conflict_with: str | None = None
```

Extraction and review use separate prompts and separate model requests. Review receives redacted candidate/evidence JSON, not extraction reasoning.

- [ ] **Step 4: Implement deterministic gates**

`evaluate_gates()` returns ordered blocker codes. Implement `secret`, `insufficient_evidence`, `unknown_project`, `duplicate`, `conflict`, `speculation`, `rule_authority`, and `lesson_verification`. A non-empty blocker tuple always overrides model confidence and verdict.

```python
@dataclass(frozen=True)
class GateResult:
    allowed: bool
    blockers: tuple[str, ...]


def threshold_passes(kind: KnowledgeType, confidence: float) -> bool:
    return confidence >= {
        KnowledgeType.RULE: 0.97,
        KnowledgeType.LESSON: 0.93,
        KnowledgeType.TASK_STATE: 0.90,
    }[kind]
```

- [ ] **Step 5: Implement automatic and manual review actions**

`ReviewService.review_session()` saves extracted candidates before calling the independent reviewer, records a failed attempt when the model is unavailable or reaches the effective timeout, evaluates gates, and automatically accepts only `ACCEPT` results that pass type threshold and all gates. `accept()`, `edit()`, and `reject()` always append actor and before/after hashes.

Add `retro review`, `show`, `accept`, `edit`, and `reject` commands. Evidence excerpts displayed by review are already redacted.

- [ ] **Step 6: Implement conflicts, scope, expiry, and archive**

`KnowledgeService.detect_conflict()` keeps existing knowledge active and creates a pending conflict. `resolve_conflict()` creates a new version and records superseded IDs. `expire_task_states(at)` marks task state stale after `valid_until`. `promote_global()` requires actor `user`. `archive()` preserves content and history. Do not implement a one-token hard-delete shortcut; sensitive purge is isolated in Task 9.

- [ ] **Step 7: Implement idempotent review retry**

```python
def retry_candidate(self, candidate_id: str) -> ReviewResult | None:
    candidate = self.repository.require_pending_candidate(candidate_id)
    evidence = self.repository.evidence_for_candidate(candidate_id)
    input_json = canonical_review_input(candidate, evidence)
    input_hash = sha256(input_json.encode("utf-8")).hexdigest()
    completed = self.repository.find_completed_review_attempt(candidate_id, input_hash)
    if completed:
        return completed.result
    attempt = self.repository.begin_review_attempt_for_retry(candidate_id, input_hash)
    try:
        result = self.reviewer.review(input_json, timeout=self.model_timeout_seconds)
    except Exception as exc:
        self.repository.finish_review_attempt(attempt.id, "failed", error=safe_error(exc))
        return None
    self.repository.finish_review_attempt(attempt.id, "completed", result_json=result_json(result))
    return self._apply_review_result(candidate, evidence, result)


def retry_session(self, session_id: str) -> list[ReviewResult | None]:
    return [self.retry_candidate(item.id) for item in self.repository.pending_candidates_for_session(session_id)]
```

Add `retro review retry --candidate <id>` and `retro review retry --session <id>` as a required mutually exclusive pair. Failed attempts stay pending; only a later successful result may enter normal threshold/gate processing.

- [ ] **Step 8: Run review and lifecycle tests**

Run: `python -m pytest tests/test_agentretro_review.py -q`

Expected: type semantics, two-stage parsing, thresholds, every hard gate, auto acceptance, model failure/timeout, idempotent retry, manual actions, conflict, expiry, scope, archive, and audit tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 9: Mark covered OpenSpec tasks complete**

Change `3.1` through `3.9` to `[x]`; leave `3.10` and `3.11` open.

- [ ] **Step 10: Commit review and lifecycle behavior**

```bash
git add src/agent_retro tests/test_agentretro_review.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Accept retrospective knowledge only with evidence and gates"
```

---

### Task 5: Obsidian Projection, Managed Boundaries, and Rollback

**Files:**
- Create: `src/agent_retro/infrastructure/obsidian.py`
- Create: `src/agent_retro/application/sync.py`
- Modify: `src/agent_retro/infrastructure/sqlite_repository.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Test: `tests/test_agentretro_obsidian.py`

**Interfaces:**
- Produces: `ObsidianProjection`, `SyncPlan`, `SyncService.plan/apply/retry`, `ProjectionCoordinator.after_commit()`, and purge-aware backup enumeration/removal primitives.
- Consumes: active knowledge, audit, sync journal, settings vault/backup roots.
- Closes OpenSpec tasks: `4.1` through `4.6`; reconciliation/deep merge is Task 6, purge cleanup is Task 9, and scenario trace is Task 10.

- [ ] **Step 1: Write failing three-file and boundary tests**

```python
def test_rule_projects_to_rule_file(tmp_path, accepted_rule):
    vault = tmp_path / "vault"
    projection = ObsidianProjection(vault)
    plan = projection.plan("NPKI", [accepted_rule])
    assert tuple(write.target for write in plan.writes) == (
        vault / "项目" / "NPKI" / "AgentRetro" / "规则.md",
    )


def test_summary_update_preserves_unmanaged_bytes(tmp_path):
    target = tmp_path / "项目_NPKI.md"
    target.write_text("人工前言\n<!-- agentretro:summary:start project=NPKI -->\n旧摘要\n<!-- agentretro:summary:end -->\n人工结尾\n", encoding="utf-8")
    updated = replace_managed_block(target.read_bytes(), "NPKI", "新摘要")
    assert updated.startswith("人工前言\n".encode())
    assert updated.endswith("人工结尾\n".encode())


def test_committed_acceptance_attempts_one_projection(coordinator, repository, sync_service, accepted_rule):
    coordinator.after_commit("accept", accepted_rule.id, accepted_rule.project_id)
    assert sync_service.apply_calls == 1
    assert repository.projection_event_count(accepted_rule.project_id) == 1


def test_projection_failure_keeps_sqlite_and_marks_pending(coordinator, repository, sync_service, accepted_rule):
    sync_service.error = OSError("vault unavailable")
    result = coordinator.after_commit("accept", accepted_rule.id, accepted_rule.project_id)
    assert repository.get_knowledge(accepted_rule.id).status == "active"
    assert result.status == ProjectionStatus.SYNC_PENDING
```

- [ ] **Step 2: Run Obsidian tests and verify missing adapter failure**

Run: `python -m pytest tests/test_agentretro_obsidian.py -q`

Expected: import fails for the missing projection adapter.

- [ ] **Step 3: Implement deterministic aggregate rendering**

Map `RULE` to `规则.md`, `LESSON` to `经验.md`, and `TASK_STATE` to `任务状态.md`. Sort active entries by stable ID and archived entries under `## 已归档`. Each entry contains its ID, scope, confidence, source references, version, updated time, and text. Rendering the same knowledge twice must produce identical bytes.

- [ ] **Step 4: Implement containment and managed markers**

Resolve every target and confirm it remains under the configured vault root. Reject path traversal and symlink escape. `replace_managed_block()` accepts exactly one start/end pair with the same project attribute and rejects missing, duplicate, nested, or mismatched markers. Only bytes between markers change.

- [ ] **Step 5: Implement journaled multi-file apply**

```python
@dataclass(frozen=True)
class PlannedWrite:
    target: Path
    before_hash: str
    after_bytes: bytes

@dataclass(frozen=True)
class SyncPlan:
    id: str
    project_id: str
    writes: tuple[PlannedWrite, ...]
    backup_dir: Path
```

`SyncService.apply()` verifies mapping, vault containment, marker validity, last managed/full hashes, and rollback state before the first write; copies every existing target into the run backup; creates the SQLite journal; writes same-directory temporary files; calls `os.replace`; reads back every target; and records post-hashes. Inject one replace failure after the first successful replacement and assert all targets restore exactly.

- [ ] **Step 6: Implement pending, retry, and rollback-required states**

An unavailable vault leaves knowledge accepted and marks the event/job `sync_pending`. `retro sync retry` rebuilds a fresh plan from current hashes. If restoration fails or a restored hash differs, mark `rollback_required`; `retro sync retry` must refuse until doctor/recovery clears it.

`ProjectionCoordinator.after_commit(cause, entity_id, project_id)` runs only after the SQLite transaction has committed. Derive the projection-event ID from project, cause, entity ID, and current eligible-knowledge hash; reuse the event on retries; and attempt exactly one batched projection before the command returns. Call it after automatic/manual acceptance, edit, reviewed vault adoption, conflict resolution, archive, and completed purge. A failure returns a warning and recovery command, never rolls back SQLite, and never reports the vault as current.

Append-only log records use the projection-event ID as their stable key. Rendering or retrying the same event must produce byte-identical aggregate files and no duplicate log line. Expose `enumerate_backups_containing(content_hash)` and `remove_confirmed_backup_copy(path, expected_hash)` for Task 9; ordinary successful sync never deletes a backup.

- [ ] **Step 7: Run Obsidian sync and failure-injection tests**

Run: `python -m pytest tests/test_agentretro_obsidian.py -q`

Expected: rendering, markers, byte preservation, containment, pre-hash, backup, successful apply, injected rollback, pending retry, and rollback blocking pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Mark covered OpenSpec tasks complete**

Change `4.1` through `4.6` to `[x]`; leave `4.7` through `4.11` open.

- [ ] **Step 9: Commit recoverable Obsidian projection**

```bash
git add src/agent_retro tests/test_agentretro_obsidian.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Project accepted knowledge into Obsidian without unsafe overwrite"
```

---

### Task 6: External-Edit Reconciliation and Controlled Deep Merge

**Files:**
- Create: `src/agent_retro/application/merge.py`
- Modify: `src/agent_retro/application/sync.py`
- Modify: `src/agent_retro/infrastructure/obsidian.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Test: `tests/test_agentretro_merge.py`

**Interfaces:**
- Produces: `MergePlan`, `MergeService.create_plan()`, `MergeService.apply()`, reconciliation actions `keep_database`, `adopt_vault`, and `manual_edit`.
- Consumes: journaled write protocol from Task 5.
- Closes OpenSpec tasks: `4.7`, `4.8`, `4.9` after reconciliation, stale-plan, exact-operation, and rollback-reuse tests pass.

- [ ] **Step 1: Write failing external-edit and stale-plan tests**

```python
def test_external_edit_blocks_sync(sync_service, synchronized_target):
    synchronized_target.write_text("手工修改", encoding="utf-8")
    result = sync_service.plan("NPKI")
    assert result.status == "external_edit_conflict"
    assert result.writes == ()


def test_stale_merge_plan_cannot_apply(merge_service, merge_plan):
    merge_plan.targets[0].path.write_text("newer user edit", encoding="utf-8")
    with pytest.raises(StalePlanError):
        merge_service.apply(merge_plan.id, confirmed=True)
```

- [ ] **Step 2: Run merge tests and verify missing service failure**

Run: `python -m pytest tests/test_agentretro_merge.py -q`

Expected: import fails for the missing merge service.

- [ ] **Step 3: Implement reconciliation without silent overwrite**

`adopt_vault` parses the changed managed entry and creates an `EDIT` candidate with source `obsidian-manual-edit`; it does not directly activate knowledge. After normal review accepts that candidate, Task 5's projection coordinator handles the resulting projection event. `keep_database` produces a replacement diff and requires confirmation before using Task 5's journaled apply. `manual_edit` leaves both versions unchanged and records the conflict as awaiting user input.

- [ ] **Step 4: Implement immutable merge plans**

```python
@dataclass(frozen=True)
class MergeTarget:
    path: Path
    input_hash: str
    output_bytes: bytes
    unified_diff: str

@dataclass(frozen=True)
class MergePlan:
    id: str
    project_id: str
    targets: tuple[MergeTarget, ...]
    deletes: tuple[Path, ...]
    renames: tuple[tuple[Path, Path], ...]
    conflicts: tuple[str, ...]
```

Persist the complete plan and hashes. Preview prints every target and unified diff. Apply verifies hashes, confirmation, and destructive-operation acknowledgements before delegating all writes to the journaled protocol.

- [ ] **Step 5: Enforce exact destructive confirmation**

General `--apply` authorizes content edits only. Each delete, rename, move, or unresolved conflict requires its exact operation ID in `--confirm-operation`. With any missing operation ID, apply returns exit code 2 and writes nothing.

- [ ] **Step 6: Run reconciliation and merge safety tests**

Run: `python -m pytest tests/test_agentretro_merge.py -q`

Expected: external edit detection, adopt-vault candidate, keep-database preview, stale plan, no-write preview, explicit apply, destructive confirmation, rollback reuse, and audit tests pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Mark covered OpenSpec tasks complete**

Change `4.7`, `4.8`, and `4.9` to `[x]`; leave `4.10` and `4.11` open.

- [ ] **Step 8: Commit controlled organization behavior**

```bash
git add src/agent_retro tests/test_agentretro_merge.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Require current confirmed plans for deep Obsidian merges"
```

---

### Task 7: Briefing, Doctor, and Previewed Codex Integration

**Files:**
- Create: `src/agent_retro/application/brief.py`
- Create: `src/agent_retro/application/doctor.py`
- Create: `src/agent_retro/infrastructure/codex_guidance.py`
- Modify: `src/agent_retro/application/bootstrap.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Modify: `src/agent_retro/presentation/output.py`
- Test: `tests/test_agentretro_briefing.py`
- Test: `tests/test_agentretro_codex_integration.py`

**Interfaces:**
- Produces: `BriefService.build()`, `DoctorService.run()`, `CodexGuidance.preview()`, `apply()`, `remove()`.
- Consumes: active knowledge queries, sync health, user-local settings, journaled file safety primitives.
- Closes OpenSpec tasks: `5.1` through `5.7`; scenario trace task `5.8` remains for Task 10.

- [ ] **Step 1: Write failing brief selection and budget tests**

```python
def test_brief_excludes_invalid_states(brief_service):
    result = brief_service.build(BriefRequest(task="review NPKI rollback", project_id="NPKI", max_tokens=6000))
    assert [item.status for item in result.items] == ["active", "active", "active"]
    assert all(item.status not in {"pending_review", "rejected", "conflicting", "archived", "stale"} for item in result.items)


def test_brief_reports_omitted_items(brief_service):
    result = brief_service.build(BriefRequest(task="NPKI", project_id="NPKI", max_tokens=100))
    assert result.estimated_tokens <= 100
    assert result.omitted_count > 0


def test_brief_is_deterministic_for_same_clock_and_inputs(brief_service):
    first = brief_service.build(BriefRequest(task="NPKI rollback", project_id="NPKI"))
    second = brief_service.build(BriefRequest(task="NPKI rollback", project_id="NPKI"))
    assert [item.id for item in first.items] == [item.id for item in second.items]


def test_rules_over_budget_fail_without_truncation(brief_service_with_large_rules):
    with pytest.raises(BriefBudgetError, match="规则"):
        brief_service_with_large_rules.build(BriefRequest(task="NPKI", project_id="NPKI", max_tokens=1))
```

- [ ] **Step 2: Implement deterministic local briefing and deadline**

Filter to active eligible knowledge, then use fixed category order: project `RULE`, explicitly global `RULE`, non-expired project `TASK_STATE`, relevant `LESSON`. Rules are mandatory; if their total exceeds the budget, raise `BriefBudgetError` without rendering a partial result. Include or omit every later item atomically.

```python
DEFAULT_RELEVANCE_WEIGHTS = {"keyword": 0.70, "recency": 0.20, "evidence": 0.10}


def tokenize(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    latin = re.findall(r"[a-z0-9]+", normalized)
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", normalized)
    return frozenset([*latin, *cjk])


def relevance_score(task: str, item: Knowledge, at: datetime) -> tuple[float, str]:
    task_tokens = tokenize(task)
    item_tokens = tokenize(item.text)
    overlap = len(task_tokens & item_tokens) / max(1, len(task_tokens | item_tokens))
    age_days = max(0.0, (at - item.updated_at).total_seconds() / 86400)
    recency = 1.0 / (1.0 + age_days / 30.0)
    evidence = min(1.0, len(item.evidence_ids) / 3.0)
    score = 0.70 * overlap + 0.20 * recency + 0.10 * evidence
    return (-score, item.id)


def estimate_tokens(value: str) -> int:
    return math.ceil(len(value.encode("utf-8")) / 3)
```

The stable ID is the final ascending tie-break. Use the injected monotonic clock and fail with `BriefTimeoutError` once the configurable default 5-second deadline is reached; never return partial success. Include evidence references, stale/conflict counts, `sync_pending` warnings, and reproducible omitted IDs/reasons. Render terminal, Markdown, and stable JSON from one `BriefResult` model without an LLM or vector call.

- [ ] **Step 3: Write failing Codex integration tests**

```python
def test_integration_preview_does_not_write(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    target = codex_home / "AGENTS.md"
    target.write_text("user rules\n", encoding="utf-8")
    integration = CodexGuidance(codex_home, tmp_path / "backups")
    preview = integration.preview()
    assert target.read_text(encoding="utf-8") == "user rules\n"
    assert "agentretro:codex:start" in preview.diff


def test_apply_preserves_outside_bytes(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    target = codex_home / "AGENTS.md"
    target.write_bytes(b"before\nafter\n")
    integration = CodexGuidance(codex_home, tmp_path / "backups")
    preview = integration.preview()
    integration.apply(preview.id)
    content = target.read_bytes()
    assert content.startswith(b"before\n")
    assert content.endswith(b"after\n")


def test_override_blocks_apply_and_remove(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "AGENTS.override.md").write_text("override", encoding="utf-8")
    integration = CodexGuidance(codex_home, tmp_path / "backups")
    with pytest.raises(GuidanceOverrideConflict):
        integration.apply(integration.preview().id)
    with pytest.raises(GuidanceOverrideConflict):
        integration.remove(integration.preview_remove().id)
```

- [ ] **Step 4: Implement preview/apply/remove**

Use one managed block:

```text
<!-- agentretro:codex:start version=1 -->
When a task depends on prior decisions, project history, user preferences, or current task state, run `retro brief` for that task and project. Do not scan the whole vault for self-contained tasks.
<!-- agentretro:codex:end -->
```

Resolve the target internally as `resolved_codex_home / "AGENTS.md"`; reject a target/symlink outside the effective home and never accept a target-path argument. Preview records missing-file creation or target hash, exact diff, and backup path without writing. Apply and remove require a current preview ID, refuse while `AGENTS.override.md` exists, back up an existing target, preserve all outside bytes plus encoding and newline convention, replace atomically, and read back. A manually changed managed block or target hash invalidates the operation. No force option exists.

Detect UTF-8 BOM, UTF-16 LE/BE BOM, strict UTF-8, then the active Windows preferred encoding; encode only the managed block with the detected codec and existing newline sequence. `discover_managed_instruction(codex_home)` is the non-writing smoke: it resolves the same canonical target, reads it, and returns true only for one exact managed block. It must never run Codex, scan memory, or touch any other file.

- [ ] **Step 5: Implement doctor checks**

Return ordered checks named `codex_source`, `safety_limits`, `database`, `migration`, `model`, `obsidian_root`, `project_mapping`, `backup_path`, `sync_recovery`, `purge_recovery`, `codex_integration`, `codex_override`, and `console_encoding`. Each check has `healthy`, `warning`, or `error`, a redacted summary, and one recovery command. Model output reports only configured or missing. `rollback_required`, `purge_incomplete`, and an override conflict are surfaced without sensitive content.

- [ ] **Step 6: Wire brief, doctor, and integrate commands**

Add `retro brief`, `retro doctor`, and `retro integrate codex` subcommands. `integrate codex` previews unless `--apply` or `--remove` is present. JSON mode prints no ANSI sequences.

- [ ] **Step 7: Run briefing, doctor, and integration tests**

Run: `python -m pytest tests/test_agentretro_briefing.py tests/test_agentretro_codex_integration.py -q`

Expected: deterministic selection, byte-budget, mandatory-rule overflow, local deadline, evidence, warning, output, doctor redaction, canonical target, missing-file preview, override refusal, preview, apply, stale hash, manual block edit, remove, encoding/newline/outside-byte preservation, discoverability smoke, and native-memory non-interference pass.

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 8: Mark covered OpenSpec tasks complete**

Change `5.1` through `5.7` to `[x]`; leave `5.8` open for Task 10.

- [ ] **Step 9: Commit task-scoped Codex context**

```bash
git add src/agent_retro tests/test_agentretro_briefing.py tests/test_agentretro_codex_integration.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Supply bounded reviewed context to later Codex tasks"
```

---

### Task 8: End-to-End, Security, Windows, and Legacy Regression Gate

**Files:**
- Create: `tests/test_agentretro_e2e.py`
- Create: `tests/test_agentretro_security.py`
- Create: `tests/test_agentretro_subprocess.py`
- Modify only if the failing regression proves necessary: `src/ai_todo_assistant/presentation/cli.py:1148`
- Modify: `README.md`
- Modify: `openspec/changes/add-agentretro-mvp/tasks.md`

**Interfaces:**
- Verifies all prior tasks as one product path.
- May add one encoding-only fallback to the existing CLI; no Todo/WorkItem logic change is allowed.
- Closes OpenSpec tasks: `6.1` through `6.4`; full scenario and completion gates remain for Task 10.

- [ ] **Step 1: Add a temporary end-to-end test**

Create a test that passes temporary `home`, `codex_home`, vault, database, backup, and canonical-guidance paths through dependency injection, writes one completed synthetic session, injects deterministic extraction/review gateways, runs capture, review, automatic acceptance, same-command three-file sync, and brief, then asserts the brief contains the accepted item and evidence ID. Do not read or hash real user paths from the test; structural isolation is proven by injecting only `tmp_path` roots and by asserting no path recorded in SQLite escapes them.

- [ ] **Step 2: Add secret leakage assertions**

Use a unique fixture value `TOKEN_FOR_REDACTION_TEST`. After capture, review, backup, sync, brief, and log creation, recursively inspect every temporary test state file as bytes and assert the fixture value is absent. Assert the redaction marker and source hashes remain present.

- [ ] **Step 3: Add Windows subprocess smoke tests**

Run the installed module entry under explicit `PYTHONIOENCODING=gbk:strict` and `PYTHONIOENCODING=utf-8:strict` for `retro --help`, a capture failure, review list, and empty brief. Assert exit codes are defined and stderr contains no `UnicodeEncodeError`.

Add a regression that invokes the existing non-interactive help path under GBK. If it fails, change only `_display_response()` so a caught `UnicodeEncodeError` retries with `safe_text(response, sys.stdout.encoding)`. Do not change command dispatch, help content, or Todo/WorkItem services.

- [ ] **Step 4: Document install, configuration, and safety boundaries**

Update `README.md` with the `retro` command list, `<user-home>/.agentretro/` state, model-config reuse, explicit capture, three Obsidian files, preview/apply behavior, `retro doctor`, and a warning that automated tests never use real user paths.

- [ ] **Step 5: Run targeted and full verification**

Run: `python -m pytest tests/test_agentretro_e2e.py tests/test_agentretro_security.py tests/test_agentretro_subprocess.py -q`

Expected: end-to-end, leakage, encoding, and legacy regression tests pass.

Run: `python -m pytest -q`

Expected: the complete existing and AgentRetro suite passes with zero failures.

Run: `openspec validate add-agentretro-mvp --strict`

Expected: `Change 'add-agentretro-mvp' is valid`.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 6: Run final scope and security self-review**

Confirm from `git diff --stat` and `git diff` that:

- no real credential or machine-specific absolute path entered the repository;
- existing Todo/WorkItem code changed only for the proven encoding fallback, if needed;
- no test writes outside temporary paths;
- no hidden hook, watcher, service, global guidance write, or native-memory write was introduced;
- every OpenSpec requirement has at least one passing scenario test.

- [ ] **Step 7: Mark covered OpenSpec tasks complete and commit**

Change `6.1` through `6.4` to `[x]`; leave `6.5` and `6.6` open. Commit the integration, security, Windows, and compatibility evidence:

```bash
git add README.md tests openspec/changes/add-agentretro-mvp/tasks.md src/ai_todo_assistant/presentation/cli.py
git commit -m "Prove AgentRetro is safe, reversible, and regression-free"
```

---

### Task 9: Explicit Sensitive-Data Purge With Residual Verification

**Files:**
- Create: `src/agent_retro/application/purge.py`
- Modify: `src/agent_retro/application/knowledge.py`
- Modify: `src/agent_retro/infrastructure/sqlite/repository.py`
- Modify: `src/agent_retro/infrastructure/obsidian/sync.py`
- Modify: `src/agent_retro/presentation/cli.py`
- Create: `tests/test_agentretro_purge.py`
- Modify: `openspec/changes/add-agentretro-mvp/tasks.md`

**Interfaces:**
- `PurgeService.plan(knowledge_id: str) -> PurgePlan` is read-only and returns one immutable operation per stored copy.
- `PurgeService.apply(plan_id: str, confirmed_operation_ids: frozenset[str], actor: str = "user") -> PurgeStatus` is the only destructive entry point.
- Ordinary archive/delete remains reversible; purge is reserved for explicit sensitive-data removal.
- Closes OpenSpec tasks: `3.10` and `4.10`.

- [ ] **Step 1: Write failing purge-plan tests**

Create a sensitive knowledge fixture whose unique marker is present in SQLite knowledge text, candidate excerpts, audit details, a managed Obsidian file, logs/traces, sync backups, migration backups, and merge backups. Assert `plan()`:

- does not change any byte or database row;
- enumerates every marker-bearing copy and only that knowledge's managed copies;
- reports redacted location labels rather than content;
- produces deterministic operation IDs for the same unchanged state;
- refuses a missing, already-purged, or currently `sync_pending` knowledge item with a typed error.

Operation IDs are `sha256(plan_id + location_kind + normalized_location + expected_hash)`; `expected_hash` is captured during planning so stale state invalidates apply.

- [ ] **Step 2: Write failing all-or-nothing confirmation tests**

```python
def test_apply_requires_confirmation_for_every_operation(purge_fixture):
    plan = purge_fixture.service.plan(purge_fixture.knowledge_id)
    before = purge_fixture.snapshot()
    with pytest.raises(IncompletePurgeConfirmation):
        purge_fixture.service.apply(plan.id, frozenset(op.id for op in plan.operations[:-1]))
    assert purge_fixture.snapshot() == before


def test_success_removes_all_sensitive_copies_and_leaves_content_free_tombstone(purge_fixture):
    plan = purge_fixture.service.plan(purge_fixture.knowledge_id)
    status = purge_fixture.service.apply(plan.id, frozenset(op.id for op in plan.operations))
    assert status == PurgeStatus.PURGED
    purge_fixture.assert_marker_absent_everywhere()
    tombstone = purge_fixture.repository.get_purge_tombstone(purge_fixture.knowledge_id)
    assert tombstone.status == "purged"
    assert not hasattr(tombstone, "text")
    assert not hasattr(tombstone, "excerpt")
    assert not hasattr(tombstone, "summary")
    assert not hasattr(tombstone, "content_hash")
```

Also assert the tombstone records only opaque IDs, actor, time, operation count, status, and residual count. It must not retain reversible encodings, content-derived hashes, evidence excerpts, or original file names.

- [ ] **Step 3: Write failing interrupted-cleanup and projection-block tests**

Inject a failure after the first file cleanup. Assert the durable purge job becomes `purge_incomplete`, residual locations remain redacted, a success audit is absent, and both automatic and manual projection reject that knowledge until recovery finishes. A retry must resume from the journal and converge without recreating removed content.

Assert ordinary sync/migration backups for unrelated knowledge remain intact while every backup containing the sensitive marker is rewritten or removed and read back.

- [ ] **Step 4: Implement journaled purge planning and recovery**

`plan()` searches only the repository's registered database, managed vault paths, configured local logs/traces, and registered backup roots. It never follows arbitrary links or scans the whole user profile. Persist the plan, hashes, and operation status in `purge_jobs` / `purge_operations`, but persist no sensitive content in those rows.

`apply()` performs these phases:

1. Load the immutable plan and require exact confirmation of all pending operation IDs before writing.
2. Re-read every location and compare its expected hash; stale or newly discovered content invalidates the plan with no mutation.
3. Mark the knowledge `purge_in_progress`, which blocks projection and briefing.
4. Clean managed files/backups through temp-file + atomic replace and readback; remove marker-bearing log/trace records through their adapters.
5. In one SQLite transaction remove sensitive candidate, evidence excerpt, knowledge, review, conflict, audit-detail, and projection payload fields; retain only the content-free tombstone and purge journal.
6. Scan the registered locations again for residual copies. Mark `purged` only when none remain; otherwise mark `purge_incomplete` with redacted residual kinds and keep projection blocked.

The recovery method uses only the persisted operation journal. It must never restore a backup containing the purged marker. Purge audit messages contain operation kinds/counts and status only.

- [ ] **Step 5: Wire explicit CLI plan/apply/recover commands**

Add:

```text
retro knowledge purge <id> --plan
retro knowledge purge <id> --apply-plan <plan-id> --confirm-operation <id> ...
retro knowledge purge <id> --recover
```

No `--force`, wildcard confirmation, interactive default, or implicit purge is allowed. Text output and JSON output must not include sensitive values or absolute user paths.

- [ ] **Step 6: Run purge and full regression tests**

Run: `python -m pytest tests/test_agentretro_purge.py -q`

Expected: planning, exact confirmation, stale-plan refusal, content-free tombstone, interrupted cleanup, recovery, projection block, residual verification, and backup-retention tests pass.

Run: `python -m pytest -q`

Expected: the full existing and AgentRetro suite passes.

- [ ] **Step 7: Mark covered OpenSpec tasks complete and commit**

Change `3.10` and `4.10` to `[x]`, then commit only the purge implementation and its evidence:

```bash
git add src/agent_retro tests/test_agentretro_purge.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Remove sensitive retrospective data with explicit proof"
```

---

### Task 10: Complete Scenario Traceability and Release Verification

**Files:**
- Create: `tests/agentretro_scenarios.py`
- Create: `tests/test_agentretro_scenario_coverage.py`
- Modify: `README.md`
- Modify: `openspec/changes/add-agentretro-mvp/tasks.md`

**Interfaces:**
- `SCENARIO_TESTS: dict[str, tuple[str, ...]]` is the executable mapping from every OpenSpec scenario ID to one or more pytest node IDs.
- No OpenSpec task is complete unless its behavior is both implemented and represented in this mapping.
- Closes OpenSpec tasks: `2.10`, `3.11`, `4.11`, `5.8`, `6.5`, and `6.6`.

- [ ] **Step 1: Create the failing 98-scenario coverage gate**

Parse `openspec/changes/add-agentretro-mvp/specs/**/spec.md` for scenario IDs `CR-01..CR-22`, `KR-01..KR-24`, `OS-01..OS-24`, and `BR-01..BR-28`. Assert:

```python
assert discovered == set(SCENARIO_TESTS)
assert len(discovered) == 98
assert all(node_ids for node_ids in SCENARIO_TESTS.values())
```

Resolve every mapped node ID through `pytest --collect-only -q` and fail when a referenced module, class, parameter, or test name is missing. Do not accept broad module-only mappings or placeholder test names.

- [ ] **Step 2: Populate the scenario-to-test mapping**

Map each ID to the narrowest existing test node. Add or tighten tests only where the mapping exposes a genuine scenario gap. One test may cover multiple scenarios when its assertions prove each behavior; one scenario may map to multiple tests when it crosses adapters. Keep scenario IDs in this dedicated registry rather than duplicating them in production code.

- [ ] **Step 3: Add release-boundary documentation**

Document that the MVP is local and explicit: capture is invoked by the user; accepted knowledge synchronizes in the same command; real vault/global guidance changes require preview plus explicit apply; deep merge and sensitive purge require exact confirmation; automated tests inject temporary paths; Codex native memory is neither read nor written.

- [ ] **Step 4: Run the executable coverage and Windows smoke gates**

Run:

```bash
python -m pytest tests/test_agentretro_scenario_coverage.py -q
python -m pytest tests/test_agentretro_subprocess.py -q
python -m pytest -q
openspec validate add-agentretro-mvp --strict
git diff --check
```

Expected: all 98 scenarios are discovered and mapped to collected tests; GBK and UTF-8 subprocess cases pass; the full suite is green; strict OpenSpec validation succeeds; diff check is clean.

- [ ] **Step 5: Perform final scope and artifact review**

Read `git diff develop...HEAD` plus the remaining working-tree diff. Confirm:

- production code is confined to `src/agent_retro` except a test-proven encoding-only legacy fallback;
- no machine-specific path, credential, secret fixture, or real user content is present;
- no hidden watcher, hook, daemon, vector store, native-memory adapter, or external write exists;
- every configured filesystem target is contained under an injected/configured root;
- every completed OpenSpec task has executable evidence and every one of the 98 scenarios is mapped.

- [ ] **Step 6: Mark all remaining OpenSpec tasks complete and commit**

After the gates pass, change `2.10`, `3.11`, `4.11`, `5.8`, `6.5`, and `6.6` to `[x]`. Confirm all 52 task boxes are checked, rerun strict validation, then commit:

```bash
git add README.md tests/agentretro_scenarios.py tests/test_agentretro_scenario_coverage.py openspec/changes/add-agentretro-mvp/tasks.md
git commit -m "Close AgentRetro MVP with executable scenario evidence"
```

---

## Requirement Coverage Map

| Capability | Requirements | Implementing tasks |
|---|---|---|
| `codex-session-retrospective` | explicit completed capture, real source, limits, idempotency, normalization, persistent project routing, reclassification, minimal redacted evidence | Tasks 1-3, 8, 10 |
| `retrospective-knowledge-review` | three types, separate review attempts/retry, thresholds/gates, automatic decision, manual actions, conflicts, scope/expiry/archive, explicit sensitive purge, audit | Tasks 2, 4, 8-10 |
| `obsidian-knowledge-sync` | same-command three-file projection, managed boundaries, journal/rollback, recovery, external edits, controlled deep merge, backup retention and purge | Tasks 2, 5-6, 8-10 |
| `retrospective-briefing` | independent CLI, bounded model config, accepted-only deterministic brief, exact token budget, previewed Codex integration, progressive loading, doctor | Tasks 1, 7-8, 10 |
| `release-evidence` | real-path isolation, redaction, Windows GBK/UTF-8 smoke, legacy regression, strict validation, all 98 OpenSpec scenarios | Tasks 8, 10 |

## Final Verification Commands

```bash
python -m pytest tests/test_agentretro_scenario_coverage.py -q
python -m pytest tests/test_agentretro_subprocess.py -q
python -m pytest -q
openspec validate add-agentretro-mvp --strict
git diff --check
git status --short
```

All six commands must complete successfully or the implementation remains incomplete. The final readback must also show all 52 OpenSpec task boxes checked and all 98 scenario IDs mapped to collected tests.
