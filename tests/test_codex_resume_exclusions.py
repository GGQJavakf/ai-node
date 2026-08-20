import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.persistence.codex_resume_exclusions import JsonCodexResumeExclusionStore


class TestJsonCodexResumeExclusionStore(unittest.TestCase):
    def test_exclude_include_and_list_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "codex-resume-exclusions.json")
            store = JsonCodexResumeExclusionStore(path)

            excluded = store.exclude("thread-1", "等待人工确认")
            listed = store.list_exclusions()
            included = store.include("thread-1")

            self.assertEqual(excluded.thread_id, "thread-1")
            self.assertEqual(excluded.reason, "等待人工确认")
            self.assertEqual([item.thread_id for item in listed], ["thread-1"])
            self.assertTrue(included)
            self.assertEqual(store.list_exclusions(), [])

    def test_write_uses_replace_without_leaving_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "codex-resume-exclusions.json")
            store = JsonCodexResumeExclusionStore(path)

            store.exclude("thread-1")
            store.exclude("thread-2")

            self.assertTrue(os.path.exists(path))
            leftovers = [name for name in os.listdir(tmp) if name.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_invalid_schema_fails_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "codex-resume-exclusions.json")
            original = '{"exclusions": {"thread_id": "old"}}'
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original)
            store = JsonCodexResumeExclusionStore(path)

            with self.assertRaises(ValueError):
                store.exclude("thread-new")
            with self.assertRaises(ValueError):
                store.include("thread-old")

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)


if __name__ == "__main__":
    unittest.main()
