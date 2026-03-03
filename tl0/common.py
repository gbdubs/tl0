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
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

VALID_STATUSES = {"pending", "claimed", "in-progress", "done", "stuck"}
VALID_MODELS = set(_config.get("valid_models", ["opus", "sonnet", "haiku"]))

REQUIRED_FIELDS = {
    "id", "title", "description", "status", "created_at", "updated_at",
    "blocked_by", "tags"
}

OPTIONAL_FIELDS = {
    "model", "thinking",
    "claimed_by", "claimed_at", "completed_at", "design_references",
    "produces", "context_files", "result", "tasks_created", "parent_task"
}

ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


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
    if "status" in task and task["status"] not in VALID_STATUSES:
        errors.append(f"'status' must be one of {sorted(VALID_STATUSES)}, got '{task['status']}'")
    if "model" in task and task["model"] is not None and VALID_MODELS and task["model"] not in VALID_MODELS:
        errors.append(f"'model' must be one of {sorted(VALID_MODELS)}, got '{task['model']}'")
    if "thinking" in task and task["thinking"] is not None and not isinstance(task["thinking"], bool):
        errors.append(f"'thinking' must be a boolean, got {type(task['thinking']).__name__}")

    # Array fields
    for field in ("blocked_by", "tags", "produces", "context_files", "tasks_created"):
        if field in task:
            if not isinstance(task[field], list):
                errors.append(f"'{field}' must be an array, got {type(task[field]).__name__}")
            elif not all(isinstance(x, str) for x in task[field]):
                errors.append(f"'{field}' must contain only strings")

    # Nullable string fields
    for field in ("claimed_by", "claimed_at", "completed_at", "result", "parent_task"):
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

    # Consistency checks
    if task.get("status") in ("claimed", "in-progress") and not task.get("claimed_by"):
        errors.append(f"Status is '{task['status']}' but 'claimed_by' is not set")
    if task.get("status") == "done" and not task.get("result"):
        errors.append("Status is 'done' but 'result' is not set")

    return errors


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
    """Build a map of task_id -> status."""
    return {t["id"]: t["status"] for t in tasks}
