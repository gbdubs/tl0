"""Mark a task as done."""

import argparse
import json
import os
import sys

from tl0.common import load_task, save_task, task_status, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Complete a task")
    parser.add_argument("task_id", nargs="?", help="Task UUID (prefix OK). Defaults to TL0_TASK_ID env var.")
    parser.add_argument("--result", required=True, help="Summary of what was done")
    parser.add_argument("--created", default="", help="Comma-separated UUIDs of child tasks created")
    args = parser.parse_args(argv)

    task_id = args.task_id or os.environ.get("TL0_TASK_ID")
    if not task_id:
        parser.error("task_id required (or set TL0_TASK_ID env var)")

    task = load_task(task_id)

    status = task_status(task)
    if status != "claimed":
        print(f"Error: task status is '{status}', must be 'claimed'", file=sys.stderr)
        sys.exit(1)

    # Who claimed it? Carry the agent into the done event.
    claiming_agent = task["events"][-1].get("by") if task["events"] else None

    task["result"] = args.result
    task["events"].append({"type": "done", "at": now_iso(), "by": claiming_agent} if claiming_agent
                          else {"type": "done", "at": now_iso()})

    created_ids = [x.strip() for x in args.created.split(",") if x.strip()] if args.created else []

    if created_ids:
        existing = set(task.get("task_children", []))
        task["task_children"] = list(existing | set(created_ids))

    save_task(task)

    # Set task_parent on each child if not already set
    for cid in created_ids:
        try:
            child = load_task(cid)
            if not child.get("task_parent"):
                child["task_parent"] = task["id"]
                save_task(child)
        except SystemExit:
            print(f"Warning: child task {cid} not found, skipping parent link", file=sys.stderr)

    git_commit(f"complete: {task['title']}")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": "done"}, indent=2))
