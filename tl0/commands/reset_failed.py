"""Reset failed tasks back to pending so they can be retried."""

import argparse
import sys

from tl0.common import load_all_tasks, save_task, task_status, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Reset failed tasks back to pending")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be reset without making changes")
    args = parser.parse_args(argv)

    tasks = load_all_tasks()
    affected = [t for t in tasks if task_status(t) == "failed"]

    if not affected:
        print("No failed tasks found.")
        return

    print(f"Found {len(affected)} failed task(s).")

    if args.dry_run:
        for t in affected:
            print(f"  {t['id'][:8]}  {t['title'][:60]}")
            print(f"    reason: {(t.get('failure_reason') or '')[:100]}")
        print(f"\nRun without --dry-run to reset these tasks.")
        return

    for task in affected:
        while task["events"] and task["events"][-1]["type"] == "failed":
            task["events"].pop()
        while task["events"] and task["events"][-1]["type"] == "claimed":
            task["events"].pop()
        task["failure_reason"] = None
        save_task(task)

    git_commit(f"reset-failed: {len(affected)} tasks reset to pending")
    print(f"Reset {len(affected)} failed task(s) back to pending.")
