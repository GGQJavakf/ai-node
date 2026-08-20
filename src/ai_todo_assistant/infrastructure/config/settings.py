"""统一配置加载器。"""
import json
import os
from pathlib import Path
from typing import Any, Literal


DEFAULT_CODEX_RESUME_TIMEOUT = 240
DEFAULT_SYNC_WATCH_INTERVAL_SECONDS = 1800
DEFAULT_SETTINGS = {
    "auth_mode": "openai_api",
    "api_key": "",
    "api_base": "https://api.openai.com/v1/chat/completions",
    "model": "gpt-3.5-turbo",
    "request_timeout": 45,
    "api_retry_limit": 2,
    "api_retry_backoff": 1.0,
    "codex_command": "codex",
    "codex_timeout": 120,
    "codex_request_timeout": 240,
    "codex_use_app_server": True,
    "codex_app_server_timeout": 240,
    "codex_app_server_start_timeout": 45,
    "codex_app_server_fallback_to_exec": True,
    "codex_home": "",
    "codex_source_home": "",
    "codex_retry_limit": 1,
    "codex_ignore_user_config": True,
    "codex_ignore_rules": True,
    "codex_resume_enabled": True,
    "codex_resume_timeout": DEFAULT_CODEX_RESUME_TIMEOUT,
    "codex_resume_exclusions_file": "data/codex-resume-exclusions.json",
    "validation_retry_limit": 3,
    "session_memory_limit": 20,
    "storage_backend": "sqlite",
    "sqlite_path": "data/todos.db",
    "todo_data_file": "todos.json",
    "workflow_data_file": "data/workflow.json",
    "codex_task_report_dir": "data/codex-task-reports",
    "sync_watch_interval_seconds": DEFAULT_SYNC_WATCH_INTERVAL_SECONDS,
    "auto_migrate_json": True,
}

LOCAL_SETTINGS_FILE = "settings.local.json"
LEGACY_SETTINGS_FILE = "settings.json"
SETTINGS_FILE_ENV = "AI_SETTINGS_FILE"
SettingsFailureReason = Literal[
    "path_empty",
    "path_not_absolute",
    "path_invalid",
    "file_missing",
    "path_not_file",
    "file_unreadable",
    "invalid_json",
    "non_object_json",
]


class SettingsConfigurationError(RuntimeError):
    """A sanitized, typed failure for a selected settings file."""

    def __init__(self, reason: SettingsFailureReason) -> None:
        self.reason = reason
        super().__init__(f"AI settings configuration failed ({reason}).")


def load_settings(project_root: str | None = None) -> dict:
    """
    加载 AI 配置。

    优先级固定为：默认值 < 配置文件 < 环境变量。
    AI_SETTINGS_FILE 可显式选择一个绝对路径，并且不回退到其他
    配置文件。源码检出中仍优先读取 config/settings.local.json；
    如果不存在，再兼容读取旧的 config/settings.json。
    这样 CLI、旧版 Agent 和后续 API 入口都能获得一致行为。
    """
    root, config_path, is_explicit = _resolve_settings_file(project_root)
    config: dict[str, Any] = DEFAULT_SETTINGS.copy()
    loaded_config = _read_settings_file(config_path, is_explicit=is_explicit)
    config.update({key: value for key, value in loaded_config.items() if value is not None})

    config["api_key"] = os.getenv("AI_API_KEY", config["api_key"])
    config["api_base"] = os.getenv("AI_API_BASE", config["api_base"])
    config["model"] = os.getenv("AI_MODEL", config["model"])
    config["auth_mode"] = os.getenv("AI_AUTH_MODE", config["auth_mode"])
    config["request_timeout"] = int(os.getenv("AI_REQUEST_TIMEOUT", config["request_timeout"]))
    config["api_retry_limit"] = int(os.getenv("AI_API_RETRY_LIMIT", config["api_retry_limit"]))
    config["api_retry_backoff"] = float(
        os.getenv("AI_API_RETRY_BACKOFF", config["api_retry_backoff"])
    )
    config["codex_command"] = os.getenv("AI_CODEX_COMMAND", config["codex_command"])
    config["codex_timeout"] = int(os.getenv("AI_CODEX_TIMEOUT", config["codex_timeout"]))
    config["codex_request_timeout"] = int(
        os.getenv("AI_CODEX_REQUEST_TIMEOUT", config["codex_request_timeout"])
    )
    config["codex_use_app_server"] = _as_bool(
        os.getenv("AI_CODEX_USE_APP_SERVER", config["codex_use_app_server"])
    )
    config["codex_app_server_timeout"] = int(
        os.getenv("AI_CODEX_APP_SERVER_TIMEOUT", config["codex_app_server_timeout"])
    )
    config["codex_app_server_start_timeout"] = int(
        os.getenv("AI_CODEX_APP_SERVER_START_TIMEOUT", config["codex_app_server_start_timeout"])
    )
    config["codex_app_server_fallback_to_exec"] = _as_bool(
        os.getenv(
            "AI_CODEX_APP_SERVER_FALLBACK_TO_EXEC",
            config["codex_app_server_fallback_to_exec"],
        )
    )
    config["codex_home"] = os.getenv("AI_CODEX_HOME", config["codex_home"])
    config["codex_source_home"] = os.getenv("AI_CODEX_SOURCE_HOME", config["codex_source_home"])
    config["codex_retry_limit"] = int(os.getenv("AI_CODEX_RETRY_LIMIT", config["codex_retry_limit"]))
    config["codex_ignore_user_config"] = _as_bool(
        os.getenv("AI_CODEX_IGNORE_USER_CONFIG", config["codex_ignore_user_config"])
    )
    config["codex_ignore_rules"] = _as_bool(
        os.getenv("AI_CODEX_IGNORE_RULES", config["codex_ignore_rules"])
    )
    config["codex_resume_enabled"] = _as_bool(
        os.getenv("AI_CODEX_RESUME_ENABLED", config["codex_resume_enabled"])
    )
    config["codex_resume_timeout"] = _as_positive_int(
        os.getenv("AI_CODEX_RESUME_TIMEOUT", config["codex_resume_timeout"]),
        DEFAULT_CODEX_RESUME_TIMEOUT,
    )
    config["codex_resume_exclusions_file"] = os.getenv(
        "AI_CODEX_RESUME_EXCLUSIONS_FILE", config["codex_resume_exclusions_file"]
    )
    config["validation_retry_limit"] = int(
        os.getenv("AI_VALIDATION_RETRY_LIMIT", config["validation_retry_limit"])
    )
    config["session_memory_limit"] = int(
        os.getenv("AI_SESSION_MEMORY_LIMIT", config["session_memory_limit"])
    )
    config["storage_backend"] = os.getenv("TODO_STORAGE_BACKEND", config["storage_backend"])
    config["sqlite_path"] = os.getenv("TODO_SQLITE_PATH", config["sqlite_path"])
    config["todo_data_file"] = os.getenv("TODO_DATA_FILE", config["todo_data_file"])
    config["workflow_data_file"] = os.getenv("WORKFLOW_DATA_FILE", config["workflow_data_file"])
    config["codex_task_report_dir"] = os.getenv(
        "AI_CODEX_TASK_REPORT_DIR", config["codex_task_report_dir"]
    )
    config["sync_watch_interval_seconds"] = _as_positive_int(
        os.getenv("AI_SYNC_WATCH_INTERVAL_SECONDS", config["sync_watch_interval_seconds"]),
        DEFAULT_SYNC_WATCH_INTERVAL_SECONDS,
    )
    config["auto_migrate_json"] = _as_bool(
        os.getenv("TODO_AUTO_MIGRATE_JSON", config["auto_migrate_json"])
    )
    config["project_root"] = root
    return config


def _resolve_settings_file(
    project_root: str | None,
) -> tuple[str | None, Path | None, bool]:
    explicit_raw = os.getenv(SETTINGS_FILE_ENV)
    if explicit_raw is not None:
        explicit_value = explicit_raw.strip()
        if not explicit_value:
            raise SettingsConfigurationError("path_empty")
        try:
            explicit_path = Path(explicit_value)
        except (OSError, RuntimeError, ValueError):
            raise SettingsConfigurationError("path_invalid") from None
        if not explicit_path.is_absolute():
            raise SettingsConfigurationError("path_not_absolute")
        try:
            normalized = explicit_path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            raise SettingsConfigurationError("path_invalid") from None
        return _root_for_explicit_settings(normalized), normalized, True

    root = _fallback_root(project_root)
    if root is None:
        return None, None, False
    config_dir = Path(root) / "config"
    local_path = config_dir / LOCAL_SETTINGS_FILE
    legacy_path = config_dir / LEGACY_SETTINGS_FILE
    return root, local_path if local_path.is_file() else legacy_path, False


def _read_settings_file(
    config_path: Path | None,
    *,
    is_explicit: bool,
) -> dict[str, object]:
    if config_path is None:
        return {}
    if is_explicit:
        try:
            if not config_path.exists():
                raise SettingsConfigurationError("file_missing")
            if not config_path.is_file():
                raise SettingsConfigurationError("path_not_file")
        except SettingsConfigurationError:
            raise
        except OSError:
            raise SettingsConfigurationError("file_unreadable") from None
    elif not config_path.is_file():
        return {}

    try:
        with config_path.open("r", encoding="utf-8") as settings_stream:
            loaded = json.load(settings_stream)
    except json.JSONDecodeError:
        raise SettingsConfigurationError("invalid_json") from None
    except (OSError, UnicodeError):
        raise SettingsConfigurationError("file_unreadable") from None
    if not isinstance(loaded, dict):
        raise SettingsConfigurationError("non_object_json")
    return loaded


def _fallback_root(project_root: str | None) -> str | None:
    if project_root:
        return str(Path(project_root).expanduser().resolve(strict=False))
    return _development_project_root()


def _development_project_root() -> str | None:
    """Return the checkout root only when this module is running from ``src``."""

    module_path = Path(__file__).resolve()
    try:
        candidate = module_path.parents[4]
    except IndexError:
        return None
    source_module = (
        candidate
        / "src"
        / "ai_todo_assistant"
        / "infrastructure"
        / "config"
        / "settings.py"
    )
    if source_module.resolve(strict=False) != module_path:
        return None
    return str(candidate)


def _root_for_explicit_settings(settings_path: Path) -> str:
    parent = settings_path.parent
    if parent.name.casefold() == "config":
        parent = parent.parent
    return str(parent)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


