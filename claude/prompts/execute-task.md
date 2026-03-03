# Execute a Task

You have been assigned a task to implement. The task ID and agent ID are provided at the end of this prompt as TASK_ID and AGENT_ID.

You are running in a git worktree branched from main. Your job is to implement the task and commit your work. The outer loop handles merging to main and marking the task done — you do NOT do those things.

## Step 1: Read the task

```bash
tl0 show $TASK_ID
```

Read the full task JSON carefully. Pay attention to:
- `description` — this is your implementation spec
- `design_references` — read EVERY referenced file and section
- `context_files` — read these too
- `produces` — expected output files (guidance, not gospel)
- `blocked_by` — these are done; check their `result` fields for useful context

## Step 2: Read design references

For each entry in `design_references`, read the actual file and find the referenced section. These are the source of truth.

If the task has `context_files`, read those too.

## Step 3: Check task size

If the task is too large to implement in one pass (> ~200 lines, > 5 files, multiple unrelated concerns), **decompose it instead of implementing it**:

```bash
tl0 create --title "..." --description "..." --tags "..." --parent $TASK_ID --produces "..."
# ... create all children ...
tl0 done $TASK_ID --result "Decomposed into N tasks" --created "uuid1,uuid2,..."
```

Then stop. The outer loop will pick up the children.

## Step 4: Implement

Write the code described in the task description. Follow design specs exactly.

Guidelines:
- Match existing code style and patterns in the codebase
- Use the exact function signatures, types, and interfaces specified in design docs
- Import from the paths specified in design references
- Don't add features or abstractions beyond what the task describes
- Don't refactor adjacent code

## Step 5: Write tests

Write tests for everything you implement.

## Step 6: Verify

Run the project's verification commands (typecheck, tests, etc.) and fix any failures.

## Step 7: Commit early and often

Commit as you go — don't save it all for the end. Use messages referencing the task:

```bash
git add <specific files>
git commit -m "[task:${TASK_ID:0:8}] <concise summary>"
```

## Step 8: Write a result summary

**CRITICAL: You MUST actually execute a shell command to write this file. Do not just describe or narrate writing it — run the command.**

When finished, write a result summary to `.task-result.txt` in the repo root by executing this shell command:

```bash
echo "Built <what>. Files: <list>. Key decisions: <any>. Notes for downstream: <any>." > .task-result.txt
```

The outer loop reads this file to determine success. If the file does not exist on disk, the task will be marked as failed regardless of what you output as text.

Do NOT call `tl0 done` yourself. The outer loop handles that.
Do NOT commit `.task-result.txt`.

## If stuck

1. Re-read design references and related completed tasks
2. If truly stuck, write what went wrong to `.task-result.txt` and stop

## Rules

- Implement exactly what the task describes. Nothing more.
- Every implementation needs tests.
- Commit your work before writing the result summary.
- If the task is too big, decompose instead of implementing.
- Never call `tl0 done` — the loop owns that.
