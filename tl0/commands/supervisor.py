#!/usr/bin/env python3
"""tl0h supervisor — Web UI to manage parallel task loops.

Spawns task_loop.sh subprocesses with --max-tasks 1 and manages the pool
dynamically via a browser-based control panel.

Usage:
    tl0h supervisor [--port PORT] [--parallelism N] [--model M] [--tag T]
"""

import argparse
import html
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from tl0.common import (
    load_all_tasks, load_task, save_task, validate_task_shape,
    now_iso, git_commit, VALID_MODELS,
    task_status, task_claimed_by, task_last_claimed_at, task_completed_at, task_created_at,
    task_updated_at, TRANSCRIPTS_FOLDER,
)
from tl0.config import load_config
from tl0.commands.viewer import HTML as VIEWER_HTML, _build_favicon_svg as _build_viewer_favicon, _build_transcript_summary, _build_transcript_messages


# ──────────────────────────────────────────────────────────────────────────────
# Bird names for worker naming
# ──────────────────────────────────────────────────────────────────────────────

BIRD_NAMES = [
    "Avocet", "Bobolink", "Crow", "Dowitcher", "Egret",
    "Finch", "Goshawk", "Harrier", "Ibis", "Jay",
    "Killdeer", "Loon", "Magpie", "Nuthatch", "Oriole",
    "Parrot", "Quail", "Robin", "Sparrow", "Towhee",
    "Uguisu", "Vulture", "Waxwing", "Xenops", "Yellowthroat",
    "Zebra Finch",
]


# ──────────────────────────────────────────────────────────────────────────────
# Loop process wrapper
# ──────────────────────────────────────────────────────────────────────────────

class LoopWorker:
    """Tracks a single task_loop.sh subprocess."""

    __slots__ = (
        "slot_id", "proc", "status_file", "log_lines",
        "started_at", "finished_at", "exit_code", "loop_args",
    )

    LOG_CAPACITY = 500  # keep last N lines of stdout

    def __init__(self, slot_id: str, proc: subprocess.Popen,
                 status_file: Path, loop_args: list[str]):
        self.slot_id = slot_id
        self.proc = proc
        self.status_file = status_file
        self.log_lines: list[str] = []
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.loop_args = loop_args

    def poll(self) -> int | None:
        if self.exit_code is not None:
            return self.exit_code
        rc = self.proc.poll()
        if rc is not None:
            self.exit_code = rc
            self.finished_at = time.time()
        return rc

    def read_status(self) -> dict:
        try:
            if self.status_file.exists():
                return json.loads(self.status_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def kill(self):
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def drain_stdout(self):
        """Non-blocking read of available stdout lines."""
        if self.proc.stdout is None:
            return
        import select
        while True:
            ready, _, _ = select.select([self.proc.stdout], [], [], 0)
            if not ready:
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            self.log_lines.append(line.decode("utf-8", errors="replace").rstrip("\n"))
            if len(self.log_lines) > self.LOG_CAPACITY:
                self.log_lines = self.log_lines[-self.LOG_CAPACITY:]


# ──────────────────────────────────────────────────────────────────────────────
# Supervisor state (thread-safe)
# ──────────────────────────────────────────────────────────────────────────────

class SupervisorState:

    def __init__(self, loop_script: Path, base_loop_args: list[str]):
        self._lock = threading.Lock()
        self.loop_script = loop_script
        self.base_loop_args = base_loop_args
        self.desired_parallelism: int = 0
        self.workers: dict[str, LoopWorker] = {}
        self.history: list[dict] = []
        self.status_dir = Path(f"/tmp/tl0-supervisor-{os.getpid()}")
        self.status_dir.mkdir(parents=True, exist_ok=True)
        self.quota_dir = self.status_dir / "quota"
        self.quota_dir.mkdir(parents=True, exist_ok=True)
        self.shutting_down = False
        self.total_completed = 0
        # Quota tracking
        self.quota_snapshots: list[dict] = []  # [{timestamp, utilization, resets_at, status, ...}]
        self.quota_auto_drained = False  # True if we auto-drained due to high utilization
        self._pre_drain_parallelism: int = 0

    def _next_bird_name(self) -> str:
        """Return the first bird name not currently in use by an active worker."""
        used = {w.slot_id for w in self.workers.values()}
        for name in BIRD_NAMES:
            if name not in used:
                return name
        # Fallback if all bird names are taken
        return f"worker-{uuid.uuid4().hex[:6]}"

    def spawn_loop(self) -> LoopWorker:
        bird_name = self._next_bird_name()
        slot_id = bird_name
        status_file = self.status_dir / f"{slot_id}.json"

        env = os.environ.copy()
        env["TL0_LOOP_STATUS_FILE"] = str(status_file)
        env["TL0_QUOTA_DIR"] = str(self.quota_dir)
        env["TL0_LOOP_SLOT_ID"] = slot_id

        args = [
            "bash", str(self.loop_script),
            "--max-tasks", "1",
            "--agent", bird_name,
        ] + self.base_loop_args

        proc = subprocess.Popen(
            args,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        worker = LoopWorker(slot_id, proc, status_file, self.base_loop_args)
        with self._lock:
            self.workers[slot_id] = worker
        return worker

    def reap_and_reconcile(self):
        with self._lock:
            # Drain stdout from all workers
            for w in self.workers.values():
                w.drain_stdout()

            finished_ids = []
            for slot_id, w in self.workers.items():
                if w.poll() is not None:
                    finished_ids.append(slot_id)

            for slot_id in finished_ids:
                w = self.workers.pop(slot_id)
                w.drain_stdout()  # final drain
                status = w.read_status()
                self.history.append({
                    "slot_id": w.slot_id,
                    "task_id": status.get("task_id", ""),
                    "task_title": status.get("task_title", ""),
                    "started_at": w.started_at,
                    "finished_at": w.finished_at,
                    "exit_code": w.exit_code,
                    "log_tail": w.log_lines[-20:],
                })
                if w.exit_code == 0 and status.get("task_id"):
                    self.total_completed += 1
                self.history = self.history[-50:]
                try:
                    w.status_file.unlink(missing_ok=True)
                except OSError:
                    pass

            active_count = len(self.workers)
            deficit = self.desired_parallelism - active_count

        # Read quota files from workers
        self._collect_quota_snapshots()

        # Auto-drain if utilization >= 90%
        self._check_auto_drain()

        # Recompute deficit after potential auto-drain (drain sets desired_parallelism = 0)
        with self._lock:
            deficit = self.desired_parallelism - len(self.workers)

        # Spawn outside the lock
        if deficit > 0 and not self.shutting_down:
            for _ in range(deficit):
                self.spawn_loop()

    def _collect_quota_snapshots(self):
        """Read quota info files written by workers."""
        try:
            for f in self.quota_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    # Only add if newer than our last snapshot
                    ts = data.get("timestamp", 0)
                    if not self.quota_snapshots or ts > self.quota_snapshots[-1].get("timestamp", 0):
                        self.quota_snapshots.append(data)
                    # Keep last 100 snapshots
                    if len(self.quota_snapshots) > 100:
                        self.quota_snapshots = self.quota_snapshots[-100:]
                except (json.JSONDecodeError, OSError):
                    pass
        except OSError:
            pass

    def _check_auto_drain(self):
        """Auto-drain pool when quota utilization >= 90%."""
        if not self.quota_snapshots:
            return
        latest = self.quota_snapshots[-1]
        utilization = latest.get("utilization")
        status = latest.get("status", "")

        if status == "rejected" or (utilization is not None and utilization >= 0.9):
            if not self.quota_auto_drained and self.desired_parallelism > 0:
                self._pre_drain_parallelism = self.desired_parallelism
                self.quota_auto_drained = True
                # Drain: stop spawning, kill idle workers
                self.drain()

        # If quota was auto-drained and resets_at has passed, restore parallelism
        if self.quota_auto_drained:
            resets_at = latest.get("resets_at")
            if resets_at and time.time() > resets_at:
                self.quota_auto_drained = False
                if self.desired_parallelism == 0 and self._pre_drain_parallelism > 0:
                    self.desired_parallelism = self._pre_drain_parallelism
                    self._pre_drain_parallelism = 0

    def get_quota_info(self) -> dict:
        """Compute quota status from recent snapshots."""
        if not self.quota_snapshots:
            return {"available": False}

        latest = self.quota_snapshots[-1]
        result = {
            "available": True,
            "status": latest.get("status", ""),
            "utilization": latest.get("utilization"),
            "resets_at": latest.get("resets_at"),
            "rate_limit_type": latest.get("rate_limit_type", ""),
            "last_updated": latest.get("timestamp"),
            "auto_drained": self.quota_auto_drained,
            "burn_rate_per_min": None,
            "projected_exhaustion_min": None,
        }

        # Compute burn rate from snapshots with utilization data
        util_points = [
            (s["timestamp"], s["utilization"])
            for s in self.quota_snapshots
            if s.get("utilization") is not None and s.get("timestamp")
        ]
        if len(util_points) >= 2:
            # Use the earliest and latest points for a smoothed rate
            t0, u0 = util_points[0]
            t1, u1 = util_points[-1]
            dt_min = (t1 - t0) / 60.0
            if dt_min > 0:
                burn_rate = (u1 - u0) / dt_min  # utilization change per minute
                result["burn_rate_per_min"] = round(burn_rate, 6)
                if burn_rate > 0 and u1 is not None:
                    remaining = 1.0 - u1
                    result["projected_exhaustion_min"] = round(remaining / burn_rate, 1)

        return result

    def get_snapshot(self) -> dict:
        with self._lock:
            active = []
            for w in self.workers.values():
                status = w.read_status()
                active.append({
                    "slot_id": w.slot_id,
                    "pid": w.proc.pid,
                    "started_at": w.started_at,
                    "elapsed_s": round(time.time() - w.started_at, 1),
                    "task_id": status.get("task_id", ""),
                    "task_title": status.get("task_title", ""),
                    "phase": status.get("phase", "starting"),
                })
            return {
                "desired_parallelism": self.desired_parallelism,
                "active_count": len(self.workers),
                "total_completed": self.total_completed,
                "active": sorted(active, key=lambda x: x["started_at"]),
                "history": list(self.history),
            }

    def get_logs(self, slot_id: str) -> list[str] | None:
        with self._lock:
            w = self.workers.get(slot_id)
            if w:
                w.drain_stdout()
                return list(w.log_lines)
            # Check history
            for h in self.history:
                if h["slot_id"] == slot_id:
                    return h.get("log_tail", [])
        return None

    def set_parallelism(self, n: int):
        with self._lock:
            self.desired_parallelism = max(0, n)

    def kill_all(self):
        with self._lock:
            for w in self.workers.values():
                w.kill()
            self.desired_parallelism = 0

    def drain(self):
        with self._lock:
            self.desired_parallelism = 0
            for w in self.workers.values():
                status = w.read_status()
                phase = status.get("phase", "")
                if phase in ("polling", "idle", "starting", ""):
                    w.kill()

    def spawn_oneoff(self, task_id: str) -> LoopWorker:
        """Spawn a worker that runs exactly one specific task, then exits."""
        bird_name = self._next_bird_name()
        slot_id = bird_name
        status_file = self.status_dir / f"{slot_id}.json"

        env = os.environ.copy()
        env["TL0_LOOP_STATUS_FILE"] = str(status_file)
        env["TL0_QUOTA_DIR"] = str(self.quota_dir)
        env["TL0_LOOP_SLOT_ID"] = slot_id

        args = [
            "bash", str(self.loop_script),
            "--task-id", task_id,
            "--agent", bird_name,
        ] + self.base_loop_args

        proc = subprocess.Popen(
            args,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        worker = LoopWorker(slot_id, proc, status_file, self.base_loop_args)
        with self._lock:
            self.workers[slot_id] = worker
        return worker

    def shutdown(self):
        self.shutting_down = True
        self.kill_all()


def _reaper_thread(state: SupervisorState):
    while not state.shutting_down:
        try:
            state.reap_and_reconcile()
        except Exception:
            pass
        time.sleep(2)


# ──────────────────────────────────────────────────────────────────────────────
# Embedded HTML
# ──────────────────────────────────────────────────────────────────────────────

SUPERVISOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{PAGE_TITLE}}</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
:root {
  --bg: #f5f6f8;
  --card-bg: #ffffff;
  --border: #e1e4e8;
  --text: #1f2937;
  --text-muted: #6b7280;
  --header-h: 48px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

/* Header */
#header {
  height: var(--header-h);
  background: {{HEADER_BG}};
  color: white;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  flex-shrink: 0;
  user-select: none;
}
#header h1 { font-size: 14px; font-weight: 600; letter-spacing: 0.2px; }
#header .stats { font-size: 11px; color: #9ca3af; margin-left: auto; }

/* Main content */
.content { max-width: 960px; margin: 0 auto; padding: 20px; width: 100%; }

/* Cards */
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.card h2 {
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

/* Controls */
.controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.parallelism-control {
  display: flex;
  align-items: center;
  gap: 8px;
}
.parallelism-control label {
  font-weight: 500;
  font-size: 13px;
}
.parallelism-control .value {
  font-size: 24px;
  font-weight: 700;
  min-width: 36px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.btn {
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid var(--border);
  background: white;
  font-size: 12px;
  font-weight: 500;
  transition: background 0.1s;
}
.btn:hover { background: #f3f4f6; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.btn-primary { background: #2563eb; color: white; border-color: #2563eb; }
.btn-primary:hover { background: #1d4ed8; }
.btn-warn { background: #f59e0b; color: white; border-color: #f59e0b; }
.btn-warn:hover { background: #d97706; }
.btn-danger { background: #ef4444; color: white; border-color: #ef4444; }
.btn-danger:hover { background: #dc2626; }
.spacer { flex: 1; }

/* Status badges */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}
.badge-pending    { background: #e5e7eb; color: #374151; }
.badge-claimed    { background: #dbeafe; color: #1e40af; }
.badge-in-progress { background: #fef3c7; color: #92400e; }
.badge-done       { background: #d1fae5; color: #065f46; }
.badge-stuck      { background: #fee2e2; color: #991b1b; }
.badge-failed     { background: #fecaca; color: #7f1d1d; }

/* Phase badges */
.phase {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}
.phase-polling   { background: #e5e7eb; color: #374151; }
.phase-starting  { background: #e5e7eb; color: #374151; }
.phase-idle      { background: #e5e7eb; color: #374151; }
.phase-claimed   { background: #dbeafe; color: #1e40af; }
.phase-executing { background: #fef3c7; color: #92400e; }
.phase-merging   { background: #d1fae5; color: #065f46; }
.phase-quota_rejected { background: #fee2e2; color: #991b1b; }
.phase-quota_backoff  { background: #fee2e2; color: #991b1b; }
.phase-failed         { background: #fecaca; color: #7f1d1d; }

/* Tables */
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 8px;
  border-bottom: 1px solid #f3f4f6;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
tr:last-child td { border-bottom: none; }
.task-title { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-id { font-family: monospace; font-size: 11px; color: var(--text-muted); }
.empty-state { color: var(--text-muted); font-style: italic; padding: 12px 8px; }

/* Task summary chips */
.task-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.task-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}
.task-chip .count { font-weight: 700; }

/* Log viewer */
.log-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 100;
}
.log-overlay.active { display: flex; align-items: center; justify-content: center; }
.log-panel {
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 10px;
  width: 90%;
  max-width: 800px;
  height: 70vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.log-header {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  background: #2d2d2d;
  border-bottom: 1px solid #404040;
  gap: 12px;
}
.log-header h3 { font-size: 13px; font-weight: 600; color: #e5e7eb; }
.log-header .close-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  font-size: 18px;
  padding: 4px 8px;
}
.log-header .close-btn:hover { color: white; }
.log-body {
  flex: 1;
  overflow: auto;
  padding: 12px 16px;
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Create task form */
.create-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}
.create-toggle h2 { margin-bottom: 0; }
.create-form { display: none; margin-top: 12px; }
.create-form.active { display: block; }
.form-row { margin-bottom: 10px; }
.form-row label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.form-row input, .form-row textarea, .form-row select {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  background: white;
  color: var(--text);
}
.form-row textarea { min-height: 80px; resize: vertical; }
.form-row input:focus, .form-row textarea:focus, .form-row select:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37,99,235,0.15);
}
.form-row-inline {
  display: flex;
  gap: 12px;
}
.form-row-inline .form-row { flex: 1; margin-bottom: 0; }
.form-actions { display: flex; gap: 8px; margin-top: 12px; }
.form-error {
  color: #dc2626;
  font-size: 12px;
  margin-top: 8px;
  display: none;
}
.form-error.active { display: block; }

/* Quota bar */
.quota-bar-outer {
  width: 100%;
  height: 20px;
  background: #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  margin: 8px 0;
}
.quota-bar-inner {
  height: 100%;
  border-radius: 10px;
  transition: width 0.5s ease, background 0.3s ease;
}
.quota-details {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 6px;
}
.quota-details span { white-space: nowrap; }
.quota-details .label { font-weight: 600; color: var(--text); }
.quota-auto-drain {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  background: #fee2e2;
  color: #991b1b;
  margin-left: 8px;
}

.form-success {
  color: #065f46;
  font-size: 12px;
  margin-top: 8px;
  display: none;
}
.form-success.active { display: block; }
</style>
</head>
<body>
  <div id="header">
    <h1>{{PAGE_TITLE}}</h1>
    <span class="stats" id="stats"></span>
    <a href="/viewer/" style="color:white; text-decoration:none; font-size:12px; padding:4px 10px; border:1px solid rgba(255,255,255,0.3); border-radius:6px; font-weight:500;">Viewer →</a>
  </div>

  <div class="content">
    <!-- Controls -->
    <div class="card">
      <h2>Parallelism</h2>
      <div class="controls">
        <div class="parallelism-control">
          <button class="btn btn-sm" id="btn-down" title="Decrease">&#x2212;</button>
          <span class="value" id="parallelism-display">0</span>
          <button class="btn btn-sm" id="btn-up" title="Increase">+</button>
        </div>
        <span style="color:var(--text-muted); font-size:12px" id="active-label">0 active</span>
        <div class="spacer"></div>
        <button class="btn btn-warn" id="btn-drain" title="Stop spawning new loops; kill idle ones; let executing loops finish">Drain</button>
        <button class="btn btn-danger" id="btn-kill" title="Kill all loops immediately">Kill All</button>
        <button class="btn btn-sm" id="btn-free-all" title="Free all claimed tasks back to pending">Free All</button>
        <button class="btn btn-sm" id="btn-reset-failed" title="Reset failed tasks back to pending so they can be retried" style="display:none">Reset Failed</button>
      </div>
    </div>

    <!-- Quota -->
    <div class="card" id="quota-card" style="display:none">
      <h2>API Quota</h2>
      <div id="quota-container"></div>
    </div>

    <!-- Active Workers -->
    <div class="card">
      <h2>Active Loops</h2>
      <div id="workers-container">
        <div class="empty-state">No active loops. Increase parallelism to start.</div>
      </div>
    </div>

    <!-- Task Queue Summary -->
    <div class="card">
      <h2>Task Queue</h2>
      <div class="task-summary" id="task-summary">
        <span class="empty-state">Loading...</span>
      </div>
    </div>

    <!-- Create Task -->
    <div class="card">
      <div class="create-toggle" id="create-toggle">
        <h2>Create Task</h2>
        <button class="btn btn-sm btn-primary" id="create-expand-btn">+ New Task</button>
      </div>
      <div class="create-form" id="create-form">
        <div class="form-row">
          <label for="ct-title">Title</label>
          <input type="text" id="ct-title" placeholder="Action-oriented task title" maxlength="200">
        </div>
        <div class="form-row">
          <label for="ct-description">Description</label>
          <textarea id="ct-description" placeholder="Full implementation specification..."></textarea>
        </div>
        <div class="form-row-inline">
          <div class="form-row">
            <label for="ct-model">Model</label>
            <select id="ct-model">
              <option value="">(default)</option>
            </select>
          </div>
          <div class="form-row">
            <label for="ct-tags">Tags</label>
            <input type="text" id="ct-tags" placeholder="area:api, priority:high">
          </div>
        </div>
        <div class="form-row">
          <label for="ct-blocked-by">Blocked By (task ID prefixes, comma-separated)</label>
          <input type="text" id="ct-blocked-by" placeholder="abc123, def456">
        </div>
        <div class="form-actions">
          <button class="btn btn-primary" id="ct-submit">Create Task</button>
          <button class="btn" id="ct-cancel">Cancel</button>
        </div>
        <div class="form-error" id="ct-error"></div>
        <div class="form-success" id="ct-success"></div>
      </div>
    </div>

    <!-- History -->
    <div class="card">
      <h2>Recent Completions</h2>
      <div id="history-container">
        <div class="empty-state">No completions yet.</div>
      </div>
    </div>
  </div>

  <!-- Log overlay -->
  <div class="log-overlay" id="log-overlay">
    <div class="log-panel">
      <div class="log-header">
        <h3 id="log-title">Logs</h3>
        <button class="close-btn" id="log-close">&times;</button>
      </div>
      <div class="log-body" id="log-body"></div>
    </div>
  </div>

<script>
let state = { desired_parallelism: 0, active_count: 0, total_completed: 0, active: [], history: [] };
let taskCounts = {};

function formatElapsed(s) {
  s = Math.floor(s);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60), sec = s % 60;
  if (m < 60) return m + 'm' + sec + 's';
  const h = Math.floor(m / 60);
  return h + 'h' + (m % 60) + 'm';
}

function formatTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function escHtml(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

async function apiPost(path, body) {
  await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : '{}'
  });
  await refresh();
}

async function setParallelism(n) {
  await apiPost('/api/parallelism', { desired: Math.max(0, n) });
}

async function refresh() {
  try {
    const res = await fetch('/api/status');
    state = await res.json();
    render();
  } catch (e) { /* server might be shutting down */ }
}

function render() {
  // Header stats
  document.getElementById('stats').textContent =
    'Completed: ' + state.total_completed + '  |  Active: ' + state.active_count;

  // Parallelism controls
  document.getElementById('parallelism-display').textContent = state.desired_parallelism;
  document.getElementById('active-label').textContent = state.active_count + ' active';

  // Workers table
  const wc = document.getElementById('workers-container');
  if (state.active.length === 0) {
    wc.innerHTML = '<div class="empty-state">No active loops. Increase parallelism to start.</div>';
  } else {
    let html = '<table><thead><tr>';
    html += '<th>Slot</th><th>Task</th><th>Phase</th><th>Elapsed</th><th></th>';
    html += '</tr></thead><tbody>';
    for (const w of state.active) {
      const title = w.task_title
        ? escHtml(w.task_title)
        : '<span style="color:var(--text-muted)">(waiting for task)</span>';
      const tid = w.task_id ? '<div class="task-id">' + escHtml(w.task_id.substring(0, 8)) + '</div>' : '';
      html += '<tr>';
      html += '<td style="font-family:monospace; font-size:11px">' + escHtml(w.slot_id) + '</td>';
      html += '<td><div class="task-title">' + title + '</div>' + tid + '</td>';
      html += '<td><span class="phase phase-' + escHtml(w.phase) + '">' + escHtml(w.phase) + '</span></td>';
      html += '<td>' + formatElapsed(w.elapsed_s) + '</td>';
      html += '<td><button class="btn btn-sm" onclick="viewLogs(\'' + escHtml(w.slot_id) + '\')">Logs</button></td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    wc.innerHTML = html;
  }

  // History table
  const hc = document.getElementById('history-container');
  if (state.history.length === 0) {
    hc.innerHTML = '<div class="empty-state">No completions yet.</div>';
  } else {
    let html = '<table><thead><tr>';
    html += '<th>Task</th><th>Duration</th><th>Exit</th><th>Finished</th><th></th>';
    html += '</tr></thead><tbody>';
    for (const h of state.history.slice().reverse()) {
      const title = h.task_title
        ? escHtml(h.task_title)
        : '<span style="color:var(--text-muted)">' + escHtml(h.slot_id) + '</span>';
      const dur = (h.finished_at && h.started_at)
        ? formatElapsed(h.finished_at - h.started_at)
        : '-';
      const exitClass = h.exit_code === 0 ? 'color:#065f46' : 'color:#991b1b; font-weight:600';
      html += '<tr>';
      html += '<td class="task-title">' + title + '</td>';
      html += '<td>' + dur + '</td>';
      html += '<td style="' + exitClass + '">' + (h.exit_code ?? '-') + '</td>';
      html += '<td>' + formatTime(h.finished_at) + '</td>';
      html += '<td><button class="btn btn-sm" onclick="viewLogs(\'' + escHtml(h.slot_id) + '\')">Logs</button></td>';
      html += '</tr>';
    }
    html += '</tbody></table>';
    hc.innerHTML = html;
  }

  // Task summary
  renderTaskSummary();
}

function renderTaskSummary() {
  const el = document.getElementById('task-summary');
  const order = ['pending', 'claimed', 'in-progress', 'done', 'failed', 'stuck'];
  const parts = [];
  for (const s of order) {
    const n = taskCounts[s] || 0;
    if (n > 0) {
      parts.push('<span class="task-chip badge-' + s + '"><span class="count">' + n + '</span> ' + s + '</span>');
    }
  }
  el.innerHTML = parts.length ? parts.join('') : '<span class="empty-state">No tasks</span>';
  // Show Reset Failed button only when there are failed tasks
  const resetFailedBtn = document.getElementById('btn-reset-failed');
  if (resetFailedBtn) {
    resetFailedBtn.style.display = (taskCounts['failed'] || 0) > 0 ? '' : 'none';
  }
}

async function refreshTasks() {
  try {
    const res = await fetch('/api/tasks');
    const tasks = await res.json();
    taskCounts = {};
    for (const t of tasks) {
      taskCounts[t.status] = (taskCounts[t.status] || 0) + 1;
    }
    renderTaskSummary();
  } catch (e) { /* ignore */ }
}

// Log viewer
let logRefreshInterval = null;

async function viewLogs(slotId) {
  document.getElementById('log-title').textContent = 'Logs - ' + slotId;
  document.getElementById('log-overlay').classList.add('active');
  await loadLogs(slotId);
  // Auto-refresh logs while open
  if (logRefreshInterval) clearInterval(logRefreshInterval);
  logRefreshInterval = setInterval(() => loadLogs(slotId), 2000);
}

async function loadLogs(slotId) {
  try {
    const res = await fetch('/api/logs/' + slotId);
    if (res.ok) {
      const data = await res.json();
      const body = document.getElementById('log-body');
      body.textContent = data.lines.join('\n') || '(no output yet)';
      body.scrollTop = body.scrollHeight;
    }
  } catch (e) { /* ignore */ }
}

function closeLogs() {
  document.getElementById('log-overlay').classList.remove('active');
  if (logRefreshInterval) { clearInterval(logRefreshInterval); logRefreshInterval = null; }
}

// Event handlers
document.getElementById('btn-up').onclick = () => setParallelism(state.desired_parallelism + 1);
document.getElementById('btn-down').onclick = () => setParallelism(state.desired_parallelism - 1);
document.getElementById('btn-drain').onclick = async () => {
  await apiPost('/api/drain');
};
document.getElementById('btn-kill').onclick = async () => {
  if (!confirm('Kill all running loops immediately?\n\nTasks in progress will be left in claimed/in-progress state.\nUse "Free All" button to reset them.')) return;
  await apiPost('/api/kill-all');
};
document.getElementById('btn-free-all').onclick = async () => {
  if (!confirm('Free all claimed tasks back to pending?')) return;
  const res = await apiPost('/api/free-all');
  if (res && res.freed !== undefined) {
    alert('Freed ' + res.freed + ' task(s).');
  }
  refreshTasks();
};
document.getElementById('btn-reset-failed').onclick = async () => {
  if (!confirm('Reset all failed tasks back to pending so they can be retried?\n\nThis clears failure reasons. Use this after fixing the underlying issue.')) return;
  const res = await fetch('/api/reset-failed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  const data = await res.json();
  if (data.reset !== undefined) {
    alert('Reset ' + data.reset + ' failed task(s) back to pending.');
  }
  refreshTasks();
};
document.getElementById('log-close').onclick = closeLogs;
document.getElementById('log-overlay').onclick = (e) => {
  if (e.target === document.getElementById('log-overlay')) closeLogs();
};
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLogs();
});

// Create task form
const createForm = document.getElementById('create-form');
const createToggle = document.getElementById('create-expand-btn');
const ctError = document.getElementById('ct-error');
const ctSuccess = document.getElementById('ct-success');

// Populate model dropdown with valid models
async function populateModels() {
  const sel = document.getElementById('ct-model');
  // Models come from config; we infer them from existing tasks
  try {
    const res = await fetch('/api/tasks');
    const tasks = await res.json();
    const models = new Set();
    for (const t of tasks) { if (t.model) models.add(t.model); }
    for (const m of ['sonnet', 'opus', 'haiku']) models.add(m); // defaults
    for (const m of Array.from(models).sort()) {
      const opt = document.createElement('option');
      opt.value = m; opt.textContent = m;
      sel.appendChild(opt);
    }
  } catch (e) { /* ignore */ }
}
populateModels();

createToggle.onclick = () => {
  createForm.classList.toggle('active');
  ctError.classList.remove('active');
  ctSuccess.classList.remove('active');
};
document.getElementById('ct-cancel').onclick = () => {
  createForm.classList.remove('active');
  ctError.classList.remove('active');
  ctSuccess.classList.remove('active');
};

document.getElementById('ct-submit').onclick = async () => {
  ctError.classList.remove('active');
  ctSuccess.classList.remove('active');

  const title = document.getElementById('ct-title').value.trim();
  const description = document.getElementById('ct-description').value.trim();
  const model = document.getElementById('ct-model').value;
  const tags = document.getElementById('ct-tags').value.trim();
  const blockedBy = document.getElementById('ct-blocked-by').value.trim();

  if (!title) { ctError.textContent = 'Title is required'; ctError.classList.add('active'); return; }
  if (!description) { ctError.textContent = 'Description is required'; ctError.classList.add('active'); return; }

  try {
    const res = await fetch('/api/tasks/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description, model, tags, blocked_by: blockedBy })
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      ctError.textContent = data.error || 'Unknown error';
      ctError.classList.add('active');
      return;
    }
    ctSuccess.textContent = 'Created: ' + data.title + ' (' + data.id.substring(0, 8) + ')';
    ctSuccess.classList.add('active');
    // Clear form
    document.getElementById('ct-title').value = '';
    document.getElementById('ct-description').value = '';
    document.getElementById('ct-model').value = '';
    document.getElementById('ct-tags').value = '';
    document.getElementById('ct-blocked-by').value = '';
    // Refresh task counts
    refreshTasks();
  } catch (e) {
    ctError.textContent = 'Network error: ' + e.message;
    ctError.classList.add('active');
  }
};

// Quota display
let quotaData = { available: false };

async function refreshQuota() {
  try {
    const res = await fetch('/api/quota');
    quotaData = await res.json();
    renderQuota();
  } catch (e) { /* ignore */ }
}

function renderQuota() {
  const card = document.getElementById('quota-card');
  const container = document.getElementById('quota-container');
  if (!quotaData.available) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';

  const util = quotaData.utilization;
  const pct = util != null ? Math.round(util * 100) : null;
  const status = quotaData.status || '';

  // Bar color
  let barColor = '#22c55e'; // green
  if (status === 'rejected') barColor = '#ef4444'; // red
  else if (pct != null && pct >= 90) barColor = '#ef4444'; // red
  else if (pct != null && pct >= 70) barColor = '#f59e0b'; // yellow

  let html = '';

  // Progress bar
  if (pct != null) {
    html += '<div class="quota-bar-outer">';
    html += '<div class="quota-bar-inner" style="width:' + Math.min(pct, 100) + '%;background:' + barColor + '"></div>';
    html += '</div>';
  }

  // Details row
  html += '<div class="quota-details">';
  if (pct != null) {
    html += '<span><span class="label">Utilization:</span> ' + pct + '%</span>';
  }
  if (status === 'rejected') {
    html += '<span style="color:#991b1b;font-weight:600">QUOTA EXHAUSTED</span>';
  }
  if (quotaData.burn_rate_per_min != null && quotaData.burn_rate_per_min > 0) {
    html += '<span><span class="label">Burn rate:</span> ' + (quotaData.burn_rate_per_min * 100).toFixed(2) + '%/min</span>';
  }
  if (quotaData.projected_exhaustion_min != null && quotaData.projected_exhaustion_min > 0 && status !== 'rejected') {
    const mins = Math.round(quotaData.projected_exhaustion_min);
    html += '<span><span class="label">Exhaustion in:</span> ~' + mins + ' min</span>';
  }
  if (quotaData.resets_at) {
    const resetDate = new Date(quotaData.resets_at * 1000);
    html += '<span><span class="label">Resets:</span> ' + resetDate.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) + '</span>';
  }
  if (quotaData.auto_drained) {
    html += '<span class="quota-auto-drain">AUTO-DRAINED</span>';
  }
  if (quotaData.rate_limit_type) {
    html += '<span><span class="label">Window:</span> ' + escHtml(quotaData.rate_limit_type) + '</span>';
  }
  html += '</div>';

  container.innerHTML = html;
}

// Initial load + polling
refresh();
refreshTasks();
refreshQuota();
setInterval(refresh, 2000);
setInterval(refreshTasks, 10000);
setInterval(refreshQuota, 10000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Favicon
# ──────────────────────────────────────────────────────────────────────────────

_FAVICON_SVG_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="{color}"/>
  <text x="16" y="22" text-anchor="middle" font-family="sans-serif"
        font-size="11" font-weight="bold" fill="white">TL0</text>
</svg>"""


def _build_favicon_svg(color: str) -> str:
    return _FAVICON_SVG_TEMPLATE.format(color=color)


# ──────────────────────────────────────────────────────────────────────────────
# Task creation helper (avoids sys.exit from save_task on validation error)
# ──────────────────────────────────────────────────────────────────────────────

def _create_task(data: dict) -> dict:
    """Create a task from POST data. Raises ValueError on validation failure."""
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not title:
        raise ValueError("Title is required")
    if not description:
        raise ValueError("Description is required")

    model = data.get("model") or None
    if model and VALID_MODELS and model not in VALID_MODELS:
        raise ValueError(f"Model must be one of {sorted(VALID_MODELS)}, got '{model}'")

    tags_raw = data.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if isinstance(tags_raw, str) else tags_raw

    blocked_by_raw = data.get("blocked_by", "")
    if isinstance(blocked_by_raw, str):
        blocked_by = [b.strip() for b in blocked_by_raw.split(",") if b.strip()]
    else:
        blocked_by = blocked_by_raw

    # Resolve blocked_by prefixes to full UUIDs
    resolved_blocked = []
    for ref in blocked_by:
        try:
            t = load_task(ref)
            resolved_blocked.append(t["id"])
        except SystemExit:
            raise ValueError(f"Could not resolve blocked-by reference: '{ref}'")

    created_by = None
    parent_raw = (data.get("parent") or "").strip()
    if parent_raw:
        try:
            creator = load_task(parent_raw)
            created_by = creator["id"]
        except SystemExit:
            raise ValueError(f"Could not resolve parent reference: '{parent_raw}'")

    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "events": [{"type": "created", "at": now_iso()}],
        "blocked_by": resolved_blocked,
        "tags": tags,
        "model": model,
        "thinking": data.get("thinking"),
        "result": None,
        "created_by": created_by,
    }

    errors = validate_task_shape(task)
    if errors:
        raise ValueError("Validation failed: " + "; ".join(errors))

    save_task(task)

    git_commit(f"create: {title}")
    return {"ok": True, "id": task_id, "title": title}


# ──────────────────────────────────────────────────────────────────────────────
# HTTP server
# ──────────────────────────────────────────────────────────────────────────────

class SupervisorHandler(BaseHTTPRequestHandler):
    state: SupervisorState = None  # type: ignore[assignment]
    page_title: str = "tl0 Supervisor"
    header_bg: str = "#1e3a5f"
    favicon_svg: str = ""
    viewer_page_title: str = "tl0 Task Viewer"
    viewer_header_bg: str = "#111827"
    viewer_favicon_svg: str = ""
    code_repo: str = ""
    github_repo_url: str = ""

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            rendered = SUPERVISOR_HTML \
                .replace('{{PAGE_TITLE}}', html.escape(self.page_title)) \
                .replace('{{HEADER_BG}}', self.header_bg)
            self._respond(200, rendered, 'text/html')

        elif path == '/favicon.svg':
            self._respond(200, self.favicon_svg, 'image/svg+xml')

        elif path == '/api/status':
            self._respond_json(self.state.get_snapshot())

        elif path == '/api/tasks':
            raw = load_all_tasks()
            tasks = []
            for t in raw:
                t = dict(t)
                t["status"]        = task_status(t)
                t["claimed_by"]    = task_claimed_by(t)
                t["claimed_at"]    = task_last_claimed_at(t)
                t["completed_at"]  = task_completed_at(t)
                t["created_at"]    = task_created_at(t)
                tasks.append(t)
            self._respond_json(tasks)

        elif path == '/api/quota':
            self._respond_json(self.state.get_quota_info())

        elif path.startswith('/api/logs/'):
            slot_id = path[len('/api/logs/'):]
            lines = self.state.get_logs(slot_id)
            if lines is not None:
                self._respond_json({"lines": lines})
            else:
                self.send_response(404)
                self.end_headers()

        # ── Embedded viewer routes ──
        elif path in ('/viewer', '/viewer/', '/viewer/index.html'):
            rendered = VIEWER_HTML \
                .replace('{{PAGE_TITLE}}', html.escape(self.viewer_page_title)) \
                .replace('{{HEADER_BG}}', self.viewer_header_bg) \
                .replace('{{GITHUB_REPO_URL}}', self.github_repo_url) \
                .replace("href=\"/favicon.svg\"", "href=\"/viewer/favicon.svg\"") \
                .replace("fetch('/api/tasks')", "fetch('/viewer/api/tasks')") \
                .replace("fetch('/api/transcripts/'", "fetch('/viewer/api/transcripts/'") \
                .replace("fetch('/api/transcript-messages/'", "fetch('/viewer/api/transcript-messages/'") \
                .replace("fetch(`/api/transcript-messages/", "fetch(`/viewer/api/transcript-messages/") \
                .replace("fetch('/api/all-transcripts')", "fetch('/viewer/api/all-transcripts')") \
                .replace("fetch('/api/loop-log/'", "fetch('/viewer/api/loop-log/'") \
                .replace("fetch('/api/diff/'", "fetch('/viewer/api/diff/'") \
                .replace("fetch('/api/diff-stat/'", "fetch('/viewer/api/diff-stat/'")
            # Inject a nav link back to the supervisor
            rendered = rendered.replace(
                '<span id="supervisor-link-slot"></span>',
                '<a href="/" style="color:#e5e7eb; text-decoration:none; font-size:11px; padding:4px 10px; border:1px solid #4b5563; border-radius:5px; font-weight:500; background:#374151;">← Supervisor</a>',
                1,
            )
            # Enable "Run Now" button when embedded in supervisor
            rendered = rendered.replace(
                "window.__SUPERVISOR_ENABLED__ = false",
                "window.__SUPERVISOR_ENABLED__ = true",
                1,
            )
            rendered = rendered.replace(
                "window.__SUPERVISOR_API_BASE__ = ''",
                "window.__SUPERVISOR_API_BASE__ = '/viewer'",
                1,
            )
            self._respond(200, rendered, 'text/html')

        elif path == '/viewer/favicon.svg':
            self._respond(200, self.viewer_favicon_svg, 'image/svg+xml')

        elif path == '/viewer/api/tasks':
            raw = load_all_tasks()
            tasks = []
            for t in raw:
                t = dict(t)
                t["status"]        = task_status(t)
                t["claimed_by"]    = task_claimed_by(t)
                t["claimed_at"]    = task_last_claimed_at(t)
                t["completed_at"]  = task_completed_at(t)
                t["created_at"]    = task_created_at(t)
                t["updated_at"]    = task_updated_at(t)
                t["parent_task"]   = t.get("created_by")
                tasks.append(t)
            # Derive tasks_created by scanning created_by references
            for t in tasks:
                t["tasks_created"] = [o["id"] for o in tasks if o.get("created_by") == t["id"]]
            self._respond_json(tasks)

        elif path.startswith('/viewer/api/transcript-messages/'):
            parts = path.split('/')
            # /viewer/api/transcript-messages/<task_id>/<filename>
            if len(parts) >= 6:
                task_id = parts[4]
                filename = parts[5]
                self._respond_json(_build_transcript_messages(task_id, filename))
            else:
                self.send_response(404)
                self.end_headers()

        elif path.startswith('/viewer/api/transcripts/'):
            task_id = path.split('/')[-1]
            self._respond_json(_build_transcript_summary(task_id))

        elif path == '/viewer/api/all-transcripts':
            result = {}
            if TRANSCRIPTS_FOLDER.is_dir():
                for td in TRANSCRIPTS_FOLDER.iterdir():
                    if td.is_dir():
                        result[td.name] = _build_transcript_summary(td.name)
            self._respond_json(result)

        elif path.startswith('/viewer/api/loop-log/'):
            task_id = path.split('/')[-1]
            log_path = TRANSCRIPTS_FOLDER / task_id / 'loop.log'
            if log_path.exists():
                self._respond(200, log_path.read_text(), 'text/plain')
            else:
                self.send_response(404)
                self.end_headers()

        elif path.startswith('/viewer/api/diff-stat/'):
            sha = path.split('/')[-1]
            if not re.fullmatch(r'[0-9a-fA-F]{6,40}', sha) or not self.code_repo:
                self._respond_json({'files': 0})
                return
            try:
                result = subprocess.run(
                    ['git', 'diff', '--numstat', f'{sha}~1..{sha}'],
                    cwd=self.code_repo,
                    capture_output=True, text=True, timeout=10,
                )
                files = len([l for l in result.stdout.splitlines() if l.strip()]) if result.returncode == 0 else 0
            except Exception:
                files = 0
            self._respond_json({'files': files})

        elif path.startswith('/viewer/api/diff/'):
            sha = path.split('/')[-1]
            if not re.fullmatch(r'[0-9a-fA-F]{6,40}', sha) or not self.code_repo:
                self.send_response(400)
                self.end_headers()
                return
            try:
                result = subprocess.run(
                    ['git', 'diff', f'{sha}~1..{sha}'],
                    cwd=self.code_repo,
                    capture_output=True, text=True, timeout=30,
                )
                diff_text = result.stdout if result.returncode == 0 else f"git diff failed: {result.stderr}"
            except Exception as exc:
                diff_text = f"Error running git diff: {exc}"
            self._respond(200, diff_text, 'text/plain')

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == '/api/parallelism':
            data = json.loads(body) if body else {}
            n = int(data.get("desired", 0))
            self.state.set_parallelism(n)
            self.state.reap_and_reconcile()
            self._respond_json({"ok": True, "desired": n})

        elif path == '/api/kill-all':
            self.state.kill_all()
            self._respond_json({"ok": True})

        elif path == '/api/drain':
            self.state.drain()
            self._respond_json({"ok": True})

        elif path == '/api/free-all':
            try:
                from tl0.common import load_all_tasks, save_task, task_status, task_claimed_by, now_iso, git_commit
                tasks = load_all_tasks()
                freed = []
                for task in tasks:
                    if task_status(task) == "claimed":
                        task["events"].append({"type": "freed", "at": now_iso()})
                        save_task(task)
                        freed.append(task["id"])
                if freed:
                    git_commit(f"free-all: released {len(freed)} tasks back to pending")
                self._respond_json({"ok": True, "freed": len(freed)})
            except Exception as e:
                self._respond_error(500, str(e))

        elif path == '/api/reset-failed':
            try:
                from tl0.common import load_all_tasks, save_task, task_status, now_iso, git_commit
                tasks = load_all_tasks()
                reset = []
                for task in tasks:
                    if task_status(task) == "failed":
                        # Remove the failed event and the preceding claimed event
                        while task["events"] and task["events"][-1]["type"] == "failed":
                            task["events"].pop()
                        while task["events"] and task["events"][-1]["type"] == "claimed":
                            task["events"].pop()
                        task["failure_reason"] = None
                        save_task(task)
                        reset.append(task["id"])
                if reset:
                    git_commit(f"reset-failed: {len(reset)} tasks reset to pending")
                self._respond_json({"ok": True, "reset": len(reset)})
            except Exception as e:
                self._respond_error(500, str(e))

        elif path == '/api/tasks/create':
            try:
                data = json.loads(body) if body else {}
                result = _create_task(data)
                self._respond_json(result)
            except ValueError as e:
                self._respond_error(400, str(e))
            except Exception as e:
                self._respond_error(500, str(e))

        elif path in ('/api/run-task', '/viewer/api/run-task'):
            try:
                data = json.loads(body) if body else {}
                task_id = data.get("task_id", "").strip()
                if not task_id:
                    self._respond_error(400, "task_id is required")
                    return
                # Validate task exists and is pending
                try:
                    task = load_task(task_id)
                except SystemExit:
                    self._respond_error(404, f"Task not found: {task_id}")
                    return
                status = task_status(task)
                if status != "pending":
                    self._respond_error(400, f"Task is {status}, not pending")
                    return
                worker = self.state.spawn_oneoff(task["id"])
                self._respond_json({"ok": True, "slot_id": worker.slot_id, "task_id": task["id"]})
            except Exception as e:
                self._respond_error(500, str(e))

        else:
            self.send_response(404)
            self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length) if length else b''

    def _respond_json(self, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond(self, code: int, text: str, content_type: str):
        body = text.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', f'{content_type}; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_error(self, code: int, message: str):
        body = json.dumps({"error": message}).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # suppress access log noise


# ──────────────────────────────────────────────────────────────────────────────
# Port helper
# ──────────────────────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Supervisor: manage parallel task loops via web UI'
    )
    parser.add_argument('--port', type=int, default=0,
                        help='Port to serve on (default: random free port)')
    parser.add_argument('--no-open', action='store_true',
                        help="Don't auto-open the browser")
    parser.add_argument('--model', default='',
                        help='Model filter passed to each task loop')
    parser.add_argument('--tag', action='append', default=[],
                        help='Tag filter passed to each task loop (repeatable)')
    parser.add_argument('--prompt', default='',
                        help='Execution prompt path passed to each task loop')
    parser.add_argument('--poll', type=int, default=30,
                        help='Poll interval for idle loops in seconds (default: 30)')
    parser.add_argument('--parallelism', '-n', type=int, default=0,
                        help='Initial number of loops to start (default: 0, set via UI)')
    args = parser.parse_args(argv)

    loop_script = Path(__file__).resolve().parent.parent / "loop" / "task_loop.sh"
    if not loop_script.exists():
        print(f"Error: task loop script not found at {loop_script}", file=sys.stderr)
        sys.exit(1)

    # Build base args for loops
    base_loop_args = []
    if args.model:
        base_loop_args += ["--model", args.model]
    for tag in args.tag:
        base_loop_args += ["--tag", tag]
    if args.prompt:
        base_loop_args += ["--prompt", args.prompt]
    base_loop_args += ["--poll", str(args.poll)]

    # Auto-reset any tasks erroneously completed due to quota errors
    try:
        from tl0.commands.reset_quota_errors import main as reset_quota_main
        reset_quota_main([])
    except Exception as e:
        print(f"  (quota reset check: {e})")

    state = SupervisorState(loop_script, base_loop_args)
    state.set_parallelism(args.parallelism)

    # Start reaper thread
    reaper = threading.Thread(target=_reaper_thread, args=(state,), daemon=True)
    reaper.start()

    # Trigger initial spawn if parallelism > 0
    if args.parallelism > 0:
        state.reap_and_reconcile()

    # Configure handler
    port = args.port or _find_free_port()
    config = load_config()
    header_bg = config.get("supervisor_color", "#1e3a5f")

    SupervisorHandler.state = state
    SupervisorHandler.page_title = f"{Path.cwd().name} — tl0 Supervisor"
    SupervisorHandler.header_bg = header_bg
    SupervisorHandler.favicon_svg = _build_favicon_svg(header_bg)

    viewer_bg = config.get("viewer_color", "#111827")
    SupervisorHandler.viewer_page_title = f"{Path.cwd().name} — tl0 Task Viewer"
    SupervisorHandler.viewer_header_bg = viewer_bg
    SupervisorHandler.viewer_favicon_svg = _build_viewer_favicon(viewer_bg)

    # Resolve code repo path and GitHub URL for diff viewer
    code_repo = ""
    github_repo_url = ""
    try:
        code_repo = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        pass
    if code_repo:
        try:
            remote_url = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=code_repo, capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            m = re.match(r'git@github\.com:(.+?)(?:\.git)?$', remote_url)
            if m:
                github_repo_url = f'https://github.com/{m.group(1)}'
            else:
                m = re.match(r'https://github\.com/(.+?)(?:\.git)?$', remote_url)
                if m:
                    github_repo_url = f'https://github.com/{m.group(1)}'
        except Exception:
            pass
    SupervisorHandler.code_repo = code_repo
    SupervisorHandler.github_repo_url = github_repo_url

    server = HTTPServer(('127.0.0.1', port), SupervisorHandler)
    url = f'http://localhost:{port}'

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    print(f'Supervisor -> {url}  (Ctrl+C to stop)')
    print(f'Viewer     -> {url}/viewer/')
    if base_loop_args:
        print(f'  Loop args: {" ".join(base_loop_args)}')
    print(f'  Initial parallelism: {args.parallelism}')

    # Register signal handlers that reliably stop serve_forever().
    # Relying on KeyboardInterrupt alone is fragile on macOS when
    # the server is actively handling a request (browser polls every 2s).
    def _request_shutdown(signum, frame):
        server._BaseServer__shutdown_request = True

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        server.serve_forever()
    finally:
        print('\nShutting down...')
        state.shutdown()
        deadline = time.time() + 10
        while state.workers and time.time() < deadline:
            state.reap_and_reconcile()
            time.sleep(0.5)
        for w in list(state.workers.values()):
            w.kill()
        shutil.rmtree(state.status_dir, ignore_errors=True)
        print('Stopped.')


if __name__ == '__main__':
    main()
