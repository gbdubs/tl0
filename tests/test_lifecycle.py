"""Tests for the full task lifecycle: create -> claim -> done."""

import json
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch

from tl0.common import load_all_tasks, load_task, save_task, task_status_map, task_status, task_claimed_by, task_completed_at


class TestTaskLifecycle:
    def test_create_and_load(self, tasks_dir, make_task):
        task = make_task(title="Build widget", description="Build a widget component")
        loaded = load_task(task["id"])
        assert loaded["title"] == "Build widget"
        assert task_status(loaded) == "pending"

    def test_save_validates(self, tasks_dir, make_task):
        task = make_task()
        task["events"].append({"type": "banana", "at": "2024-01-01T00:00:00+00:00"})
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

        # Claim it by appending an event
        from tl0.common import now_iso
        task["events"].append({"type": "claimed", "at": now_iso(), "by": "test-agent"})
        save_task(task)

        loaded = load_task(task["id"])
        assert task_status(loaded) == "claimed"
        assert task_claimed_by(loaded) == "test-agent"

    def test_complete_flow(self, tasks_dir, make_task):
        task = make_task(title="Completable task", status="claimed", claimed_by="agent-1")

        task["result"] = "Built the widget."
        task["events"].append({"type": "done", "at": "2024-01-01T00:00:00+00:00", "by": "agent-1"})
        save_task(task)

        loaded = load_task(task["id"])
        assert task_status(loaded) == "done"
        assert loaded["result"] == "Built the widget."
        assert task_completed_at(loaded) == "2024-01-01T00:00:00+00:00"

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

    def test_created_by_linking(self, tasks_dir, make_task):
        creator = make_task(title="Creator task")
        child = make_task(title="Child task", created_by=creator["id"])

        loaded_child = load_task(child["id"])
        assert loaded_child["created_by"] == creator["id"]


class TestCreatedBy:
    def test_default_created_by_is_none(self, tasks_dir, make_task):
        task = make_task(title="Human task")
        loaded = load_task(task["id"])
        assert loaded["created_by"] is None

    def test_created_by_from_task(self, tasks_dir, make_task):
        creator = make_task(title="Creator task")
        child = make_task(title="Child task", created_by=creator["id"])
        loaded = load_task(child["id"])
        assert loaded["created_by"] == creator["id"]

    def test_trace_root_task(self, tasks_dir, make_task):
        from tl0.commands.trace import main as trace_main
        import io
        from contextlib import redirect_stdout

        task = make_task(title="Root task")
        f = io.StringIO()
        with redirect_stdout(f):
            trace_main([task["id"], "--json"])
        chain = json.loads(f.getvalue())
        assert len(chain) == 1
        assert chain[0]["id"] == task["id"]
        assert "created_by" not in chain[0]

    def test_trace_chain(self, tasks_dir, make_task):
        from tl0.commands.trace import main as trace_main
        import io
        from contextlib import redirect_stdout

        root = make_task(title="Root task")
        mid = make_task(title="Mid task", created_by=root["id"])
        leaf = make_task(title="Leaf task", created_by=mid["id"])

        f = io.StringIO()
        with redirect_stdout(f):
            trace_main([leaf["id"], "--json"])
        chain = json.loads(f.getvalue())
        assert len(chain) == 3
        assert chain[0]["id"] == leaf["id"]
        assert chain[1]["id"] == mid["id"]
        assert chain[2]["id"] == root["id"]

    def test_trace_missing_creator(self, tasks_dir, make_task):
        from tl0.commands.trace import main as trace_main
        import io
        from contextlib import redirect_stdout

        task = make_task(title="Orphan", created_by="00000000-0000-0000-0000-000000000000")
        f = io.StringIO()
        with redirect_stdout(f):
            trace_main([task["id"], "--json"])
        chain = json.loads(f.getvalue())
        assert len(chain) == 2
        assert "error" in chain[1]


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
