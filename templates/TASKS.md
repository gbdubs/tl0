# Task System

This project uses tl0 to coordinate work across parallel agents. Task data lives at the configured tasks directory, while the CLI is available as `tl0`.

## Current Mode: EXECUTION

**The project is in EXECUTION mode.** Agents claim leaf tasks and implement them — writing code, tests, and marking tasks done with a summary of what was built.

## How the Task Tree Works

Tasks form a **tree** via `parent_task`, and a **DAG** via `blocked_by`.

- **`parent_task`** means "I am a part of this larger task." A parent is done when ALL its children are done.
- **`blocked_by`** means "I cannot start until these other tasks are done." This captures ordering constraints across the tree.
- A task with **no children** is a **leaf task**. Only leaf tasks get implemented.

### Task Lifecycle

```
pending → claimed → in-progress → done
                                → stuck
```

## CLI Reference

```bash
tl0 find                              # List claimable tasks (pending, unblocked, unclaimed)
tl0 find --model sonnet --tag X       # Filter by model or tag
tl0 show {uuid-prefix}                # View a task (first 8 chars of UUID is enough)
tl0 show --brief --status pending     # Brief list with filters
tl0 status                            # Dashboard summary
tl0 claim {uuid} {agent-id}           # Claim a task
tl0 done {uuid} --result "..."        # Complete a task
tl0 done {uuid} --result "..." --created "uuid1,uuid2"  # Complete + link child tasks
tl0 create --title "..." --description "..." --tags 'a,b' --blocked-by 'uuid1' --parent 'uuid'
tl0 update {uuid} --status stuck      # Update fields
tl0 validate                          # Check all tasks for errors
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
2. If you can't:
   - Mark your task stuck: `tl0 update {uuid} --status stuck`
   - Create a resolution task: `tl0 create --title "Resolve: ..." --description "..." --parent {uuid}`
   - Add blocker: `tl0 update {uuid} --add-blocked-by {resolution-uuid}`
