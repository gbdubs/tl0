# tl0

Task coordination system for parallel AI agents.

tl0 manages a tree+DAG of tasks stored as git-backed JSON files. Multiple agents can claim, implement, and complete tasks concurrently with atomic claiming and automatic conflict resolution.

## Install

```bash
python3 -m pip install -e .
```

After installing, ensure the Python scripts directory is on your PATH. If you see a warning like _"The scripts tl0h and tl0m are installed in '...' which is not on PATH"_, add the listed directory:

```bash
# Add to your ~/.zshrc (or ~/.bashrc):
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"
```

Then restart your shell or run `source ~/.zshrc`.

## CLIs

tl0 provides two separate CLIs:

- **`tl0h`** — Human-facing interface (project init, viewer, supervisor, etc.)
- **`tl0m`** — Machine-facing interface for AI agents running in task loops

`tl0h` is blocked inside task loops (via `TL0_TASK_ID` env var guard). Agents must use `tl0m`.

## Quick Start

```bash
# Initialize a project
tl0h init --name my-project

# Create tasks
tl0h create --title "Build auth service" --description "Implement JWT-based auth..." --tags "phase:1,area:auth"
tl0h create --title "Build user model" --description "Create user table migration..." --tags "phase:0,area:database"

# Find and claim work (human or machine)
tl0m find                    # List claimable tasks
tl0m claim <uuid> my-agent   # Claim a task
tl0m done <uuid> --result "Built auth service with tests"

# Monitor
tl0h show --all              # Show all tasks
tl0h viewer                  # Web UI
tl0h supervisor              # Manage parallel task loops
```

## Task Model

Tasks form a **tree** (via `task_parent`) and a **DAG** (via `blocked_by`):

- **Tree**: Parent tasks decompose into children. A parent is done when all children are done.
- **DAG**: `blocked_by` captures ordering constraints. A task is claimable only when all blockers are done.
- **Leaf tasks**: Tasks with no children — only these get implemented.

### Lifecycle

```
pending → claimed → done
        ↑         |
        └─────────┘  (freed → back to pending)
```

## Configuration

Create `tl0.json` in your project root (or set `TL0_TASKS_DIR` env var):

```json
{
  "project_name": "my-project",
  "tasks_dir": "~/my-project-tasks",
  "valid_models": ["opus", "sonnet", "haiku"]
}
```

## CLI Commands

### `tl0h` — Human Interface

| Command | Description |
|---------|-------------|
| `tl0h init` | Initialize a new tl0 project |
| `tl0h create` | Create a new task |
| `tl0h show` | Show task(s) by ID or filter |
| `tl0h status` | Compact task system dashboard |
| `tl0h validate` | Validate all tasks and report errors |
| `tl0h trace` | Trace a task back to its progenitor |
| `tl0h transcript` | Show execution transcript for a task |
| `tl0h catalog` | Build task catalog for dependency auditing |
| `tl0h apply-deps` | Apply dependency audit proposals |
| `tl0h viewer` | Interactive web-based task viewer |
| `tl0h supervisor` | Web UI to manage parallel task loops |
| `tl0h free-all` | Free all claimed tasks back to pending |
| `tl0h reset` | Delete all tasks (destructive) |
| `tl0h resume` | Resume a preserved task (merge only) |

### `tl0m` — Machine Interface

| Command | Description |
|---------|-------------|
| `tl0m find` | Find claimable tasks (pending, unblocked) |
| `tl0m claim` | Claim a task for an agent |
| `tl0m show` | Show task details (defaults to current task) |
| `tl0m update` | Update task fields |
| `tl0m create` | Create a subtask (requires `TL0_TASK_ID`) |
| `tl0m done` | Mark the current task as done (requires `TL0_TASK_ID`) |
| `tl0m free` | Release the current task (requires `TL0_TASK_ID`) |

## Claude Code Integration

tl0 ships with Claude Code commands in `claude/commands/`. Copy them to your project's `.claude/commands/` to enable:

- `/task` — Pick up and process a task from the queue
- `/task-loop-reset` — Diagnose and fix stalled agent state
- `/dependency-audit` — Audit task dependencies
- `/dependency-audit-all` — Full-tree dependency audit
- `/review-tasks` — Audit task tree for gaps and risks

## Task Loop

The task loop (`tl0/loop/task_loop.sh`) continuously claims tasks, runs them in git worktrees, and merges results back to main. It handles merge conflicts, retries, and parallel execution safely.

```bash
tl0h supervisor                        # Web UI for managing loops
./tl0/loop/task_loop.sh                # Run continuously
./tl0/loop/task_loop.sh --model sonnet # Filter by model
./tl0/loop/task_loop.sh --once         # Run one task
./tl0/loop/task_loop.sh --resume <uuid># Resume a failed task
```

## Schema

Tasks are JSON files with these core fields:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | UUID, matches filename |
| `title` | yes | Concise, action-oriented |
| `description` | yes | Full implementation spec |
| `events` | yes | Append-only lifecycle log; status is derived from this |
| `blocked_by` | yes | UUIDs that must be done first |
| `tags` | yes | Freeform labels (`category:value`) |
| `model` | no | AI model to use |
| `thinking` | no | Extended thinking mode |
| `task_parent` | no | Parent task UUID |
| `task_children` | no | Child task UUIDs |
| `produces` | no | File paths created/modified |
| `context_files` | no | Files to read before starting |
| `design_references` | no | Design doc references |
| `result` | no | Completion summary (set when done) |

## License

MIT
