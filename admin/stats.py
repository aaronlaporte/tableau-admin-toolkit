"""
JSON-file-backed run statistics tracker.

Records how many times each operation has been run, how many successes and
failures occurred, and provides summary/history queries.  The stats file
lives outside the repo at ``~/.tableau-admin/run_stats.json`` by default so
it is never accidentally committed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_STATS_PATH = Path.home() / ".tableau-admin" / "run_stats.json"


@dataclass
class RunRecord:
    """A single recorded run of an operation."""

    timestamp: str
    operation: str
    success: bool
    details: dict = field(default_factory=dict)


class StatsTracker:
    """
    Append-only run statistics backed by a JSON file.

    Usage::

        tracker = StatsTracker()
        tracker.record_run("batch_publish_workbooks", success=True)
        tracker.get_summary()
    """

    def __init__(self, stats_path: str | Path | None = None) -> None:
        self.path = Path(stats_path or _DEFAULT_STATS_PATH)
        self._ensure_file()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_run(
        self,
        operation: str,
        success: bool,
        details: dict | None = None,
    ) -> RunRecord:
        """Append a run record. ``success`` is True if the job completed without failures."""
        record = RunRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            operation=operation,
            success=success,
            details=details or {},
        )
        data = self._load()
        data["runs"].append(asdict(record))
        self._save(data)
        logger.info(
            "Recorded run: %s — %s",
            operation,
            "SUCCESS" if success else "FAILED",
        )
        return record

    def get_summary(self, operation: Optional[str] = None) -> dict:
        """
        Return aggregate stats.

        Keys: ``total_runs``, ``succeeded``, ``failed``,
        ``success_rate``, ``last_run``.
        """
        runs = self._filtered_runs(operation)
        succeeded = sum(1 for r in runs if r.get("success"))
        failed = sum(1 for r in runs if not r.get("success"))
        return {
            "operation": operation or "all",
            "total_runs": len(runs),
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(succeeded / len(runs), 4) if runs else 0.0,
            "last_run": runs[-1]["timestamp"] if runs else None,
        }

    def get_history(
        self,
        operation: Optional[str] = None,
        last_n: int = 50,
    ) -> list[dict]:
        """Return the most recent *last_n* run records."""
        runs = self._filtered_runs(operation)
        return runs[-last_n:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filtered_runs(self, operation: Optional[str]) -> list[dict]:
        data = self._load()
        runs = data.get("runs", [])
        if operation:
            runs = [r for r in runs if r.get("operation") == operation]
        return runs

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._save({"runs": []})
            logger.debug("Created stats file at %s", self.path)

    def _load(self) -> dict:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
