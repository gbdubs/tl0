"""Mark a task as done."""

import argparse
import json
import sys

from tl0.common import load_task, save_task, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Complete a task")
    parser.add_argument("task_id", help="Task UUID (prefix OK)")
    parser.add_argument("--result", required=True, help="Summary of what was done")
    parser.add_argument("--created", default="", help="Comma-separated UUIDs of child tasks created")
    args = parser.parse_args(argv)

    task = load_task(args.task_id)

    if task["status"] not in ("claimed", "in-progress"):
        print(f"Error: task status is '{task['status']}', must be 'claimed' or 'in-progress'", file=sys.stderr)
        sys.exit(1)

    now = now_iso()
    task["status"] = "done"
    task["completed_at"] = now
    task["updated_at"] = now
    task["result"] = args.result

    created_ids = [x.strip() for x in args.created.split(",") if x.strip()] if args.created else []

    if created_ids:
        existing = set(task.get("tasks_created", []))
        task["tasks_created"] = list(existing | set(created_ids))

    save_task(task)

    # Set parent_task on each child if not already set
    for cid in created_ids:
        try:
            child = load_task(cid)
            if not child.get("parent_task"):
                child["parent_task"] = task["id"]
                child["updated_at"] = now
                save_task(child)
        except SystemExit:
            print(f"Warning: child task {cid} not found, skipping parent link", file=sys.stderr)

    git_commit(f"complete: {task['title']}")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": "done"}, indent=2))
