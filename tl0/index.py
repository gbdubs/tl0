"""SQLite index layer for fast task and transcript queries.

The index is a disposable cache — JSON files remain the source of truth.
Delete TASKS_DIR/.cache/index.db and it rebuilds automatically on next access.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

from tl0.common import (
    task_status, task_claimed_by, task_last_claimed_at,
    task_completed_at, task_created_at, task_updated_at,
)

# Minimum seconds between automatic full syncs on the read path.
_SYNC_THROTTLE_SECS = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    title          TEXT,
    description    TEXT,
    status         TEXT NOT NULL,
    model          TEXT,
    thinking       INTEGER,
    created_by     TEXT,
    merge_sha      TEXT,
    result         TEXT,
    failure_reason TEXT,
    claimed_by     TEXT,
    created_at     TEXT,
    claimed_at     TEXT,
    completed_at   TEXT,
    updated_at     TEXT,
    blocked_by     TEXT,
    tags           TEXT,
    task_json      TEXT NOT NULL,
    file_mtime     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_by ON tasks(created_by);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

CREATE TABLE IF NOT EXISTS transcript_summaries (
    task_id        TEXT NOT NULL,
    filename       TEXT NOT NULL,
    num_events     INTEGER,
    num_turns      INTEGER,
    duration_ms    INTEGER,
    cost_usd       REAL,
    model          TEXT,
    tool_errors    INTEGER,
    result_preview TEXT,
    file_mtime     REAL NOT NULL,
    PRIMARY KEY (task_id, filename)
);

CREATE TABLE IF NOT EXISTS tool_usage (
    task_id    TEXT NOT NULL,
    filename   TEXT NOT NULL,
    tool_name  TEXT NOT NULL,
    count      INTEGER NOT NULL,
    PRIMARY KEY (task_id, filename, tool_name)
);
"""


class Index:
    def __init__(self, tasks_dir: Path):
        self._tasks_dir = tasks_dir
        self._tasks_folder = tasks_dir / "tasks"
        self._transcripts_folder = tasks_dir / "transcripts"
        cache_dir = tasks_dir / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Ensure .cache/ is gitignored in the tasks repo
        gitignore = tasks_dir / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            if ".cache/" not in content:
                with open(gitignore, "a") as f:
                    f.write("\n.cache/\n")
        else:
            gitignore.write_text(".cache/\n")
        self._db_path = cache_dir / "index.db"
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._last_task_sync: float = 0.0
        self._last_transcript_sync: float = 0.0
        # Initial sync so the DB is warm on first query.
        self.sync_tasks()
        self.sync_transcripts()

    # ------------------------------------------------------------------
    # Sync: mtime-based incremental refresh
    # ------------------------------------------------------------------

    def rebuild(self):
        """Full rebuild from disk."""
        self._conn.execute("DELETE FROM tasks")
        self._conn.execute("DELETE FROM transcript_summaries")
        self._conn.execute("DELETE FROM tool_usage")
        self._conn.commit()
        self.sync_tasks(force=True)
        self.sync_transcripts(force=True)

    def sync_tasks(self, *, force: bool = False):
        """Sync tasks table with JSON files on disk (mtime-based)."""
        if not force:
            now = time.monotonic()
            if now - self._last_task_sync < _SYNC_THROTTLE_SECS:
                return
        if not self._tasks_folder.exists():
            return

        # Current mtimes from DB
        stored = {}
        for row in self._conn.execute("SELECT id, file_mtime FROM tasks"):
            stored[row[0]] = row[1]

        # Disk state
        disk_ids = set()
        for p in self._tasks_folder.glob("*.json"):
            task_id = p.stem
            disk_ids.add(task_id)
            mtime = os.path.getmtime(p)
            if task_id in stored and stored[task_id] == mtime:
                continue
            # Read and upsert
            try:
                with open(p) as f:
                    task = json.load(f)
                self._upsert_task(task, mtime)
            except (json.JSONDecodeError, OSError):
                continue

        # Remove deleted tasks
        removed = set(stored.keys()) - disk_ids
        if removed:
            self._conn.executemany(
                "DELETE FROM tasks WHERE id = ?",
                [(tid,) for tid in removed],
            )

        self._conn.commit()
        self._last_task_sync = time.monotonic()

    def sync_transcripts(self, *, force: bool = False):
        """Sync transcript_summaries with JSONL files on disk."""
        if not force:
            now = time.monotonic()
            if now - self._last_transcript_sync < _SYNC_THROTTLE_SECS:
                return
        if not self._transcripts_folder.exists():
            return

        stored = {}
        for row in self._conn.execute(
            "SELECT task_id, filename, file_mtime FROM transcript_summaries"
        ):
            stored[(row[0], row[1])] = row[2]

        disk_keys = set()
        for task_dir in self._transcripts_folder.iterdir():
            if not task_dir.is_dir():
                continue
            task_id = task_dir.name
            for jf in task_dir.glob("*.jsonl"):
                key = (task_id, jf.name)
                disk_keys.add(key)
                mtime = os.path.getmtime(jf)
                if key in stored and stored[key] == mtime:
                    continue
                try:
                    self._upsert_transcript(task_id, jf, mtime)
                except OSError:
                    continue

        removed = set(stored.keys()) - disk_keys
        if removed:
            for task_id, filename in removed:
                self._conn.execute(
                    "DELETE FROM transcript_summaries WHERE task_id = ? AND filename = ?",
                    (task_id, filename),
                )
                self._conn.execute(
                    "DELETE FROM tool_usage WHERE task_id = ? AND filename = ?",
                    (task_id, filename),
                )

        self._conn.commit()
        self._last_transcript_sync = time.monotonic()

    # ------------------------------------------------------------------
    # Notify: fast single-item updates (called from write path)
    # ------------------------------------------------------------------

    def notify_task_changed(self, task_id: str):
        """Re-index a single task from its JSON file."""
        p = self._tasks_folder / f"{task_id}.json"
        if not p.exists():
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._conn.commit()
            return
        try:
            mtime = os.path.getmtime(p)
            with open(p) as f:
                task = json.load(f)
            self._upsert_task(task, mtime)
            self._conn.commit()
        except (json.JSONDecodeError, OSError):
            pass

    def notify_transcript_written(self, task_id: str, filename: str):
        """Re-index a single transcript JSONL file."""
        p = self._transcripts_folder / task_id / filename
        if not p.exists():
            return
        try:
            mtime = os.path.getmtime(p)
            self._upsert_transcript(task_id, p, mtime)
            self._conn.commit()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all_tasks(self) -> list[dict]:
        """Return all tasks with transcript summaries from the index.

        Relies on notify_task_changed() / notify_transcript_written() for
        incremental freshness, with a throttled full sync as safety net.
        """
        self.sync_tasks()          # throttled — no-op unless stale
        self.sync_transcripts()    # throttled — no-op unless stale
        rows = self._conn.execute(
            "SELECT task_json, status, claimed_by, claimed_at, completed_at, "
            "created_at, updated_at, created_by, id FROM tasks"
        ).fetchall()

        # Build created_by -> [child_ids] map
        children: dict[str, list[str]] = {}
        for row in rows:
            created_by = row[7]
            task_id = row[8]
            if created_by:
                children.setdefault(created_by, []).append(task_id)

        # Build transcript summaries from DB (no filesystem sync)
        tx_summaries = self._build_transcript_summaries_from_db()

        tasks = []
        for row in rows:
            t = json.loads(row[0])
            t["status"] = row[1]
            t["claimed_by"] = row[2]
            t["claimed_at"] = row[3]
            t["completed_at"] = row[4]
            t["created_at"] = row[5]
            t["updated_at"] = row[6]
            t["parent_task"] = t.get("created_by")
            t["source"] = t.get("created_by") or "human"
            t["tasks_created"] = children.get(t["id"], [])
            t["transcript"] = tx_summaries.get(t["id"])
            tasks.append(t)

        return tasks

    def _build_transcript_summaries_from_db(self, task_id: str | None = None) -> dict:
        """Build transcript summaries from DB without filesystem sync.

        If *task_id* is given, only that task's data is queried (much faster).
        """
        if task_id is not None:
            rows = self._conn.execute(
                "SELECT task_id, filename, num_events, num_turns, duration_ms, "
                "cost_usd, model, tool_errors, result_preview FROM transcript_summaries "
                "WHERE task_id = ?", (task_id,)
            ).fetchall()
            tool_rows = self._conn.execute(
                "SELECT task_id, filename, tool_name, count FROM tool_usage "
                "WHERE task_id = ?", (task_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT task_id, filename, num_events, num_turns, duration_ms, "
                "cost_usd, model, tool_errors, result_preview FROM transcript_summaries"
            ).fetchall()
            tool_rows = self._conn.execute(
                "SELECT task_id, filename, tool_name, count FROM tool_usage"
            ).fetchall()

        # Build tool usage map: (task_id, filename) -> {tool: count}
        tool_map: dict[tuple[str, str], dict[str, int]] = {}
        for task_id, filename, tool_name, count in tool_rows:
            key = (task_id, filename)
            tool_map.setdefault(key, {})[tool_name] = count

        # Group by task_id
        by_task: dict[str, list] = {}
        for row in rows:
            task_id = row[0]
            by_task.setdefault(task_id, []).append(row)

        result = {}
        for task_id, task_rows in by_task.items():
            invocations = []
            total_cost = 0.0
            total_duration = 0
            merge_conflict_count = 0
            total_tool_errors = 0

            for row in task_rows:
                filename = row[1]
                inv = {"file": filename, "num_events": row[2] or 0}
                if row[3] is not None:
                    inv["num_turns"] = row[3]
                if row[4] is not None:
                    inv["duration_ms"] = row[4]
                    total_duration += row[4]
                if row[5] is not None:
                    inv["cost_usd"] = row[5]
                    total_cost += row[5]
                if row[6]:
                    inv["model"] = row[6]
                inv["tool_errors"] = row[7] or 0
                total_tool_errors += inv["tool_errors"]
                if row[8]:
                    inv["result_preview"] = row[8]

                tools = tool_map.get((task_id, filename))
                if tools:
                    inv["tool_usage"] = tools

                if "merge-conflict" in filename:
                    merge_conflict_count += 1

                invocations.append(inv)

            result[task_id] = {
                "has_transcript": True,
                "invocations": invocations,
                "total_cost_usd": total_cost,
                "total_duration_ms": total_duration,
                "merge_conflict_count": merge_conflict_count,
                "total_tool_errors": total_tool_errors,
            }

        return result

    def get_all_transcript_summaries(self) -> dict:
        """Return transcript summaries grouped by task_id.

        Uses throttled sync — relies on notify_transcript_written() for
        incremental freshness.
        """
        self.sync_transcripts()  # throttled

        result = self._build_transcript_summaries_from_db()

        # Add loop.log info (only needed for detailed transcript view)
        for task_id, summary in result.items():
            loop_log = self._transcripts_folder / task_id / "loop.log"
            has_loop_log = loop_log.exists()
            loop_log_lines = 0
            if has_loop_log:
                try:
                    loop_log_lines = len(loop_log.read_text().splitlines())
                except OSError:
                    pass
            summary["has_loop_log"] = has_loop_log
            summary["loop_log_lines"] = loop_log_lines

        return result

    def get_transcript_summary(self, task_id: str) -> dict:
        """Return transcript summary for a single task from the index DB.

        No filesystem sync — relies on notify_transcript_written() for
        freshness, with throttled full sync as safety net.
        """
        summary = self._build_transcript_summaries_from_db(task_id=task_id).get(
            task_id, {"has_transcript": False}
        )
        # Add loop.log info for single-task view
        loop_log = self._transcripts_folder / task_id / "loop.log"
        has_loop_log = loop_log.exists()
        loop_log_lines = 0
        if has_loop_log:
            try:
                loop_log_lines = len(loop_log.read_text().splitlines())
            except OSError:
                pass
        summary["has_loop_log"] = has_loop_log
        summary["loop_log_lines"] = loop_log_lines
        return summary

    def find_ready(self, model: str | None = None, tags: list[str] | None = None) -> list[dict]:
        """Find tasks that are pending with all blockers done."""
        self.sync_tasks()  # throttled

        # Get all pending tasks
        rows = self._conn.execute(
            "SELECT task_json, blocked_by FROM tasks WHERE status = 'pending'"
        ).fetchall()

        # Get status map for blocker checking
        status_map = dict(
            self._conn.execute("SELECT id, status FROM tasks").fetchall()
        )

        ready = []
        for task_json_str, blocked_by_str in rows:
            task = json.loads(task_json_str)
            blocked_by = json.loads(blocked_by_str) if blocked_by_str else []

            # All blockers must be done
            if not all(status_map.get(bid) == "done" for bid in blocked_by):
                continue

            # Apply filters
            if model and task.get("model") != model:
                continue
            if tags and not all(t in task.get("tags", []) for t in tags):
                continue

            ready.append(task)

        # Spread siblings apart: prefer tasks whose parent does NOT already
        # have a claimed (in-progress) task.  This reduces merge conflicts
        # when multiple workers poll at the same time.
        in_progress_parents: set[str] = set()
        for (cby,) in self._conn.execute(
            "SELECT created_by FROM tasks WHERE status = 'claimed' AND created_by IS NOT NULL"
        ).fetchall():
            in_progress_parents.add(cby)

        def _sort_key(t: dict) -> tuple:
            parent = t.get("created_by") or ""
            # 0 = no sibling in progress (preferred), 1 = sibling in progress
            sibling_running = 1 if parent in in_progress_parents else 0
            return (sibling_running, task_created_at(t) or "")

        ready.sort(key=_sort_key)
        return ready

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize(s):
        """Replace surrogate characters that SQLite's text binding can't handle."""
        if isinstance(s, str):
            return s.encode("utf-8", errors="replace").decode("utf-8")
        return s

    def _upsert_task(self, task: dict, mtime: float):
        """Insert or replace a task row from its parsed JSON."""
        _s = self._sanitize
        self._conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, title, description, status, model, thinking,
                created_by, merge_sha, result, failure_reason,
                claimed_by, created_at, claimed_at, completed_at, updated_at,
                blocked_by, tags, task_json, file_mtime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task["id"],
                _s(task.get("title")),
                _s(task.get("description")),
                task_status(task),
                task.get("model"),
                1 if task.get("thinking") else 0,
                task.get("created_by"),
                task.get("merge_sha"),
                _s(task.get("result")),
                _s(task.get("failure_reason")),
                task_claimed_by(task),
                task_created_at(task),
                task_last_claimed_at(task),
                task_completed_at(task),
                task_updated_at(task),
                json.dumps(task.get("blocked_by", [])),
                json.dumps(task.get("tags", [])),
                json.dumps(task, ensure_ascii=True),
                mtime,
            ),
        )

    def _upsert_transcript(self, task_id: str, filepath: Path, mtime: float):
        """Parse a JSONL transcript file and upsert summary + tool usage."""
        filename = filepath.name
        events = []
        for line in filepath.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        # Count tool usage and errors
        tool_counts: dict[str, int] = {}
        tool_error_count = 0
        for e in events:
            if e.get("type") == "assistant" and isinstance(
                e.get("message", {}).get("content"), list
            ):
                for block in e["message"]["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tool_counts[name] = tool_counts.get(name, 0) + 1
            elif e.get("type") == "user" and isinstance(
                e.get("message", {}).get("content"), list
            ):
                for block in e["message"]["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        if block.get("is_error"):
                            tool_error_count += 1

        # Extract result event data
        num_turns = None
        duration_ms = None
        cost_usd = None
        model = None
        result_preview = None

        for e in reversed(events):
            if e.get("type") == "result":
                num_turns = e.get("num_turns", 0)
                duration_ms = e.get("duration_ms", 0)
                cost_usd = e.get("total_cost_usd", 0)
                mu = e.get("modelUsage", {})
                if mu:
                    model = next(iter(mu), None)
                result = e.get("result", "")
                if isinstance(result, list):
                    result = " ".join(
                        b.get("text", "")
                        for b in result
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                if result:
                    result_preview = result[:200]
                break

        # Upsert summary
        self._conn.execute(
            """INSERT OR REPLACE INTO transcript_summaries
               (task_id, filename, num_events, num_turns, duration_ms,
                cost_usd, model, tool_errors, result_preview, file_mtime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id, filename, len(events), num_turns, duration_ms,
                cost_usd, model, tool_error_count, result_preview, mtime,
            ),
        )

        # Replace tool usage rows
        self._conn.execute(
            "DELETE FROM tool_usage WHERE task_id = ? AND filename = ?",
            (task_id, filename),
        )
        if tool_counts:
            self._conn.executemany(
                """INSERT INTO tool_usage (task_id, filename, tool_name, count)
                   VALUES (?, ?, ?, ?)""",
                [(task_id, filename, name, count) for name, count in tool_counts.items()],
            )
