"""Tests for tl0h/tl0m CLI enforcement guards."""

import os
import pytest
from unittest.mock import patch


class TestTl0hGuard:
    """tl0h must refuse to run when TL0_TASK_ID is set."""

    def test_tl0h_fails_when_task_id_set(self, tasks_dir, capsys):
        from tl0.cli_human import main
        with patch.dict(os.environ, {"TL0_TASK_ID": "some-task-id"}):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "tl0h is not available" in captured.err
        assert "tl0m" in captured.err

    def test_tl0h_ok_when_no_task_id(self, tasks_dir, capsys):
        from tl0.cli_human import main
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main()
        # Should exit 1 from "no command given", not from our guard
        captured = capsys.readouterr()
        assert "not available" not in captured.err


class TestTl0mGuard:
    """tl0m task-specific commands must refuse to run when TL0_TASK_ID is not set."""

    def _run_tl0m(self, args, env_overrides=None):
        from tl0.cli_machine import main
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        if env_overrides:
            env.update(env_overrides)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main.__wrapped__(args) if hasattr(main, "__wrapped__") else None
        return exc_info

    def test_done_requires_task_id(self, tasks_dir, capsys):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                _require_task_id("done")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TL0_TASK_ID" in captured.err

    def test_free_requires_task_id(self, tasks_dir, capsys):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                _require_task_id("free")
        assert exc_info.value.code == 1

    def test_create_requires_task_id(self, tasks_dir, capsys):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                _require_task_id("create")
        assert exc_info.value.code == 1

    def test_find_does_not_require_task_id(self, tasks_dir):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            # Should not raise
            _require_task_id("find")

    def test_claim_does_not_require_task_id(self, tasks_dir):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            _require_task_id("claim")

    def test_show_does_not_require_task_id(self, tasks_dir):
        from tl0.cli_machine import _require_task_id
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            _require_task_id("show")

    def test_done_ok_with_task_id(self, tasks_dir):
        from tl0.cli_machine import _require_task_id
        with patch.dict(os.environ, {"TL0_TASK_ID": "some-task-id"}):
            # Should not raise
            _require_task_id("done")


class TestCompleteImplicitTaskId:
    """complete.py should use TL0_TASK_ID when no explicit task_id is given."""

    def test_complete_uses_env_task_id(self, tasks_dir, make_task, capsys):
        from tl0.commands.complete import main
        task = make_task(status="claimed", claimed_by="agent-1")
        with patch.dict(os.environ, {"TL0_TASK_ID": task["id"]}):
            main(["--result", "Done via env var"])
        captured = capsys.readouterr()
        import json
        result = json.loads(captured.out)
        assert result["status"] == "done"
        assert result["id"] == task["id"]

    def test_complete_explicit_id_overrides_env(self, tasks_dir, make_task, capsys):
        from tl0.commands.complete import main
        task = make_task(status="claimed", claimed_by="agent-1")
        other = make_task(status="claimed", claimed_by="agent-1")
        with patch.dict(os.environ, {"TL0_TASK_ID": other["id"]}):
            main([task["id"], "--result", "Done explicit"])
        captured = capsys.readouterr()
        import json
        result = json.loads(captured.out)
        assert result["id"] == task["id"]

    def test_complete_fails_without_any_task_id(self, tasks_dir, capsys):
        from tl0.commands.complete import main
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                main(["--result", "Done"])


class TestFreeImplicitTaskId:
    """free.py should use TL0_TASK_ID when no explicit task_id is given."""

    def test_free_uses_env_task_id(self, tasks_dir, make_task, capsys):
        from tl0.commands.free import main
        task = make_task(status="claimed", claimed_by="agent-1")
        with patch.dict(os.environ, {"TL0_TASK_ID": task["id"]}):
            main([])
        captured = capsys.readouterr()
        import json
        result = json.loads(captured.out)
        assert result["status"] == "pending"
        assert result["id"] == task["id"]

    def test_free_fails_without_any_task_id(self, tasks_dir, capsys):
        from tl0.commands.free import main
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                main([])


class TestShowImplicitTaskId:
    """show.py should default to TL0_TASK_ID when called with no args."""

    def test_show_defaults_to_env_task_id(self, tasks_dir, make_task, capsys):
        from tl0.commands.show import main
        task = make_task(title="My task")
        make_task(title="Other task")
        with patch.dict(os.environ, {"TL0_TASK_ID": task["id"]}):
            main([])
        captured = capsys.readouterr()
        import json
        result = json.loads(captured.out)
        assert result["id"] == task["id"]

    def test_show_all_tasks_when_no_env_and_no_args(self, tasks_dir, make_task, capsys):
        from tl0.commands.show import main
        make_task(title="Task 1")
        make_task(title="Task 2")
        env = {k: v for k, v in os.environ.items() if k != "TL0_TASK_ID"}
        with patch.dict(os.environ, env, clear=True):
            main([])
        captured = capsys.readouterr()
        import json
        results = json.loads(captured.out)
        assert len(results) == 2
