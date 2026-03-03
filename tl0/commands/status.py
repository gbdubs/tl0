"""Print a compact dashboard of task system state."""

import sys
from datetime import datetime, timezone
from collections import Counter

from tl0.common import load_all_tasks, task_status_map


TRUNC = 60


def trunc(s, n=TRUNC):
    return s[:n-1] + "…" if len(s) > n else s


def ago(iso_str):
    """Human-readable time-ago string."""
    if not iso_str:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "?"


def main(argv: list[str] | None = None):
    tasks = load_all_tasks()

    if not tasks:
        print("No tasks.")
        return

    status_map = task_status_map(tasks)
    counts = Counter(t["status"] for t in tasks)
    total = len(tasks)

    # Header
    parts = []
    for s in ["done", "in-progress", "claimed", "pending", "stuck"]:
        c = counts.get(s, 0)
        if c:
            parts.append(f"{c} {s}")
    print(f"  {total} tasks: {', '.join(parts)}")
    print()

    # Active work (claimed + in-progress)
    active = [t for t in tasks if t["status"] in ("claimed", "in-progress")]
    active.sort(key=lambda t: t.get("claimed_at") or t.get("updated_at") or "")
    if active:
        print(f"  ACTIVE ({len(active)})")
        for t in active:
            agent = t.get("claimed_by") or "?"
            when = ago(t.get("claimed_at"))
            model = f"[{t['model']:6s}]  " if t.get("model") else ""
            print(f"    {t['id'][:8]}  {model}{trunc(t['title'])}  ({agent}, {when})")
        print()

    # Stuck
    stuck = [t for t in tasks if t["status"] == "stuck"]
    if stuck:
        print(f"  STUCK ({len(stuck)})")
        for t in stuck:
            model = f"[{t['model']:6s}]  " if t.get("model") else ""
            print(f"    {t['id'][:8]}  {model}{trunc(t['title'])}")
        print()

    # Ready to claim
    ready = []
    for t in tasks:
        if t["status"] != "pending" or t["claimed_by"] is not None:
            continue
        if all(status_map.get(bid) == "done" for bid in t.get("blocked_by", [])):
            ready.append(t)
    ready.sort(key=lambda t: t.get("created_at", ""))
    if ready:
        print(f"  READY ({len(ready)})")
        for t in ready[:15]:
            model = f"[{t['model']:6s}]  " if t.get("model") else ""
            print(f"    {t['id'][:8]}  {model}{trunc(t['title'])}")
        if len(ready) > 15:
            print(f"    ... and {len(ready) - 15} more")
        print()

    # Blocked
    blocked_count = counts.get("pending", 0) - len(ready)
    if blocked_count > 0:
        print(f"  BLOCKED ({blocked_count} pending tasks waiting on dependencies)")
        print()

    # Recently completed
    done = [t for t in tasks if t["status"] == "done" and t.get("completed_at")]
    done.sort(key=lambda t: t["completed_at"], reverse=True)
    if done:
        print(f"  RECENTLY DONE")
        for t in done[:10]:
            when = ago(t["completed_at"])
            print(f"    {t['id'][:8]}  {trunc(t['title'])}  ({when})")
        if len(done) > 10:
            print(f"    ... and {len(done) - 10} more completed")
        print()

    # Recently created
    by_created = sorted(tasks, key=lambda t: t.get("created_at", ""), reverse=True)
    print(f"  RECENTLY CREATED")
    for t in by_created[:10]:
        when = ago(t["created_at"])
        status = t["status"]
        print(f"    {t['id'][:8]}  {status:12s}  {trunc(t['title'])}  ({when})")
    if len(by_created) > 10:
        print(f"    ... and {len(by_created) - 10} more")
    print()

    # Model breakdown for non-done tasks
    remaining = [t for t in tasks if t["status"] != "done"]
    models_present = [t["model"] for t in remaining if t.get("model")]
    if models_present:
        model_counts = Counter(models_present)
        parts = [f"{c} {m}" for m, c in sorted(model_counts.items())]
        print(f"  REMAINING BY MODEL: {', '.join(parts)}")

    # Tag breakdown for non-done tasks (top 10)
    tag_counts = Counter()
    for t in remaining:
        for tag in t.get("tags", []):
            tag_counts[tag] += 1
    if tag_counts:
        top = tag_counts.most_common(10)
        print(f"  TOP TAGS (remaining): {', '.join(f'{tag}({c})' for tag, c in top)}")
