"""Show or manage task execution transcripts."""

import argparse
import json
import sys
from pathlib import Path

from tl0.common import load_all_tasks, resolve_prefix, task_status, TRANSCRIPTS_FOLDER


def _load_events(path: Path) -> list[dict]:
    """Parse a JSONL transcript file into a list of events."""
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _list_transcript_files(transcript_dir: Path) -> list[Path]:
    """List transcript files in a task's transcript directory, sorted by name."""
    files = []
    if transcript_dir.is_dir():
        files = sorted(transcript_dir.glob("*.jsonl"))
    return files


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Show task execution transcripts")
    parser.add_argument("task_id", help="Task UUID (prefix match OK)")
    parser.add_argument("--path", action="store_true", help="Print transcript directory/file path(s)")
    parser.add_argument("--summary", action="store_true", help="Show a summary of the transcript(s)")
    parser.add_argument("--raw", action="store_true", help="Print raw JSONL content")
    parser.add_argument("--loop-log", action="store_true", help="Show the task loop orchestration log")
    parser.add_argument("--label", help="Show only the transcript with this label (e.g. 'execute', 'merge-conflict')")
    args = parser.parse_args(argv)

    task = resolve_prefix(args.task_id)
    task_id = task["id"]
    transcript_dir = TRANSCRIPTS_FOLDER / task_id

    if not transcript_dir.exists():
        print(f"No transcripts found for task {task_id[:8]} ({task['title']})", file=sys.stderr)
        sys.exit(1)

    # --loop-log: show the orchestration log
    if args.loop_log:
        loop_log = transcript_dir / "loop.log"
        if not loop_log.exists():
            print(f"No loop log found for task {task_id[:8]}", file=sys.stderr)
            sys.exit(1)
        print(loop_log.read_text(), end="")
        return

    # --path: print directory or file paths
    if args.path:
        if args.label:
            matches = sorted(transcript_dir.glob(f"*-{args.label}.jsonl"))
            for m in matches:
                print(m)
            if not matches:
                print(f"No transcript matching label '{args.label}'", file=sys.stderr)
                sys.exit(1)
        else:
            print(transcript_dir)
        return

    # Collect transcript files
    if args.label:
        transcript_files = sorted(transcript_dir.glob(f"*-{args.label}.jsonl"))
        if not transcript_files:
            print(f"No transcript matching label '{args.label}' for task {task_id[:8]}", file=sys.stderr)
            sys.exit(1)
    else:
        transcript_files = _list_transcript_files(transcript_dir)

    if not transcript_files:
        print(f"No transcript files found in {transcript_dir}", file=sys.stderr)
        sys.exit(1)

    if args.raw:
        for tf in transcript_files:
            if len(transcript_files) > 1:
                print(f"--- {tf.name} ---")
            print(tf.read_text(), end="")
        return

    if args.summary:
        _print_summary(task, transcript_dir, transcript_files)
    else:
        # Default: print all events from all transcripts
        for tf in transcript_files:
            if len(transcript_files) > 1:
                print(f"\n--- {tf.name} ---")
            for event in _load_events(tf):
                print(json.dumps(event, indent=2))


def _print_summary(task: dict, transcript_dir: Path, transcript_files: list[Path]):
    """Print a human-readable summary of all transcripts for a task."""
    print(f"Transcript for task {task['id'][:8]}: {task['title']}")
    print(f"  Status: {task_status(task)}")
    print(f"  Transcript dir: {transcript_dir}")
    print(f"  Claude invocations: {len(transcript_files)}")

    # Show loop log info if it exists
    loop_log = transcript_dir / "loop.log"
    if loop_log.exists():
        line_count = len(loop_log.read_text().splitlines())
        print(f"  Loop log: {line_count} lines (use --loop-log to view)")

    for tf in transcript_files:
        events = _load_events(tf)
        print(f"\n  [{tf.name}]")
        print(f"    Events: {len(events)}")

        # Count event types
        type_counts: dict[str, int] = {}
        tool_counts: dict[str, int] = {}
        for e in events:
            etype = e.get("type", "unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1

            # Count tool uses
            if etype == "assistant" and isinstance(e.get("message", {}).get("content"), list):
                for block in e["message"]["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

        print(f"    Event types: {', '.join(f'{t}:{c}' for t, c in sorted(type_counts.items()))}")

        if tool_counts:
            print(f"    Tool usage: {', '.join(f'{t}:{c}' for t, c in sorted(tool_counts.items(), key=lambda x: -x[1]))}")

        # Show result if present
        for e in reversed(events):
            if e.get("type") == "result":
                result = e.get("result", "")
                if isinstance(result, str):
                    text = result
                elif isinstance(result, list):
                    text = " ".join(
                        b.get("text", "") for b in result
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                else:
                    text = str(result)
                if text:
                    print(f"    Result: {text[:200]}{'...' if len(text) > 200 else ''}")
                break
