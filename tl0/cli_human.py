"""tl0h — Human-facing CLI for the tl0 task coordination system.

Not available inside a task loop. Use tl0m for machine/agent commands.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tl0.config import load_config


def _guard_not_in_task_loop():
    if os.environ.get("TL0_TASK_ID"):
        print(
            "Error: tl0h is not available from within a task execution loop.\n"
            "Use tl0m for machine/agent commands.",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_init(args):
    """Initialize a new tl0 project."""
    config_path = Path("tl0.json")
    if config_path.exists() and not args.force:
        print(f"tl0.json already exists. Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    project_name = args.name or Path.cwd().name
    tasks_dir = args.tasks_dir or f"~/{project_name}-tasks"

    config = {
        "project_name": project_name,
        "tasks_dir": tasks_dir,
    }

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    # Create the tasks directory and initialize git
    resolved = Path(tasks_dir).expanduser().resolve()
    tasks_folder = resolved / "tasks"
    transcripts_folder = resolved / "transcripts"
    tasks_folder.mkdir(parents=True, exist_ok=True)
    transcripts_folder.mkdir(parents=True, exist_ok=True)

    if not (resolved / ".git").exists():
        subprocess.run(["git", "init"], cwd=resolved, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=resolved, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init: tl0 task store", "--allow-empty"],
            cwd=resolved, capture_output=True
        )

    print(f"Initialized tl0 project:")
    print(f"  Config:    {config_path.resolve()}")
    print(f"  Tasks dir: {resolved}")
    print(f"  Tasks:     {tasks_folder}")


def main():
    _guard_not_in_task_loop()

    parser = argparse.ArgumentParser(
        prog="tl0h",
        description="tl0 human interface — task coordination for parallel AI agents",
    )
    parser.add_argument('-C', '--project-dir', type=str,
                        help='Run as if invoked from this directory')
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = sub.add_parser("init", help="Initialize a new tl0 project")
    p_init.add_argument("--name", help="Project name (default: directory name)")
    p_init.add_argument("--tasks-dir", help="Tasks directory path")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")

    # create
    sub.add_parser("create", help="Create a new task")

    # show
    sub.add_parser("show", help="Show task(s) by ID or filter")
    sub.add_parser("get", help="Alias for show")

    # viewer
    sub.add_parser("viewer", help="Interactive web-based task viewer")

    # supervisor
    sub.add_parser("supervisor", help="Web UI to manage parallel task loops")

    # resume
    sub.add_parser("resume", help="Resume a preserved task (merge only, skip claude)")

    # free-all
    sub.add_parser("free-all", help="Free all claimed tasks back to pending")

    # status
    sub.add_parser("status", help="Show compact task system dashboard")

    # validate
    sub.add_parser("validate", help="Validate all tasks and report errors")

    # reset
    sub.add_parser("reset", help="Delete all tasks (destructive)")

    # trace
    sub.add_parser("trace", help="Trace a task back to its progenitor")

    # transcript
    sub.add_parser("transcript", help="Show execution transcript for a task")

    # catalog
    sub.add_parser("catalog", help="Build task catalog markdown for dependency auditing")

    # apply-deps
    sub.add_parser("apply-deps", help="Apply dependency audit proposals to the task tree")

    # reset-quota-errors
    sub.add_parser("reset-quota-errors", help="Reset tasks erroneously completed due to quota/rate-limit errors")

    # reset-failed
    sub.add_parser("reset-failed", help="Reset failed tasks back to pending so they can be retried")

    # Parse just the command name, pass the rest through to subcommands
    args, remaining = parser.parse_known_args()

    # Change working directory before any subcommand imports (which resolve config from cwd)
    if args.project_dir:
        target = Path(args.project_dir).expanduser().resolve()
        if not target.is_dir():
            print(f"Error: --project-dir '{args.project_dir}' is not a directory", file=sys.stderr)
            sys.exit(1)
        os.chdir(target)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cmd = args.command

    if cmd == "init":
        args = p_init.parse_args(remaining)
        cmd_init(args)

    elif cmd in ("create",):
        from tl0.commands.create import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("show", "get"):
        from tl0.commands.show import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("viewer",):
        from tl0.commands.viewer import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("supervisor",):
        from tl0.commands.supervisor import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("resume",):
        # Delegate to the task loop script with --resume --once
        loop_script = Path(__file__).parent / "loop" / "task_loop.sh"
        if not loop_script.exists():
            print(f"Error: task loop script not found at {loop_script}", file=sys.stderr)
            sys.exit(1)
        os.execvp("bash", ["bash", str(loop_script), "--once", "--resume"] + remaining)

    elif cmd in ("free-all",):
        from tl0.commands.free_all import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("status",):
        from tl0.commands.status import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("validate",):
        from tl0.commands.validate import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("reset",):
        from tl0.commands.reset import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("trace",):
        from tl0.commands.trace import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("transcript",):
        from tl0.commands.transcript import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("catalog",):
        from tl0.analysis.build_catalog import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("apply-deps",):
        from tl0.analysis.apply_deps import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("reset-quota-errors",):
        from tl0.commands.reset_quota_errors import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("reset-failed",):
        from tl0.commands.reset_failed import main as cmd_main
        cmd_main(remaining)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
