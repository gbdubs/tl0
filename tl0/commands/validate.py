"""Validate all tasks against the schema and check for structural issues."""

import json
import sys
from pathlib import Path

from tl0.common import TASKS_DIR, TASKS_FOLDER, SCHEMA_PATH, load_all_tasks, save_task, task_status, VALID_MODELS

# Fields that hold UUID references to other tasks
_REF_LIST_FIELDS = ("blocked_by",)
_REF_SCALAR_FIELDS = ("created_by",)


def resolve_truncated_ref(ref: str, all_ids: set) -> str | None:
    """Return the full UUID if *ref* is an unambiguous prefix or suffix of exactly one ID."""
    if ref in all_ids:
        return None  # already correct
    matches = [fid for fid in all_ids if fid.startswith(ref) or fid.endswith(ref)]
    return matches[0] if len(matches) == 1 else None


def fix_truncated_refs(task: dict, all_ids: set) -> list[str]:
    """Rewrite any truncated UUID references in *task* to their full IDs in place."""
    fixes = []
    tid = task.get("id", "<missing-id>")

    for field in _REF_LIST_FIELDS:
        refs = task.get(field)
        if not refs:
            continue
        new_refs = []
        for ref in refs:
            full = resolve_truncated_ref(ref, all_ids)
            if full:
                fixes.append(f"{tid}: {field} {ref!r} -> {full!r}")
                new_refs.append(full)
            else:
                new_refs.append(ref)
        task[field] = new_refs

    for field in _REF_SCALAR_FIELDS:
        ref = task.get(field)
        if not ref:
            continue
        full = resolve_truncated_ref(ref, all_ids)
        if full:
            fixes.append(f"{tid}: {field} {ref!r} -> {full!r}")
            task[field] = full

    return fixes


def validate_task(task: dict, schema: dict, all_ids: set) -> list[str]:
    """Validate a single task. Returns list of error strings."""
    errors = []
    tid = task.get("id", "<missing-id>")

    # Check required fields
    for field in schema.get("required", []):
        if field not in task:
            errors.append(f"{tid}: missing required field '{field}'")

    # Check filename matches id
    expected_path = TASKS_FOLDER / f"{tid}.json"
    if not expected_path.exists():
        errors.append(f"{tid}: filename does not match id")

    if "model" in task and task["model"] is not None and VALID_MODELS and task["model"] not in VALID_MODELS:
        errors.append(f"{tid}: invalid model '{task.get('model')}'")

    # Check events are well-formed
    for i, event in enumerate(task.get("events", [])):
        if not isinstance(event, dict):
            errors.append(f"{tid}: events[{i}] must be an object")
            continue
        if event.get("type") not in ("created", "claimed", "freed", "done"):
            errors.append(f"{tid}: events[{i}].type '{event.get('type')}' is invalid")
        if "at" not in event:
            errors.append(f"{tid}: events[{i}] missing 'at' timestamp")

    # Check done tasks have result
    if task_status(task) == "done" and not task.get("result"):
        errors.append(f"{tid}: status is 'done' but result is not set")

    # Check blocked_by references exist
    for bid in task.get("blocked_by", []):
        if bid not in all_ids:
            errors.append(f"{tid}: blocked_by references non-existent task {bid}")

    # Check created_by reference exists
    creator = task.get("created_by")
    if creator and creator not in all_ids:
        errors.append(f"{tid}: created_by references non-existent task {creator}")

    # Check no unexpected fields
    allowed = set(schema.get("properties", {}).keys())
    for key in task:
        if key not in allowed:
            errors.append(f"{tid}: unexpected field '{key}'")

    return errors


def check_cycles(tasks: list[dict]) -> list[str]:
    """Detect cycles in the blocked_by graph."""
    errors = []
    graph = {t["id"]: set(t.get("blocked_by", [])) for t in tasks}

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in graph}

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in color:
                continue  # dangling ref, caught elsewhere
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                errors.append(f"Cycle detected: {' -> '.join(cycle)}")
                return
            if color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for tid in graph:
        if color[tid] == WHITE:
            dfs(tid, [])

    return errors


def main(argv: list[str] | None = None):
    tasks = load_all_tasks()

    if not tasks:
        print("No tasks found. Validation passed (empty task set).")
        return

    with open(SCHEMA_PATH) as f:
        schema = json.load(f)

    all_ids = {t["id"] for t in tasks}

    # Auto-fix pass: resolve truncated UUID references
    all_fixes = []
    for task in tasks:
        fixes = fix_truncated_refs(task, all_ids)
        if fixes:
            save_task(task)
            all_fixes.extend(fixes)

    if all_fixes:
        print(f"Fixed {len(all_fixes)} truncated reference(s):")
        for fix in all_fixes:
            print(f"  > {fix}")

    # Validation pass
    all_errors = []
    for task in tasks:
        all_errors.extend(validate_task(task, schema, all_ids))

    all_errors.extend(check_cycles(tasks))

    if all_errors:
        print(f"Validation failed with {len(all_errors)} error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Validation passed. {len(tasks)} task(s) checked.")
