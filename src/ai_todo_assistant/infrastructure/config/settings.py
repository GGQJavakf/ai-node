"""统一配置加载器。"""
import json
import os


DEFAULT_SETTINGS = {
    "auth_mode": "openai_api",
    "api_key": "",
    "api_base": "https://api.openai.com/v1/chat/completions",
    "model": "gpt-3.5-turbo",
    "codex_command": "codex",
    "codex_timeout": 120,
    "validation_retry_limit": 3,
}


def load_settings(project_root: str | None = None) -> dict:
    """
    加载 AI 配置。

    优先级固定为：默认值 < config/settings.json < 环境变量。
    这样 CLI、旧版 Agent 和后续 API 入口都能获得一致行为。
    """
    root = project_root or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    config_path = os.path.join(root, "config", "settings.json")
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
    config["codex_command"] = os.getenv("AI_CODEX_COMMAND", config["codex_command"])
    config["codex_timeout"] = int(os.getenv("AI_CODEX_TIMEOUT", config["codex_timeout"]))
    config["validation_retry_limit"] = int(
        os.getenv("AI_VALIDATION_RETRY_LIMIT", config["validation_retry_limit"])
    )
    return config


