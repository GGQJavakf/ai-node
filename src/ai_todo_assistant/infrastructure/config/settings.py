"""统一配置加载器。"""
import json
import os


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
    "validation_retry_limit": 3,
    "session_memory_limit": 20,
    "storage_backend": "sqlite",
    "sqlite_path": "data/todos.db",
    "todo_data_file": "todos.json",
    "workflow_data_file": "data/workflow.json",
    "codex_task_report_dir": "data/codex-task-reports",
    "sync_watch_interval_seconds": 1800,
    "auto_migrate_json": True,
}

LOCAL_SETTINGS_FILE = "settings.local.json"
LEGACY_SETTINGS_FILE = "settings.json"


def load_settings(project_root: str | None = None) -> dict:
    """
    加载 AI 配置。

    优先级固定为：默认值 < 本地运行配置 < 环境变量。
    本地运行配置优先读取 config/settings.local.json；如果不存在，
    再兼容读取旧的 config/settings.json。
    这样 CLI、旧版 Agent 和后续 API 入口都能获得一致行为。
    """
    root = project_root or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    config_dir = os.path.join(root, "config")
    local_config_path = os.path.join(config_dir, LOCAL_SETTINGS_FILE)
    legacy_config_path = os.path.join(config_dir, LEGACY_SETTINGS_FILE)
    config_path = local_config_path if os.path.exists(local_config_path) else legacy_config_path
    config = DEFAULT_SETTINGS.copy()

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                config.update({k: v for k, v in loaded_config.items() if v is not None})
        except Exception as e:
            print(f"警告: 加载配置文件失败: {e}")

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
        DEFAULT_SETTINGS["sync_watch_interval_seconds"],
    )
    config["auto_migrate_json"] = _as_bool(
        os.getenv("TODO_AUTO_MIGRATE_JSON", config["auto_migrate_json"])
    )
    config["project_root"] = root
    return config


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


