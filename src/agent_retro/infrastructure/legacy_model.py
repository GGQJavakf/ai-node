"""Read-only adapter for the existing product's model client configuration."""

from ai_todo_assistant.infrastructure.config import load_settings
from ai_todo_assistant.infrastructure.llm import build_llm_client


MODEL_CONFIG_KEYS = (
    "auth_mode",
    "api_key",
    "api_base",
    "model",
    "request_timeout",
    "api_retry_limit",
    "api_retry_backoff",
    "codex_command",
    "codex_timeout",
    "codex_request_timeout",
    "codex_use_app_server",
    "codex_app_server_timeout",
    "codex_app_server_start_timeout",
    "codex_app_server_fallback_to_exec",
    "codex_retry_limit",
    "codex_ignore_user_config",
    "codex_ignore_rules",
)


def load_legacy_model_config(project_root: str | None = None) -> dict[str, object]:
    """Return a fresh allowlisted model configuration dictionary."""

    source = load_settings(project_root)
    return {key: source.get(key) for key in MODEL_CONFIG_KEYS}


def build_retro_llm_client(project_root: str | None = None):
    """Build the shared LLM client without exposing unrelated legacy settings."""

    return build_llm_client(load_legacy_model_config(project_root))


def build_retro_llm_client_from_config(config: dict[str, object]):
    """Build from one already-read config while reapplying the allowlist."""

    filtered = {key: config.get(key) for key in MODEL_CONFIG_KEYS}
    return build_llm_client(filtered)
