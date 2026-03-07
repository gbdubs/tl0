"""Reset tasks that were erroneously marked done due to quota/rate-limit errors."""

import argparse
import json
import sys

from tl0.common import load_all_tasks, save_task, task_status, git_commit


QUOTA_ERROR_INDICATORS = [
    "hit your limit",
    "rate limit",
    "rate_limit",
    "resets ",  # "resets 10am (America/Denver)"
]


def is_quota_error_result(result: str) -> bool:
    """Check if a task result looks like a quota/rate-limit error."""
    if not result:
        return False
    lower = result.lower()
    # Must have the fallback prefix (meaning no real work was done)
    if not lower.startswith("[fallback-from-stdout]"):
        return False
    return any(indicator in lower for indicator in QUOTA_ERROR_INDICATORS)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Reset tasks erroneously completed due to quota errors")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be reset without making changes")
    args = parser.parse_args(argv)

    tasks = load_all_tasks()
    affected = []

    for task in tasks:
        if task_status(task) != "done":
            continue
        result = task.get("result") or ""
        if is_quota_error_result(result):
            affected.append(task)

    if not affected:
        print("No quota-error tasks found.")
        return

    print(f"Found {len(affected)} tasks with quota-error results.")

    if args.dry_run:
        for t in affected:
            print(f"  {t['id'][:8]}  {t['title'][:60]}")
            print(f"    result: {(t.get('result') or '')[:100]}")
        print(f"\nRun without --dry-run to reset these tasks.")
        return

    for task in affected:
        # Remove the last 'done' event
        while task["events"] and task["events"][-1]["type"] == "done":
            task["events"].pop()
        # Also remove the claiming event so the task goes back to pending
        while task["events"] and task["events"][-1]["type"] == "claimed":
            task["events"].pop()
        task["result"] = None
        save_task(task)

    git_commit(f"reset: {len(affected)} tasks erroneously completed due to quota errors")
    print(f"Reset {len(affected)} tasks back to pending.")
