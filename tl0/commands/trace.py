"""Trace a task back to its progenitor (root source)."""

import argparse
import json
import sys

from tl0.common import load_all_tasks


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Trace a task back to its origin")
    parser.add_argument("task_id", help="Task UUID (prefix OK)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output the chain as JSON")
    args = parser.parse_args(argv)

    all_tasks = load_all_tasks()
    tasks_by_id = {t["id"]: t for t in all_tasks}

    # Resolve prefix
    matches = [t for t in all_tasks if t["id"].startswith(args.task_id)]
    if not matches:
        print(f"No task matching '{args.task_id}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Ambiguous prefix '{args.task_id}' matches {len(matches)} tasks:", file=sys.stderr)
        for m in matches:
            print(f"  {m['id']}  {m['title']}", file=sys.stderr)
        sys.exit(1)

    task = matches[0]

    # Walk the created_by chain
    chain = []
    seen = set()
    current = task

    while True:
        chain.append({"id": current["id"], "title": current["title"]})
        seen.add(current["id"])

        creator = current.get("created_by")
        if not creator:
            break

        if creator in seen:
            chain.append({"error": f"cycle detected at {creator}"})
            break
        if creator not in tasks_by_id:
            chain.append({"error": f"creator task {creator} not found"})
            break

        current = tasks_by_id[creator]

    if args.as_json:
        print(json.dumps(chain, indent=2))
    else:
        for i, entry in enumerate(chain):
            if "error" in entry:
                print(f"  {'  ' * i}⚠ {entry['error']}")
                break
            prefix = "→ " if i > 0 else ""
            indent = "  " * i
            is_root = (i == len(chain) - 1 and not entry.get("error"))
            root_label = "  (root — no creator)" if is_root and not current.get("created_by") else ""
            print(f"  {indent}{prefix}{entry['id'][:8]}  {entry['title']}{root_label}")
