"""Free a task — reset it from claimed/in-progress/stuck back to pending."""

import argparse
import json
import sys

from tl0.common import load_task, save_task, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Free a task back to pending")
    parser.add_argument("task_id", help="Task UUID (prefix OK)")
    args = parser.parse_args(argv)

    task = load_task(args.task_id)

    if task["status"] not in ("claimed", "in-progress", "stuck"):
        print(f"Error: task status is '{task['status']}', can only free claimed/in-progress/stuck tasks", file=sys.stderr)
        sys.exit(1)

    old_status = task["status"]
    old_agent = task.get("claimed_by", "?")

    task["status"] = "pending"
    task["claimed_by"] = None
    task["claimed_at"] = None
    task["updated_at"] = now_iso()

    save_task(task)
    git_commit(f"free: {task['title']} (was {old_status} by {old_agent})")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": "pending", "was": old_status}, indent=2))
