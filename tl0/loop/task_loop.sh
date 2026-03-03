#!/usr/bin/env bash
#
# task-loop — Continuously claim tasks, implement them in worktrees, merge back.
#
# Usage:
#   ./scripts/task-loop                     # Run with defaults
#   ./scripts/task-loop --model sonnet      # Only pick up sonnet tasks
#   ./scripts/task-loop --tag area:api      # Only pick up tasks with this tag
#   ./scripts/task-loop --once              # Run one task then exit
#   ./scripts/task-loop --max-tasks 5       # Run up to 5 tasks then exit
#   ./scripts/task-loop --dry-run           # Show what would be done, don't do it
#   ./scripts/task-loop --resume UUID       # Resume a preserved task (skip claude, just merge)
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
  if ! $EXPECTED_EXIT; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!! TASK LOOP EXITED UNEXPECTEDLY (code=$exit_code) !!!"
    echo "!!! $(date)                                     !!!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    # Audible alert — terminal bell + macOS say + system sound
    printf '\a\a\a'
    osascript -e 'display notification "Task loop died!" with title "TASK LOOP DOWN" sound name "Sosumi"' 2>/dev/null || true
    # Random Hamlet death quotes for dramatic flair
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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_CMD="tl0"
CODE_REPO="$(git -C "$REPO_ROOT" rev-parse --show-toplevel)"
WORKTREE_BASE="$CODE_REPO/.task-worktrees"
TASK_PROMPT="${TL0_EXEC_PROMPT:-$(dirname "$0")/../../../claude/prompts/execute-task.md}"
AGENT_ID="task-loop-$$"

# Defaults
MODEL_FILTER=""
TAG_FILTER=""
ONCE=false
MAX_TASKS=0  # 0 = unlimited
DRY_RUN=false
POLL_INTERVAL=30
RESUME_TASK_ID=""

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
    -h|--help)
      sed -n '2,/^$/s/^# *//p' "$0"
      EXPECTED_EXIT=true; exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; EXPECTED_EXIT=true; exit 1 ;;
  esac
done

log()  { echo "[$(date +%H:%M:%S)] $*"; }
warn() { echo "[$(date +%H:%M:%S)] WARN: $*" >&2; }

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
  # Abort any in-progress merge/rebase left by a previous crash
  git -C "$CODE_REPO" merge --abort 2>/dev/null || true
  git -C "$CODE_REPO" rebase --abort 2>/dev/null || true

  git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true

  if ! git -C "$CODE_REPO" pull --ff-only --quiet origin main 2>/dev/null; then
    # ff-only failed (diverged local main) — hard-reset to match origin.
    # Avoid pull --rebase here: it silently drops merge commits, which can
    # leave orphaned files in the working tree and cause later ff merges to
    # fail with "untracked working tree files would be overwritten".
    warn "Fast-forward pull of main failed. Resetting to origin/main..."
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
  fi
}

# After merging main into a task branch, regenerate derived files so they
# reflect the combined dependency tree rather than a textual merge of JSON.
reconcile_generated_files() {
  local wt="$1"
  log "    Reconciling generated files (npm install)..."
  (cd "$wt" && npm install --package-lock-only --ignore-scripts > /dev/null 2>&1) || true
  if [ -n "$(git -C "$wt" status --porcelain package-lock.json 2>/dev/null)" ]; then
    git -C "$wt" add package-lock.json 2>/dev/null
    git -C "$wt" commit -m "chore: regenerate package-lock.json after merge" 2>/dev/null || true
  fi
}

# Print instructions for resuming a failed task.
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
  echo "    ./scripts/task-loop --resume $task_id"
  echo ""
  echo "  To resume with claude re-run:"
  echo "    git worktree add $WORKTREE_BASE/$short_id $branch"
  echo "    cd $WORKTREE_BASE/$short_id && claude -p ..."
  echo ""
  echo "  To abandon:"
  echo "    ./scripts/tasks free $task_id"
  echo "    git branch -D $branch"
  echo "    git push origin --delete $branch 2>/dev/null"
  echo "========================================================"
  echo ""
}

# Attempt to merge main into the task branch in the worktree.
# Returns 0 on success, 1 on unresolvable conflict.
merge_main_into_branch() {
  local worktree="$1"
  local short_id="$2"
  local model="$3"
  local label="${4:-}"

  if git -C "$worktree" merge --quiet main -m "Merge main into task/$short_id${label:+ ($label)}" 2>/dev/null; then
    return 0
  fi

  # Merge conflict — have claude resolve it
  log "    Merge conflict detected. Asking claude to resolve..."
  local resolve_exit=0
  (cd "$worktree" && claude -p \
    --model "$model" \
    --dangerously-skip-permissions \
    "There are merge conflicts after merging main into this task branch. Resolve all conflicts, then commit. Run 'git diff --name-only --diff-filter=U' to see conflicted files. For each one, read it, resolve the conflict markers, and 'git add' it. Then 'git commit --no-edit'."
  ) || resolve_exit=$?

  # Check if conflicts were resolved
  local unmerged
  unmerged=$(git -C "$worktree" diff --name-only --diff-filter=U 2>/dev/null | wc -l | tr -d ' ')
  if [ "$unmerged" -ne 0 ]; then
    warn "Claude failed to resolve merge conflicts."
    git -C "$worktree" merge --abort 2>/dev/null || true
    return 1
  fi

  return 0
}

# Merge a task branch into main and push. Retries on parallel advancement.
# Returns 0 on success, 1 on failure.
merge_and_push() {
  local worktree="$1"
  local short_id="$2"
  local branch="$3"
  local model="$4"

  # Single unified loop: each attempt fetches the latest main, fast-forward
  # merges the task branch (re-merging main into the task branch if needed),
  # and then pushes.  A push rejection or ff failure loops back to the top so
  # that the next attempt re-merges freshly from the new origin/main.
  #
  # Previous design had separate merge (max 5) and push (max 3) retry loops.
  # The push loop could not trigger a re-merge when origin advanced between
  # the local ff-merge and the push, so it exhausted its 3 attempts and gave
  # up even though re-merging would have succeeded.
  local max_attempts=20
  local pushed=false

  for attempt in $(seq 1 $max_attempts); do
    log "    Merge+push attempt $attempt/$max_attempts..."

    # Ensure CODE_REPO working tree is clean and on latest main.
    # A previous failed ff-only or aborted rebase can leave untracked/dirty
    # files that cause subsequent ff merges to fail at the checkout stage
    # (git prints "Updating X..Y" but returns exit 1, with the real error
    # hidden by 2>/dev/null).
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true

    # Try fast-forward first (ideal — clean linear history).
    if git -C "$CODE_REPO" merge --ff-only "$branch" 2>/dev/null; then
      # FF succeeded — try to push.
      if git -C "$CODE_REPO" push origin main 2>/dev/null; then
        pushed=true
        break
      fi
      # Push rejected — another loop pushed between our ff-merge and push.
      # Reset and loop back to re-merge from the new origin/main.
      warn "Push rejected (attempt $attempt/$max_attempts). Resetting and retrying..."
      git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
      git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
      sleep $((1 + RANDOM % 3))
      continue
    fi

    # FF failed — need to merge main into task branch first.
    log "    Fast-forward not possible. Merging latest main into task branch..."
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true

    if ! merge_main_into_branch "$worktree" "$short_id" "$model" "attempt $attempt"; then
      warn "Could not merge main into task branch on attempt $attempt. Aborting retries."
      break
    fi
    reconcile_generated_files "$worktree"

    # After merging main into the branch, fetch again (main may have moved
    # during the merge) and try ff-only + push.
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true

    if ! git -C "$CODE_REPO" merge --ff-only "$branch" 2>/dev/null; then
      # Another parallel loop pushed while we were merging. Loop back so the
      # next attempt re-merges from the new main tip.
      log "    FF still failed after re-merging. Retrying in ~3s..."
      git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
      git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
      sleep $((2 + RANDOM % 4))
      continue
    fi

    if git -C "$CODE_REPO" push origin main 2>/dev/null; then
      pushed=true
      break
    fi

    # Push rejected after a successful re-merge — loop back.
    warn "Push rejected after re-merge (attempt $attempt/$max_attempts). Retrying..."
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    sleep $((1 + RANDOM % 3))
  done

  if ! $pushed; then
    # Clean up any in-progress merge/rebase state on the main repo
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    return 1
  fi

  return 0
}

run_task() {
  local task_json="$1"
  local skip_claude="${2:-false}"
  local task_id model thinking title short_id branch worktree

  task_id=$(echo "$task_json" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
  model=$(echo "$task_json"   | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['model'])")
  thinking=$(echo "$task_json" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['thinking'])")
  title=$(echo "$task_json"   | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['title'][:60])")
  short_id="${task_id:0:8}"
  branch="task/$short_id"
  worktree="$WORKTREE_BASE/$short_id"

  log "Task: $short_id — $title"

  if $DRY_RUN; then
    log "    [DRY RUN] Would claim, create worktree, run claude, merge."
    return 0
  fi

  # --- Claim (skip if resuming — task is already claimed) ---
  if ! $skip_claude; then
    if ! tl0 claim "$task_id" "$AGENT_ID" > /dev/null 2>&1; then
      warn "Failed to claim $short_id (probably claimed by another agent). Skipping."
      return 0
    fi
  fi

  # --- Pull latest main ---
  pull_main

  if $skip_claude; then
    # --- Resume mode: use existing branch ---
    # Check if worktree already exists
    if [ ! -d "$worktree" ]; then
      # Try to set up worktree from existing branch
      if git -C "$CODE_REPO" show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        git -C "$CODE_REPO" worktree add --quiet "$worktree" "$branch" 2>/dev/null || {
          warn "Failed to create worktree from existing branch."
          return 1
        }
      elif git -C "$CODE_REPO" show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
        git -C "$CODE_REPO" fetch origin "$branch" 2>/dev/null || true
        git -C "$CODE_REPO" worktree add --quiet "$worktree" -b "$branch" "origin/$branch" 2>/dev/null || {
          warn "Failed to create worktree from origin branch."
          return 1
        }
      else
        warn "Branch $branch not found locally or on origin. Cannot resume."
        return 1
      fi
    fi
  else
    # --- Create worktree ---
    # Clean up stale remnants from previous attempts (crashed loop, etc.)
    cleanup_worktree "$short_id"

    if ! git -C "$CODE_REPO" worktree add --quiet "$worktree" -b "$branch" main 2>/dev/null; then
      warn "Failed to create worktree. Freeing task."
      tl0 free "$task_id" 2>/dev/null || true
      return 1
    fi

    # --- Run claude ---
    local prompt
    prompt="$(cat "$TASK_PROMPT")

TASK_ID=$task_id
AGENT_ID=$AGENT_ID"

    local claude_exit=0
    (cd "$worktree" && claude -p \
      --model "$model" \
      --dangerously-skip-permissions \
      "$prompt"
    ) || claude_exit=$?

    if [ $claude_exit -ne 0 ]; then
      warn "Claude exited with code $claude_exit for task $short_id."
    fi
  fi

  # --- Read result summary (claude writes this instead of marking done) ---
  local result_text=""
  if [ -f "$worktree/.task-result.txt" ]; then
    result_text=$(cat "$worktree/.task-result.txt")
  fi

  # --- Check if claude committed anything ---
  local commit_count
  commit_count=$(git -C "$worktree" rev-list --count main.."$branch" 2>/dev/null || echo "0")

  if [ "$commit_count" -eq 0 ]; then
    if [ -n "$result_text" ]; then
      # No commits but result file exists — this is a read-only task (verify, review, decompose).
      # Skip merge, mark done directly.
      tl0 done "$task_id" --result "$result_text" 2>/dev/null \
        || warn "Failed to mark task done. May need manual completion."
      cleanup_worktree "$short_id"
      return 0
    else
      warn "No commits on branch and no result file. Task may have failed."
      # Preserve the branch in case claude did useful work that wasn't committed
      git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
      print_resume_instructions "$task_id" "$short_id" "$branch" "Claude produced no commits or result"
      # Don't free — leave claimed so user can investigate
      return 1
    fi
  fi

  # --- Stash uncommitted changes (e.g. package-lock.json left by npm install) ---
  # Git refuses to merge if uncommitted changes overlap with incoming changes.
  local stashed=false
  if [ -n "$(git -C "$worktree" status --porcelain 2>/dev/null)" ]; then
    log "    Stashing uncommitted changes before merge..."
    git -C "$worktree" stash push -u -m "task-loop: pre-merge stash" 2>/dev/null && stashed=true
  fi

  # --- Merge main into the task branch (resolve conflicts on the branch, not main) ---
  log "    Pulling latest main and merging into task branch..."
  pull_main

  if ! merge_main_into_branch "$worktree" "$short_id" "$model"; then
    warn "Failed to merge main into task branch. Preserving work."
    git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
    print_resume_instructions "$task_id" "$short_id" "$branch" "Merge conflict with main"
    return 1
  fi

  reconcile_generated_files "$worktree"

  # --- Restore and commit stashed changes ---
  if $stashed; then
    log "    Restoring stashed changes..."
    git -C "$worktree" stash pop 2>/dev/null || true
    # Commit any restored changes so the branch is clean for ff-merge
    if [ -n "$(git -C "$worktree" status --porcelain 2>/dev/null)" ]; then
      git -C "$worktree" add -A 2>/dev/null
      # Never commit .task-result.txt — it causes merge conflicts across parallel loops
      git -C "$worktree" reset HEAD .task-result.txt 2>/dev/null || true
      git -C "$worktree" commit -m "[task:$short_id] Include uncommitted changes from task execution" 2>/dev/null || true
    fi
  fi

  # --- Merge task branch into main and push ---
  if ! merge_and_push "$worktree" "$short_id" "$branch" "$model"; then
    warn "Failed to merge and push task branch. Preserving work."
    # Make sure main is in a clean state — merge_and_push already resets,
    # but do it again defensively in case it exited early.
    git -C "$CODE_REPO" merge --abort 2>/dev/null || true
    git -C "$CODE_REPO" rebase --abort 2>/dev/null || true
    git -C "$CODE_REPO" fetch origin main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" checkout main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" reset --hard origin/main --quiet 2>/dev/null || true
    git -C "$CODE_REPO" clean -fd --quiet 2>/dev/null || true
    # Push the task branch so work isn't lost
    git -C "$CODE_REPO" push origin "$branch" 2>/dev/null || true
    print_resume_instructions "$task_id" "$short_id" "$branch" "Merge/push to main failed"
    return 1
  fi

  # --- Mark task done (only after successful merge to main) ---
  if [ -z "$result_text" ]; then
    result_text="Implemented by $AGENT_ID. $commit_count commit(s) merged to main."
  fi
  tl0 done "$task_id" --result "$result_text" 2>/dev/null \
    || warn "Failed to mark task done. May need manual completion."

  # --- Cleanup ---
  cleanup_worktree "$short_id"
  # Clean up remote task branch now that it's merged
  git -C "$CODE_REPO" push origin --delete "$branch" 2>/dev/null || true

  return 0
}

# --- Resume mode ---
if [[ -n "$RESUME_TASK_ID" ]]; then
  log "Resuming task $RESUME_TASK_ID..."
  task_json=$(python3 -c "
import json, sys
sys.path.insert(0, '$TOOLS')
from common import load_task
t = load_task('$RESUME_TASK_ID')
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
  task_json=$(tl0 find "${FIND_ARGS[@]}" 2>/dev/null)

  if [ "$task_json" = "[]" ] || [ -z "$task_json" ]; then
    if $ONCE; then
      log "No tasks available. Exiting (--once mode)."
      EXPECTED_EXIT=true; exit 0
    fi
    log "No tasks available. Polling in ${POLL_INTERVAL}s..."
    sleep "$POLL_INTERVAL"
    continue
  fi

  if run_task "$task_json"; then
    tasks_completed=$((tasks_completed + 1))
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
