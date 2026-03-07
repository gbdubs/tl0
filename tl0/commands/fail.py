"""Mark a task as failed due to an unrecoverable error."""

import argparse
import json
import os
import sys

from tl0.common import load_task, save_task, task_status, now_iso, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Fail a task (unrecoverable error)")
    parser.add_argument("task_id", nargs="?", help="Task UUID (prefix OK). Defaults to TL0_TASK_ID env var.")
    parser.add_argument("--reason", required=True, help="Explanation of why the task cannot be completed")
    args = parser.parse_args(argv)

    task_id = args.task_id or os.environ.get("TL0_TASK_ID")
    if not task_id:
        parser.error("task_id required (or set TL0_TASK_ID env var)")

    task = load_task(task_id)

    status = task_status(task)
    if status != "claimed":
        print(f"Error: task status is '{status}', must be 'claimed'", file=sys.stderr)
        sys.exit(1)

    # Who claimed it? Carry the agent into the failed event.
    claiming_agent = task["events"][-1].get("by") if task["events"] else None

    task["failure_reason"] = args.reason
    task["events"].append({"type": "failed", "at": now_iso(), "by": claiming_agent} if claiming_agent
                          else {"type": "failed", "at": now_iso()})

    save_task(task)

    git_commit(f"fail: {task['title']}")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": "failed", "failure_reason": args.reason}, indent=2))
