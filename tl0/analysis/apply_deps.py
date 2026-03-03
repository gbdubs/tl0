"""Apply dependency audit results to the task tree.

Reads a JSON file of proposed dependency additions, validates them
(no cycles, no self-refs, no duplicates), and applies them.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tl0.common import TASKS_DIR, TASKS_FOLDER, load_all_tasks


def resolve_prefix(prefix, all_ids):
    """Resolve a UUID prefix to a full UUID."""
    prefix = prefix.strip()
    if prefix in all_ids:
        return prefix
    matches = [tid for tid in all_ids if tid.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    return None


def detect_cycle(graph, start):
    """DFS cycle detection. Returns the cycle path if found, else None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)
    parent = {}

    def dfs(node):
        color[node] = GRAY
        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle = [neighbor, node]
                cur = node
                while cur != neighbor and cur in parent:
                    cur = parent[cur]
                    cycle.append(cur)
                cycle.reverse()
                return cycle
            if color[neighbor] == WHITE:
                parent[neighbor] = node
                result = dfs(neighbor)
                if result:
                    return result
        color[node] = BLACK
        return None

    return dfs(start)


def is_transitively_redundant(task_id, new_blocker, graph):
    """Check if task_id can already reach new_blocker through existing edges."""
    visited = set()
    queue = []
    for existing in graph.get(task_id, []):
        if existing != new_blocker:
            queue.append(existing)

    while queue:
        current = queue.pop(0)
        if current == new_blocker:
            return True
        if current in visited:
            continue
        visited.add(current)
        for neighbor in graph.get(current, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return False


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Apply dependency audit results")
    parser.add_argument("proposals_file", help="JSON file with proposed dependencies")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without applying")
    parser.add_argument("--skip-validation", action="store_true", help="Skip cycle/redundancy checks")
    args = parser.parse_args(argv)

    with open(args.proposals_file) as f:
        proposals = json.load(f)

    tasks_list = load_all_tasks()
    tasks = {t["id"]: t for t in tasks_list}
    all_ids = set(tasks.keys())

    # Build current dependency graph
    graph = {}
    for tid, t in tasks.items():
        graph[tid] = list(t.get("blocked_by", []))

    applied = 0
    skipped_cycle = 0
    skipped_redundant = 0
    skipped_duplicate = 0
    skipped_unknown = 0
    skipped_self = 0

    for proposal in proposals:
        raw_task_id = proposal["task_id"]
        task_id = resolve_prefix(raw_task_id, all_ids)
        if not task_id:
            print(f"  SKIP: cannot resolve task '{raw_task_id}'")
            skipped_unknown += 1
            continue

        for raw_blocker in proposal.get("add_blocked_by", []):
            blocker_id = resolve_prefix(raw_blocker, all_ids)
            if not blocker_id:
                print(f"  SKIP: cannot resolve blocker '{raw_blocker}' for task {task_id[:8]}")
                skipped_unknown += 1
                continue

            if blocker_id == task_id:
                print(f"  SKIP: self-reference {task_id[:8]}")
                skipped_self += 1
                continue

            if blocker_id in tasks[task_id].get("blocked_by", []):
                skipped_duplicate += 1
                continue

            if not args.skip_validation:
                graph.setdefault(task_id, []).append(blocker_id)
                cycle = detect_cycle(graph, blocker_id)
                graph[task_id].remove(blocker_id)

                if cycle:
                    print(f"  SKIP CYCLE: {task_id[:8]} blocked_by {blocker_id[:8]} "
                          f"would create cycle: {' -> '.join(c[:8] for c in cycle)}")
                    skipped_cycle += 1
                    continue

                if is_transitively_redundant(task_id, blocker_id, graph):
                    skipped_redundant += 1
                    continue

            reason = proposal.get("reason", "")
            task_title = tasks[task_id]["title"][:60]
            blocker_title = tasks[blocker_id]["title"][:60]
            print(f"  ADD: {task_id[:8]} \"{task_title}\"")
            print(f"    blocked_by += {blocker_id[:8]} \"{blocker_title}\"")
            if reason:
                print(f"    reason: {reason}")

            if not args.dry_run:
                graph.setdefault(task_id, []).append(blocker_id)
                tasks[task_id].setdefault("blocked_by", []).append(blocker_id)
                tasks[task_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
                with open(TASKS_FOLDER / f"{task_id}.json", "w") as f:
                    json.dump(tasks[task_id], f, indent=2)
                    f.write("\n")

            applied += 1

    print(f"\nSummary:")
    print(f"  Applied: {applied}")
    print(f"  Skipped (already present): {skipped_duplicate}")
    print(f"  Skipped (would create cycle): {skipped_cycle}")
    print(f"  Skipped (transitively redundant): {skipped_redundant}")
    print(f"  Skipped (unknown task/blocker): {skipped_unknown}")
    print(f"  Skipped (self-reference): {skipped_self}")

    if args.dry_run:
        print(f"\n  (DRY RUN -- nothing was written)")
