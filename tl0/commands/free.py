"""Free a task — reset it from claimed back to pending."""

import argparse
import json
import os
import sys

from tl0.common import load_task, save_task, task_lock, task_status, task_claimed_by, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Free a task back to pending")
    parser.add_argument("task_id", nargs="?", help="Task UUID (prefix OK). Defaults to TL0_TASK_ID env var.")
    parser.add_argument("--by", default=None, help="Identifier of who is freeing the task (e.g. 'human')")
    args = parser.parse_args(argv)

    task_id = args.task_id or os.environ.get("TL0_TASK_ID")
    if not task_id:
        parser.error("task_id required (or set TL0_TASK_ID env var)")

    with task_lock():
        task = load_task(task_id)

        status = task_status(task)
        if status != "claimed":
            print(f"Error: task status is '{status}', can only free claimed tasks", file=sys.stderr)
            sys.exit(1)

        old_agent = task_claimed_by(task) or "?"

        event = {"type": "freed", "at": now_iso()}
        if args.by:
            event["by"] = args.by
        task["events"].append(event)

        save_task(task)

    git_commit(f"free: {task['title']} (was claimed by {old_agent})")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": "pending", "was_claimed_by": old_agent}, indent=2))
