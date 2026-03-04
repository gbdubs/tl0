"""Free all non-done tasks back to pending."""

import json

from tl0.common import load_all_tasks, save_task, task_status, task_claimed_by, now_iso, git_commit


def main(argv: list[str] | None = None):
    tasks = load_all_tasks()
    freed = []

    for task in tasks:
        if task_status(task) == "claimed":
            old_agent = task_claimed_by(task) or "?"
            task["events"].append({"type": "freed", "at": now_iso()})
            save_task(task)
            freed.append({"id": task["id"], "title": task["title"], "was_claimed_by": old_agent})

    if not freed:
        print("No claimed tasks to free.")
        return

    git_commit(f"free-all: released {len(freed)} tasks back to pending")
    print(json.dumps(freed, indent=2))
    print(f"\nFreed {len(freed)} task(s).")
