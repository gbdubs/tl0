"""Tests for the full task lifecycle: create -> claim -> done."""

import json
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch

from tl0.common import load_all_tasks, load_task, save_task, task_status_map


class TestTaskLifecycle:
    def test_create_and_load(self, tasks_dir, make_task):
        task = make_task(title="Build widget", description="Build a widget component")
        loaded = load_task(task["id"])
        assert loaded["title"] == "Build widget"
        assert loaded["status"] == "pending"

    def test_save_validates(self, tasks_dir, make_task):
        task = make_task()
        task["status"] = "banana"
        with pytest.raises(SystemExit):
            save_task(task)

    def test_load_all_tasks(self, tasks_dir, make_task):
        make_task(title="Task 1")
        make_task(title="Task 2")
        make_task(title="Task 3")
        all_tasks = load_all_tasks()
        assert len(all_tasks) == 3

    def test_load_by_prefix(self, tasks_dir, make_task):
        task = make_task(task_id="abcdef01-0000-0000-0000-000000000001")
        loaded = load_task("abcdef01")
        assert loaded["id"] == task["id"]

    def test_claim_flow(self, tasks_dir, make_task):
        task = make_task(title="Claimable task")

        # Claim it
        from tl0.common import now_iso, git_commit
        task["status"] = "claimed"
        task["claimed_by"] = "test-agent"
        task["claimed_at"] = now_iso()
        task["updated_at"] = now_iso()
        save_task(task)

        loaded = load_task(task["id"])
        assert loaded["status"] == "claimed"
        assert loaded["claimed_by"] == "test-agent"

    def test_complete_flow(self, tasks_dir, make_task):
        task = make_task(title="Completable task", status="claimed", claimed_by="agent-1")

        task["status"] = "done"
        task["result"] = "Built the widget."
        task["completed_at"] = "2024-01-01T00:00:00+00:00"
        save_task(task)

        loaded = load_task(task["id"])
        assert loaded["status"] == "done"
        assert loaded["result"] == "Built the widget."

    def test_blocked_task_not_ready(self, tasks_dir, make_task):
        blocker = make_task(title="Blocker", status="pending")
        blocked = make_task(title="Blocked", blocked_by=[blocker["id"]])

        all_tasks = load_all_tasks()
        status_map = task_status_map(all_tasks)

        # The blocked task's blockers are not done
        blockers_done = all(
            status_map.get(bid) == "done"
            for bid in blocked["blocked_by"]
        )
        assert not blockers_done

    def test_unblocked_when_blocker_done(self, tasks_dir, make_task):
        blocker = make_task(title="Blocker", status="done", result="Done",
                           claimed_by="agent")
        blocked = make_task(title="Blocked", blocked_by=[blocker["id"]])

        all_tasks = load_all_tasks()
        status_map = task_status_map(all_tasks)

        blockers_done = all(
            status_map.get(bid) == "done"
            for bid in blocked["blocked_by"]
        )
        assert blockers_done

    def test_parent_child_linking(self, tasks_dir, make_task):
        parent = make_task(title="Parent task")
        child = make_task(title="Child task", parent_task=parent["id"])

        # Update parent's tasks_created
        parent["tasks_created"] = [child["id"]]
        save_task(parent)

        loaded_parent = load_task(parent["id"])
        assert child["id"] in loaded_parent["tasks_created"]

        loaded_child = load_task(child["id"])
        assert loaded_child["parent_task"] == parent["id"]


class TestCycleDetection:
    def test_no_cycle(self, tasks_dir, make_task):
        from tl0.commands.validate import check_cycles
        a = make_task(title="A")
        b = make_task(title="B", blocked_by=[a["id"]])
        c = make_task(title="C", blocked_by=[b["id"]])

        errors = check_cycles([a, b, c])
        assert errors == []

    def test_simple_cycle(self, tasks_dir, make_task):
        from tl0.commands.validate import check_cycles
        a_id = "aaaa0000-0000-0000-0000-000000000001"
        b_id = "bbbb0000-0000-0000-0000-000000000001"
        a = make_task(title="A", task_id=a_id, blocked_by=[b_id])
        b = make_task(title="B", task_id=b_id, blocked_by=[a_id])

        errors = check_cycles([a, b])
        assert len(errors) > 0
        assert "Cycle" in errors[0]
