"""Shared test fixtures for tl0 tests."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def tasks_dir(tmp_path):
    """Create a temporary tasks directory and configure tl0 to use it."""
    tasks_folder = tmp_path / "tasks"
    tasks_folder.mkdir()

    # Initialize as a git repo so git_commit doesn't fail
    os.system(f"cd {tmp_path} && git init -q && git add . && git commit -q -m init --allow-empty")

    # Patch the module-level constants
    with patch("tl0.common.TASKS_DIR", tmp_path), \
         patch("tl0.common.TASKS_FOLDER", tasks_folder):
        yield tasks_folder


@pytest.fixture
def make_task(tasks_dir):
    """Factory to create a task JSON file in the temp tasks directory."""
    from tl0.common import now_iso

    def _make(title="Test task", description="A test task", status="pending",
              blocked_by=None, tags=None, task_id=None, model=None, thinking=None,
              claimed_by=None, created_by=None, result=None,
              events=None, **kwargs):
        import uuid
        tid = task_id or str(uuid.uuid4())
        now = now_iso()

        # Build events from shorthand args if events not provided explicitly
        if events is None:
            events = [{"type": "created", "at": now}]
            if status == "claimed" and claimed_by:
                events.append({"type": "claimed", "at": now, "by": claimed_by})
            elif status == "done":
                agent = claimed_by or "unknown"
                events.append({"type": "claimed", "at": now, "by": agent})
                events.append({"type": "done", "at": now, "by": agent})

        task = {
            "id": tid,
            "title": title,
            "description": description,
            "events": events,
            "blocked_by": blocked_by or [],
            "tags": tags or [],
            "model": model,
            "thinking": thinking,
            "result": result,
            "created_by": created_by,
        }
        task.update(kwargs)
        path = tasks_dir / f"{tid}.json"
        with open(path, "w") as f:
            json.dump(task, f, indent=2)
            f.write("\n")
        return task

    return _make
