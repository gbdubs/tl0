"""Update arbitrary fields on a task."""

import argparse
import json
import sys

from tl0.common import load_task, load_all_tasks, save_task, git_commit, task_status, VALID_MODELS


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Update a task's fields")
    parser.add_argument("task_id", help="Task UUID (prefix match OK)")
    parser.add_argument("--title", help="New title")
    parser.add_argument("--description", help="New description")
    parser.add_argument("--model", default=None, help="New model")
    parser.add_argument("--thinking", type=lambda x: x.lower() == "true")
    parser.add_argument("--add-tags", default="", help="Comma-separated tags to add")
    parser.add_argument("--remove-tags", default="", help="Comma-separated tags to remove")
    parser.add_argument("--add-blocked-by", default="", help="Comma-separated task UUIDs to add as blockers")
    parser.add_argument("--remove-blocked-by", default="", help="Comma-separated task UUIDs to remove as blockers")
    parser.add_argument("--result", help="Set result text (use 'done' command for lifecycle transitions)")
    parser.add_argument("--merge-attempt-count", type=int, default=None, help="Set merge attempt counter (for script task retries)")
    args = parser.parse_args(argv)

    # Resolve prefix
    all_tasks = load_all_tasks()
    matches = [t for t in all_tasks if t["id"].startswith(args.task_id)]
    if not matches:
        print(f"No task matching '{args.task_id}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Ambiguous prefix '{args.task_id}'", file=sys.stderr)
        sys.exit(1)
    task = matches[0]

    changed = False

    if args.title and args.title != task["title"]:
        task["title"] = args.title
        changed = True
    if args.description and args.description != task["description"]:
        task["description"] = args.description
        changed = True
    if args.model and args.model != task.get("model"):
        task["model"] = args.model
        changed = True
    if args.thinking is not None and args.thinking != task.get("thinking"):
        task["thinking"] = args.thinking
        changed = True
    if args.result is not None:
        task["result"] = args.result
        changed = True
    if args.merge_attempt_count is not None:
        task["merge_attempt_count"] = args.merge_attempt_count
        changed = True

    if args.add_tags:
        for tag in args.add_tags.split(","):
            tag = tag.strip()
            if tag and tag not in task["tags"]:
                task["tags"].append(tag)
                changed = True

    if args.remove_tags:
        for tag in args.remove_tags.split(","):
            tag = tag.strip()
            if tag in task["tags"]:
                task["tags"].remove(tag)
                changed = True

    if args.add_blocked_by:
        for bid in args.add_blocked_by.split(","):
            bid = bid.strip()
            if bid and bid not in task["blocked_by"]:
                task["blocked_by"].append(bid)
                changed = True

    if args.remove_blocked_by:
        for bid in args.remove_blocked_by.split(","):
            bid = bid.strip()
            if bid in task["blocked_by"]:
                task["blocked_by"].remove(bid)
                changed = True

    if not changed:
        print("No changes made.")
        return

    save_task(task)
    git_commit(f"update: {task['title']}")
    print(json.dumps({"id": task["id"], "title": task["title"], "status": task_status(task)}, indent=2))
