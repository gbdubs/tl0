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
              claimed_by=None, parent_task=None, result=None, tasks_created=None,
              **kwargs):
        import uuid
        tid = task_id or str(uuid.uuid4())
        now = now_iso()
        task = {
            "id": tid,
            "title": title,
            "description": description,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "blocked_by": blocked_by or [],
            "tags": tags or [],
            "model": model,
            "thinking": thinking,
            "claimed_by": claimed_by,
            "claimed_at": now if claimed_by else None,
            "completed_at": None,
            "design_references": [],
            "produces": [],
            "context_files": [],
            "result": result,
            "tasks_created": tasks_created or [],
            "parent_task": parent_task,
        }
        task.update(kwargs)
        path = tasks_dir / f"{tid}.json"
        with open(path, "w") as f:
            json.dump(task, f, indent=2)
            f.write("\n")
        return task

    return _make
