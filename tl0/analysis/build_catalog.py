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
    parent_ids = {t.get("parent_task") for t in tasks.values()}
    leaf_tasks = {tid: t for tid, t in tasks.items() if tid not in parent_ids}

    lines = []
    lines.append("# Task Catalog")
    lines.append("")
    lines.append(f"Generated from {len(tasks)} total tasks, {len(leaf_tasks)} leaf tasks.")
    lines.append("")

    # Section 1: produces index
    lines.append("## Produces Index")
    lines.append("")
    lines.append("Maps output file paths to the task that creates them.")
    lines.append("")
    produces_map = defaultdict(list)
    for tid, t in sorted(leaf_tasks.items(), key=lambda x: x[1]["title"]):
        for p in t.get("produces", []):
            produces_map[p].append(tid)

    for path in sorted(produces_map.keys()):
        tids = produces_map[path]
        for tid in tids:
            t = leaf_tasks[tid]
            lines.append(f"- `{path}` <- {tid[:8]} \"{t['title'][:80]}\" [phase:{get_phase(t)}]")
    lines.append("")

    # Section 2: tasks by phase + area
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
            produces = ", ".join(t.get("produces", [])[:3])
            produces_str = f" produces=[{produces}]" if produces else ""
            lines.append(
                f"- {t['id'][:8]} \"{t['title'][:100]}\" "
                f"[{areas}]{blocker_str}{produces_str}"
            )
        lines.append("")

    # Section 3: Design reference index
    lines.append("## Design Reference Index")
    lines.append("")
    lines.append("Which tasks reference which design sections.")
    lines.append("")
    ref_map = defaultdict(list)
    for tid, t in leaf_tasks.items():
        for ref in t.get("design_references", []):
            key = ref.get("file", "?")
            section = ref.get("section", "")
            if section:
                key = f"{key} > {section}"
            ref_map[key].append(tid)

    for key in sorted(ref_map.keys()):
        tids = ref_map[key]
        tid_strs = ", ".join(t[:8] for t in tids)
        lines.append(f"- {key}: {tid_strs}")
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
