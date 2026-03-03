Diagnose why no tasks are claimable and reset stalled task-loop state.

# What this command does

Task loops stall when agents die mid-run and leave behind orphaned state. This command finds and fixes two failure modes:

1. **Stale `claimed_by` on pending tasks** — a dead agent partially claimed a task but its status was rolled back to `pending` without clearing `claimed_by`. The `find` command silently skips these.
2. **Stale `claimed` tasks whose blockers are now done** — a dead agent claimed a task while it was blocked, the blockers completed, but no agent resumed.

# Step 1: Check current status

```bash
tl0 status
```

Look at:
- **ACTIVE** count — any claimed tasks with timestamps hours+ old are suspect
- **READY** count — if 0 despite many pending tasks, stale state is likely

# Step 2: Find stale `claimed_by` on pending tasks

```bash
python3 -c "
import json, os
from pathlib import Path

tasks_dir = Path(os.environ.get('TL0_TASKS_DIR', '')) or Path.home() / 'tl0-tasks'
tasks_folder = tasks_dir / 'tasks'

stale = []
for f in tasks_folder.glob('*.json'):
    d = json.load(open(f))
    if d['status'] == 'pending' and d.get('claimed_by'):
        stale.append((d['id'][:8], d.get('claimed_by',''), d['title'][:65]))

print(f'Pending tasks with stale claimed_by: {len(stale)}')
for s in stale:
    print(f'  {s[0]} (was: {s[1]}): {s[2]}')
"
```

# Step 3: Find stale `claimed` tasks with all blockers done

```bash
python3 -c "
import json, os
from pathlib import Path

tasks_dir = Path(os.environ.get('TL0_TASKS_DIR', '')) or Path.home() / 'tl0-tasks'
tasks_folder = tasks_dir / 'tasks'

tasks = {}
for f in tasks_folder.glob('*.json'):
    d = json.load(open(f))
    tasks[d['id']] = d

stalled = []
for t in tasks.values():
    if t['status'] != 'claimed':
        continue
    all_done = all(tasks.get(b, {}).get('status') == 'done' for b in t.get('blocked_by', []))
    if all_done:
        stalled.append(t)

print(f'Stalled claimed tasks (all blockers done): {len(stalled)}')
for t in stalled:
    age = t.get('claimed_at', '')
    print(f'  {t[\"id\"][:8]} (claimed_by={t.get(\"claimed_by\",\"?\")}, at={age[:16]}): {t[\"title\"][:60]}')
"
```

# Step 4: Clear stale `claimed_by` from pending tasks

Fix them by patching the JSON directly:

```bash
python3 -c "
import json, os
from pathlib import Path

tasks_dir = Path(os.environ.get('TL0_TASKS_DIR', '')) or Path.home() / 'tl0-tasks'
tasks_folder = tasks_dir / 'tasks'
fixed = []

for f in sorted(tasks_folder.glob('*.json')):
    d = json.load(open(f))
    if d['status'] == 'pending' and d.get('claimed_by') is not None:
        agent = d['claimed_by']
        d['claimed_by'] = None
        d['claimed_at'] = None
        f.write_text(json.dumps(d, indent=2) + '\n')
        fixed.append((d['id'][:8], agent, d['title'][:60]))

print(f'Fixed {len(fixed)} tasks:')
for tid, agent, title in fixed:
    print(f'  {tid} (was: {agent}): {title}')
"
```

# Step 5: Free stalled `claimed` tasks

For each stalled task found in Step 3:

```bash
tl0 free <uuid-prefix>
```

# Step 6: Verify the fix

```bash
tl0 status
```

The **READY** count should now show claimable tasks.
