# Task System

This project uses tl0 to coordinate work across parallel agents. Task data lives at the configured tasks directory. Use `tl0h` for human operations and `tl0m` for agent operations inside a task loop.

## Current Mode: EXECUTION

**The project is in EXECUTION mode.** Agents claim leaf tasks and implement them — writing code, tests, and marking tasks done with a summary of what was built.

## How the Task Tree Works

Tasks form a **tree** via `task_parent`, and a **DAG** via `blocked_by`.

- **`task_parent`** means "I am a part of this larger task." A parent is done when ALL its children are done.
- **`blocked_by`** means "I cannot start until these other tasks are done." This captures ordering constraints across the tree.
- A task with **no children** is a **leaf task**. Only leaf tasks get implemented.

### Task Lifecycle

Status is derived from the `events` array (append-only log):

```
pending → claimed → done
        ↑         |
        └─────────┘  (freed → back to pending)
```

## CLI Reference

Human operations (`tl0h`):
```bash
tl0h show {uuid-prefix}               # View a task (first 8 chars of UUID is enough)
tl0h show --brief --status pending    # Brief list with filters
tl0h show --brief --tag phase:1       # Filter by tag
tl0h status                           # Dashboard summary
tl0h validate                         # Check all tasks for errors
tl0h create --title "..." --description "..." --tags 'a,b' --blocked-by 'uuid1' --parent 'uuid'
tl0h free-all                         # Release all claimed tasks
```

Agent operations (`tl0m`, requires `TL0_TASK_ID` for task-scoped commands):
```bash
tl0m find                             # List claimable tasks (pending, unblocked, unclaimed)
tl0m find --model sonnet --tag X      # Filter by model or tag
tl0m claim {uuid} {agent-id}          # Claim a task
tl0m show                             # Show current task (uses TL0_TASK_ID)
tl0m show {uuid-prefix}               # Show a specific task
tl0m done --result "..."              # Complete current task
tl0m done --result "..." --created "uuid1,uuid2"  # Complete + link child tasks
tl0m create --title "..." --description "..." --tags 'a,b' --blocked-by 'uuid1' --parent 'uuid'
tl0m update {uuid} --add-blocked-by {uuid}  # Update fields
```

## Tag Conventions

- `phase:N` — implementation phase
- `area:X` — system area
- `priority:X` — critical / high / medium / low
- `type:X` — decompose / atomic / verify / review

## What Makes a Task Atomic

A leaf task is **atomic** when:
- **<= ~200 lines of new code** (excluding tests)
- **<= 5 files** created or modified
- **One coherent concept**
- **Self-contained description**
- **Clear inputs and outputs**

## When Stuck

1. Try to resolve it yourself
2. If you can't, write what went wrong to `.task-result.txt` and stop — the loop will free the task
