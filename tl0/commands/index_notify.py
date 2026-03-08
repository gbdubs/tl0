"""Notify the index of task or transcript changes."""

import argparse


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Notify index of changes")
    parser.add_argument("--task", required=True, help="Task ID that changed")
    parser.add_argument("--transcript", help="Transcript filename that was written")
    args = parser.parse_args(argv)

    from tl0.common import _get_index
    index = _get_index()

    if args.transcript:
        index.notify_transcript_written(args.task, args.transcript)
    else:
        index.notify_task_changed(args.task)
