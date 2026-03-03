"""Free all non-done tasks back to pending."""

import json

from tl0.common import load_all_tasks, save_task, now_iso, git_commit


def main(argv: list[str] | None = None):
    tasks = load_all_tasks()
    freed = []

    for task in tasks:
        if task["status"] in ("claimed", "in-progress", "stuck"):
            old_status = task["status"]
            old_agent = task.get("claimed_by", "?")
            task["status"] = "pending"
            task["claimed_by"] = None
            task["claimed_at"] = None
            task["updated_at"] = now_iso()
            save_task(task)
            freed.append({"id": task["id"], "title": task["title"], "was": old_status, "was_agent": old_agent})

    if not freed:
        print("No claimed/in-progress/stuck tasks to free.")
        return

    git_commit(f"free-all: released {len(freed)} tasks back to pending")
    print(json.dumps(freed, indent=2))
    print(f"\nFreed {len(freed)} task(s).")
