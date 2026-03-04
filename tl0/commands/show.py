"""Show one or more tasks by ID or filter."""

import argparse
import json
import os
import sys

from tl0.common import load_task, load_all_tasks, task_status, task_claimed_by, task_created_at


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Show task details")
    parser.add_argument("task_ids", nargs="*", help="Task UUID(s) to show. Prefix match OK (e.g., first 8 chars). Defaults to TL0_TASK_ID if set and no IDs given.")
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--tag", action="append", default=[], help="Filter by tag")
    parser.add_argument("--brief", action="store_true", help="One-line-per-task summary")
    args = parser.parse_args(argv)

    # When called with no explicit IDs and no filters, default to TL0_TASK_ID
    task_ids = args.task_ids
    if not task_ids and not args.status and not args.tag:
        env_task_id = os.environ.get("TL0_TASK_ID")
        if env_task_id:
            task_ids = [env_task_id]

    if task_ids:
        tasks = []
        all_tasks = load_all_tasks()
        for prefix in task_ids:
            matches = [t for t in all_tasks if t["id"].startswith(prefix)]
            if not matches:
                print(f"No task matching '{prefix}'", file=sys.stderr)
                sys.exit(1)
            if len(matches) > 1:
                print(f"Ambiguous prefix '{prefix}' matches {len(matches)} tasks:", file=sys.stderr)
                for m in matches:
                    print(f"  {m['id']}  {m['title']}", file=sys.stderr)
                sys.exit(1)
            tasks.extend(matches)
    else:
        tasks = load_all_tasks()
        if args.status:
            tasks = [t for t in tasks if task_status(t) == args.status]
        if args.tag:
            tasks = [t for t in tasks if all(tag in t.get("tags", []) for tag in args.tag)]
        tasks.sort(key=lambda t: task_created_at(t) or "")

    if args.brief:
        for t in tasks:
            blocked = f" [blocked by {len(t.get('blocked_by', []))}]" if t.get("blocked_by") else ""
            claimant = task_claimed_by(t)
            claimed = f" ({claimant})" if claimant else ""
            model = f"[{t['model']}] " if t.get("model") else ""
            status = task_status(t)
            print(f"{t['id'][:8]}  {status:12s} {model}{t['title']}{blocked}{claimed}")
    else:
        print(json.dumps(tasks if len(tasks) != 1 else tasks[0], indent=2))
