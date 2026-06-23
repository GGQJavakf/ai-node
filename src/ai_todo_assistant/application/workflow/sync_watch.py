"""Local scheduled trigger for the existing sync workflow."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterator


@dataclass(frozen=True)
class SyncWatchResult:
    run_number: int
    triggered_at: str
    sync_output: str
    next_action: str


class SyncWatchRunner:
    """Runs an existing sync callback on an interval and reports every trigger."""

    def __init__(
        self,
        sync_once: Callable[[str], str],
        recommend_next: Callable[[], str],
        now: Callable[[], object] | None = None,
        sleep: Callable[[int], None] | None = None,
    ):
        self.sync_once = sync_once
        self.recommend_next = recommend_next
        self.now = now or datetime.now
        self.sleep = sleep or time.sleep

    def run(self, interval_seconds: int, path: str, max_runs: int | None = None) -> Iterator[SyncWatchResult]:
        interval = max(1, int(interval_seconds))
        run_number = 0
        while True:
            run_number += 1
            yield SyncWatchResult(
                run_number=run_number,
                triggered_at=_format_moment(self.now()),
                sync_output=self.sync_once(path),
                next_action=self.recommend_next(),
            )
            if max_runs is not None and run_number >= max_runs:
                return
            self.sleep(interval)


def format_sync_watch_report(result: SyncWatchResult) -> str:
    return "\n".join(
        [
            f"Sync watch trigger #{result.run_number}",
            "─" * 80,
            f"  Triggered at: {result.triggered_at}",
            "",
            "Sync result:",
            result.sync_output,
            "",
            "Next recommended action:",
            result.next_action,
            "─" * 80,
        ]
    )


def _format_moment(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)
