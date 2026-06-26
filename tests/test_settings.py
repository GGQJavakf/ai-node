import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.config.settings import load_settings


class TestSettingsLoading(unittest.TestCase):
    def test_prefers_local_runtime_settings_over_legacy_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir()
            (config_dir / "settings.json").write_text(
                json.dumps({"model": "legacy-model", "api_key": "legacy-key"}),
                encoding="utf-8",
            )
            (config_dir / "settings.local.json").write_text(
                json.dumps({"model": "local-model", "api_key": "local-key"}),
                encoding="utf-8",
            )

            settings = load_settings(project_root=tmp)

            self.assertEqual(settings["model"], "local-model")
            self.assertEqual(settings["api_key"], "local-key")

    def test_falls_back_to_legacy_settings_when_local_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir()
            (config_dir / "settings.json").write_text(
                json.dumps({"model": "legacy-model"}),
                encoding="utf-8",
            )

            settings = load_settings(project_root=tmp)

            self.assertEqual(settings["model"], "legacy-model")

    def test_environment_overrides_local_runtime_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir()
            (config_dir / "settings.local.json").write_text(
                json.dumps({"model": "local-model"}),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"AI_MODEL": "env-model"}):
                settings = load_settings(project_root=tmp)

            self.assertEqual(settings["model"], "env-model")

    def test_codex_resume_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "AI_CODEX_RESUME_ENABLED": "false",
                    "AI_CODEX_RESUME_TIMEOUT": "12",
                    "AI_CODEX_RESUME_EXCLUSIONS_FILE": "tmp/exclusions.json",
                },
            ):
                settings = load_settings(project_root=tmp)

            self.assertFalse(settings["codex_resume_enabled"])
            self.assertEqual(settings["codex_resume_timeout"], 12)
            self.assertEqual(settings["codex_resume_exclusions_file"], "tmp/exclusions.json")


if __name__ == "__main__":
    unittest.main()
