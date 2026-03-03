"""Reset the task system — delete all tasks and recommit."""

import argparse
import sys

from tl0.common import TASKS_FOLDER, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Reset all tasks")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    args = parser.parse_args(argv)

    task_files = list(TASKS_FOLDER.glob("*.json"))

    if not task_files:
        print("No tasks to delete.")
        return

    if not args.force:
        print(f"This will delete {len(task_files)} task(s). Pass --force to confirm.", file=sys.stderr)
        sys.exit(1)

    for f in task_files:
        f.unlink()

    git_commit(f"reset: deleted {len(task_files)} tasks")
    print(f"Deleted {len(task_files)} task(s).")
