import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _path  # noqa: F401
from agent_retro.infrastructure import legacy_model
from ai_todo_assistant.infrastructure.config.settings import (
    SettingsConfigurationError,
    load_settings,
)


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

    def test_explicit_settings_file_wins_and_sets_a_stable_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository_config = root / "repository" / "config"
            repository_config.mkdir(parents=True)
            (repository_config / "settings.local.json").write_text(
                json.dumps({"model": "repository-model"}),
                encoding="utf-8",
            )
            explicit_config = root / "runtime" / "config" / "selected.json"
            explicit_config.parent.mkdir(parents=True)
            explicit_config.write_text(
                json.dumps({"model": "explicit-model"}),
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {"AI_SETTINGS_FILE": str(explicit_config)},
                clear=True,
            ):
                settings = load_settings(project_root=str(root / "repository"))

            self.assertEqual(settings["model"], "explicit-model")
            self.assertEqual(settings["project_root"], str((root / "runtime").resolve()))

    def test_relative_explicit_settings_file_is_rejected_without_cwd_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "settings.local.json").write_text(
                json.dumps({"model": "cwd-poison"}),
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(
                    "os.environ",
                    {"AI_SETTINGS_FILE": "config/settings.local.json"},
                    clear=True,
                ):
                    with self.assertRaises(SettingsConfigurationError) as caught:
                        load_settings()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(caught.exception.reason, "path_not_absolute")

    def test_empty_explicit_settings_file_is_rejected(self):
        with patch.dict("os.environ", {"AI_SETTINGS_FILE": "  "}, clear=True):
            with self.assertRaises(SettingsConfigurationError) as caught:
                load_settings()

        self.assertEqual(caught.exception.reason, "path_empty")

    def test_home_relative_explicit_settings_file_is_rejected(self):
        with patch.dict(
            "os.environ", {"AI_SETTINGS_FILE": "~/settings.json"}, clear=True
        ):
            with self.assertRaises(SettingsConfigurationError) as caught:
                load_settings()

        self.assertEqual(caught.exception.reason, "path_not_absolute")

    def test_missing_explicit_settings_file_does_not_fall_back_to_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "settings.local.json").write_text(
                json.dumps({"model": "repository-model"}),
                encoding="utf-8",
            )
            missing = root / "outside" / "missing.json"

            with patch.dict(
                "os.environ",
                {"AI_SETTINGS_FILE": str(missing)},
                clear=True,
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    load_settings(project_root=tmp)

            self.assertEqual(caught.exception.reason, "file_missing")

    def test_explicit_settings_directory_is_not_accepted_as_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "settings"
            selected.mkdir()

            with patch.dict(
                "os.environ",
                {"AI_SETTINGS_FILE": str(selected)},
                clear=True,
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    load_settings()

            self.assertEqual(caught.exception.reason, "path_not_file")

    def test_unreadable_explicit_settings_file_is_a_typed_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "settings.json"
            selected.write_text("{}", encoding="utf-8")

            with (
                patch.dict(
                    "os.environ",
                    {"AI_SETTINGS_FILE": str(selected)},
                    clear=True,
                ),
                patch.object(Path, "open", side_effect=PermissionError("private path")),
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    load_settings()

            self.assertEqual(caught.exception.reason, "file_unreadable")
            self.assertNotIn("private path", str(caught.exception))

    def test_malformed_explicit_settings_json_is_a_typed_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "settings.json"
            selected.write_text('{"api_key":', encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"AI_SETTINGS_FILE": str(selected)},
                clear=True,
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    load_settings()

            self.assertEqual(caught.exception.reason, "invalid_json")

    def test_non_object_explicit_settings_json_is_a_typed_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected = Path(tmp) / "settings.json"
            selected.write_text('[{"model": "unsafe-fallback"}]', encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"AI_SETTINGS_FILE": str(selected)},
                clear=True,
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    load_settings()

            self.assertEqual(caught.exception.reason, "non_object_json")

    def test_invalid_explicit_file_blocks_api_key_and_model_client_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"

            with (
                patch.dict(
                    "os.environ",
                    {
                        "AI_SETTINGS_FILE": str(missing),
                        "AI_API_KEY": "route-secret-must-not-be-used",
                        "AI_API_BASE": "https://fallback.invalid/v1/chat/completions",
                    },
                    clear=True,
                ),
                patch.object(legacy_model, "build_llm_client") as client_builder,
            ):
                with self.assertRaises(SettingsConfigurationError) as caught:
                    legacy_model.build_retro_llm_client()

            client_builder.assert_not_called()
            self.assertEqual(caught.exception.reason, "file_missing")
            self.assertNotIn("route-secret-must-not-be-used", str(caught.exception))

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
