Audit and fix the blocked_by dependencies for a batch of tasks.

# Setup

Read these files first:
1. `TASKS.md` — understand the task schema, especially `blocked_by` semantics

# What this command does

You are auditing the task DAG. Many tasks are missing `blocked_by` edges — they appear "claimable" even though they depend on work that hasn't been done yet. Your job is to identify the real dependencies for a batch of tasks and produce a machine-readable proposals file.

# Step 1: Build or refresh the catalog

```bash
tl0h catalog
```

Then read the catalog file in your tasks directory. This is your reference for all tasks in the system.

# Step 2: Select the batch to audit

If the user passed arguments, interpret them as filters:
- `phase:N` — audit all leaf tasks in that phase
- `area:X` — audit all leaf tasks in that area
- A UUID prefix — audit just that one task
- `unblocked` — audit all leaf tasks with zero blockers
- `all` — audit every leaf task (process in phase order)

Default to `unblocked`.

# Step 3: For each task in the batch, analyze dependencies

For each task, read it with `tl0h show <uuid>` and reason through:

## 3a. What does this task REQUIRE to exist before it can be implemented?

Think about:
- **Database tables**: Does it query a table? The migration task must be a blocker.
- **Types/interfaces**: Does it import types? The defining task must be a blocker.
- **Service classes**: Does it call a service? The implementing task must be a blocker.
- **Infrastructure**: Does it assume scaffolding exists? Those tasks must be blockers.

## 3b. Search the catalog for tasks that produce those prerequisites

## 3c. Filter to DIRECT dependencies only

Transitivity handles the rest.

## 3d. Check phase consistency

A task should generally only be blocked by same-phase or lower-phase tasks.

# Step 4: Write proposals file

Create a JSON file at `.context/dep-audit-proposals.json`:

```json
[
  {
    "task_id": "full-or-prefix-uuid",
    "add_blocked_by": ["blocker-uuid-1", "blocker-uuid-2"],
    "reason": "Brief explanation"
  }
]
```

# Step 5: Dry-run validation

```bash
tl0h apply-deps .context/dep-audit-proposals.json --dry-run
```

# Step 6: Report

Output a summary of how many tasks audited, new edges proposed, etc.

Do NOT apply automatically. The user will apply with:
```bash
tl0h apply-deps .context/dep-audit-proposals.json
```

# Rules

- **Be thorough but not exhaustive**: 1-3 most critical blockers per task.
- **When uncertain, include the edge**: redundant edges are harmless.
- **Never remove existing blocked_by edges** — only add new ones.
- **Process tasks in phase order** (lowest first).
