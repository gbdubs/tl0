"""Show one or more tasks by ID or filter."""

import argparse
import json
import sys

from tl0.common import load_task, load_all_tasks


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Show task details")
    parser.add_argument("task_ids", nargs="*", help="Task UUID(s) to show. Prefix match OK (e.g., first 8 chars).")
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--tag", action="append", default=[], help="Filter by tag")
    parser.add_argument("--brief", action="store_true", help="One-line-per-task summary")
    args = parser.parse_args(argv)

    if args.task_ids:
        tasks = []
        all_tasks = load_all_tasks()
        for prefix in args.task_ids:
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
            tasks = [t for t in tasks if t["status"] == args.status]
        if args.tag:
            tasks = [t for t in tasks if all(tag in t.get("tags", []) for tag in args.tag)]
        tasks.sort(key=lambda t: t.get("created_at", ""))

    if args.brief:
        for t in tasks:
            blocked = f" [blocked by {len(t.get('blocked_by', []))}]" if t.get("blocked_by") else ""
            claimed = f" ({t['claimed_by']})" if t.get("claimed_by") else ""
            model = f"[{t['model']}] " if t.get("model") else ""
            print(f"{t['id'][:8]}  {t['status']:12s} {model}{t['title']}{blocked}{claimed}")
    else:
        print(json.dumps(tasks if len(tasks) != 1 else tasks[0], indent=2))
