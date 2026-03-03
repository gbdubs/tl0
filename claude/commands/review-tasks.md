Review the task tree for gaps, ambiguities, and risks.

# Setup

Read `TASKS.md` and project instructions first.

# What this command does

This is an analysis pass across the task tree. You are NOT decomposing or implementing — you are auditing the task tree for problems and creating new tasks to address them.

# Step 1: Load the full task tree

```bash
tl0 show --brief --status pending
tl0 show --brief --status done
tl0 show --brief --status stuck
```

If the user passed arguments, focus on that area:
- Tag filter: `tl0 show --brief --tag <value>`
- UUID: `tl0 show <prefix>` for a specific subtree

# Step 2: Pick a review focus

Choose ONE of the following review types (or use what the user specified):

## A. Boundary Review
Check interfaces between adjacent subsystems. Create `type:verify` tasks for uncovered boundaries.

## B. Ambiguity Review
For each leaf task, flag where design docs are vague or underspecified. Create `type:review` tasks for significant ambiguities.

## C. Completeness Review
Compare the task tree against design documents. Create new tasks for anything missing.

## D. Risk Review
Identify highest-risk areas. Create `type:verify` tasks for risky assumptions.

## E. Sizing Review
Check leaf tasks for sizing. Reset oversized "atomic" tasks to `type:decompose`.

# Step 3: Report

- How many tasks reviewed
- Issues found (categorized)
- Tasks created
- Recommendations for next review focus

Run `tl0 validate` at the end.
