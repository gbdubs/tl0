"""Delete a task and clean up blocked_by references to it in other tasks."""

import argparse
import json
import sys

from tl0.common import (
    TASKS_FOLDER, load_task, load_all_tasks, save_task,
    task_lock, task_status, git_commit,
)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Delete a task")
    parser.add_argument("task_id", help="Task UUID (prefix OK)")
    parser.add_argument(
        "--force", action="store_true",
        help="Skip confirmation and allow deleting claimed tasks",
    )
    args = parser.parse_args(argv)

    with task_lock():
        task = load_task(args.task_id)
        task_id = task["id"]
        title = task["title"]
        status = task_status(task)

        if status == "claimed" and not args.force:
            print(
                f"Error: task is currently claimed. Pass --force to delete anyway.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Delete the task file
        task_path = TASKS_FOLDER / f"{task_id}.json"
        task_path.unlink()

        # Remove this task from blocked_by in all other tasks
        all_tasks = load_all_tasks()
        updated = []
        for other in all_tasks:
            if task_id in other.get("blocked_by", []):
                other["blocked_by"].remove(task_id)
                save_task(other)
                updated.append(other["id"])

    git_commit(f"delete: {title}")

    result = {"id": task_id, "title": title, "deleted_status": status}
    if updated:
        result["unblocked"] = updated
    print(json.dumps(result, indent=2))
