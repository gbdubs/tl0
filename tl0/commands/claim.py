"""Claim a task for an agent."""

import argparse
import json
import sys

from tl0.common import (
    load_task,
    load_all_tasks,
    save_task,
    task_lock,
    task_status_map,
    task_status,
    now_iso,
    git_commit,
)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Claim a task")
    parser.add_argument("task_id", help="Task UUID to claim")
    parser.add_argument("agent_id", help="Agent identifier")
    args = parser.parse_args(argv)

    with task_lock():
        task = load_task(args.task_id)

        # Validate claimable
        status = task_status(task)
        if status != "pending":
            print(f"Error: task status is '{status}', must be 'pending'", file=sys.stderr)
            sys.exit(1)

        # Check blockers
        all_tasks = load_all_tasks()
        status_map = task_status_map(all_tasks)
        task_map = {t["id"]: t for t in all_tasks}
        for bid in task.get("blocked_by", []):
            blocker_status = status_map.get(bid, "missing")
            if blocker_status == "failed":
                blocker = task_map.get(bid, {})
                reason = blocker.get("failure_reason", "no reason recorded")
                print(
                    f"Error: blocker {bid} failed — this task cannot proceed.\n"
                    f"  Blocker title:  {blocker.get('title', '?')}\n"
                    f"  Failure reason: {reason}",
                    file=sys.stderr,
                )
                sys.exit(1)
            if blocker_status != "done":
                print(f"Error: blocker {bid} is not done (status: {blocker_status})", file=sys.stderr)
                sys.exit(1)

        # Append claimed event
        task["events"].append({"type": "claimed", "at": now_iso(), "by": args.agent_id})

        save_task(task)

    git_commit(f"claim: {task['title']} by {args.agent_id}")
    print(json.dumps({"id": task["id"], "title": task["title"], "claimed_by": args.agent_id}, indent=2))
