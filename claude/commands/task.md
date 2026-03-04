Pick up a task from the queue and process it.

# Setup

Read these files first. Every time. Do not skip.

1. `TASKS.md` — check the **Current Mode** (PLANNING or EXECUTION) and read the rules
2. Project instructions (CLAUDE.md or equivalent)

# Find and claim a task

```bash
tl0m find
```

If the user passed arguments after `/task`, apply them as filters:
- Tag-like (e.g., `area:scoring`): `tl0m find --tag <value>`
- Model name: `tl0m find --model <value>`
- UUID prefix: `tl0m show <prefix>` directly

Pick the highest priority, lowest phase task. Claim it:
```bash
tl0m claim <uuid> <agent-id>
```

# Read the task thoroughly

Run `tl0m show <uuid>` and read the full JSON.

# PLANNING MODE — Decompose the task

**In PLANNING mode, you must NEVER write application code. Your only job is to create child tasks or confirm a task is atomic.**

## Decide: is this task atomic?

A task is atomic ONLY if ALL of these are true:
- You can estimate it at **<= ~200 lines of code** (excluding tests)
- It touches **<= 5 files**
- It is **one coherent concept** (one migration, one service, one component)
- The description is **self-contained** — no "see parent" or "as described above"
- An agent could implement it **without making architectural decisions**

If the task IS atomic:
```bash
tl0m done <uuid> --result "Atomic — ready for implementation. Estimated ~N lines across M files."
```

If the task is NOT atomic, **decompose it**.

## How to decompose

### 1. Identify the seams

Find natural boundaries:
- **Separate tables** — one task per table
- **Separate layers** (repository vs. service vs. resolver)
- **Separate domains**
- **Setup vs. logic**
- **Interface vs. implementation**
- **Verification** (write the code vs. verify integration)

### 2. Create child tasks

For EACH child:

```bash
tl0m create \
  --title "Concise action phrase" \
  --description "FULLY SELF-CONTAINED instruction..." \
  --tags "phase:N,area:X,priority:Y,type:atomic" \
  --parent <parent-uuid>
```

Set `--blocked-by` between siblings where ordering matters.

### 3. Transfer the parent's dependencies

Move the parent's `blocked_by` to the FIRST child tasks that actually depend on them.

### 4. Include verification tasks

For every group of 3+ implementation tasks, add a **verification task** as the last sibling (tag with `type:verify`).

### 5. Complete the parent

```bash
tl0m done <parent-uuid> \
  --result "Decomposed into N tasks: [one-line summary of each child]" \
  --created "uuid1,uuid2,uuid3,..."
```

## Decomposition depth

Decompose **one level at a time**. If a child is still too big, it'll get picked up and decomposed on the next pass.

# EXECUTION MODE — Implement the task

**Only applies when TASKS.md says EXECUTION mode.**

Even in execution mode, check task size first. If too big, decompose instead.

1. Implement the code described in `description` — match design specs exactly
2. Write tests for every implementation task
3. Run typecheck and tests, fix failures
4. Commit with message: `[task:<first-8-chars>] <what was built>`
5. Complete the task:
```bash
tl0m done <uuid> --result "Built [what]. Files: [list]. Key decisions: [any]. Notes for downstream: [any]."
```

# When stuck

1. Check completed related tasks — their `result` may help
2. If stuck, write what went wrong and stop

# Rules

- **PLANNING mode = no application code. Only task creation.**
- **Never mark a big task as "atomic" to avoid decomposing it.**
- **Descriptions must be self-contained.**
- **Always include verification tasks** when decomposing.
