"""tl0m — Machine-facing CLI for the tl0 task coordination system.

Intended for use by AI agents running inside a tl0 task loop.
Task-specific commands (create, done, free) require TL0_TASK_ID to be set.
Bootstrap commands (find, claim, show, update) do not require TL0_TASK_ID.
"""

import argparse
import os
import sys

# Commands that require TL0_TASK_ID to be set.
# find/claim/show/update are exempt: they operate on arbitrary tasks, not the current one.
_TASK_CONTEXT_COMMANDS = {"create", "done", "complete", "free", "release"}


def _require_task_id(cmd: str):
    if cmd in _TASK_CONTEXT_COMMANDS and not os.environ.get("TL0_TASK_ID"):
        print(
            f"Error: TL0_TASK_ID must be set to use 'tl0m {cmd}'.\n"
            "This variable is set automatically by the tl0 task loop.",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="tl0m",
        description="tl0 machine interface — for AI agents running inside a task loop",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # find / ready — no TL0_TASK_ID required
    sub.add_parser("find", help="Find tasks ready to be claimed")
    sub.add_parser("ready", help="Alias for find")

    # claim — no TL0_TASK_ID required
    sub.add_parser("claim", help="Claim a task")

    # show / get — no TL0_TASK_ID required; defaults to TL0_TASK_ID when called with no args
    sub.add_parser("show", help="Show task details (defaults to current task if TL0_TASK_ID is set)")
    sub.add_parser("get", help="Alias for show")

    # update — no TL0_TASK_ID required; operates on arbitrary tasks
    sub.add_parser("update", help="Update task fields (e.g. tags, model, status)")

    # create — requires TL0_TASK_ID; source auto-set from env var
    sub.add_parser("create", help="Create a new subtask (source auto-set from TL0_TASK_ID)")

    # done / complete — requires TL0_TASK_ID; task ID defaults to TL0_TASK_ID
    sub.add_parser("done", help="Mark the current task as done")
    sub.add_parser("complete", help="Alias for done")

    # free / release — requires TL0_TASK_ID; task ID defaults to TL0_TASK_ID
    sub.add_parser("free", help="Release the current task back to pending")
    sub.add_parser("release", help="Alias for free")

    args, remaining = parser.parse_known_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cmd = args.command
    _require_task_id(cmd)

    if cmd in ("find", "ready"):
        from tl0.commands.find_ready import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("claim",):
        from tl0.commands.claim import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("show", "get"):
        from tl0.commands.show import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("update",):
        from tl0.commands.update import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("create",):
        from tl0.commands.create import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("done", "complete"):
        from tl0.commands.complete import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("free", "release"):
        from tl0.commands.free import main as cmd_main
        cmd_main(remaining)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
