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
        "blocked_by": [],
        "tags": [],
        "events": [{"type": "created", "at": now_iso()}],
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
            result=None,
            task_children=[],
            task_parent=None,
        )
        errors = validate_task_shape(task)
        assert errors == []

    def test_missing_required_field(self):
        task = _minimal_task()
        del task["title"]
        errors = validate_task_shape(task)
        assert any("title" in e for e in errors)

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
        # A task whose last event is "done" but has no result should fail
        task = _minimal_task(events=[
            {"type": "created", "at": now_iso()},
            {"type": "claimed", "at": now_iso(), "by": "agent-1"},
            {"type": "done", "at": now_iso(), "by": "agent-1"},
        ])
        errors = validate_task_shape(task)
        assert any("result" in e for e in errors)

    def test_invalid_event_type(self):
        task = _minimal_task(events=[{"type": "banana", "at": now_iso()}])
        errors = validate_task_shape(task)
        assert any("banana" in e for e in errors)

    def test_event_missing_at(self):
        task = _minimal_task(events=[{"type": "claimed", "by": "agent-1"}])
        errors = validate_task_shape(task)
        assert any("at" in e for e in errors)

    def test_model_is_optional(self):
        task = _minimal_task()
        # No model field at all — should be valid
        errors = validate_task_shape(task)
        assert errors == []

    def test_thinking_is_optional(self):
        task = _minimal_task()
        errors = validate_task_shape(task)
        assert errors == []
