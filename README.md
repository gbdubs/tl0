# tl0

Task coordination system for parallel AI agents.

tl0 manages a tree+DAG of tasks stored as git-backed JSON files. Multiple agents can claim, implement, and complete tasks concurrently with atomic claiming and automatic conflict resolution.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# Initialize a project
tl0 init --name my-project

# Create tasks
tl0 create --title "Build auth service" --description "Implement JWT-based auth..." --tags "phase:1,area:auth"
tl0 create --title "Build user model" --description "Create user table migration..." --tags "phase:0,area:database"

# Find and claim work
tl0 find                    # List claimable tasks
tl0 claim <uuid> my-agent   # Claim a task
tl0 done <uuid> --result "Built auth service with tests"

# Monitor
tl0 status                  # Dashboard
tl0 viewer                  # Web UI
tl0 validate                # Check tree integrity
```

## Task Model

Tasks form a **tree** (via `parent_task`) and a **DAG** (via `blocked_by`):

- **Tree**: Parent tasks decompose into children. A parent is done when all children are done.
- **DAG**: `blocked_by` captures ordering constraints. A task is claimable only when all blockers are done.
- **Leaf tasks**: Tasks with no children — only these get implemented.

### Lifecycle

```
pending → claimed → in-progress → done
                                → stuck
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

| Command | Description |
|---------|-------------|
| `tl0 init` | Initialize a new tl0 project |
| `tl0 create` | Create a new task |
| `tl0 find` | Find claimable tasks (pending, unblocked) |
| `tl0 show` | Show task(s) by ID or filter |
| `tl0 claim` | Claim a task for an agent |
| `tl0 done` | Mark a task as done |
| `tl0 free` | Release a claimed/stuck task back to pending |
| `tl0 update` | Update task fields |
| `tl0 validate` | Check all tasks for errors |
| `tl0 status` | Print dashboard summary |
| `tl0 reset` | Delete all tasks (requires `--force`) |
| `tl0 viewer` | Interactive web-based task viewer |
| `tl0 catalog` | Build markdown catalog for auditing |
| `tl0 apply-deps` | Apply dependency audit proposals |

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
./tl0/loop/task_loop.sh                    # Run continuously
./tl0/loop/task_loop.sh --model sonnet     # Filter by model
./tl0/loop/task_loop.sh --once             # Run one task
./tl0/loop/task_loop.sh --resume <uuid>    # Resume a failed task
```

## Schema

Tasks are JSON files with these core fields:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | UUID, matches filename |
| `title` | yes | Concise, action-oriented |
| `description` | yes | Full implementation spec |
| `status` | yes | pending/claimed/in-progress/done/stuck |
| `blocked_by` | yes | UUIDs that must be done first |
| `tags` | yes | Freeform labels (`category:value`) |
| `model` | no | AI model to use |
| `thinking` | no | Extended thinking mode |
| `parent_task` | no | Parent task UUID |
| `tasks_created` | no | Child task UUIDs |
| `produces` | no | File paths created/modified |
| `context_files` | no | Files to read before starting |
| `design_references` | no | Design doc references |
| `result` | no | Completion summary (required when done) |

## License

MIT
