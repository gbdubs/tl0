"""Create a new task."""

import argparse
import json
import os
import uuid

from tl0.common import VALID_MODELS, load_task, save_task, now_iso, git_commit


def parse_refs(refs_str: str) -> list[dict]:
    """Parse design references from 'file:section:note' format."""
    if not refs_str:
        return []
    result = []
    for ref in refs_str.split(","):
        parts = ref.strip().split(":", 2)
        entry: dict = {"file": parts[0]}
        if len(parts) > 1 and parts[1]:
            entry["section"] = parts[1]
        if len(parts) > 2 and parts[2]:
            entry["note"] = parts[2]
        result.append(entry)
    return result


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Create a new task")
    parser.add_argument("--title", required=True, help="Task title")
    parser.add_argument("--description", required=True, help="Task description")
    parser.add_argument("--model", default=None, help="Model to use")
    parser.add_argument("--thinking", default=None, type=lambda x: x.lower() == "true",
                        help="Whether extended thinking is needed")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--blocked-by", default="", help="Comma-separated task UUIDs")
    parser.add_argument("--design-refs", default="", help="Comma-separated file:section:note")
    parser.add_argument("--produces", default="", help="Comma-separated file paths")
    parser.add_argument("--context-files", default="", help="Comma-separated file paths")
    parser.add_argument("--parent", default=None, help="Creator task UUID (prefix OK). Also auto-detected from TL0_TASK_ID env var.")

    args = parser.parse_args(argv)

    # Validate model if provided
    if args.model and VALID_MODELS and args.model not in VALID_MODELS:
        parser.error(f"model must be one of {sorted(VALID_MODELS)}, got '{args.model}'")

    # Resolve creator: explicit flag > TL0_TASK_ID env var > None
    created_by = None
    if args.parent:
        creator = load_task(args.parent)
        created_by = creator["id"]
    elif os.environ.get("TL0_TASK_ID"):
        created_by = os.environ["TL0_TASK_ID"]

    task_id = str(uuid.uuid4())

    task = {
        "id": task_id,
        "title": args.title,
        "description": args.description,
        "events": [{"type": "created", "at": now_iso()}],
        "blocked_by": [x.strip() for x in args.blocked_by.split(",") if x.strip()],
        "tags": [x.strip() for x in args.tags.split(",") if x.strip()],
        "model": args.model,
        "thinking": args.thinking,
        "design_references": parse_refs(args.design_refs),
        "produces": [x.strip() for x in args.produces.split(",") if x.strip()],
        "context_files": [x.strip() for x in args.context_files.split(",") if x.strip()],
        "result": None,
        "created_by": created_by,
    }

    save_task(task)

    git_commit(f"create: {args.title}")
    print(json.dumps({"id": task_id, "title": args.title}, indent=2))
