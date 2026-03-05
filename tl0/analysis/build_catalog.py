"""Build a condensed task catalog for dependency auditing.

Generates catalog.md in the tasks directory — a single file an agent can read
to understand every task in the tree without loading hundreds of JSON files.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from tl0.common import TASKS_DIR, TASKS_FOLDER, load_all_tasks


def get_phase(task):
    for tag in task.get("tags", []):
        if tag.startswith("phase:"):
            val = tag.split(":")[1]
            try:
                return int(val)
            except ValueError:
                return val
    return None


def get_areas(task):
    return [tag.split(":")[1] for tag in task.get("tags", []) if tag.startswith("area:")]


def build_catalog(tasks_list):
    tasks = {t["id"]: t for t in tasks_list}
    parent_ids = {t.get("task_parent") for t in tasks.values()}
    leaf_tasks = {tid: t for tid, t in tasks.items() if tid not in parent_ids}

    lines = []
    lines.append("# Task Catalog")
    lines.append("")
    lines.append(f"Generated from {len(tasks)} total tasks, {len(leaf_tasks)} leaf tasks.")
    lines.append("")

    # Section 1: tasks by phase + area
    lines.append("## Tasks by Phase")
    lines.append("")

    phase_groups = defaultdict(list)
    for tid, t in leaf_tasks.items():
        p = get_phase(t)
        phase_groups[p].append(t)

    def phase_sort_key(x):
        if x is None:
            return (2, 0, "")
        if isinstance(x, int):
            return (0, x, "")
        return (1, 0, str(x))

    for phase in sorted(phase_groups.keys(), key=phase_sort_key):
        group = sorted(phase_groups[phase], key=lambda t: t["title"])
        lines.append(f"### Phase {phase} ({len(group)} tasks)")
        lines.append("")
        for t in group:
            areas = ", ".join(get_areas(t))
            blockers = ", ".join(b[:8] for b in t.get("blocked_by", []))
            blocker_str = f" blocked_by=[{blockers}]" if blockers else ""
            lines.append(
                f"- {t['id'][:8]} \"{t['title'][:100]}\" "
                f"[{areas}]{blocker_str}"
            )
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Build task catalog for dependency auditing")
    parser.add_argument("--out", default=str(TASKS_DIR / "catalog.md"),
                        help="Output path (default: <tasks_dir>/catalog.md)")
    args = parser.parse_args(argv)

    tasks = load_all_tasks()
    catalog = build_catalog(tasks)

    with open(args.out, "w") as f:
        f.write(catalog)

    print(f"Catalog written to {args.out} ({len(catalog)} bytes, {catalog.count(chr(10))} lines)")
