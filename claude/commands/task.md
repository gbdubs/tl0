Pick up a task from the queue and process it.

# Setup

Read these files first. Every time. Do not skip.

1. `TASKS.md` — check the **Current Mode** (PLANNING or EXECUTION) and read the rules
2. Project instructions (CLAUDE.md or equivalent)

# Find and claim a task

```bash
tl0 find
```

If the user passed arguments after `/task`, apply them as filters:
- Tag-like (e.g., `area:scoring`): `tl0 find --tag <value>`
- Model name: `tl0 find --model <value>`
- UUID prefix: `tl0 show <prefix>` directly

Pick the highest priority, lowest phase task. Claim it:
```bash
tl0 claim <uuid> <agent-id>
```

# Read the task thoroughly

Run `tl0 show <uuid>` and read the full JSON.

Then read EVERY file listed in `design_references` — read the actual design file and section referenced, not just the task description. Also read any `context_files`.

# PLANNING MODE — Decompose the task

**In PLANNING mode, you must NEVER write application code. Your only job is to create child tasks or confirm a task is atomic.**

## Decide: is this task atomic?

A task is atomic ONLY if ALL of these are true:
- You can estimate it at **<= ~200 lines of code** (excluding tests)
- It touches **<= 5 files**
- It is **one coherent concept** (one migration, one service, one component)
- The description is **self-contained** — no "see parent" or "as described above"
- It references **1-2 specific design sections**, not whole documents
- An agent could implement it **without making architectural decisions**

If the task IS atomic:
```bash
tl0 done <uuid> --result "Atomic — ready for implementation. Estimated ~N lines across M files. Produces: [brief list]."
```

If the task is NOT atomic, **decompose it**.

## How to decompose

### 1. Identify the seams

Read the design references and find natural boundaries:
- **Separate tables** — one task per table
- **Separate layers** (repository vs. service vs. resolver)
- **Separate domains**
- **Setup vs. logic**
- **Interface vs. implementation**
- **Verification** (write the code vs. verify integration)

### 2. Create child tasks

For EACH child:

```bash
tl0 create \
  --title "Concise action phrase" \
  --description "FULLY SELF-CONTAINED instruction..." \
  --tags "phase:N,area:X,priority:Y,type:atomic" \
  --parent <parent-uuid> \
  --design-refs "FILE.md:SECTION:NOTE" \
  --produces "path/to/file1,path/to/file2"
```

Set `--blocked-by` between siblings where ordering matters.

### 3. Transfer the parent's dependencies

Move the parent's `blocked_by` to the FIRST child tasks that actually depend on them.

### 4. Include verification tasks

For every group of 3+ implementation tasks, add a **verification task** as the last sibling (tag with `type:verify`).

### 5. Complete the parent

```bash
tl0 done <parent-uuid> \
  --result "Decomposed into N tasks: [one-line summary of each child]" \
  --created "uuid1,uuid2,uuid3,..."
```

### 6. Validate

```bash
tl0 validate
```

## Decomposition depth

Decompose **one level at a time**. If a child is still too big, it'll get picked up and decomposed on the next pass.

# EXECUTION MODE — Implement the task

**Only applies when TASKS.md says EXECUTION mode.**

Even in execution mode, check task size first. If too big, decompose instead.

1. Read all `design_references` and `context_files`
2. Implement the code described in `description` — match design specs exactly
3. Write tests for every implementation task
4. Run typecheck and tests, fix failures
5. Commit with message: `[task:<first-8-chars>] <what was built>`
6. Complete the task:
```bash
tl0 done <uuid> --result "Built [what]. Files: [list]. Key decisions: [any]. Notes for downstream: [any]."
```

# When stuck

1. Re-read design references
2. Check completed related tasks — their `result` may help
3. If stuck:
   ```bash
   tl0 update <uuid> --status stuck
   tl0 create --title "Resolve: <question>" --description "<detailed context>" --parent <uuid>
   tl0 update <uuid> --add-blocked-by <new-resolution-uuid>
   ```

# Rules

- **PLANNING mode = no application code. Only task creation.**
- **Never mark a big task as "atomic" to avoid decomposing it.**
- **Descriptions must be self-contained.**
- **Always include verification tasks** when decomposing.
- **Run `tl0 validate`** after creating tasks.
