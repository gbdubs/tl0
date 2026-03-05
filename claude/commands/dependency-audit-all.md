Run dependency-audit across all tasks in the tree, working phase by phase.

# Setup

Read `TASKS.md` first.

# What this command does

This is the batch orchestrator for `/dependency-audit`. It processes the ENTIRE task tree systematically, tracking which tasks have been audited and which remain.

# Step 1: Build the catalog and check progress

```bash
tl0h catalog
```

Check if prior audit work exists:
```bash
cat .context/dep-audit-progress.json 2>/dev/null || echo '{"audited": [], "proposals": []}'
```

# Step 2: Identify unaudited tasks

Load all leaf tasks and subtract the already-audited set. Group remaining by phase.

# Step 3: Process in batches by phase

Work through phases in order: 0, 1, 2, 3, 4, 5. Within each phase, process in batches of 20-30 tasks.

For each batch:
- Read the catalog section for this phase
- Analyze each task (same reasoning as `/dependency-audit`)
- Append proposals to `.context/dep-audit-proposals.json`
- Update `.context/dep-audit-progress.json`
- Validate periodically with `tl0h apply-deps ... --dry-run`

# Step 4: Final report

```bash
tl0h apply-deps .context/dep-audit-proposals.json --dry-run
```

# Resumability

This command is designed to be resumed across sessions via the progress file.
