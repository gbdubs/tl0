#!/usr/bin/env bash
#
# tl0 loop — Continuously claim tasks, implement them in worktrees, merge back.
#
# Usage:
#   tl0 loop                              # Run with defaults
#   tl0 loop --model sonnet               # Only pick up sonnet tasks
#   tl0 loop --tag area:api               # Only pick up tasks with this tag
#   tl0 loop --once                       # Run one task then exit
#   tl0 loop --max-tasks 5                # Run up to 5 tasks then exit
#   tl0 loop --dry-run                    # Show what would be done, don't do it
#   tl0 loop --resume UUID                # Resume a preserved task (skip claude, just merge)
#   tl0 loop --prompt /path/to/prompt.md  # Custom execution prompt
#
# Each iteration:
#   1. Pulls latest main from origin
#   2. Finds the next claimable task and claims it
#   3. Creates a git worktree (branch: task/<short-id>) from main
#   4. Runs claude -p (dangerously-skip-permissions) in the worktree
#   5. Pulls main again, merges main INTO the task branch (claude resolves conflicts)
#   6. Fast-forward merges the branch into main, pushes
#   7. Marks the task done (only after merge succeeds)
#   8. Cleans up the worktree
#
# On failure, task branches are preserved (pushed to origin) with resume
# instructions. Use --resume to pick up where a failed task left off.
#
# Safe for parallel execution — multiple instances can run simultaneously
# because task claiming is atomic (first claim wins). Merge conflicts are
# resolved by claude on its branch, not on main.

set -euo pipefail

# Alert loudly on unexpected exit — this loop should run forever.
EXPECTED_EXIT=false
alert_on_exit() {
  local exit_code=$?
  # Clean up supervisor status file if running under supervisor
  [[ -n "${TL0_LOOP_STATUS_FILE:-}" ]] && rm -f "$TL0_LOOP_STATUS_FILE" 2>/dev/null || true
  if ! $EXPECTED_EXIT; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!! TASK LOOP EXITED UNEXPECTEDLY (code=$exit_code) !!!"
    echo "!!! $(date)                                     !!!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    printf '\a\a\a'
    osascript -e 'display notification "Task loop died!" with title "TASK LOOP DOWN" sound name "Sosumi"' 2>/dev/null || true
    HAMLET_DEATH_LINES=(
      "To die, to sleep. To sleep, perchance to dream."
      "The rest is silence."
      "Now cracks a noble heart. Good night, sweet prince."
      "A man may fish with the worm that hath eat of a king, and eat of the fish that hath fed of that worm."
      "Imperious Caesar, dead and turned to clay, might stop a hole to keep the wind away."
      "If it be now, tis not to come. If it be not to come, it will be now."
      "There is a special providence in the fall of a sparrow."
      "O, I die, Horatio!"
      "Alexander died, Alexander was buried, Alexander returneth to dust."
      "The undiscovered country, from whose bourn no traveller returns."
    )
    RANDOM_LINE="${HAMLET_DEATH_LINES[$((RANDOM % ${#HAMLET_DEATH_LINES[@]}))]}"
    say "$RANDOM_LINE" 2>/dev/null &
  fi
}
trap alert_on_exit EXIT

# Resolve the code repo from the current working directory
CODE_REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Error: must be run from within a git repository." >&2
  EXPECTED_EXIT=true; exit 1
}
WORKTREE_BASE="$CODE_REPO/.task-worktrees"

# Pick the first bird name not already in use as an agent ID
_pick_bird_name() {
  local birds=(
    Avocet Bobolink Crow Dowitcher Egret
    Finch Goshawk Harrier Ibis Jay
    Killdeer Loon Magpie Nuthatch Oriole
    Parrot Quail Robin Sparrow Towhee
    Uguisu Vulture Waxwing Xenops Yellowthroat
    "Zebra Finch"
  )
  local used_agents
  used_agents=$(tl0m find --limit 100 2>/dev/null \
    | python3 -c "
import json,sys
tasks = json.load(sys.stdin)
agents = set()
for t in tasks:
    cb = t.get('claimed_by','')
    if cb: agents.add(cb)
print('\n'.join(agents))
" 2>/dev/null || true)
  for bird in "${birds[@]}"; do
    if ! echo "$used_agents" | grep -qxF "$bird"; then
      echo "$bird"
      return
    fi
  done
  echo "worker-$$"
}

AGENT_ID="$(_pick_bird_name)"

# Resolve the transcripts directory from tl0's tasks dir
TRANSCRIPTS_DIR=$(python3 -c "
from tl0.common import TRANSCRIPTS_FOLDER
print(TRANSCRIPTS_FOLDER)
" 2>/dev/null) || {
  echo "Error: could not resolve transcripts directory." >&2
  EXPECTED_EXIT=true; exit 1
}
mkdir -p "$TRANSCRIPTS_DIR"

# Resolve the execution prompt. Priority:
# 1. --prompt CLI arg (set below during arg parsing)
# 2. TL0_EXEC_PROMPT env var
# 3. tl0.json execution.prompt (relative to repo root)
# 4. Bundled default in tl0 package
TL0_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLED_PROMPT="$TL0_SCRIPT_DIR/../prompts/execute-task.md"

resolve_prompt() {
  # Already set by --prompt arg
  if [[ -n "${TASK_PROMPT:-}" ]]; then
    return
  fi
  # Env var
  if [[ -n "${TL0_EXEC_PROMPT:-}" ]]; then
    TASK_PROMPT="$TL0_EXEC_PROMPT"
    return
  fi
  # tl0.json execution.prompt
  local config_prompt
  config_prompt=$(python3 -c "
import json, pathlib, sys
p = pathlib.Path('$CODE_REPO')
for d in [p] + list(p.parents):
    f = d / 'tl0.json'
    if f.exists():
        cfg = json.loads(f.read_text())
        ep = cfg.get('execution', {}).get('prompt', '')
        if ep:
            print((d / ep).resolve())
            sys.exit(0)
        break
" 2>/dev/null || true)
  if [[ -n "$config_prompt" ]] && [[ -f "$config_prompt" ]]; then
    TASK_PROMPT="$config_prompt"
    return
  fi
  # Bundled default
  if [[ -f "$BUNDLED_PROMPT" ]]; then
    TASK_PROMPT="$BUNDLED_PROMPT"
    return
  fi
  echo "Error: no execution prompt found. Use --prompt, TL0_EXEC_PROMPT, or set execution.prompt in tl0.json." >&2
  EXPECTED_EXIT=true; exit 1
}

# Defaults
MODEL_FILTER=""
TAG_FILTER=""
ONCE=false
MAX_TASKS=0  # 0 = unlimited
DRY_RUN=false
POLL_INTERVAL=30
RESUME_TASK_ID=""
TASK_PROMPT=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)      MODEL_FILTER="$2"; shift 2 ;;
    --tag)        TAG_FILTER="$2"; shift 2 ;;
    --once)       ONCE=true; shift ;;
    --max-tasks)  MAX_TASKS="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    --poll)       POLL_INTERVAL="$2"; shift 2 ;;
    --agent)      AGENT_ID="$2"; shift 2 ;;
    --resume)     RESUME_TASK_ID="$2"; shift 2 ;;
    --prompt)     TASK_PROMPT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,/^$/s/^# *//p' "$0"
      EXPECTED_EXIT=true; exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; EXPECTED_EXIT=true; exit 1 ;;
  esac
done

resolve_prompt

# Per-task transcript state (set inside run_task, cleared after)
TASK_TRANSCRIPT_DIR=""
TASK_SESSION_ID=""
CLAUDE_CALL_SEQ=0

log() {
  local msg="[$(date +%H:%M:%S)] $*"
  echo "$msg"
  [[ -n "$TASK_TRANSCRIPT_DIR" ]] && [[ -d "$TASK_TRANSCRIPT_DIR" ]] && echo "$msg" >> "$TASK_TRANSCRIPT_DIR/loop.log" || true
}
warn() {
  local msg="[$(date +%H:%M:%S)] WARN: $*"
  echo "$msg" >&2
  [[ -n "$TASK_TRANSCRIPT_DIR" ]] && [[ -d "$TASK_TRANSCRIPT_DIR" ]] && echo "$msg" >> "$TASK_TRANSCRIPT_DIR/loop.log" || true
}

# Write status to supervisor status file (if running under supervisor).
# No-op when TL0_LOOP_STATUS_FILE is not set.
write_status() {
  local phase="$1" task_id="${2:-}" task_title="${3:-}"
  [[ -z "${TL0_LOOP_STATUS_FILE:-}" ]] && return 0
  printf '{"phase":"%s","task_id":"%s","task_title":"%s","timestamp":%d}\n' \
    "$phase" "$task_id" "$task_title" "$(date +%s)" \
    > "$TL0_LOOP_STATUS_FILE" 2>/dev/null || true
}

# Run claude with transcript capture. Usage:
#   run_claude <label> <worktree> <model> <prompt> [resume_session_id]
# If resume_session_id is provided, passes --resume to continue that session.
# Sets CLAUDE_OUTPUT and returns claude's exit code.
run_claude() {
  local label="$1"
  local worktree="$2"
  local model="$3"
  local prompt="$4"
  local resume_session_id="${5:-}"

  CLAUDE_CALL_SEQ=$((CLAUDE_CALL_SEQ + 1))
  local seq
  seq=$(printf "%02d" "$CLAUDE_CALL_SEQ")
  local transcript_file="$TASK_TRANSCRIPT_DIR/${seq}-${label}.jsonl"

  if [[ -n "$resume_session_id" ]]; then
    log "    Running claude [$seq-$label] (resuming session $resume_session_id)..."
  else
    log "    Running claude [$seq-$label]..."
  fi

  local claude_exit=0
  CLAUDE_OUTPUT=""
  CLAUDE_OUTPUT=$(cd "$worktree" && claude -p \
    --model "$model" \
    --verbose \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    ${resume_session_id:+--resume "$resume_session_id"} \
    "$prompt" 2>&1 \
    | tee "$transcript_file"
  ) || claude_exit=$?

  if [ $claude_exit -ne 0 ]; then
    warn "Claude [$seq-$label] exited with code $claude_exit."
  fi

  log "    Transcript [$seq-$label] saved ($(wc -l < "$transcript_file" | tr -d ' ') events)"
  return $claude_exit
}

# Check a transcript file for quota rejection.
# Outputs the resetsAt timestamp if rejected, empty otherwise.
# Returns 0 if quota was rejected, 1 if not.
check_quota_rejected() {
  local transcript_file="$1"
  python3 -c "
import json, sys
for line in open('$transcript_file'):
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if msg.get('type') == 'rate_limit_event':
        info = msg.get('rate_limit_info', {})
        if info.get('status') == 'rejected':
            print(info.get('resetsAt', ''))
            sys.exit(0)
    if msg.get('type') == 'result' and msg.get('is_error'):
        text = msg.get('result', '')
        if isinstance(text, str) and 'hit your limit' in text.lower():
            print('')
            sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# Extract quota utilization info from a transcript file.
# Outputs JSON with utilization data, or empty string if none found.
extract_quota_info() {
  local transcript_file="$1"
  python3 -c "
import json, sys, time
for line in open('$transcript_file'):
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if msg.get('type') == 'rate_limit_event':
        info = msg.get('rate_limit_info', {})
        out = {
            'timestamp': int(time.time()),
            'status': info.get('status', ''),
            'rate_limit_type': info.get('rateLimitType', ''),
            'utilization': info.get('utilization'),
            'resets_at': info.get('resetsAt'),
        }
        print(json.dumps(out))
        sys.exit(0)
" 2>/dev/null
}

# Write quota info to shared directory (if running under supervisor).
write_quota_info() {
  local transcript_file="$1"
  [[ -z "${TL0_QUOTA_DIR:-}" ]] && return 0
  local info
  info=$(extract_quota_info "$transcript_file")
  [[ -z "$info" ]] && return 0
  local slot_id="${TL0_LOOP_SLOT_ID:-$$}"
  echo "$info" > "$TL0_QUOTA_DIR/${slot_id}.json" 2>/dev/null || true
}

mkdir -p "$WORKTREE_BASE"

# Build find args
FIND_ARGS=(--limit 1)
[[ -n "$MODEL_FILTER" ]] && FIND_ARGS+=(--model "$MODEL_FILTER")
[[ -n "$TAG_FILTER" ]]   && FIND_ARGS+=(--tag "$TAG_FILTER")

cleanup_worktree() {
  local short_id="$1"
  local wt="$WORKTREE_BASE/$short_id"
  local branch="task/$short_id"
  if [ -d "$wt" ]; then
    git -C "$CODE_REPO" worktree remove --force "$wt" 2>/dev/null || true
  fi
  git -C "$CODE_REPO" worktree prune 2>/dev/null || true
  git -C "$CODE_REPO" branch -D "$branch" 2>/dev/null || true
}

pull_main() {
  git -C "$CODE_REPO" merge --abort 2>/dev/null || true
  git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
  git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true

  if ! git -C "$CODE_REPO" pull --ff-only --quiet origin main 2>/dev/null; then
    warn "Fast-forward pull of main failed. Resetting to origin/main..."
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
  fi
}

reconcile_generated_files() {
  local wt="$1"
  # Check for package.json (Node.js project)
  if [ -f "$wt/package.json" ] && command -v npm &>/dev/null; then
    log "    Reconciling generated files (npm install)..."
    (cd "$wt" && npm install --package-lock-only --ignore-scripts > /dev/null 2>&1) || true
    if [ -n "$(git -C "$wt" status --porcelain package-lock.json 2>/dev/null)" ]; then
      git -C "$wt" add package-lock.json 2>/dev/null
      git -C "$wt" commit -m "chore: regenerate package-lock.json after merge" 2>/dev/null || true
    fi
  fi
}

print_resume_instructions() {
  local task_id="$1"
  local short_id="$2"
  local branch="$3"
  local reason="$4"

  echo ""
  echo "========================================================"
  echo "  TASK PRESERVED — $reason"
  echo "========================================================"
  echo "  Task:   $task_id"
  echo "  Branch: $branch"
  echo ""
  echo "  To resume (merge only, skip claude):"
  echo "    tl0h resume $task_id"
  echo ""
  echo "  To resume with claude re-run:"
  echo "    git worktree add $WORKTREE_BASE/$short_id $branch"
  echo "    cd $WORKTREE_BASE/$short_id && claude -p ..."
  echo ""
  echo "  To abandon:"
  echo "    tl0m free $task_id"
  echo "    git branch -D $branch"
  echo "    git push origin --delete $branch 2>/dev/null"
  echo "========================================================"
  echo ""
}

merge_main_into_branch() {
  local worktree="$1"
  local short_id="$2"
  local model="$3"
  local label="${4:-}"

  if git -C "$worktree" merge --quiet main -m "Merge main into task/$short_id${label:+ ($label)}" 2>/dev/null; then
    return 0
  fi

  log "    Merge conflict detected. Asking claude to resolve..."
  local resolve_exit=0
  run_claude "merge-conflict" "$worktree" "$model" \
    "There are merge conflicts after merging main into this task branch. Resolve all conflicts, then commit. Run 'git diff --name-only --diff-filter=U' to see conflicted files. For each one, read it, resolve the conflict markers, and 'git add' it. Then 'git commit --no-edit'." \
    "$TASK_SESSION_ID" \
    || resolve_exit=$?

  local unmerged
  unmerged=$(git -C "$worktree" diff --name-only --diff-filter=U 2>/dev/null | wc -l | tr -d ' ')
  if [ "$unmerged" -ne 0 ]; then
    warn "Claude failed to resolve merge conflicts."
    git -C "$worktree" merge --abort 2>/dev/null || true
    return 1
  fi

  return 0
}

merge_and_push() {
  local worktree="$1"
  local short_id="$2"
  local branch="$3"
  local model="$4"
  local commit_msg="$5"

  local max_attempts=20
  local pushed=false
  local pushed_sha=""
  local sha_candidate pre_commit_sha

  for attempt in $(seq 1 $max_attempts); do
    log "    Squash+push attempt $attempt/$max_attempts..."

    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true

    if git -C "$CODE_REPO" merge --squash "$branch" 2>/dev/null; then
      pre_commit_sha=$(git -C "$CODE_REPO" rev-parse HEAD 2>/dev/null || true)
      git -C "$CODE_REPO" commit -m "$commit_msg" 2>/dev/null || true
      sha_candidate=$(git -C "$CODE_REPO" rev-parse HEAD 2>/dev/null || true)
      # If commit was a no-op (no changes), don't record a stale SHA
      if [ "$sha_candidate" = "$pre_commit_sha" ]; then
        sha_candidate=""
      fi
      if git -C "$CODE_REPO" push origin main 2>/dev/null; then
        pushed=true
        pushed_sha="$sha_candidate"
        break
      fi
      warn "Push rejected (attempt $attempt/$max_attempts). Resetting and retrying..."
      git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
      git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
      sleep $((1 + RANDOM % 3))
      continue
    fi

    log "    Squash had conflicts. Merging latest main into task branch..."
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true

    if ! merge_main_into_branch "$worktree" "$short_id" "$model" "attempt $attempt"; then
      warn "Could not merge main into task branch on attempt $attempt. Aborting retries."
      break
    fi
    reconcile_generated_files "$worktree"

    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true

    if ! git -C "$CODE_REPO" merge --squash "$branch" 2>/dev/null; then
      log "    Squash still conflicted after re-merging. Retrying in ~3s..."
      git -C "$CODE_REPO" merge --abort 2>/dev/null || true
      git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
      git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
      sleep $((2 + RANDOM % 4))
      continue
    fi

    pre_commit_sha=$(git -C "$CODE_REPO" rev-parse HEAD 2>/dev/null || true)
    git -C "$CODE_REPO" commit -m "$commit_msg" 2>/dev/null || true
    sha_candidate=$(git -C "$CODE_REPO" rev-parse HEAD 2>/dev/null || true)
    if [ "$sha_candidate" = "$pre_commit_sha" ]; then
      sha_candidate=""
    fi
    if git -C "$CODE_REPO" push origin main 2>/dev/null; then
      pushed=true
      pushed_sha="$sha_candidate"
      break
    fi

    warn "Push rejected after re-merge (attempt $attempt/$max_attempts). Retrying..."
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    sleep $((1 + RANDOM % 3))
  done

  if ! $pushed; then
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    return 1
  fi

  MERGE_AND_PUSH_SHA="$pushed_sha"
  return 0
}

run_task() {
  local task_json="$1"
  local skip_claude="${2:-false}"
  local task_id model thinking title description short_id branch worktree task_start_time

  task_id=$(echo "$task_json"     | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
  model=$(echo "$task_json"       | python3 -c "import json,sys; print(json.load(sys.stdin)[0].get('model', 'sonnet'))")
  thinking=$(echo "$task_json"    | python3 -c "import json,sys; print(json.load(sys.stdin)[0].get('thinking', False))")
  title=$(echo "$task_json"       | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['title'][:60])")
  description=$(echo "$task_json" | python3 -c "import json,sys; print(json.load(sys.stdin)[0].get('description', ''))")
  task_start_time=$(date +%s)
  short_id="${task_id:0:8}"
  branch="task/$short_id"
  worktree="$WORKTREE_BASE/$short_id"

  # --- Set up per-task transcript directory ---
  TASK_TRANSCRIPT_DIR="$TRANSCRIPTS_DIR/$task_id"
  CLAUDE_CALL_SEQ=0
  mkdir -p "$TASK_TRANSCRIPT_DIR"

  log "Task: $short_id — $title"

  if $DRY_RUN; then
    log "    [DRY RUN] Would claim, create worktree, run claude, merge."
    TASK_TRANSCRIPT_DIR=""; TASK_SESSION_ID=""
    return 0
  fi

  # Ensure TL0_TASK_ID is unset when this function returns (success or failure)
  trap 'unset TL0_TASK_ID 2>/dev/null || true' RETURN

  # --- Claim (skip if resuming — task is already claimed) ---
  if ! $skip_claude; then
    if ! tl0m claim "$task_id" "$AGENT_ID" > /dev/null 2>&1; then
      warn "Failed to claim $short_id (probably claimed by another agent). Skipping."
      TASK_TRANSCRIPT_DIR=""; TASK_SESSION_ID=""
      return 0
    fi
  fi

  # Set TL0_TASK_ID immediately after claiming so all subsequent tl0m calls
  # can use it as the implicit task identifier (no need to pass task_id explicitly).
  export TL0_TASK_ID="$task_id"
  write_status "claimed" "$task_id" "$title"

  # --- Pull latest main ---
  pull_main

  if $skip_claude; then
    # --- Resume mode: use existing branch ---
    if [ ! -d "$worktree" ]; then
      if git -C "$CODE_REPO" show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        git -C "$CODE_REPO" worktree add --quiet "$worktree" "$branch" 2>/dev/null || {
          warn "Failed to create worktree from existing branch."
          TASK_TRANSCRIPT_DIR=""; TASK_SESSION_ID=""
          return 1
        }
      elif git -C "$CODE_REPO" show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
        git -C "$CODE_REPO" fetch origin "$branch" 2>/dev/null || true
        git -C "$CODE_REPO" worktree add --quiet "$worktree" -b "$branch" "origin/$branch" 2>/dev/null || {
          warn "Failed to create worktree from origin branch."
          TASK_TRANSCRIPT_DIR=""
          return 1
        }
      else
        warn "Branch $branch not found locally or on origin. Cannot resume."
        TASK_TRANSCRIPT_DIR=""
        return 1
      fi
    fi
  else
    # --- Create worktree ---
    cleanup_worktree "$short_id"

    if ! git -C "$CODE_REPO" worktree add --quiet "$worktree" -b "$branch" main 2>/dev/null; then
      warn "Failed to create worktree. Freeing task."
      tl0m free 2>/dev/null || true
      TASK_TRANSCRIPT_DIR=""
      return 1
    fi

    # --- Run claude ---
    local prompt
    prompt="$(cat "$TASK_PROMPT")

TL0_TASK_ID=$task_id
AGENT_ID=$AGENT_ID

Use 'tl0m' for all task operations (create subtasks, mark done, etc.)."

    local claude_exit=0
    local claude_stdout=""

    write_status "executing" "$task_id" "$title"
    run_claude "execute" "$worktree" "$model" "$prompt" || claude_exit=$?

    # --- Check for quota rejection ---
    local transcript_file="$TASK_TRANSCRIPT_DIR/01-execute.jsonl"
    write_quota_info "$transcript_file"

    local resets_at=""
    if resets_at=$(check_quota_rejected "$transcript_file"); then
      warn "Quota/rate-limit rejection detected. Freeing task."
      if [[ -n "$resets_at" ]]; then
        local reset_time
        reset_time=$(date -r "$resets_at" "+%H:%M %Z" 2>/dev/null || echo "unknown")
        log "    Quota resets at: $reset_time (ts=$resets_at)"
      fi
      write_status "quota_rejected" "$task_id" "$title"
      tl0m free 2>/dev/null || true
      cleanup_worktree "$short_id"
      TASK_TRANSCRIPT_DIR=""
      TASK_SESSION_ID=""
      return 2  # special exit: quota rejected
    fi

    # Extract session ID from transcript for use in follow-up calls (e.g. merge conflict resolution).
    TASK_SESSION_ID=$(python3 -c "
import json, sys
for line in open('$transcript_file'):
    line = line.strip()
    if not line: continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    sid = msg.get('sessionId', '')
    if sid:
        print(sid)
        sys.exit(0)
" 2>/dev/null || true)
    if [[ -n "$TASK_SESSION_ID" ]]; then
      log "    Session ID: $TASK_SESSION_ID"
    fi

    # Extract final text result from the stream-json transcript.
    # Skip results where is_error is true (e.g. quota errors, API failures).
    claude_stdout=$(python3 -c "
import json, sys
text_parts = []
for line in open('$transcript_file'):
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if msg.get('type') == 'result':
        if msg.get('is_error'):
            continue
        result = msg.get('result', '')
        if isinstance(result, str):
            text_parts.append(result)
        elif isinstance(result, list):
            for block in result:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
if text_parts:
    print(text_parts[-1])
" 2>/dev/null || true)
  fi

  # --- Read result summary ---
  local result_text=""
  if [ -f "$worktree/.task-result.txt" ]; then
    result_text=$(cat "$worktree/.task-result.txt")
  fi

  # --- Fallback: extract result from Claude's stdout ---
  if [ -z "$result_text" ] && [ -n "$claude_stdout" ]; then
    local fallback
    fallback=$(printf '%s' "$claude_stdout" | head -c 500)
    if [ -n "$fallback" ]; then
      result_text="[fallback-from-stdout] $fallback"
      log "    No .task-result.txt found; using Claude stdout as fallback result."
    fi
  fi

  # --- Check if claude committed anything ---
  local commit_count
  commit_count=$(git -C "$worktree" rev-list --count main.."$branch" 2>/dev/null || echo "0")

  if [ "$commit_count" -eq 0 ]; then
    if [ -n "$result_text" ]; then
      tl0m done --result "$result_text" 2>/dev/null \
        || warn "Failed to mark task done. May need manual completion."
      cleanup_worktree "$short_id"
      log "Task $short_id completed (no commits). Transcripts in $TASK_TRANSCRIPT_DIR/"
      TASK_TRANSCRIPT_DIR=""
      return 0
    else
      warn "No commits on branch and no result file. Task may have failed."
      git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
      print_resume_instructions "$task_id" "$short_id" "$branch" "Claude produced no commits or result"
      TASK_TRANSCRIPT_DIR=""
      return 1
    fi
  fi

  # --- Stash uncommitted changes ---
  local stashed=false
  if [ -n "$(git -C "$worktree" status --porcelain 2>/dev/null)" ]; then
    log "    Stashing uncommitted changes before merge..."
    git -C "$worktree" stash push -u -m "task-loop: pre-merge stash" 2>/dev/null && stashed=true
  fi

  # --- Merge main into the task branch ---
  write_status "merging" "$task_id" "$title"
  log "    Pulling latest main and merging into task branch..."
  pull_main

  if ! merge_main_into_branch "$worktree" "$short_id" "$model"; then
    warn "Failed to merge main into task branch. Preserving work."
    git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
    print_resume_instructions "$task_id" "$short_id" "$branch" "Merge conflict with main"
    TASK_TRANSCRIPT_DIR=""
    return 1
  fi

  reconcile_generated_files "$worktree"

  # --- Restore and commit stashed changes ---
  if $stashed; then
    log "    Restoring stashed changes..."
    git -C "$worktree" stash pop 2>/dev/null || true
    if [ -n "$(git -C "$worktree" status --porcelain 2>/dev/null)" ]; then
      git -C "$worktree" add -A 2>/dev/null
      git -C "$worktree" reset HEAD .task-result.txt 2>/dev/null || true
      git -C "$worktree" commit -m "[task:$short_id] Include uncommitted changes from task execution" 2>/dev/null || true
    fi
  fi

  # --- Build squash commit message ---
  local elapsed=$(( $(date +%s) - task_start_time ))
  local duration
  duration="$(( elapsed / 3600 ))h$(( (elapsed % 3600) / 60 ))m$(( elapsed % 60 ))s"
  local commit_msg
  commit_msg="$(printf '%s - %s\n\nTL0 Task ID: %s\n\n%s\n\nExecution Time: %s' \
    "$short_id" "$title" "$task_id" "$description" "$duration")"

  # --- Squash-merge task branch into main and push ---
  MERGE_AND_PUSH_SHA=""
  if ! merge_and_push "$worktree" "$short_id" "$branch" "$model" "$commit_msg"; then
    warn "Failed to merge and push task branch. Preserving work."
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
    print_resume_instructions "$task_id" "$short_id" "$branch" "Merge/push to main failed"
    TASK_TRANSCRIPT_DIR=""
    return 1
  fi

  # --- Capture merge SHA (set atomically inside merge_and_push) ---
  local merge_sha="$MERGE_AND_PUSH_SHA"

  # --- Mark task done ---
  if [ -z "$result_text" ]; then
    result_text="Implemented by $AGENT_ID. $commit_count commit(s) merged to main."
  fi
  tl0m done --result "$result_text" ${merge_sha:+--merge-sha "$merge_sha"} 2>/dev/null \
    || warn "Failed to mark task done. May need manual completion."

  # --- Cleanup ---
  cleanup_worktree "$short_id"
  git -C "$CODE_REPO" push origin --delete "$branch" 2>/dev/null || true

  log "Task $short_id completed. Transcripts in $TASK_TRANSCRIPT_DIR/"
  write_status "idle"
  TASK_TRANSCRIPT_DIR=""
  TASK_SESSION_ID=""
  return 0
}

# --- Resume mode ---
if [[ -n "$RESUME_TASK_ID" ]]; then
  log "Resuming task $RESUME_TASK_ID..."
  task_json=$(tl0m show "$RESUME_TASK_ID" 2>/dev/null | python3 -c "
import json, sys
t = json.load(sys.stdin)
if isinstance(t, list):
    print(json.dumps(t))
else:
    print(json.dumps([t]))
" 2>/dev/null)

  if [ -z "$task_json" ] || [ "$task_json" = "null" ] || [ "$task_json" = "[]" ]; then
    warn "Could not load task $RESUME_TASK_ID"
    EXPECTED_EXIT=true; exit 1
  fi

  run_task "$task_json" true || {
    warn "Resume failed for task $RESUME_TASK_ID."
    EXPECTED_EXIT=true; exit 1
  }

  log "Resume complete."
  EXPECTED_EXIT=true; exit 0
fi

# --- Main loop ---
tasks_completed=0
log "Task loop starting (agent=$AGENT_ID)"
log "  Code repo: $CODE_REPO"
log "  Worktrees: $WORKTREE_BASE"
log "  Prompt:    $TASK_PROMPT"
log "  Filters: model=${MODEL_FILTER:-any} tag=${TAG_FILTER:-any}"
[[ "$MAX_TASKS" -gt 0 ]] && log "  Max tasks: $MAX_TASKS"
log ""

while true; do
  # Check task limit
  if [[ "$MAX_TASKS" -gt 0 ]] && [[ "$tasks_completed" -ge "$MAX_TASKS" ]]; then
    log "Completed $tasks_completed task(s). Exiting (--max-tasks $MAX_TASKS)."
    EXPECTED_EXIT=true; exit 0
  fi

  # Sync main before looking for tasks
  pull_main

  # Find next task
  write_status "polling"
  task_json=$(tl0m find "${FIND_ARGS[@]}" 2>/dev/null)

  if [ "$task_json" = "[]" ] || [ -z "$task_json" ]; then
    if $ONCE; then
      log "No tasks available. Exiting (--once mode)."
      EXPECTED_EXIT=true; exit 0
    fi
    log "No tasks available. Polling in ${POLL_INTERVAL}s..."
    sleep "$POLL_INTERVAL"
    continue
  fi

  run_task_exit=0
  run_task "$task_json" || run_task_exit=$?

  if [ "$run_task_exit" -eq 0 ]; then
    tasks_completed=$((tasks_completed + 1))
  elif [ "$run_task_exit" -eq 2 ]; then
    log "Quota rejected. Backing off for 5 minutes..."
    write_status "quota_backoff"
    sleep 300
  else
    log "Task failed. Continuing to next task..."
  fi

  if $ONCE; then
    log "Ran one task. Exiting (--once mode)."
    EXPECTED_EXIT=true; exit 0
  fi

  # Brief pause between tasks
  sleep 2
done
