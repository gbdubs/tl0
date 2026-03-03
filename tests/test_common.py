"""Tests for tl0.common — validation, loading, saving."""

import json
import pytest
from pathlib import Path

from tl0.common import validate_task_shape, now_iso


def _minimal_task(**overrides):
    """Build a minimal valid task dict."""
    task = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Test task",
        "description": "A test",
        "status": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "blocked_by": [],
        "tags": [],
    }
    task.update(overrides)
    return task


class TestValidateTaskShape:
    def test_minimal_valid_task(self):
        task = _minimal_task()
        errors = validate_task_shape(task)
        assert errors == []

    def test_full_valid_task(self):
        task = _minimal_task(
            model="opus",
            thinking=True,
            claimed_by=None,
            claimed_at=None,
            completed_at=None,
            design_references=[{"file": "TDD.md", "section": "1"}],
            produces=["src/foo.ts"],
            context_files=["src/bar.ts"],
            result=None,
            tasks_created=[],
            parent_task=None,
        )
        errors = validate_task_shape(task)
        assert errors == []

    def test_missing_required_field(self):
        task = _minimal_task()
        del task["title"]
        errors = validate_task_shape(task)
        assert any("title" in e for e in errors)

    def test_invalid_status(self):
        task = _minimal_task(status="banana")
        errors = validate_task_shape(task)
        assert any("status" in e for e in errors)

    def test_unexpected_field(self):
        task = _minimal_task(surprise="hello")
        errors = validate_task_shape(task)
        assert any("surprise" in e for e in errors)

    def test_title_too_long(self):
        task = _minimal_task(title="x" * 201)
        errors = validate_task_shape(task)
        assert any("200" in e for e in errors)

    def test_empty_title(self):
        task = _minimal_task(title="")
        errors = validate_task_shape(task)
        assert any("empty" in e for e in errors)

    def test_blocked_by_must_be_strings(self):
        task = _minimal_task(blocked_by=[123])
        errors = validate_task_shape(task)
        assert any("strings" in e for e in errors)

    def test_done_without_result(self):
        task = _minimal_task(status="done")
        errors = validate_task_shape(task)
        assert any("result" in e for e in errors)

    def test_claimed_without_claimed_by(self):
        task = _minimal_task(status="claimed")
        errors = validate_task_shape(task)
        assert any("claimed_by" in e for e in errors)

    def test_design_references_validation(self):
        task = _minimal_task(design_references=[{"no_file": True}])
        errors = validate_task_shape(task)
        assert any("file" in e for e in errors)

    def test_model_is_optional(self):
        task = _minimal_task()
        # No model field at all — should be valid
        errors = validate_task_shape(task)
        assert errors == []

    def test_thinking_is_optional(self):
        task = _minimal_task()
        errors = validate_task_shape(task)
        assert errors == []
