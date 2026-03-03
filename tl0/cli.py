"""tl0 CLI — Task coordination system for parallel AI agents."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tl0.config import resolve_tasks_dir, load_config


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
    tasks_folder.mkdir(parents=True, exist_ok=True)

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
    parser = argparse.ArgumentParser(
        prog="tl0",
        description="Task coordination system for parallel AI agents",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = sub.add_parser("init", help="Initialize a new tl0 project")
    p_init.add_argument("--name", help="Project name (default: directory name)")
    p_init.add_argument("--tasks-dir", help="Tasks directory path")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")

    # create
    p_create = sub.add_parser("create", help="Create a new task")
    # (args handled by create.main)

    # find
    sub.add_parser("find", help="Find tasks ready to be claimed")
    sub.add_parser("ready", help="Alias for find")

    # show
    sub.add_parser("show", help="Show task(s) by ID or filter")
    sub.add_parser("get", help="Alias for show")

    # claim
    sub.add_parser("claim", help="Claim a task")

    # done / complete
    sub.add_parser("done", help="Mark a task as done")
    sub.add_parser("complete", help="Alias for done")

    # free / release
    sub.add_parser("free", help="Release a task back to pending")
    sub.add_parser("release", help="Alias for free")

    # free-all
    sub.add_parser("free-all", help="Free all claimed/in-progress/stuck tasks back to pending")

    # update
    sub.add_parser("update", help="Update task fields")

    # validate / check
    sub.add_parser("validate", help="Validate all tasks")
    sub.add_parser("check", help="Alias for validate")

    # status / dashboard
    sub.add_parser("status", help="Print dashboard summary")
    sub.add_parser("dashboard", help="Alias for status")

    # reset
    sub.add_parser("reset", help="Delete all tasks (requires --force)")

    # viewer
    sub.add_parser("viewer", help="Interactive web-based task viewer")

    # catalog
    sub.add_parser("catalog", help="Build task catalog for dependency auditing")

    # apply-deps
    sub.add_parser("apply-deps", help="Apply dependency audit proposals")

    # reset-for-execution
    sub.add_parser("reset-for-execution", help="Reset planning tasks for execution mode")

    # loop
    sub.add_parser("loop", help="Run task execution loop (claim, implement, merge)")

    # Parse just the command name, pass the rest through to subcommands
    args, remaining = parser.parse_known_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cmd = args.command

    if cmd == "init":
        # Re-parse with init-specific args
        args = p_init.parse_args(remaining)
        cmd_init(args)

    elif cmd in ("create",):
        from tl0.commands.create import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("find", "ready"):
        from tl0.commands.find_ready import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("show", "get"):
        from tl0.commands.show import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("claim",):
        from tl0.commands.claim import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("done", "complete"):
        from tl0.commands.complete import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("free", "release"):
        from tl0.commands.free import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("free-all",):
        from tl0.commands.free_all import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("update",):
        from tl0.commands.update import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("validate", "check"):
        from tl0.commands.validate import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("status", "dashboard"):
        from tl0.commands.status import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("reset",):
        from tl0.commands.reset import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("viewer",):
        from tl0.commands.viewer import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("catalog",):
        from tl0.analysis.build_catalog import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("apply-deps",):
        from tl0.analysis.apply_deps import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("reset-for-execution",):
        from tl0.analysis.reset_for_execution import main as cmd_main
        cmd_main(remaining)

    elif cmd in ("loop",):
        # Delegate to bash script — it manages worktrees, git, and claude
        loop_script = Path(__file__).parent / "loop" / "task_loop.sh"
        if not loop_script.exists():
            print(f"Error: task loop script not found at {loop_script}", file=sys.stderr)
            sys.exit(1)
        os.execvp("bash", ["bash", str(loop_script)] + remaining)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
