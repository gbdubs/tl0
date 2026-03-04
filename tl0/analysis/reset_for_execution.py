"""Reset leaf tasks from done -> pending for execution mode.

Finds done leaf tasks whose result indicates they were planning completions
(containing a configurable marker, default "Atomic"), and resets them to
pending so they can be claimed for implementation.
"""

import argparse
import json
from pathlib import Path

from tl0.common import TASKS_FOLDER, load_all_tasks, task_status, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Reset planning-complete tasks for execution")
    parser.add_argument("--marker", default="Atomic",
                        help="String to look for in result field (default: 'Atomic')")
    args = parser.parse_args(argv)

    tasks_list = load_all_tasks()
    tasks = {t["id"]: t for t in tasks_list}

    # Build set of parent IDs (tasks that have children)
    parent_ids = set()
    for task in tasks.values():
        if task.get("parent_task"):
            parent_ids.add(task["parent_task"])

    reset_count = 0
    skip_not_done = 0
    skip_has_children = 0
    skip_no_marker = 0

    for task_id, task in tasks.items():
        if task_status(task) != "done":
            skip_not_done += 1
            continue

        if task_id in parent_ids:
            skip_has_children += 1
            continue

        result = task.get("result", "") or ""
        if args.marker not in result:
            skip_no_marker += 1
            continue

        # Append a freed event to reset to pending, and clear result
        task["events"].append({"type": "freed", "at": now_iso(), "by": "reset_for_execution"})
        task["result"] = None

        task_path = TASKS_FOLDER / f"{task_id}.json"
        with open(task_path, "w") as fh:
            json.dump(task, fh, indent=2)
            fh.write("\n")

        reset_count += 1

    git_commit(f"reset-for-execution: reset {reset_count} tasks")
    print(f"Reset: {reset_count}")
    print(f"Skipped (not done): {skip_not_done}")
    print(f"Skipped (has children): {skip_has_children}")
    print(f"Skipped (no '{args.marker}' in result): {skip_no_marker}")
    print(f"Total: {len(tasks)}")
