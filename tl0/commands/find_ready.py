"""Find tasks that are ready to be claimed."""

import argparse
import json

from tl0.common import load_all_tasks, task_status_map, VALID_MODELS


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Find claimable tasks")
    parser.add_argument("--tag", action="append", default=[], help="Filter by tag (can repeat)")
    parser.add_argument("--model", default=None, help="Filter by model")
    parser.add_argument("--limit", type=int, default=0, help="Max results (0 = all)")
    args = parser.parse_args(argv)

    tasks = load_all_tasks()
    status_map = task_status_map(tasks)

    ready = []
    for task in tasks:
        # Must be pending and unclaimed
        if task["status"] != "pending" or task["claimed_by"] is not None:
            continue

        # All blockers must be done
        blockers_done = all(
            status_map.get(bid) == "done"
            for bid in task.get("blocked_by", [])
        )
        if not blockers_done:
            continue

        # Apply filters
        if args.model and task.get("model") != args.model:
            continue
        if args.tag and not all(t in task.get("tags", []) for t in args.tag):
            continue

        ready.append(task)

    # Sort by creation time (oldest first)
    ready.sort(key=lambda t: t.get("created_at", ""))

    if args.limit > 0:
        ready = ready[:args.limit]

    print(json.dumps(ready, indent=2))
