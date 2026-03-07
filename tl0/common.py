"""Shared utilities for the tl0 task system."""

import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

from tl0.config import load_config, resolve_tasks_dir, resolve_project_name

# Load config once at import time (modules cache this)
_config = load_config()

TASKS_DIR = resolve_tasks_dir(_config)
TASKS_FOLDER = TASKS_DIR / "tasks"
TRANSCRIPTS_FOLDER = TASKS_DIR / "transcripts"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

VALID_STATUSES = {"pending", "claimed", "done", "failed"}
VALID_MODELS = set(_config.get("valid_models", ["opus", "sonnet", "haiku"]))

REQUIRED_FIELDS = {
    "id", "title", "description", "blocked_by", "tags", "events"
}

OPTIONAL_FIELDS = {
    "model", "thinking",
    "design_references", "produces", "context_files",
    "result", "created_by", "merge_sha",
    "failure_reason",
}

ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

VALID_EVENT_TYPES = {"created", "claimed", "freed", "done", "failed"}


# ---------------------------------------------------------------------------
# Status derivation (pure functions over events)
# ---------------------------------------------------------------------------

def task_status(task: dict) -> str:
    """Derive status from the task's event log. Returns 'pending', 'claimed', 'done', or 'failed'.

    The 'created' event is skipped — only lifecycle events determine status.
    """
    for event in reversed(task.get("events", [])):
        if event["type"] == "claimed":
            return "claimed"
        if event["type"] == "done":
            return "done"
        if event["type"] == "failed":
            return "failed"
        if event["type"] == "freed":
            return "pending"
        # skip "created"
    return "pending"


def task_claimed_by(task: dict) -> str | None:
    """Return the agent from the most recent claimed event, or None if not currently claimed."""
    if task_status(task) != "claimed":
        return None
    for event in reversed(task.get("events", [])):
        if event["type"] == "claimed":
            return event.get("by")
    return None


def task_last_claimed_at(task: dict) -> str | None:
    """Return the timestamp of the most recent claimed event, or None."""
    for event in reversed(task.get("events", [])):
        if event["type"] == "claimed":
            return event["at"]
    return None


def task_completed_at(task: dict) -> str | None:
    """Return the timestamp of the done event, or None."""
    for event in reversed(task.get("events", [])):
        if event["type"] == "done":
            return event["at"]
    return None


def task_created_at(task: dict) -> str | None:
    """Return the timestamp of the 'created' event (first event), or None."""
    events = task.get("events", [])
    if events and events[0]["type"] == "created":
        return events[0]["at"]
    return None


def task_updated_at(task: dict) -> str | None:
    """Return the timestamp of the last event."""
    events = task.get("events", [])
    return events[-1]["at"] if events else None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_task_shape(task: dict) -> list[str]:
    """Validate a task dict against the expected schema. Returns list of error strings."""
    errors = []

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in task:
            errors.append(f"Missing required field: '{field}'")

    # No unexpected fields
    for key in task:
        if key not in ALL_FIELDS:
            errors.append(f"Unexpected field: '{key}'")

    # Type checks
    if "id" in task and not isinstance(task["id"], str):
        errors.append(f"'id' must be a string, got {type(task['id']).__name__}")
    if "title" in task:
        if not isinstance(task["title"], str):
            errors.append(f"'title' must be a string, got {type(task['title']).__name__}")
        elif len(task["title"]) == 0:
            errors.append("'title' must not be empty")
        elif len(task["title"]) > 200:
            errors.append(f"'title' exceeds 200 chars ({len(task['title'])})")
    if "description" in task:
        if not isinstance(task["description"], str):
            errors.append(f"'description' must be a string, got {type(task['description']).__name__}")
        elif len(task["description"]) == 0:
            errors.append("'description' must not be empty")
    if "model" in task and task["model"] is not None and VALID_MODELS and task["model"] not in VALID_MODELS:
        errors.append(f"'model' must be one of {sorted(VALID_MODELS)}, got '{task['model']}'")
    if "thinking" in task and task["thinking"] is not None and not isinstance(task["thinking"], bool):
        errors.append(f"'thinking' must be a boolean, got {type(task['thinking']).__name__}")

    # events array
    if "events" in task:
        if not isinstance(task["events"], list):
            errors.append(f"'events' must be an array, got {type(task['events']).__name__}")
        else:
            for i, event in enumerate(task["events"]):
                if not isinstance(event, dict):
                    errors.append(f"'events[{i}]' must be an object")
                    continue
                if "type" not in event:
                    errors.append(f"'events[{i}]' missing required 'type' field")
                elif event["type"] not in VALID_EVENT_TYPES:
                    errors.append(f"'events[{i}].type' must be one of {sorted(VALID_EVENT_TYPES)}, got '{event['type']}'")
                if "at" not in event:
                    errors.append(f"'events[{i}]' missing required 'at' field")
                for key in event:
                    if key not in ("type", "at", "by"):
                        errors.append(f"'events[{i}]' has unexpected field '{key}'")

    # Array fields
    for field in ("blocked_by", "tags", "produces", "context_files"):
        if field in task:
            if not isinstance(task[field], list):
                errors.append(f"'{field}' must be an array, got {type(task[field]).__name__}")
            elif not all(isinstance(x, str) for x in task[field]):
                errors.append(f"'{field}' must contain only strings")

    # Nullable string fields
    for field in ("result", "created_by", "merge_sha", "failure_reason"):
        if field in task and task[field] is not None and not isinstance(task[field], str):
            errors.append(f"'{field}' must be a string or null, got {type(task[field]).__name__}")

    # design_references structure
    if "design_references" in task:
        if not isinstance(task["design_references"], list):
            errors.append("'design_references' must be an array")
        else:
            for i, ref in enumerate(task["design_references"]):
                if not isinstance(ref, dict):
                    errors.append(f"'design_references[{i}]' must be an object")
                elif "file" not in ref:
                    errors.append(f"'design_references[{i}]' missing required 'file' field")

    # Consistency checks (derived from events)
    if "events" in task and isinstance(task["events"], list):
        if task_status(task) == "done" and not task.get("result"):
            errors.append("Last event is 'done' but 'result' is not set")
        if task_status(task) == "failed" and not task.get("failure_reason"):
            errors.append("Last event is 'failed' but 'failure_reason' is not set")

    return errors


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def resolve_prefix(prefix: str, tasks: list[dict] | None = None) -> dict:
    """Resolve a UUID prefix to a single task. Exits on no match or ambiguity."""
    if tasks is None:
        tasks = load_all_tasks()
    matches = [t for t in tasks if t["id"].startswith(prefix)]
    if not matches:
        print(f"Error: no task matching '{prefix}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Error: ambiguous prefix '{prefix}' matches {len(matches)} tasks:", file=sys.stderr)
        for m in matches:
            print(f"  {m['id']}  {m['title']}", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def load_task(task_id: str) -> dict:
    """Load a task by exact UUID or prefix match."""
    # Try exact match first (fast path)
    path = TASKS_FOLDER / f"{task_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    # Fall back to prefix match
    return resolve_prefix(task_id)


def save_task(task: dict):
    """Write a task to disk after validation."""
    errors = validate_task_shape(task)
    if errors:
        print(f"Task validation failed ({task.get('id', '?')}):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)
    path = TASKS_FOLDER / f"{task['id']}.json"
    with open(path, "w") as f:
        json.dump(task, f, indent=2)
        f.write("\n")


def load_all_tasks() -> list[dict]:
    """Load all tasks from the tasks directory."""
    tasks = []
    if not TASKS_FOLDER.exists():
        return tasks
    for p in TASKS_FOLDER.glob("*.json"):
        with open(p) as f:
            tasks.append(json.load(f))
    return tasks


def now_iso() -> str:
    """Current time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def git_commit(message: str):
    """Stage all changes and commit in the tasks repo."""
    subprocess.run(
        ["git", "add", "."],
        cwd=TASKS_DIR,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=TASKS_DIR,
        capture_output=True,
    )


def task_status_map(tasks: list[dict]) -> dict[str, str]:
    """Build a map of task_id -> derived status."""
    return {t["id"]: task_status(t) for t in tasks}
