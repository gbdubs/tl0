#!/usr/bin/env python3
"""Open a web-based task viewer in the default browser.

Usage:
    python3 util/viewer.py [--port PORT] [--no-open]
"""

import argparse
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


from tl0.common import load_all_tasks, task_status, task_claimed_by, task_last_claimed_at, task_completed_at, task_created_at, task_updated_at, TRANSCRIPTS_FOLDER, TASKS_FOLDER, git_commit
from tl0.config import load_config
from tl0.commands.shared_modal import SHARED_MODAL_CSS, SHARED_MODAL_JS

# ──────────────────────────────────────────────────────────────────────────────
# Single-page HTML app (embedded so the script is self-contained)
# ──────────────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{PAGE_TITLE}}</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
:root {
  --bg: #f5f6f8;
  --sidebar-bg: #ffffff;
  --border: #e1e4e8;
  --text: #1f2937;
  --text-muted: #6b7280;
  --accent: #2563eb;
  --accent-bg: #eff6ff;
  --sidebar-w: 400px;
  --header-h: 48px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Header ────────────────────────────────────────────────── */
#header {
  height: var(--header-h);
  background: {{HEADER_BG}};
  color: white;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  user-select: none;
}
#header h1 { font-size: 14px; font-weight: 600; letter-spacing: 0.2px; }
#stats { font-size: 11px; color: #9ca3af; margin-left: auto; }
#refresh-btn {
  padding: 4px 10px; border-radius: 5px; cursor: pointer;
  background: #374151; border: 1px solid #4b5563; color: #e5e7eb;
  font-size: 11px; transition: background 0.1s;
}
#refresh-btn:hover { background: #4b5563; }
#view-dropdown-wrap { position: relative; }
#view-dropdown-btn {
  padding: 4px 10px; border-radius: 5px; cursor: pointer;
  background: #374151; border: 1px solid #4b5563; color: #e5e7eb;
  font-size: 11px; transition: all 0.1s;
}
#view-dropdown-btn:hover { background: #4b5563; }
#view-dropdown-btn.active { background: #2563eb; border-color: #3b82f6; color: white; }
#view-dropdown-menu {
  position: absolute; top: calc(100% + 4px); right: 0;
  background: #1f2937; border: 1px solid #374151; border-radius: 6px;
  overflow: hidden; z-index: 100; min-width: 150px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
#view-dropdown-menu button {
  display: block; width: 100%; padding: 8px 14px; text-align: left;
  background: none; border: none; color: #e5e7eb; font-size: 12px;
  cursor: pointer; transition: background 0.1s;
}
#view-dropdown-menu button:hover { background: #374151; }
#view-dropdown-menu button.active { color: #60a5fa; }
#sidebar.hidden { display: none; }

/* ── App shell ──────────────────────────────────────────────── */
#app { display: flex; flex: 1; overflow: hidden; }

/* ── Sidebar ────────────────────────────────────────────────── */
#sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Controls */
#controls {
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 7px;
  flex-shrink: 0;
}
#search-row { display: flex; gap: 6px; align-items: center; }
#search {
  flex: 1; padding: 7px 10px;
  border: 1px solid var(--border); border-radius: 6px;
  font-size: 13px; outline: none; background: #fafbfc;
}
#search:focus { border-color: var(--accent); background: white; }
#clear-filters {
  display: none; padding: 7px 12px; border-radius: 6px; cursor: pointer;
  font-size: 13px; font-weight: 500; white-space: nowrap;
  border: 1px solid #3b82f6; background: #2563eb; color: white;
  transition: all 0.1s;
}
#clear-filters:hover { background: #1d4ed8; border-color: #1d4ed8; }
.no-results-clear-filters {
  margin-top: 10px; padding: 6px 14px; border-radius: 6px; cursor: pointer;
  font-size: 12px; font-weight: 500;
  border: 1px solid #3b82f6; background: #2563eb; color: white;
  transition: all 0.1s;
}
.no-results-clear-filters:hover { background: #1d4ed8; border-color: #1d4ed8; }

/* Column filter context menu */
.col-filter-menu {
  position: fixed; z-index: 9999; min-width: 180px;
  background: white; border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12); padding: 4px 0;
  font-size: 12px;
}
.col-filter-menu .cfm-header {
  padding: 6px 12px; font-weight: 600; color: var(--text-muted);
  border-bottom: 1px solid var(--border); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.3px;
}
.col-filter-menu .cfm-item {
  padding: 6px 12px; cursor: pointer; display: flex; align-items: center; gap: 6px;
}
.col-filter-menu .cfm-item:hover { background: #f3f4f6; }
.col-filter-menu .cfm-item .cfm-op { font-weight: 600; width: 20px; text-align: center; color: var(--accent); }

/* Active column filter pills */
.table-filter-pills { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
.table-filter-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500;
  background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; cursor: default;
}
.table-filter-pill .pill-x {
  cursor: pointer; font-size: 13px; line-height: 1; color: #93c5fd;
  margin-left: 2px;
}
.table-filter-pill .pill-x:hover { color: #dc2626; }

/* Filter chips row */
.chip-row { display: flex; gap: 4px; flex-wrap: wrap; }
.chip {
  padding: 3px 9px; border-radius: 12px; cursor: pointer;
  font-size: 11px; font-weight: 500;
  border: 1px solid var(--border);
  background: #f3f4f6; color: var(--text-muted);
  transition: all 0.1s;
  white-space: nowrap;
}
.chip:hover { border-color: #9ca3af; }
.chip.active { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
.chip[data-status="pending"].active   { background:#fff7ed; color:#c2410c; border-color:#fb923c; }
.chip[data-status="claimed"].active   { background:#eff6ff; color:#1d4ed8; border-color:#3b82f6; }
.chip[data-status="in-progress"].active { background:#f0fdf4; color:#15803d; border-color:#4ade80; }
.chip[data-status="done"].active      { background:#f0fdf4; color:#166534; border-color:#86efac; }
.chip[data-status="stuck"].active     { background:#fff1f2; color:#be123c; border-color:#fb7185; }

/* Tag filters */
#tag-section {
  border-bottom: 1px solid var(--border);
  overflow-y: auto;
  max-height: 210px;
  flex-shrink: 0;
  padding: 8px 12px;
}
.tag-group { margin-bottom: 4px; }
.tag-group-header {
  display: flex; align-items: center; gap: 4px;
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--text-muted);
  cursor: pointer; padding: 2px 0; user-select: none;
}
.tag-group-header:hover { color: var(--text); }
.tag-group-arrow { font-size: 8px; }
.tag-chips { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.tag-chip {
  padding: 2px 7px; border-radius: 10px; cursor: pointer;
  font-size: 11px; background: #f3f4f6; color: var(--text-muted);
  border: 1px solid transparent; transition: all 0.1s;
}
.tag-chip:hover { border-color: #9ca3af; }
.tag-chip.active { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }

/* View toggle */
#view-row {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
#result-count { font-size: 11px; color: var(--text-muted); margin-right: auto; }
.view-btn {
  padding: 3px 10px; border-radius: 4px; cursor: pointer;
  font-size: 11px; border: 1px solid var(--border);
  background: white; color: var(--text-muted); transition: all 0.1s;
}
.view-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

/* Task list */
#task-list-container { flex: 1; overflow-y: auto; }
.no-results {
  padding: 32px 16px; text-align: center;
  color: var(--text-muted); font-size: 13px;
}

/* Task item */
.task-item {
  display: flex; align-items: flex-start;
  padding: 7px 10px; cursor: pointer;
  border-left: 3px solid transparent;
  gap: 7px; transition: background 0.08s;
  min-width: 0;
}
.task-item:hover { background: #f9fafb; }
.task-item.selected { background: var(--accent-bg); border-left-color: var(--accent); }

.task-item[data-depth="1"] { padding-left: 22px; }
.task-item[data-depth="2"] { padding-left: 34px; }
.task-item[data-depth="3"] { padding-left: 46px; }
.task-item[data-depth="4"] { padding-left: 58px; }

.t-toggle {
  width: 24px; min-width: 24px; height: 24px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 14px; flex-shrink: 0; user-select: none;
  transition: color 0.1s; cursor: pointer;
}
.t-toggle:hover { color: var(--text); }
.t-dot {
  width: 7px; min-width: 7px; height: 7px; border-radius: 50%;
  margin-top: 4px; flex-shrink: 0;
}
.t-dot.pending     { background: #fb923c; }
.t-dot.claimed     { background: #3b82f6; }
.t-dot.in-progress { background: #22c55e; }
.t-dot.done        { background: #86efac; }
.t-dot.stuck       { background: #f87171; }

.t-body { flex: 1; min-width: 0; }
.t-title {
  font-size: 12px; line-height: 1.45; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.t-meta { display: flex; align-items: center; gap: 4px; margin-top: 2px; flex-wrap: wrap; }
.badge {
  padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 500;
}
.badge-opus    { background: #f5f3ff; color: #6d28d9; }
.badge-sonnet  { background: #eff6ff; color: #1d4ed8; }
.badge-haiku   { background: #ecfeff; color: #0e7490; }
.badge-think   { background: #fff7ed; color: #c2410c; }
.badge-block   { background: #fff1f2; color: #be123c; }
.t-sub-count   { font-size: 10px; color: #9ca3af; }

/* ── Detail panel ──────────────────────────────────────────── */
#detail { flex: 1; overflow-y: auto; padding: 0 28px 24px 28px; }
#empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 8px;
  color: var(--text-muted);
}
.d-header {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg); padding: 24px 0 12px 0; margin: 0 0 14px 0;
  border-bottom: 1px solid var(--border);
}
.d-title { font-size: 19px; font-weight: 600; line-height: 1.4; margin-bottom: 10px; }
.d-badges { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 0; }
.d-badge {
  padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 500;
}

.d-section {
  background: white; border: 1px solid var(--border); border-radius: 8px;
  padding: 0; margin-bottom: 14px; overflow: hidden;
}
.d-section.collapsed .d-section-body { display: none; }
.d-section-body { padding: 0 16px 15px 16px; }
.d-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--text-muted); margin-bottom: 0;
  padding: 15px 16px; cursor: pointer; display: flex; align-items: center;
  justify-content: space-between; user-select: none;
}
.d-label:hover { background: #f9fafb; }
.d-label::after {
  content: '▼'; font-size: 11px; color: #9ca3af; transition: transform 0.15s;
}
.d-section.collapsed .d-label::after { transform: rotate(-90deg); }
.d-section.collapsed .d-label { margin-bottom: 0; }
.d-collapsed-chips { display: none; margin-left: auto; margin-right: 8px; }
.d-collapsed-chips .sha-badge { font-size: 11px; padding: 2px 8px; }
.d-collapsed-chips .sha-github-link { font-size: 11px; }
.d-section.collapsed .d-collapsed-chips { display: flex; align-items: center; gap: 6px; }
.d-pre {
  font-size: 13px; line-height: 1.65; color: var(--text);
  white-space: pre-wrap; font-family: inherit; word-break: break-word;
}
.d-meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.d-meta-item label { display: block; font-size: 10px; color: var(--text-muted); font-weight: 600; margin-bottom: 2px; }
.d-meta-item value { display: block; font-size: 12px; word-break: break-all; }

.task-link {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px; border-radius: 6px;
  background: #f9fafb; border: 1px solid var(--border);
  cursor: pointer; margin: 3px 3px 3px 0;
  font-size: 12px; color: var(--accent); transition: background 0.1s;
}
.task-link:hover { background: var(--accent-bg); }
.task-link .t-dot { margin-top: 0; }

.d-tree-row {
  display: flex; align-items: center;
  border-bottom: 1px solid #f3f4f6; min-height: 30px;
}
.d-tree-row:last-child { border-bottom: none; }
.d-tree-toggle {
  width: 24px; min-width: 24px; height: 30px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  color: #9ca3af; font-size: 14px; flex-shrink: 0; user-select: none;
  transition: color 0.1s;
}
.d-tree-toggle:hover { color: var(--text); }
.d-tree-toggle.leaf { cursor: default; color: #d1d5db; font-size: 10px; }
.d-tree-toggle.leaf:hover { color: #d1d5db; }
.d-tree-cell {
  display: flex; align-items: center; gap: 7px; flex: 1; min-width: 0;
  padding: 4px 8px 4px 2px; cursor: pointer; color: var(--accent);
  font-size: 12px; border-radius: 4px; transition: background 0.1s;
}
.d-tree-cell:hover { background: var(--accent-bg); }
.d-tree-cell-text {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.d-tree-count {
  font-size: 10px; color: #9ca3af; flex-shrink: 0; white-space: nowrap;
  padding-right: 6px;
}

.d-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.d-tag {
  padding: 3px 8px; border-radius: 10px; font-size: 11px;
  background: #f3f4f6; color: var(--text-muted); cursor: pointer;
}
.d-tag:hover { background: var(--accent-bg); color: var(--accent); }

.file-list { list-style: none; }
.file-list li {
  padding: 4px 8px; font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; color: #4b5563; background: #f9fafb;
  border-radius: 4px; margin-bottom: 3px; word-break: break-all;
}
.result-box {
  padding: 12px; font-size: 13px;
  line-height: 1.65; color: var(--text);
}
.stuck-banner {
  background: #fff1f2; border-left: 3px solid #f87171;
  padding: 10px 12px; border-radius: 4px; font-size: 12px;
  color: #be123c; margin-bottom: 14px;
}

/* ── Event timeline ───────────────────────────────────────── */
.event-timeline { display: flex; flex-direction: column; gap: 0; }
.event-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0; font-size: 12px; position: relative;
}
.event-row:not(:last-child)::before {
  content: ''; position: absolute; left: 5px; top: 18px; bottom: -4px;
  width: 1px; background: #e5e7eb;
}
.event-dot {
  width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid white; box-shadow: 0 0 0 1px #d1d5db;
}
.event-type { font-weight: 600; width: 60px; flex-shrink: 0; }
.event-time { color: var(--text-muted); font-size: 11px; }
.event-by { color: var(--text-muted); font-size: 11px; font-family: monospace; }

/* ── Execution summary ────────────────────────────────────── */
.exec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px; margin-bottom: 10px; }
.exec-stat label { display: block; font-size: 10px; color: var(--text-muted); font-weight: 600; margin-bottom: 2px; }
.exec-stat value { display: block; font-size: 13px; font-weight: 500; }
.exec-tools { display: flex; flex-wrap: wrap; gap: 4px; }
.exec-tool {
  padding: 2px 7px; border-radius: 10px; font-size: 10px;
  background: #eff6ff; color: #2563eb; font-family: monospace;
}
.exec-invocation {
  background: #f9fafb; border-radius: 6px; padding: 8px 10px;
  margin-bottom: 6px; font-size: 12px;
}
.exec-invocation-header {
  display: flex; align-items: center; gap: 8px; font-weight: 500;
  margin-bottom: 4px;
}
{{SHARED_MODAL_CSS}}
.log-btn {
  padding: 3px 8px; border-radius: 5px; cursor: pointer;
  background: transparent; border: 1px solid var(--border); color: var(--text);
  font-size: 11px; transition: background 0.1s;
}
.log-btn:hover { background: var(--hover-bg, #f3f4f6); }
.sha-github-link {
  font-size: 11px; color: var(--text-muted); margin-left: 8px;
  text-decoration: none;
}
.sha-github-link:hover { color: var(--accent); text-decoration: underline; }
.exec-invocation { cursor: pointer; transition: background 0.1s; }
.exec-invocation:hover { background: #eef2ff; }


/* ── Search snippets & highlights ──────────────────────────── */
.t-snippet {
  font-size: 11px; color: var(--text-muted); line-height: 1.45;
  margin-top: 3px; overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  word-break: break-word;
}
mark {
  background: #fef08a; color: #713f12;
  border-radius: 2px; padding: 0 1px; font-style: normal;
}
.t-title mark { font-weight: 600; }

/* ── Chart time filter ────────────────────────────────────── */
#chart-time-filter {
  display: flex; align-items: center; gap: 8px;
  padding: 0 0 12px; flex-shrink: 0; flex-wrap: wrap;
}
#chart-time-filter .tf-label {
  font-size: 11px; color: var(--text-muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.5px;
}
#chart-time-filter .tf-btn {
  padding: 4px 10px; border-radius: 5px; cursor: pointer;
  background: #f3f4f6; border: 1px solid var(--border); color: var(--text);
  font-size: 11px; transition: all 0.15s; white-space: nowrap;
}
#chart-time-filter .tf-btn:hover { background: #e5e7eb; }
#chart-time-filter .tf-btn.active {
  background: var(--accent); border-color: var(--accent); color: white;
}
#chart-time-filter .tf-custom-wrap {
  display: flex; align-items: center; gap: 4px;
}
#chart-time-filter .tf-custom-wrap input[type="datetime-local"] {
  font-size: 11px; padding: 3px 6px; border: 1px solid var(--border);
  border-radius: 4px; background: white; color: var(--text);
}
#chart-time-filter .tf-supervisor-time {
  font-size: 10px; color: var(--text-muted); margin-left: auto;
}

/* ── Chart view ──────────────────────────────────────────── */
#chart-container {
  display: none; flex: 1; flex-direction: column;
  padding: 24px 28px; overflow: hidden;
}
#chart-container.visible { display: flex; }
#chart-svg-wrap {
  flex: 1; position: relative; min-height: 0;
}
#chart-svg-wrap svg { width: 100%; height: 100%; }
#chart-legend {
  display: flex; gap: 16px; justify-content: center;
  padding: 12px 0 4px; flex-shrink: 0;
}
.legend-item {
  display: flex; align-items: center; gap: 5px;
  font-size: 12px; color: var(--text);
}
.legend-swatch {
  width: 14px; height: 14px; border-radius: 3px;
}
#chart-tooltip {
  display: none; position: fixed;
  background: #1f2937; color: #f9fafb; font-size: 12px;
  padding: 8px 12px; border-radius: 6px;
  pointer-events: none; z-index: 100;
  line-height: 1.6; white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0,0,0,.25);
}
#chart-tooltip .tt-time {
  font-weight: 600; margin-bottom: 4px; font-size: 11px;
  color: #9ca3af; border-bottom: 1px solid #374151; padding-bottom: 4px;
}
#chart-tooltip .tt-row {
  display: flex; align-items: center; gap: 6px;
}
#chart-tooltip .tt-swatch {
  width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0;
}
.gap-indicator {
  stroke: #d1d5db; stroke-width: 1; stroke-dasharray: 3,3;
}

/* ── Table view ─────────────────────────────────────────── */
#table-container {
  display: none; flex: 1; flex-direction: column; overflow: hidden;
}
#table-container.visible { display: flex; }
#table-controls {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  flex-shrink: 0; background: var(--sidebar-bg);
}
#table-controls .table-result-count {
  font-size: 11px; color: var(--text-muted); margin-right: auto;
}
#col-picker-wrap { position: relative; }
#col-picker-btn {
  padding: 4px 10px; border-radius: 5px; cursor: pointer;
  background: white; border: 1px solid var(--border); color: var(--text);
  font-size: 11px; transition: all 0.1s;
}
#col-picker-btn:hover { border-color: #9ca3af; }
#col-picker-menu {
  position: absolute; top: calc(100% + 4px); right: 0;
  background: white; border: 1px solid var(--border); border-radius: 6px;
  z-index: 100; min-width: 180px; max-height: 400px; overflow-y: auto;
  box-shadow: 0 4px 12px rgba(0,0,0,.12); padding: 4px 0;
}
#col-picker-menu label {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px; font-size: 12px; cursor: pointer;
  transition: background 0.1s;
}
#col-picker-menu label:hover { background: #f9fafb; }
#col-picker-menu input[type="checkbox"] { margin: 0; }
#table-wrap {
  flex: 1; overflow: auto;
}
#task-table {
  width: 100%; border-collapse: collapse; font-size: 12px;
}
#task-table thead { position: sticky; top: 0; z-index: 10; }
#task-table th {
  background: #f9fafb; border-bottom: 2px solid var(--border);
  padding: 7px 10px; text-align: left; font-size: 11px;
  font-weight: 600; color: var(--text-muted); text-transform: uppercase;
  letter-spacing: 0.4px; cursor: pointer; user-select: none;
  white-space: nowrap; position: relative;
}
#task-table th:hover { background: #f3f4f6; }
#task-table th .sort-arrow {
  font-size: 9px; margin-left: 3px; color: #9ca3af;
}
#task-table th .sort-arrow.active { color: var(--accent); }
#task-table td {
  padding: 6px 10px; border-bottom: 1px solid #f3f4f6;
  white-space: nowrap; max-width: 300px;
  overflow: hidden; text-overflow: ellipsis;
}
#task-table tbody tr:hover { background: #f9fafb; }
#task-table .task-name-cell {
  color: var(--accent); cursor: pointer; font-weight: 500;
  max-width: 350px; overflow: hidden; text-overflow: ellipsis;
}
#task-table .task-name-cell:hover { text-decoration: underline; }
#task-table .num-cell { text-align: right; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px; }
#task-table .badge { font-size: 10px; }
#task-table .merge-yes { color: #dc2626; font-weight: 600; }
#task-table .merge-no { color: #9ca3af; }
#table-loading {
  display: flex; align-items: center; justify-content: center;
  padding: 48px; color: var(--text-muted); font-size: 13px;
}

/* Scrollbars */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

/* ── Delete button ──────────────────────────────────────────── */
.delete-task-btn {
  padding: 3px 10px; border-radius: 5px; cursor: pointer;
  background: #dc2626; border: 1px solid #b91c1c; color: white;
  font-size: 11px; margin-left: auto; transition: background 0.1s;
  flex-shrink: 0;
}
.delete-task-btn:hover { background: #b91c1c; }
.run-now-btn {
  padding: 3px 10px; border-radius: 5px; cursor: pointer;
  background: #2563eb; border: 1px solid #1d4ed8; color: white;
  font-size: 11px; transition: background 0.1s;
  flex-shrink: 0;
}
.run-now-btn:hover { background: #1d4ed8; }
.run-now-btn:disabled { background: #93c5fd; border-color: #93c5fd; cursor: not-allowed; }

/* ── Delete confirmation modal ──────────────────────────────── */
#delete-modal {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
#delete-modal-box {
  background: white; border-radius: 8px; padding: 20px 24px;
  max-width: 440px; width: 90%; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
#delete-modal-title { font-weight: 600; font-size: 15px; margin-bottom: 10px; color: var(--text); }
#delete-modal-body { font-size: 13px; color: var(--text); margin-bottom: 16px; line-height: 1.5; }
#delete-modal-btns { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
.modal-btn { padding: 5px 14px; border-radius: 5px; cursor: pointer; font-size: 12px; transition: all 0.1s; }
.modal-btn-cancel { background: white; border: 1px solid var(--border); color: var(--text); }
.modal-btn-cancel:hover { background: #f3f4f6; }
.modal-btn-secondary { background: white; border: 1px solid #9ca3af; color: var(--text); }
.modal-btn-secondary:hover { background: #f3f4f6; border-color: #6b7280; }
.modal-btn-danger { background: #dc2626; border: 1px solid #b91c1c; color: white; }
.modal-btn-danger:hover { background: #b91c1c; }
#delete-modal-error { color: #dc2626; font-size: 12px; margin-top: 8px; }

/* ── Report Card view ─────────────────────────────────────── */
#report-container {
  display: none; flex: 1; flex-direction: column; overflow-y: auto;
  padding: 24px 28px; background: var(--bg);
}
#report-container.visible { display: flex; }
.rc-section { margin-bottom: 32px; }
.rc-section-title {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--text-muted);
  margin-bottom: 12px; padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.rc-stage-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.rc-stage-label {
  width: 80px; min-width: 80px; font-size: 11px; font-weight: 600;
  color: var(--text); text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rc-stage-chart { flex: 1; }
.rc-stage-chart svg { display: block; overflow: visible; }
.rc-stage-ann { font-size: 10px; color: var(--text-muted); white-space: nowrap; min-width: 110px; }
.rc-stat-cards { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
.rc-stat-card {
  background: white; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; min-width: 110px;
}
.rc-stat-card label {
  display: block; font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.4px; color: var(--text-muted); margin-bottom: 4px;
}
.rc-stat-card value { display: block; font-size: 18px; font-weight: 700; color: var(--text); }
.rc-stat-card small { display: block; font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.rc-tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.rc-tool-card {
  background: white; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px;
}
.rc-tool-card-title {
  font-size: 11px; font-weight: 600; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 8px;
}
.rc-no-data {
  display: flex; align-items: center; justify-content: center;
  height: 120px; color: var(--text-muted); font-size: 13px;
}
.rc-axis-hint { font-size: 10px; color: #d1d5db; padding-left: 92px; margin-top: 2px; margin-bottom: 10px; }

/* ── Time-split controls ─────────────────────────────────────── */
.rc-split-bar {
  display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  background: white; border: 2px solid #3b82f6; border-radius: 8px;
  margin-bottom: 20px; flex-wrap: wrap;
}
.rc-split-bar label { font-size: 12px; font-weight: 700; color: #1d4ed8; text-transform: uppercase; letter-spacing: 0.4px; white-space: nowrap; }
.rc-split-bar input[type="datetime-local"] {
  font-size: 13px; padding: 5px 10px; border: 1px solid var(--border); border-radius: 5px;
  background: var(--bg); color: var(--text); font-family: inherit;
}
.rc-split-bar button {
  font-size: 12px; padding: 5px 12px; border: 1px solid var(--border); border-radius: 5px;
  background: var(--bg); color: var(--text-muted); cursor: pointer; font-family: inherit;
}
.rc-split-bar button:hover { background: var(--border); }
.rc-split-bar .rc-split-hint { font-size: 12px; color: var(--text-muted); }
.rc-saved-splits { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; width: 100%; margin-top: 4px; }
.rc-saved-splits .rc-saved-label { font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.3px; }
.rc-saved-chip {
  display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px;
  background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 12px;
  font-size: 11px; color: #4338ca; cursor: pointer; white-space: nowrap;
}
.rc-saved-chip:hover { background: #e0e7ff; border-color: #a5b4fc; }
.rc-saved-chip.active { background: #4338ca; color: white; border-color: #4338ca; }
.rc-saved-chip .rc-chip-x {
  font-size: 13px; line-height: 1; color: #818cf8; cursor: pointer; margin-left: 2px;
}
.rc-saved-chip .rc-chip-x:hover { color: #dc2626; }
.rc-saved-chip.active .rc-chip-x { color: rgba(255,255,255,0.7); }
.rc-saved-chip.active .rc-chip-x:hover { color: #fca5a5; }

/* ── Before/After paired rows ────────────────────────────────── */
.rc-split-group { margin-bottom: 14px; border-left: 3px solid var(--border); padding-left: 8px; }
.rc-split-group-label {
  font-size: 11px; font-weight: 700; color: var(--text); margin-bottom: 4px;
}
.rc-stage-row .rc-split-tag {
  font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px;
  padding: 1px 5px; border-radius: 3px; white-space: nowrap;
}
.rc-split-tag.before { background: #dbeafe; color: #1d4ed8; }
.rc-split-tag.after  { background: #d1fae5; color: #059669; }

.rc-split-summary {
  display: flex; gap: 24px; margin-bottom: 20px; flex-wrap: wrap;
}
.rc-split-summary-col {
  flex: 1; min-width: 280px;
}
.rc-split-summary-col .rc-split-col-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px;
  margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid var(--border);
}
.rc-split-col-title.before { color: #1d4ed8; border-color: #3b82f6; }
.rc-split-col-title.after  { color: #059669; border-color: #10b981; }

.rc-delta { font-size: 11px; font-weight: 600; margin-left: 6px; }
.rc-delta.better { color: #059669; }
.rc-delta.worse  { color: #dc2626; }
.rc-delta.neutral { color: var(--text-muted); }
</style>
</head>
<body>

<div id="header">
  <h1>Digest Task Viewer</h1>
  <div id="stats">Loading…</div>
  <button id="refresh-btn" onclick="refresh()">↺ Refresh</button>
  <div id="view-dropdown-wrap">
    <button id="view-dropdown-btn" onclick="toggleViewDropdown()">View ▼</button>
    <div id="view-dropdown-menu" style="display:none">
      <button id="view-detail-item" onclick="setView('tree'); closeViewDropdown()">Detail</button>
      <button id="view-chart-item" onclick="setView('chart'); closeViewDropdown()">Chart</button>
      <button id="view-table-item" onclick="setView('table'); closeViewDropdown()">Table</button>
      <button id="view-report-item" onclick="setView('report'); closeViewDropdown()">Report Card</button>
      <button id="view-sidebar-item" onclick="toggleSidebar(); closeViewDropdown()">Hide Sidebar</button>
    </div>
  </div>
  <span id="supervisor-link-slot"></span>
</div>

<div id="app">
  <aside id="sidebar">
    <div id="controls">
      <div id="search-row">
        <input type="text" id="search" placeholder="Search title, description, ID… (press /)" autocomplete="off" spellcheck="false">
        <button id="clear-filters" onclick="clearAllFilters()">Clear Filters</button>
      </div>
      <div class="chip-row" id="status-chips">
        <span class="chip active" data-status="all">All</span>
        <span class="chip" data-status="pending">Pending</span>
        <span class="chip" data-status="claimed">Claimed</span>
        <span class="chip" data-status="in-progress">In Progress</span>
        <span class="chip" data-status="done">Done</span>
        <span class="chip" data-status="stuck">Stuck</span>
      </div>
      <div class="chip-row" id="model-chips">
        <span class="chip active" data-model="all">All Models</span>
        <span class="chip" data-model="opus">Opus</span>
        <span class="chip" data-model="sonnet">Sonnet</span>
        <span class="chip" data-model="haiku">Haiku</span>
      </div>
    </div>

    <div id="tag-section">
    </div>

    <div id="view-row">
      <span id="result-count"></span>
    </div>

    <div id="task-list-container">
      <div id="task-list"><div class="no-results">Loading tasks…</div></div>
    </div>
  </aside>

  <main id="detail">
    <div id="empty-state">
      <div>Select a task to view details</div>
      <div class="hint">Press / to search · Click tag pills to filter</div>
    </div>
    <div id="task-detail" style="display:none"></div>
  </main>

  <div id="chart-container">
    <div id="chart-time-filter">
      <span class="tf-label">Time range:</span>
      <button class="tf-btn active" data-range="all" onclick="setChartTimeRange('all')">All time</button>
      <button class="tf-btn" data-range="supervisor" onclick="setChartTimeRange('supervisor')" id="tf-supervisor-btn" style="display:none">Since supervisor start</button>
      <button class="tf-btn" data-range="5m" onclick="setChartTimeRange('5m')">5m</button>
      <button class="tf-btn" data-range="15m" onclick="setChartTimeRange('15m')">15m</button>
      <button class="tf-btn" data-range="30m" onclick="setChartTimeRange('30m')">30m</button>
      <button class="tf-btn" data-range="1h" onclick="setChartTimeRange('1h')">1h</button>
      <button class="tf-btn" data-range="3h" onclick="setChartTimeRange('3h')">3h</button>
      <button class="tf-btn" data-range="6h" onclick="setChartTimeRange('6h')">6h</button>
      <button class="tf-btn" data-range="12h" onclick="setChartTimeRange('12h')">12h</button>
      <button class="tf-btn" data-range="24h" onclick="setChartTimeRange('24h')">24h</button>
      <div class="tf-custom-wrap">
        <button class="tf-btn" data-range="custom" onclick="setChartTimeRange('custom')">Custom since:</button>
        <input type="datetime-local" id="tf-custom-dt" onchange="onCustomTimeChange()" />
      </div>
      <span class="tf-supervisor-time" id="tf-supervisor-time"></span>
    </div>
    <div id="chart-svg-wrap"></div>
    <div id="chart-legend"></div>
  </div>

  <div id="table-container">
    <div id="table-controls">
      <span class="table-result-count" id="table-result-count"></span>
      <div id="col-picker-wrap">
        <button id="col-picker-btn" onclick="toggleColPicker()">Columns ▼</button>
        <div id="col-picker-menu" style="display:none"></div>
      </div>
    </div>
    <div id="table-filter-pills" class="table-filter-pills"></div>
    <div id="table-wrap">
      <table id="task-table"><thead><tr></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div id="report-container">
    <div class="rc-split-bar">
      <label>Time split</label>
      <input type="datetime-local" id="rc-split-dt" onchange="onRcSplitChange()" />
      <button id="rc-split-clear-btn" onclick="clearRcSplit()" style="display:none">Clear</button>
      <span class="rc-split-hint" id="rc-split-hint">Set a split point to compare before / after</span>
      <div class="rc-saved-splits" id="rc-saved-splits"></div>
    </div>
    <div id="report-loading" style="display:none;padding:24px;color:var(--text-muted)">Loading transcript data…</div>
    <div id="report-content"></div>
  </div>
</div>

<div id="delete-modal" style="display:none" onclick="closeDeleteModal(event)">
  <div id="delete-modal-box">
    <div id="delete-modal-title">Delete Task</div>
    <div id="delete-modal-body"></div>
    <div id="delete-modal-btns"></div>
    <div id="delete-modal-error"></div>
  </div>
</div>
<div id="chart-tooltip"></div>

<script>window.__GITHUB_REPO_URL__ = '{{GITHUB_REPO_URL}}';window.__SUPERVISOR_ENABLED__ = false;window.__SUPERVISOR_API_BASE__ = '';window.__SUPERVISOR_STARTED_AT__ = null;</script>
<script>
// ── State ────────────────────────────────────────────────────
let allTasks = [];
let taskMap  = {};

const state = {
  selectedId:            null,
  statusFilter:          'all',
  modelFilter:           'all',
  activeTags:            [],
  search:                '',
  view:                  'table',
  sidebarVisible:        true,
  expandedNodes:         new Set(),
  detailExpandedNodes:   new Set(),
  expandedTagCategories: new Set(),
  tableFilters:          [],   // [{col, op, value, display}]
};

// ── URL state helpers ─────────────────────────────────────────
let _updatingFromUrl = false;

function stateToUrl() {
  const p = new URLSearchParams();
  if (state.selectedId)             p.set('id',      state.selectedId);
  if (state.statusFilter !== 'all') p.set('status',  state.statusFilter);
  if (state.modelFilter  !== 'all') p.set('model',   state.modelFilter);
  if (state.activeTags.length)      p.set('tags',    state.activeTags.join(','));
  if (state.search)                 p.set('q',       state.search);
  if (state.view !== 'table')       p.set('view',    state.view);
  if (state.tableFilters.length)    p.set('filters', JSON.stringify(state.tableFilters));
  return p;
}

function urlToState() {
  const p = new URLSearchParams(location.search);
  state.selectedId   = p.get('id')     || null;
  state.statusFilter = p.get('status') || 'all';
  state.modelFilter  = p.get('model')  || 'all';
  state.activeTags   = p.get('tags')   ? p.get('tags').split(',').filter(Boolean) : [];
  state.search       = p.get('q')      || '';
  const v = p.get('view');
  state.view = (v && ['tree','chart','table','report'].includes(v)) ? v : 'table';
  try {
    const f = p.get('filters');
    state.tableFilters = f ? JSON.parse(f) : [];
  } catch (_) { state.tableFilters = []; }
}

function pushUrl(replace = false) {
  const p = stateToUrl();
  const url = p.toString() ? '?' + p.toString() : location.pathname;
  if (replace) history.replaceState(null, '', url);
  else         history.pushState(null, '', url);
}

// Handle browser native back/forward
window.addEventListener('popstate', () => {
  _updatingFromUrl = true;
  urlToState();
  applyStateToUI();
  renderTagFilters();
  renderTaskList();
  if (state.view === 'chart') renderChart();
  else if (state.view === 'table') renderTable();
  else if (state.view === 'report') renderReport();
  _updatingFromUrl = false;
});

// ── localStorage persistence ─────────────────────────────────
function loadSavedState() {
  // Legacy hash migration: #<uuid> → ?id=<uuid>
  if (!location.search && location.hash && location.hash.length > 1) {
    const hashId = location.hash.slice(1);
    if (/^[0-9a-f-]{36}$/.test(hashId)) {
      history.replaceState(null, '', '?id=' + hashId);
    }
  }
  // Phase 1: read navigation state from URL params
  urlToState();
  // Phase 2: read UI preferences from localStorage
  try {
    const s = JSON.parse(localStorage.getItem('digest_viewer') || '{}');
    if (s.sidebarVisible !== undefined) state.sidebarVisible = s.sidebarVisible;
    if (s.expandedNodes)         state.expandedNodes         = new Set(s.expandedNodes);
    if (s.detailExpandedNodes)   state.detailExpandedNodes   = new Set(s.detailExpandedNodes);
    if (s.expandedTagCategories) state.expandedTagCategories = new Set(s.expandedTagCategories);
  } catch (_) {}
}

function persist(replace = false) {
  if (_updatingFromUrl) return;
  pushUrl(replace);
  persistPrefs();
}

function persistPrefs() {
  try {
    localStorage.setItem('digest_viewer', JSON.stringify({
      sidebarVisible:        state.sidebarVisible,
      expandedNodes:         [...state.expandedNodes],
      detailExpandedNodes:   [...state.detailExpandedNodes],
      expandedTagCategories: [...state.expandedTagCategories],
    }));
  } catch (_) {}
}

// ── Data loading ─────────────────────────────────────────────
let _initialLoad = true;
async function loadTasks() {
  try {
    const res = await fetch('/api/tasks');
    allTasks  = await res.json();
    taskMap   = Object.fromEntries(allTasks.map(t => [t.id, t]));
    updateStats();
    renderTagFilters();
    updateClearFiltersButton();
    // Always render the task tree sidebar (it's visible in all view modes).
    // Then render the active main view (chart or table) on top.
    renderTaskList();
    if (state.view === 'chart') renderChart();
    else if (state.view === 'table') renderTable();
    else if (state.view === 'report') renderReport();
    if (_initialLoad) {
      _initialLoad = false;
      if (state.selectedId && taskMap[state.selectedId]) {
        _activateTask(state.selectedId);
        // Auto-open transcript if ?transcript=latest is in the URL
        const _urlP = new URLSearchParams(location.search);
        if (_urlP.get('transcript') === 'latest') {
          const _t = taskMap[state.selectedId];
          if (_t && _t.transcript && _t.transcript.invocations && _t.transcript.invocations.length) {
            const _lastInv = _t.transcript.invocations[_t.transcript.invocations.length - 1];
            showInvocationDetail(state.selectedId, _lastInv.file);
          }
        }
      } else if (state.selectedId) {
        state.selectedId = null;
        persist(true);
      }
    } else if (state.selectedId && taskMap[state.selectedId]) {
      // On refresh, re-render the open task in case data changed
      renderDetail(state.selectedId);
    }
    schedulePoll();
  } catch (e) {
    document.getElementById('task-list').innerHTML =
      `<div class="no-results">Failed to load tasks: ${e.message}</div>`;
  }
}

let _pollTimer = null;
function schedulePoll() {
  if (_pollTimer) clearTimeout(_pollTimer);
  const hasActive = allTasks.some(t => t.status === 'pending' || t.status === 'claimed' || t.status === 'in-progress');
  if (hasActive) _pollTimer = setTimeout(loadTasks, 30000);
}

// ── Run task now (one-off via supervisor) ─────────────────────
async function runTaskNow(taskId) {
  const btn = document.getElementById('run-now-' + taskId);
  if (btn) { btn.disabled = true; btn.textContent = 'Starting...'; }
  try {
    const apiBase = window.__SUPERVISOR_API_BASE__ || '';
    const res = await fetch(apiBase + '/api/run-task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId })
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      alert('Failed to run task: ' + (data.error || 'Unknown error'));
      if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
      return;
    }
    if (btn) { btn.textContent = 'Started (' + data.slot_id + ')'; }
    setTimeout(loadTasks, 3000);
  } catch (e) {
    alert('Failed to run task: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
  }
}

// ── Delete task ───────────────────────────────────────────────
let _deleteTargetId = null;

function confirmDelete(taskId) {
  const task = taskMap[taskId];
  if (!task) return;
  _deleteTargetId = taskId;

  const children = allTasks.filter(t => t.created_by === taskId);
  const modal = document.getElementById('delete-modal');
  const body  = document.getElementById('delete-modal-body');
  const btns  = document.getElementById('delete-modal-btns');
  const err   = document.getElementById('delete-modal-error');
  err.textContent = '';

  if (children.length === 0) {
    body.textContent = `Delete task "${task.title}"? This cannot be undone.`;
    btns.innerHTML = `
      <button class="modal-btn modal-btn-cancel" onclick="closeDeleteModal()">Cancel</button>
      <button class="modal-btn modal-btn-danger" onclick="executeDelete(false)">Delete</button>`;
  } else {
    body.innerHTML = `Task "<strong>${esc(task.title)}</strong>" has ${children.length} child task${children.length > 1 ? 's' : ''}. What would you like to do?`;
    btns.innerHTML = `
      <button class="modal-btn modal-btn-cancel" onclick="closeDeleteModal()">Cancel</button>
      <button class="modal-btn modal-btn-secondary" onclick="executeDelete(false)">Delete task only</button>
      <button class="modal-btn modal-btn-danger" onclick="executeDelete(true)">Delete task and children</button>`;
  }

  modal.style.display = 'flex';
}

function closeDeleteModal(event) {
  if (event && event.target !== document.getElementById('delete-modal')) return;
  document.getElementById('delete-modal').style.display = 'none';
  _deleteTargetId = null;
}

async function executeDelete(includeChildren) {
  if (!_deleteTargetId) return;
  const taskId = _deleteTargetId;
  const errEl = document.getElementById('delete-modal-error');
  errEl.textContent = '';
  try {
    const res = await fetch(`/api/tasks/${taskId}/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ include_children: includeChildren }),
    });
    if (!res.ok) {
      const txt = await res.text();
      errEl.textContent = `Error: ${txt || res.status}`;
      return;
    }
    document.getElementById('delete-modal').style.display = 'none';
    _deleteTargetId = null;
    // Clear selection if deleted task was selected
    if (state.selectedId === taskId || includeChildren) {
      state.selectedId = null;
      document.getElementById('task-detail').style.display = 'none';
      document.getElementById('empty-state').style.display = '';
      persist(true);
    }
    await loadTasks();
  } catch (e) {
    errEl.textContent = `Error: ${e.message}`;
  }
}

// ── Diff-stat cache ──────────────────────────────────────────
const _diffStatCache = {};

// ── Shared modal functions (diff, transcript) ───────────────
window._modalApiBase = '';
{{SHARED_MODAL_JS}}

async function showLoopLog(taskId) {
  try {
    const res = await fetch('/api/loop-log/' + taskId);
    if (!res.ok) return;
    const text = await res.text();
    const lines = text.split('\n');
    const linesHtml = lines.map(l => `<div class="log-line">${esc(l)}</div>`).join('');
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="log-panel">
      <div class="log-panel-header">
        <h3>Loop Log — ${taskId.slice(0,8)}</h3>
        <div class="log-panel-header-actions">
          <button class="log-copy-btn" onclick="copyLoopLog(this)">Copy All</button>
          <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">✕</button>
        </div>
      </div>
      <div class="log-panel-body log-lines-body">${linesHtml}</div>
    </div>`;
    overlay._rawText = text;
    // Click lines to select/deselect for partial copy
    overlay.querySelectorAll('.log-line').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.shiftKey && overlay._lastClickedLine != null) {
          const allLines = [...overlay.querySelectorAll('.log-line')];
          const curIdx = allLines.indexOf(el);
          const lastIdx = overlay._lastClickedLine;
          const [lo, hi] = curIdx < lastIdx ? [curIdx, lastIdx] : [lastIdx, curIdx];
          allLines.forEach((l, i) => {
            if (i >= lo && i <= hi) l.classList.add('selected');
          });
        } else if (e.metaKey || e.ctrlKey) {
          el.classList.toggle('selected');
        } else {
          const wasSelected = el.classList.contains('selected');
          overlay.querySelectorAll('.log-line.selected').forEach(l => l.classList.remove('selected'));
          if (!wasSelected) el.classList.add('selected');
        }
        overlay._lastClickedLine = [...overlay.querySelectorAll('.log-line')].indexOf(el);
        // Update copy button label
        const selCount = overlay.querySelectorAll('.log-line.selected').length;
        const btn = overlay.querySelector('.log-copy-btn');
        btn.textContent = selCount > 0 ? `Copy ${selCount} Line${selCount > 1 ? 's' : ''}` : 'Copy All';
      });
    });
    document.body.appendChild(overlay);
  } catch (_) {}
}

function copyLoopLog(btn) {
  const overlay = btn.closest('.log-overlay');
  const selected = overlay.querySelectorAll('.log-line.selected');
  let textToCopy;
  if (selected.length > 0) {
    textToCopy = [...selected].map(el => el.textContent).join('\n');
  } else {
    textToCopy = overlay._rawText;
  }
  navigator.clipboard.writeText(textToCopy).then(() => {
    const prev = btn.textContent;
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = prev; btn.classList.remove('copied'); }, 1500);
  });
}

function renderEventTimeline(events) {
  const colorMap = {created:'#9ca3af', claimed:'#3b82f6', freed:'#fb923c', done:'#22c55e'};
  let html = '<div class="event-timeline">';
  const t0 = events.length ? new Date(events[0].at).getTime() : 0;
  events.forEach((e, i) => {
    const c = colorMap[e.type] || '#9ca3af';
    const d = new Date(e.at);
    let timeStr;
    if (i === 0) {
      timeStr = d.toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
    } else {
      const diffSec = Math.round((d.getTime() - new Date(events[i - 1].at).getTime()) / 1000);
      const m = Math.floor(diffSec / 60);
      const s = diffSec % 60;
      timeStr = m > 0 ? `+${m}m ${s}s` : `+${s}s`;
    }
    html += `<div class="event-row">
      <div class="event-dot" style="background:${c};box-shadow:0 0 0 1px ${c}"></div>
      <span class="event-type">${e.type}</span>
      <span class="event-time">${timeStr}</span>
      ${e.by ? `<span class="event-by">${esc(e.by)}</span>` : ''}
    </div>`;
  });
  html += '</div>';
  return html;
}

function renderExecSection(tx, taskId) {
  let html = '<div class="exec-grid">';
  if (tx.total_duration_ms != null) {
    const secs = (tx.total_duration_ms / 1000).toFixed(1);
    html += `<div class="exec-stat"><label>Duration</label><value>${secs}s</value></div>`;
  }
  if (tx.total_cost_usd != null) {
    html += `<div class="exec-stat"><label>Cost</label><value>$${tx.total_cost_usd.toFixed(4)}</value></div>`;
  }
  if (tx.invocations && tx.invocations.length) {
    const turns = tx.invocations.reduce((s, i) => s + (i.num_turns || 0), 0);
    html += `<div class="exec-stat"><label>Turns</label><value>${turns}</value></div>`;
  }
  if (tx.has_loop_log) {
    html += `<div class="exec-stat"><label>Log</label><value><button class="log-btn" onclick="event.stopPropagation();showLoopLog('${taskId}')">View Loop Log</button></value></div>`;
  }
  html += '</div>';
  // Invocations detail
  if (tx.invocations) {
    tx.invocations.forEach(inv => {
      html += `<div class="exec-invocation" onclick="showInvocationDetail('${taskId}', '${escAttr(inv.file)}')" title="Click to view conversation">`;
      html += `<div class="exec-invocation-header">`;
      html += `<span style="font-family:monospace;font-size:11px">${esc(inv.file)}</span>`;
      if (inv.model) html += `<span class="d-badge badge-${inv.model.includes('opus')?'opus':inv.model.includes('sonnet')?'sonnet':'haiku'}" style="font-size:10px;padding:1px 6px">${esc(inv.model)}</span>`;
      if (inv.duration_ms != null) html += `<span style="color:var(--text-muted);font-size:11px">${(inv.duration_ms/1000).toFixed(1)}s</span>`;
      if (inv.cost_usd != null) html += `<span style="color:var(--text-muted);font-size:11px">$${inv.cost_usd.toFixed(4)}</span>`;
      html += `<span style="color:var(--accent);font-size:11px;margin-left:auto">View →</span>`;
      html += `</div>`;
      if (inv.tool_usage && Object.keys(inv.tool_usage).length) {
        html += `<div class="exec-tools">`;
        Object.entries(inv.tool_usage).sort((a,b) => b[1]-a[1]).forEach(([name, count]) => {
          html += `<span class="exec-tool">${esc(name)} ×${count}</span>`;
        });
        html += `</div>`;
      }
      html += `</div>`;
    });
  }
  return html;
}

async function refresh() {
  document.getElementById('stats').textContent = 'Refreshing…';
  await loadTasks();
}

function updateStats() {
  const counts = {};
  allTasks.forEach(t => counts[t.status] = (counts[t.status] || 0) + 1);
  const parts = ['done','in-progress','claimed','pending','stuck']
    .filter(s => counts[s])
    .map(s => `${counts[s]} ${s}`);
  document.getElementById('stats').textContent = `${allTasks.length} tasks · ${parts.join(' · ')}`;
}

// ── Tag filters ──────────────────────────────────────────────
function getTagGroups() {
  const groups = {};
  allTasks.forEach(t => {
    (t.tags || []).forEach(tag => {
      const [cat] = tag.includes(':') ? tag.split(':', 2) : ['other'];
      if (!groups[cat]) groups[cat] = {};
      groups[cat][tag] = (groups[cat][tag] || 0) + 1;
    });
  });
  return groups;
}

function renderTagFilters() {
  const groups  = getTagGroups();
  const section = document.getElementById('tag-section');

  section.innerHTML = '';

  Object.keys(groups).sort().forEach(cat => {
    const tags = Object.entries(groups[cat]).sort((a, b) => b[1] - a[1]);
    const isExpanded = state.expandedTagCategories.has(cat);
    const activeInCat = tags.filter(([tag]) => state.activeTags.includes(tag)).length;
    const div = document.createElement('div');
    div.className = 'tag-group';
    const header = document.createElement('div');
    header.className = 'tag-group-header';
    header.innerHTML = `<span class="tag-group-arrow">${isExpanded ? '▼' : '▶'}</span><span>${esc(cat)}</span><span style="font-weight:400;opacity:.5;margin-left:3px">${tags.length}</span>${activeInCat ? `<span style="margin-left:auto;font-size:9px;background:var(--accent-bg);color:var(--accent);border-radius:8px;padding:0 5px">${activeInCat} active</span>` : ''}`;
    header.onclick = () => toggleTagCategory(cat);
    div.appendChild(header);
    if (isExpanded) {
      const chipsEl = document.createElement('div');
      chipsEl.className = 'tag-chips';
      tags.forEach(([tag, count]) => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip' + (state.activeTags.includes(tag) ? ' active' : '');
        chip.textContent = tag.includes(':') ? tag.split(':')[1] : tag;
        chip.title = `${tag} (${count} tasks)`;
        chip.onclick = e => { e.stopPropagation(); toggleTag(tag); };
        chipsEl.appendChild(chip);
      });
      div.appendChild(chipsEl);
    }
    section.appendChild(div);
  });
}

function toggleTagCategory(cat) {
  if (state.expandedTagCategories.has(cat)) state.expandedTagCategories.delete(cat);
  else state.expandedTagCategories.add(cat);
  persistPrefs();
  renderTagFilters();
}

function toggleTag(tag) {
  const idx = state.activeTags.indexOf(tag);
  if (idx >= 0) state.activeTags.splice(idx, 1);
  else          state.activeTags.push(tag);
  persist();
  renderTagFilters();
  renderTaskList();
}
function clearTags() {
  state.activeTags = [];
  persist();
  renderTagFilters();
  renderTaskList();
}

function hasActiveFilters() {
  return state.statusFilter !== 'all' || state.modelFilter !== 'all' || state.activeTags.length > 0 || state.search.trim() !== '' || state.tableFilters.length > 0;
}

function updateClearFiltersButton() {
  document.getElementById('clear-filters').style.display = hasActiveFilters() ? 'inline-block' : 'none';
}

function clearAllFilters() {
  state.statusFilter = 'all';
  state.modelFilter = 'all';
  state.activeTags = [];
  state.search = '';
  state.tableFilters = [];
  document.getElementById('search').value = '';
  document.querySelectorAll('#status-chips .chip').forEach(c => c.classList.toggle('active', c.dataset.status === 'all'));
  document.querySelectorAll('#model-chips .chip').forEach(c => c.classList.toggle('active', c.dataset.model === 'all'));
  persist();
  renderTagFilters();
  renderTaskList();
}

// ── Filtering ────────────────────────────────────────────────
function getFiltered() {
  const q = state.search.toLowerCase().trim();
  return allTasks.filter(t => {
    if (state.statusFilter !== 'all' && t.status !== state.statusFilter) return false;
    if (state.modelFilter  !== 'all' && t.model  !== state.modelFilter)  return false;
    if (state.activeTags.length && !state.activeTags.every(tag => (t.tags || []).includes(tag))) return false;
    if (q) {
      const inTitle = t.title.toLowerCase().includes(q);
      const inDesc  = (t.description || '').toLowerCase().includes(q);
      const inId    = t.id.startsWith(q) || t.id.replace(/-/g,'').startsWith(q.replace(/-/g,''));
      const inTag   = (t.tags || []).some(tag => tag.toLowerCase().includes(q));
      if (!inTitle && !inDesc && !inId && !inTag) return false;
    }
    return true;
  });
}

// ── Task list rendering ──────────────────────────────────────
function _applyView(v) {
  const isChart  = v === 'chart';
  const isTable  = v === 'table';
  const isReport = v === 'report';
  // Keep task list visible in chart and table modes alongside the main view
  document.getElementById('task-list-container').style.display = '';
  // In chart mode: show detail only when a task is selected, otherwise show chart
  const chartShowsDetail = isChart && !!state.selectedId;
  document.getElementById('detail').style.display = (isTable || isReport) ? 'none' : (isChart && !state.selectedId ? 'none' : '');
  document.getElementById('chart-container').classList.toggle('visible', isChart && !chartShowsDetail);
  document.getElementById('table-container').classList.toggle('visible', isTable);
  document.getElementById('report-container').classList.toggle('visible', isReport);
  updateViewDropdownItems();
  renderTaskList();
  if (isChart && !state.selectedId) renderChart();
  else if (isTable) renderTable();
  else if (isReport) renderReport();
}
function setView(v) {
  state.view = v;
  if (v === 'chart') { state.selectedId = null; }
  persist();
  _applyView(v);
}
function updateViewDropdownItems() {
  const isChart  = state.view === 'chart';
  const isTable  = state.view === 'table';
  const isDetail = state.view === 'tree';
  const isReport = state.view === 'report';
  const detailItem = document.getElementById('view-detail-item');
  if (detailItem) detailItem.classList.toggle('active', isDetail);
  const chartItem = document.getElementById('view-chart-item');
  if (chartItem) chartItem.classList.toggle('active', isChart);
  const tableItem = document.getElementById('view-table-item');
  if (tableItem) tableItem.classList.toggle('active', isTable);
  const reportItem = document.getElementById('view-report-item');
  if (reportItem) reportItem.classList.toggle('active', isReport);
  const sidebarItem = document.getElementById('view-sidebar-item');
  if (sidebarItem) sidebarItem.textContent = state.sidebarVisible ? 'Hide Sidebar' : 'Show Sidebar';
  document.getElementById('view-dropdown-btn').classList.toggle('active', isChart || isTable || isReport);
}
function toggleViewDropdown() {
  const menu = document.getElementById('view-dropdown-menu');
  updateViewDropdownItems();
  menu.style.display = menu.style.display === 'none' ? '' : 'none';
}
function closeViewDropdown() {
  const menu = document.getElementById('view-dropdown-menu');
  if (menu) menu.style.display = 'none';
}
function toggleSidebar() {
  state.sidebarVisible = !state.sidebarVisible;
  persistPrefs();
  document.getElementById('sidebar').classList.toggle('hidden', !state.sidebarVisible);
  updateViewDropdownItems();
}
function toggleChartMode() {
  setView(state.view === 'chart' ? 'tree' : 'chart');
}
function toggleTableMode() {
  setView(state.view === 'table' ? 'tree' : 'table');
}

function renderTaskList() {
  updateClearFiltersButton();
  const filtered   = getFiltered();
  const container  = document.getElementById('task-list');
  container.innerHTML = '';
  document.getElementById('result-count').textContent = `${filtered.length} tasks`;

  if (filtered.length === 0) {
    const clearBtn = hasActiveFilters() ? '<br><button class="no-results-clear-filters" onclick="clearAllFilters()">Clear Filters</button>' : '';
    container.innerHTML = `<div class="no-results">No tasks match the current filters.${clearBtn}</div>`;
    return;
  }

  // Use tree when not actively searching / tag-filtering (so hierarchy is meaningful)
  const useTree = !state.search.trim() && state.activeTags.length === 0;

  if (useTree) {
    const filteredIds = new Set(filtered.map(t => t.id));
    // Roots: tasks whose parent is absent or not in filteredIds
    const roots = filtered
      .filter(t => !t.parent_task || !filteredIds.has(t.parent_task))
      .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    roots.forEach(t => renderTree(t, container, 0, filteredIds));
  } else {
    const sorted = [...filtered].sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    sorted.forEach(t => renderItem(t, container, 0, false));
  }
  // Keep report card in sync when filters change
  if (state.view === 'report') renderReport();
}

function renderTree(task, container, depth, filteredIds) {
  const children = (task.tasks_created || [])
    .map(id => taskMap[id])
    .filter(t => t && filteredIds.has(t.id))
    .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  renderItem(task, container, depth, children.length > 0);
  if (children.length && state.expandedNodes.has(task.id)) {
    children.forEach(c => renderTree(c, container, depth + 1, filteredIds));
  }
}

function renderSourceTree(task, container, depth, filteredIds, childrenOf) {
  if (!task || !filteredIds.has(task.id)) return;
  const children = (childrenOf[task.id] || [])
    .filter(id => taskMap[id] && filteredIds.has(id))
    .sort((a, b) => (taskMap[a]?.created_at || '').localeCompare(taskMap[b]?.created_at || ''));
  renderItem(task, container, depth, children.length > 0);
  if (children.length && state.expandedNodes.has(task.id)) {
    children.forEach(cid => renderSourceTree(taskMap[cid], container, depth + 1, filteredIds, childrenOf));
  }
}

function renderItem(task, container, depth, hasChildren) {
  const el = document.createElement('div');
  el.className = 'task-item' + (task.id === state.selectedId ? ' selected' : '');
  el.dataset.id    = task.id;
  el.dataset.depth = depth;

  // Toggle
  const toggle = document.createElement('div');
  toggle.className = 't-toggle';
  if (hasChildren) {
    toggle.textContent = state.expandedNodes.has(task.id) ? '▼' : '▶';
    toggle.onclick = e => {
      e.stopPropagation();
      if (state.expandedNodes.has(task.id)) state.expandedNodes.delete(task.id);
      else state.expandedNodes.add(task.id);
      persistPrefs();
      renderTaskList();
    };
  }

  // Status dot
  const dot = document.createElement('div');
  dot.className = `t-dot ${statusClass(task.status)}`;

  // Body
  const body = document.createElement('div');
  body.className = 't-body';

  const title = document.createElement('div');
  title.className = 't-title';
  const q = state.search.trim();
  if (q) title.innerHTML = highlightText(task.title, q);
  else   title.textContent = task.title;

  const meta = document.createElement('div');
  meta.className = 't-meta';

  const modelBadge = document.createElement('span');
  modelBadge.className = `badge badge-${task.model}`;
  modelBadge.textContent = task.model;
  meta.appendChild(modelBadge);

  if (task.thinking) {
    const tb = document.createElement('span');
    tb.className = 'badge badge-think';
    tb.textContent = '🧠';
    meta.appendChild(tb);
  }

  const blockers = (task.blocked_by || []).filter(id => taskMap[id]?.status !== 'done');
  if (blockers.length && task.status !== 'done') {
    const bb = document.createElement('span');
    bb.className = 'badge badge-block';
    bb.textContent = `⛔ ${blockers.length}`;
    meta.appendChild(bb);
  }

  const subCount = (task.tasks_created || []).length;
  if (subCount) {
    const sc = document.createElement('span');
    sc.className = 't-sub-count';
    sc.textContent = `${subCount} sub`;
    meta.appendChild(sc);
  }

  body.appendChild(title);
  body.appendChild(meta);

  const q2 = state.search.trim();
  if (q2) {
    const snippet = getMatchSnippet(task, q2);
    if (snippet) {
      const snipEl = document.createElement('div');
      snipEl.className = 't-snippet';
      snipEl.innerHTML = snippet;
      body.appendChild(snipEl);
    }
  }

  el.appendChild(toggle);
  el.appendChild(dot);
  el.appendChild(body);
  el.onclick = () => {
    if (state.view === 'chart' && state.selectedId === task.id) deselectTask();
    else selectTask(task.id);
  };
  container.appendChild(el);
}

// ── Task selection & detail ──────────────────────────────────
function toggleDetailNode(id) {
  if (state.detailExpandedNodes.has(id)) state.detailExpandedNodes.delete(id);
  else state.detailExpandedNodes.add(id);
  persistPrefs();
  if (state.selectedId) renderDetail(state.selectedId);
}

function selectTask(id) {
  state.selectedId = id;
  persist();
  _activateTask(id);
}
function _activateTask(id) {
  document.querySelectorAll('.task-item').forEach(el =>
    el.classList.toggle('selected', el.dataset.id === id)
  );
  if (state.view === 'chart') {
    // In chart mode: hide graph and show detail panel when a task is selected
    document.getElementById('chart-container').classList.remove('visible');
    document.getElementById('detail').style.display = '';
  }
  renderDetail(id);
  const el = document.querySelector(`.task-item[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
function deselectTask() {
  state.selectedId = null;
  persist();
  document.querySelectorAll('.task-item').forEach(el => el.classList.remove('selected'));
  if (state.view === 'chart') {
    document.getElementById('chart-container').classList.add('visible');
    document.getElementById('detail').style.display = 'none';
    renderChart();
  }
}

// Count all descendants (recursively) under taskId, excluding the node itself.
// Returns {total, done}.
function countDescendants(taskId) {
  const t = taskMap[taskId];
  if (!t) return { total: 0, done: 0 };
  const children = (t.tasks_created || []).filter(id => taskMap[id]);
  let total = children.length;
  let done  = children.filter(id => taskMap[id]?.status === 'done').length;
  children.forEach(childId => {
    const sub = countDescendants(childId);
    total += sub.total;
    done  += sub.done;
  });
  return { total, done };
}

// Topological sort of task IDs using blocked_by edges within the sibling set.
// Tasks that must come first (block others) sort earlier; ties broken by created_at.
function topoSort(ids) {
  const idSet = new Set(ids);
  const inDegree  = {};
  const successors = {};  // id -> ids that are blocked by id
  ids.forEach(id => { inDegree[id] = 0; successors[id] = []; });
  ids.forEach(id => {
    const t = taskMap[id];
    if (!t) return;
    (t.blocked_by || []).forEach(blockerId => {
      if (idSet.has(blockerId)) {
        successors[blockerId].push(id);
        inDegree[id]++;
      }
    });
  });
  const byDate = (a, b) => (taskMap[a]?.created_at || '').localeCompare(taskMap[b]?.created_at || '');
  const queue  = ids.filter(id => inDegree[id] === 0).sort(byDate);
  const result = [];
  while (queue.length) {
    const id = queue.shift();
    result.push(id);
    const newly = [];
    successors[id].forEach(succ => {
      if (--inDegree[succ] === 0) newly.push(succ);
    });
    newly.sort(byDate).forEach(s => queue.push(s));
  }
  // Append anything left (cycles or missing map entries)
  ids.forEach(id => { if (!result.includes(id)) result.push(id); });
  return result;
}

function renderSubtaskTree(taskId, depth) {
  const t = taskMap[taskId];
  if (!t) {
    return `<div class="d-tree-row" style="padding-left:${depth * 22}px">
      <span class="d-tree-toggle leaf">•</span>
      <span class="d-tree-cell" style="cursor:default;color:#9ca3af">${taskId.slice(0,8)} (missing)</span>
    </div>`;
  }
  const children   = (t.tasks_created || []).filter(id => taskMap[id]);
  const hasChildren = children.length > 0;
  const isExpanded  = state.detailExpandedNodes.has(taskId);
  const label = t.title.length > 80 ? t.title.slice(0, 80) + '…' : t.title;

  let html = `<div class="d-tree-row" style="padding-left:${depth * 22}px">`;
  if (hasChildren) {
    html += `<span class="d-tree-toggle" onclick="event.stopPropagation();toggleDetailNode('${taskId}')">${isExpanded ? '▼' : '▶'}</span>`;
  } else {
    html += `<span class="d-tree-toggle leaf">•</span>`;
  }
  html += `<div class="d-tree-cell" onclick="selectTask('${taskId}')">
    <span class="t-dot ${statusClass(t.status)}" style="width:8px;height:8px;border-radius:50%;flex-shrink:0"></span>
    <span class="d-tree-cell-text">${esc(label)}</span>
  </div>`;
  if (hasChildren) {
    const directDone  = children.filter(id => taskMap[id]?.status === 'done').length;
    const desc        = countDescendants(taskId);
    const deepSuffix  = desc.total > children.length
      ? ` · ${desc.done}/${desc.total} deep` : '';
    html += `<span class="d-tree-count">${directDone}/${children.length}${deepSuffix}</span>`;
  }
  html += `</div>`;

  if (hasChildren && isExpanded) {
    topoSort(children).forEach(childId => {
      html += renderSubtaskTree(childId, depth + 1);
    });
  }
  return html;
}

function getAncestorChain(taskId) {
  // Returns array from root ancestor down to (but NOT including) taskId.
  // Each entry is {type:'human'} or {type:'task', task: taskObj}.
  const chain = [];
  const seen = new Set();
  let current = taskMap[taskId];
  if (!current) return chain;
  seen.add(current.id);
  let src = current.source;
  while (src && src !== 'human' && taskMap[src] && !seen.has(src)) {
    seen.add(src);
    chain.unshift({ type: 'task', task: taskMap[src] });
    src = taskMap[src].source;
  }
  // Prepend human root if the chain traces back to human input
  if (!src || src === 'human') {
    chain.unshift({ type: 'human' });
  }
  return chain;
}

function renderLineageRow(type, task, depth, isSelected) {
  const indent = depth * 22;
  if (type === 'human') {
    return `<div class="d-tree-row" style="padding-left:${indent}px">
      <span class="d-tree-toggle leaf" style="color:var(--text-muted)">⌨</span>
      <span class="d-tree-cell" style="cursor:default;color:var(--text-muted);font-size:12px">human input</span>
    </div>`;
  }
  const label = task.title.length > 80 ? task.title.slice(0, 80) + '…' : task.title;
  const bold = isSelected ? 'font-weight:600;' : '';
  const click = isSelected ? '' : `onclick="selectTask('${task.id}')"`;
  const cellStyle = isSelected ? 'cursor:default;color:var(--text);pointer-events:none;' : '';
  return `<div class="d-tree-row" style="padding-left:${indent}px;${bold}">
    <span class="d-tree-toggle leaf">•</span>
    <div class="d-tree-cell" ${click} style="${cellStyle}">
      <span class="t-dot ${statusClass(task.status)}" style="width:8px;height:8px;border-radius:50%;flex-shrink:0"></span>
      <span class="d-tree-cell-text">${esc(label)}</span>
    </div>
  </div>`;
}

function renderDetail(id) {
  const task = taskMap[id];
  if (!task) return;

  document.getElementById('empty-state').style.display  = 'none';
  const panel = document.getElementById('task-detail');
  panel.style.display = 'block';

  const sc   = statusClass(task.status);
  const sbg  = statusBg(task.status);
  const sfg  = statusFg(task.status);

  const blockersDone = (task.blocked_by || []).every(id => taskMap[id]?.status === 'done');
  const openBlockers = (task.blocked_by || []).filter(id => taskMap[id]?.status !== 'done');

  let html = '';

  // Sticky header
  html += `<div class="d-header">`;
  html += `<div class="d-title">${esc(task.title)}</div>`;
  html += `<div class="d-badges">`;
  html += `<span class="d-badge" style="background:${sbg};color:${sfg}">${task.status}</span>`;
  html += `<span class="d-badge badge-${task.model}">${task.model}</span>`;
  if (task.thinking) html += `<span class="d-badge badge-think">🧠 extended thinking</span>`;
  (task.tags || []).forEach(tag => {
    html += `<span class="d-badge" style="cursor:pointer" onclick="jumpToTag('${escAttr(tag)}')" title="Filter by this tag">${esc(tag)}</span>`;
  });
  html += `<span style="font-size:11px;color:var(--text-muted);font-family:monospace">${task.id}</span>`;
  if (window.__SUPERVISOR_ENABLED__ && task.status === 'pending' && openBlockers.length === 0) {
    html += `<button class="run-now-btn" id="run-now-${escAttr(task.id)}" onclick="runTaskNow('${escAttr(task.id)}')">Run Now</button>`;
  }
  html += `<button class="delete-task-btn" onclick="confirmDelete('${escAttr(task.id)}')">Delete</button>`;
  html += `</div>`;

  if (task.status === 'stuck') {
    html += `<div class="stuck-banner" style="margin-top:10px">⚠️ This task is stuck. A resolution task should be created.</div>`;
  }
  if (openBlockers.length > 0) {
    html += `<div class="stuck-banner" style="margin-top:10px;background:#fff7ed;border-color:#fb923c;color:#c2410c">⛔ Blocked by ${openBlockers.length} unfinished task${openBlockers.length > 1 ? 's' : ''}.</div>`;
  }
  html += `</div>`;

  // Description
  html += `<div class="d-section collapsed">
    <div class="d-label" onclick="toggleSection(this)">Description</div>
    <div class="d-section-body"><pre class="d-pre">${highlightText(task.description, state.search.trim())}</pre></div>
  </div>`;

  // Result + Commit (collapsed by default, with summary chips when collapsed)
  if (task.result || task.merge_sha) {
    let resultSummaryChips = '';
    if (task.merge_sha) {
      const shortSha = task.merge_sha.slice(0, 8);
      resultSummaryChips += `<span class="d-collapsed-chips">`;
      resultSummaryChips += `<span class="sha-badge" onclick="event.stopPropagation();showDiff('${escAttr(task.merge_sha)}')" title="View diff">${shortSha}</span>`;
      if (window.__GITHUB_REPO_URL__) {
        resultSummaryChips += `<a class="sha-github-link" href="${window.__GITHUB_REPO_URL__}/commit/${encodeURIComponent(task.merge_sha)}" target="_blank" rel="noopener">GitHub ↗</a>`;
      }
      resultSummaryChips += `</span>`;
    }
    html += `<div class="d-section collapsed"><div class="d-label" onclick="toggleSection(this)"><span>Result</span>${resultSummaryChips}</div>`;
    html += `<div class="d-section-body">`;
    if (task.result) html += `<div class="result-box">${esc(task.result)}</div>`;
    if (task.merge_sha) {
      const shortSha = task.merge_sha.slice(0, 8);
      const shaMargin = task.result ? 'margin-top:8px' : '';
      html += `<div style="display:flex;align-items:center;gap:8px;${shaMargin}">`;
      html += `<span class="sha-badge" onclick="event.stopPropagation();showDiff('${escAttr(task.merge_sha)}')" title="View diff">${shortSha}</span>`;
      if (window.__GITHUB_REPO_URL__) {
        html += `<a class="sha-github-link" href="${window.__GITHUB_REPO_URL__}/commit/${encodeURIComponent(task.merge_sha)}" target="_blank" rel="noopener">View on GitHub ↗</a>`;
      }
      html += `</div>`;
    }
    html += `</div></div>`;
  }

  // Execution summary (from index, no extra fetch needed)
  if ((task.status === 'claimed' || task.status === 'done') && task.transcript && task.transcript.has_transcript) {
    const taskEvents = task.events && task.events.length ? task.events : null;
    const tx = task.transcript;
    html += '<div class="d-section"><div class="d-label" onclick="toggleSection(this)"><span>Execution</span></div>';
    html += '<div class="d-section-body">';
    if (taskEvents) html += renderEventTimeline(taskEvents);
    html += renderExecSection(tx, task.id);
    html += '</div></div>';
  }

  // Task Lineage (unified: ancestors → current → children)
  const ancestors = getAncestorChain(task.id);
  const hasChildren = (task.tasks_created || []).length > 0;
  if (ancestors.length > 0 || hasChildren) {
    let lineageLabel = 'Task Lineage';
    if (hasChildren) {
      const subs     = task.tasks_created.map(id => taskMap[id]).filter(Boolean);
      const byStatus = {};
      subs.forEach(t => byStatus[t.status] = (byStatus[t.status]||0)+1);
      const summary  = Object.entries(byStatus).map(([s,c]) => `${c} ${s}`).join(', ');
      lineageLabel += ` · ${subs.length} subtask${subs.length !== 1 ? 's' : ''} (${summary})`;
    }
    html += `<div class="d-section"><div class="d-label" onclick="toggleSection(this)">${lineageLabel}</div>`;
    html += `<div class="d-section-body">`;

    ancestors.forEach((entry, i) => {
      html += renderLineageRow(entry.type, entry.type === 'task' ? entry.task : null, i, false);
    });

    const currentDepth = ancestors.length;
    html += renderLineageRow('task', task, currentDepth, true);

    if (hasChildren) {
      topoSort(task.tasks_created.slice()).forEach(id => {
        html += renderSubtaskTree(id, currentDepth + 1);
      });
    }

    html += `</div></div>`;
  }

  // Blocked by & Blocking – side-by-side
  const blockedBy = (task.blocked_by || []);
  const blocking = Object.values(taskMap).filter(t => (t.blocked_by || []).includes(task.id));
  if (blockedBy.length || blocking.length) {
    html += `<div style="display:flex;gap:8px;margin-bottom:0">`;
    // Blocked By column
    html += `<div class="d-section" style="flex:1;min-width:0">`;
    html += `<div class="d-label" onclick="toggleSection(this)">Blocked By (${blockedBy.length})</div>`;
    html += `<div class="d-section-body">`;
    if (blockedBy.length) { blockedBy.forEach(id => { html += taskLink(id); }); }
    else { html += `<span style="color:#9ca3af;font-size:12px">None</span>`; }
    html += `</div></div>`;
    // Blocking column
    const allDone = blocking.length && blocking.every(t => t.status === 'done');
    const blockingLabel = allDone ? 'Blocked (all done)' : 'Blocking';
    html += `<div class="d-section" style="flex:1;min-width:0">`;
    html += `<div class="d-label" onclick="toggleSection(this)">${blockingLabel} (${blocking.length})</div>`;
    html += `<div class="d-section-body">`;
    if (blocking.length) { blocking.forEach(t => { html += taskLink(t.id); }); }
    else { html += `<span style="color:#9ca3af;font-size:12px">None</span>`; }
    html += `</div></div>`;
    html += `</div>`;
  }

  panel.innerHTML = html;
  panel.scrollTop = 0;
}

// ── Section collapse ─────────────────────────────────────────
function toggleSection(labelEl) {
  labelEl.parentElement.classList.toggle('collapsed');
}

// ── Link helpers ─────────────────────────────────────────────
function taskLink(id) {
  const t = taskMap[id];
  if (!t) return `<span class="task-link" style="cursor:default;color:#9ca3af">${id.slice(0,8)} (missing)</span>`;
  const label = t.title.length > 65 ? t.title.slice(0, 65) + '…' : t.title;
  return `<span class="task-link" onclick="selectTask('${id}')">
    <span class="t-dot ${statusClass(t.status)}" style="width:7px;height:7px;border-radius:50%;flex-shrink:0"></span>
    ${esc(label)}
  </span>`;
}
function metaItem(label, value) {
  return `<div class="d-meta-item"><label>${label}</label><value>${value}</value></div>`;
}

// ── Filtering shortcuts ──────────────────────────────────────
function jumpToTag(tag) {
  if (!state.activeTags.includes(tag)) {
    state.activeTags.push(tag);
    persist();
    renderTagFilters();
    renderTaskList();
  }
}

// ── Plaintext search helpers ─────────────────────────────────
function escRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function highlightText(text, query) {
  const escaped = esc(text);
  if (!query) return escaped;
  const re = new RegExp(escRegex(esc(query.trim())), 'gi');
  return escaped.replace(re, m => `<mark>${m}</mark>`);
}

function excerptMatch(text, query, before = 50, after = 110) {
  if (!text) return null;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return null;
  const start   = Math.max(0, idx - before);
  const end     = Math.min(text.length, idx + query.length + after);
  let excerpt   = text.slice(start, end);
  if (start > 0)           excerpt = '…' + excerpt;
  if (end < text.length)   excerpt = excerpt + '…';
  return highlightText(excerpt, query);
}

// Returns an HTML snippet string showing where the query matched, or null
function getMatchSnippet(task, query) {
  if (!query) return null;
  const q = query.trim();
  // Title match — title is already highlighted separately, no extra snippet
  if (task.title.toLowerCase().includes(q.toLowerCase())) return null;
  // Description
  const d = excerptMatch(task.description || '', q);
  if (d) return d;
  // Result
  const r = excerptMatch(task.result || '', q);
  if (r) return `<span style="opacity:.6">result: </span>${r}`;
  // Tags
  const tag = (task.tags || []).find(t => t.toLowerCase().includes(q.toLowerCase()));
  if (tag) return `<span style="opacity:.6">tag: </span>${highlightText(tag, q)}`;
  return null;
}

// ── Source chain (progenitor trace) ──────────────────────────
// Returns an array from root (human) to the given task, e.g.:
// [ {type:'human'}, {type:'task',task:T1}, {type:'task',task:T2}, {type:'task',task:current} ]
// Build source-based tree: tasks grouped by what created them.
// Returns { roots: [...taskIds], childrenOf: { sourceId -> [...taskIds] } }
function buildSourceTree() {
  const childrenOf = {}; // sourceTaskId -> [taskIds created by it]
  const humanRoots = [];
  allTasks.forEach(t => {
    const src = t.source;
    if (!src || src === 'human') {
      humanRoots.push(t.id);
    } else {
      if (!childrenOf[src]) childrenOf[src] = [];
      childrenOf[src].push(t.id);
    }
  });
  return { roots: humanRoots, childrenOf };
}

// ── Utilities ────────────────────────────────────────────────
function statusClass(s) { return s; }   // CSS class equals status string

function statusBg(s) {
  return {pending:'#fff7ed',claimed:'#eff6ff','in-progress':'#f0fdf4',done:'#f0fdf4',stuck:'#fff1f2'}[s] || '#f3f4f6';
}
function statusFg(s) {
  return {pending:'#c2410c',claimed:'#1d4ed8','in-progress':'#15803d',done:'#166534',stuck:'#be123c'}[s] || '#6b7280';
}
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) { return (s||'').replace(/'/g,"\\'"); }
function fmt(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
}
function agoStr(iso) {
  if (!iso) return '';
  try {
    const s = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (s < 60)    return `(${s}s ago)`;
    if (s < 3600)  return `(${Math.floor(s/60)}m ago)`;
    if (s < 86400) return `(${Math.floor(s/3600)}h ago)`;
    return `(${Math.floor(s/86400)}d ago)`;
  } catch (_) { return ''; }
}

// ── Chart ────────────────────────────────────────────────────
const STATUS_COLORS = {
  done:          '#86efac',
  'in-progress': '#22c55e',
  claimed:       '#3b82f6',
  pending:       '#fb923c',
  stuck:         '#f87171',
};
const STATUS_ORDER = ['done', 'in-progress', 'claimed', 'pending', 'stuck'];

// ── Chart time range filter ──────────────────────────────────
let _chartTimeRange = 'all';    // 'all', 'supervisor', '5m', '15m', '30m', '1h', '3h', '6h', '12h', '24h', 'custom'
let _chartCustomSince = null;   // ms timestamp for custom mode

const TIME_RANGE_MS = {
  '5m':  5 * 60 * 1000,
  '15m': 15 * 60 * 1000,
  '30m': 30 * 60 * 1000,
  '1h':  60 * 60 * 1000,
  '3h':  3 * 60 * 60 * 1000,
  '6h':  6 * 60 * 60 * 1000,
  '12h': 12 * 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
};

function _getChartTimeFloor() {
  if (_chartTimeRange === 'all') return 0;
  if (_chartTimeRange === 'supervisor' && window.__SUPERVISOR_STARTED_AT__) {
    return window.__SUPERVISOR_STARTED_AT__;
  }
  if (_chartTimeRange === 'custom' && _chartCustomSince) return _chartCustomSince;
  const ms = TIME_RANGE_MS[_chartTimeRange];
  if (ms) return Date.now() - ms;
  return 0;
}

function setChartTimeRange(range) {
  _chartTimeRange = range;
  // Update active button styling
  document.querySelectorAll('#chart-time-filter .tf-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.range === range);
  });
  if (state.view === 'chart' && !state.selectedId) renderChart();
}

function onCustomTimeChange() {
  const input = document.getElementById('tf-custom-dt');
  if (input.value) {
    _chartCustomSince = new Date(input.value).getTime();
    setChartTimeRange('custom');
  }
}

function _initChartTimeFilter() {
  // Show supervisor button if we have a start time
  const supBtn = document.getElementById('tf-supervisor-btn');
  const supTime = document.getElementById('tf-supervisor-time');
  if (window.__SUPERVISOR_STARTED_AT__) {
    supBtn.style.display = '';
    const d = new Date(window.__SUPERVISOR_STARTED_AT__);
    supTime.textContent = 'Supervisor started: ' + d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  }
}

function buildTimeline(tasks) {
  const timeFloor = _getChartTimeFloor();

  // Event-sweep approach: O(N log N) instead of O(N * M)
  // Record +1/-1 deltas at each status transition, then sweep to accumulate.
  const events = []; // { time, status, delta }
  tasks.forEach(task => {
    const created = task.created_at ? new Date(task.created_at).getTime() : NaN;
    const claimed = task.claimed_at ? new Date(task.claimed_at).getTime() : NaN;
    const completed = task.completed_at ? new Date(task.completed_at).getTime() : NaN;
    if (isNaN(created)) return;

    // Determine the "claimed" display status based on current task status
    let claimedStatus = 'claimed';
    if (task.status === 'stuck') claimedStatus = 'stuck';
    else if (task.status === 'in-progress' || task.status === 'done') claimedStatus = 'in-progress';

    if (!isNaN(completed)) {
      // Task went: pending -> claimedStatus -> done
      if (!isNaN(claimed)) {
        events.push({ time: created, status: 'pending', delta: 1 });
        events.push({ time: claimed, status: 'pending', delta: -1 });
        events.push({ time: claimed, status: claimedStatus, delta: 1 });
        events.push({ time: completed, status: claimedStatus, delta: -1 });
        events.push({ time: completed, status: 'done', delta: 1 });
      } else {
        events.push({ time: created, status: 'pending', delta: 1 });
        events.push({ time: completed, status: 'pending', delta: -1 });
        events.push({ time: completed, status: 'done', delta: 1 });
      }
    } else if (!isNaN(claimed)) {
      // Task went: pending -> claimedStatus (still active)
      events.push({ time: created, status: 'pending', delta: 1 });
      events.push({ time: claimed, status: 'pending', delta: -1 });
      events.push({ time: claimed, status: claimedStatus, delta: 1 });
    } else {
      // Task is still pending
      events.push({ time: created, status: 'pending', delta: 1 });
    }
  });

  if (events.length === 0) return [];

  // Sort by time, with -1 deltas before +1 at the same time so transitions are clean
  events.sort((a, b) => a.time - b.time || a.delta - b.delta);

  // Sweep: accumulate counts, emit a timeline point at each unique timestamp
  const counts = { pending: 0, claimed: 0, 'in-progress': 0, done: 0, stuck: 0 };
  const timeline = [];
  let i = 0;

  // Baseline counts to subtract when a time filter is active, so the y-axis
  // shows progress within the window (e.g. "done" starts at 0, not 10,000).
  let baseline = { pending: 0, claimed: 0, 'in-progress': 0, done: 0, stuck: 0 };

  if (timeFloor > 0) {
    // Pre-compute state at timeFloor by processing all events before it
    while (i < events.length && events[i].time < timeFloor) {
      counts[events[i].status] += events[i].delta;
      i++;
    }
    // Record the baseline so we can subtract it from all emitted points
    baseline = { ...counts };
    // Emit an initial point at timeFloor with zeroed baseline
    if (i < events.length) {
      const point = { time: timeFloor };
      for (const s of STATUS_ORDER) point[s] = counts[s] - baseline[s];
      timeline.push(point);
    }
  }

  while (i < events.length) {
    const t = events[i].time;
    // Apply all events at this timestamp
    while (i < events.length && events[i].time === t) {
      counts[events[i].status] += events[i].delta;
      i++;
    }
    const point = { time: t };
    for (const s of STATUS_ORDER) point[s] = Math.max(0, counts[s] - baseline[s]);
    timeline.push(point);
  }
  return timeline;
}

function collapseGaps(timeline) {
  if (timeline.length < 2) return timeline.map((p, i) => ({ ...p, x: i }));

  const GAP_THRESHOLD = 60 * 60 * 1000; // 1 hour in ms

  // Compute total non-gap time to determine a proportional gap size
  let totalRealTime = 0;
  for (let i = 1; i < timeline.length; i++) {
    const dt = timeline[i].time - timeline[i - 1].time;
    if (dt <= GAP_THRESHOLD) totalRealTime += dt;
  }
  // Gap visual width = 3% of total real time (gives a visible but small splice mark)
  const gapVisualSize = Math.max(totalRealTime * 0.03, 1);

  const result = [{ ...timeline[0], x: 0, gap: false }];
  let x = 0;
  for (let i = 1; i < timeline.length; i++) {
    const dt = timeline[i].time - timeline[i - 1].time;
    const isGap = dt > GAP_THRESHOLD;
    if (isGap) {
      x += gapVisualSize;
    } else {
      x += dt;
    }
    result.push({ ...timeline[i], x, gap: isGap });
  }
  return result;
}

function renderChart() {
  const filtered = getFiltered();
  const timeline = buildTimeline(filtered);
  const collapsed = collapseGaps(timeline);

  const wrap = document.getElementById('chart-svg-wrap');
  const legendEl = document.getElementById('chart-legend');

  if (collapsed.length < 2) {
    wrap.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">Not enough data points to render chart.</div>';
    legendEl.innerHTML = '';
    return;
  }

  const rect = wrap.getBoundingClientRect();
  const W = rect.width || 800;
  const H = rect.height || 400;
  const pad = { top: 20, right: 20, bottom: 50, left: 45 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;

  const xMin = collapsed[0].x;
  const xMax = collapsed[collapsed.length - 1].x;
  const xRange = xMax - xMin || 1;

  // Max total tasks at any point
  const maxTotal = Math.max(...collapsed.map(p =>
    STATUS_ORDER.reduce((sum, s) => sum + p[s], 0)
  ));
  const yMax = maxTotal || 1;

  function sx(x) { return pad.left + ((x - xMin) / xRange) * cw; }
  function sy(y) { return pad.top + ch - (y / yMax) * ch; }

  // Build stacked areas (bottom to top, order: done, in-progress, claimed, pending, stuck)
  const areas = {};
  STATUS_ORDER.forEach((status, si) => {
    let points = '';
    // Forward pass (top edge)
    collapsed.forEach((p, i) => {
      let yBottom = 0;
      for (let j = 0; j < si; j++) yBottom += p[STATUS_ORDER[j]];
      const yTop = yBottom + p[status];
      points += `${sx(p.x)},${sy(yTop)} `;
    });
    // Reverse pass (bottom edge)
    for (let i = collapsed.length - 1; i >= 0; i--) {
      const p = collapsed[i];
      let yBottom = 0;
      for (let j = 0; j < si; j++) yBottom += p[STATUS_ORDER[j]];
      points += `${sx(p.x)},${sy(yBottom)} `;
    }
    areas[status] = points.trim();
  });

  // Gap indicators — draw a pair of dotted lines to indicate spliced-out time
  let gapLines = '';
  collapsed.forEach((p, i) => {
    if (p.gap && i > 0) {
      const gxRight = sx(p.x);
      const gxLeft = sx(collapsed[i - 1].x);
      const mid = (gxLeft + gxRight) / 2;
      const half = Math.min(6, (gxRight - gxLeft) / 2 - 1);
      gapLines += `<line class="gap-indicator" x1="${mid - half}" y1="${pad.top}" x2="${mid - half}" y2="${pad.top + ch}"/>`;
      gapLines += `<line class="gap-indicator" x1="${mid + half}" y1="${pad.top}" x2="${mid + half}" y2="${pad.top + ch}"/>`;
    }
  });

  // Y-axis ticks
  const yTickCount = Math.min(yMax, 8);
  const yStep = Math.ceil(yMax / yTickCount);
  let yAxisSvg = '';
  for (let v = 0; v <= yMax; v += yStep) {
    const y = sy(v);
    yAxisSvg += `<line x1="${pad.left}" y1="${y}" x2="${pad.left + cw}" y2="${y}" stroke="#e5e7eb" stroke-width="0.5"/>`;
    yAxisSvg += `<text x="${pad.left - 8}" y="${y + 4}" text-anchor="end" fill="#9ca3af" font-size="10">${v}</text>`;
  }

  // X-axis time labels (pick ~6 evenly spaced)
  const labelCount = Math.min(collapsed.length, 8);
  const labelStep = Math.max(1, Math.floor(collapsed.length / labelCount));
  let xAxisSvg = '';
  for (let i = 0; i < collapsed.length; i += labelStep) {
    const p = collapsed[i];
    const x = sx(p.x);
    const d = new Date(p.time);
    const label = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    xAxisSvg += `<text x="${x}" y="${pad.top + ch + 18}" text-anchor="middle" fill="#9ca3af" font-size="10">${esc(label)}</text>`;
  }

  // Hover columns (invisible rects for each data point region)
  let hoverRects = '';
  collapsed.forEach((p, i) => {
    const x0 = i === 0 ? pad.left : (sx(collapsed[i-1].x) + sx(p.x)) / 2;
    const x1 = i === collapsed.length - 1 ? pad.left + cw : (sx(p.x) + sx(collapsed[i+1].x)) / 2;
    hoverRects += `<rect x="${x0}" y="${pad.top}" width="${x1 - x0}" height="${ch}" fill="transparent" data-idx="${i}" class="hover-col"/>`;
  });

  // Crosshair line
  const crosshairId = 'chart-crosshair';

  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">`;
  svg += yAxisSvg;
  svg += gapLines;
  STATUS_ORDER.forEach(s => {
    svg += `<polygon points="${areas[s]}" fill="${STATUS_COLORS[s]}" opacity="0.85"/>`;
  });
  svg += xAxisSvg;
  svg += `<line id="${crosshairId}" x1="0" y1="${pad.top}" x2="0" y2="${pad.top + ch}" stroke="#6b7280" stroke-width="1" opacity="0" pointer-events="none"/>`;
  svg += hoverRects;
  svg += `</svg>`;
  wrap.innerHTML = svg;

  // Tooltip + crosshair interaction
  const tooltip = document.getElementById('chart-tooltip');
  const crosshair = document.getElementById(crosshairId);
  wrap.querySelectorAll('.hover-col').forEach(rect => {
    rect.addEventListener('mouseenter', e => {
      const idx = +rect.dataset.idx;
      const p = collapsed[idx];
      const d = new Date(p.time);
      const timeStr = d.toLocaleString();
      let html = `<div class="tt-time">${esc(timeStr)}</div>`;
      const total = STATUS_ORDER.reduce((sum, s) => sum + p[s], 0);
      STATUS_ORDER.forEach(s => {
        if (p[s] > 0) {
          html += `<div class="tt-row"><span class="tt-swatch" style="background:${STATUS_COLORS[s]}"></span>${s}: ${p[s]}</div>`;
        }
      });
      html += `<div class="tt-row" style="border-top:1px solid #374151;margin-top:4px;padding-top:4px;font-weight:600">total: ${total}</div>`;
      tooltip.innerHTML = html;
      tooltip.style.display = 'block';
      crosshair.setAttribute('x1', sx(p.x));
      crosshair.setAttribute('x2', sx(p.x));
      crosshair.setAttribute('opacity', '0.5');
    });
    rect.addEventListener('mousemove', e => {
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top = (e.clientY - 10) + 'px';
    });
    rect.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
      crosshair.setAttribute('opacity', '0');
    });
  });

  // Legend
  legendEl.innerHTML = STATUS_ORDER.map(s =>
    `<div class="legend-item"><span class="legend-swatch" style="background:${STATUS_COLORS[s]}"></span>${s}</div>`
  ).join('');
}

// Re-render chart on window resize
let _chartResizeTimer;
window.addEventListener('resize', () => {
  if (state.view !== 'chart') return;
  clearTimeout(_chartResizeTimer);
  _chartResizeTimer = setTimeout(renderChart, 150);
});

// ── Report Card view ─────────────────────────────────────────
const RC_PALETTE = [
  '#3b82f6','#10b981','#8b5cf6','#f59e0b','#ef4444',
  '#06b6d4','#84cc16','#f97316','#ec4899','#6366f1'
];

function _stageColor(stageName, allStageNames) {
  const idx = allStageNames.indexOf(stageName);
  return RC_PALETTE[idx >= 0 ? idx % RC_PALETTE.length : 0];
}

function _buildStageMetrics(tasks) {
  const stageMap = {};
  for (const task of tasks) {
    const stageTag = (task.tags || []).find(t => t.startsWith('phase:'));
    const stage = stageTag ? stageTag.replace('phase:', '') : '(no phase)';
    if (!stageMap[stage]) {
      stageMap[stage] = {
        stage,
        tasks: [], txTasks: [],
        durations_ms: [], costs_usd: [], turns: [], toolErrors: [], toolCalls: [],
        toolBreakdown: {},
        modelCounts: { opus: 0, sonnet: 0, haiku: 0, other: 0 },
        totalCost: 0, totalDuration_ms: 0, totalTurns: 0, totalToolErrors: 0,
        taskCount: 0, txTaskCount: 0
      };
    }
    const e = stageMap[stage];
    e.tasks.push(task);
    e.taskCount++;
    // Model counts from task.model field
    const m = (task.model || '').toLowerCase();
    if (m.includes('opus'))   e.modelCounts.opus++;
    else if (m.includes('sonnet')) e.modelCounts.sonnet++;
    else if (m.includes('haiku'))  e.modelCounts.haiku++;
    else e.modelCounts.other++;
    // Transcript metrics
    const tx = task.transcript;
    if (!tx) continue;
    e.txTasks.push(task);
    e.txTaskCount++;
    const dur  = tx.total_duration_ms || 0;
    const cost = tx.total_cost_usd    || 0;
    const errs = tx.total_tool_errors || 0;
    let taskTurns = 0, taskCalls = 0;
    for (const inv of (tx.invocations || [])) {
      taskTurns += inv.num_turns || 0;
      for (const [name, n] of Object.entries(inv.tool_usage || {})) {
        taskCalls += n;
        e.toolBreakdown[name] = (e.toolBreakdown[name] || 0) + n;
      }
    }
    // Also check model from transcript invocation if task model is unset
    if (!task.model) {
      const invModel = (tx.invocations || [])[0]?.model || '';
      const im = invModel.toLowerCase();
      if (im.includes('opus'))        { e.modelCounts.other--; e.modelCounts.opus++; }
      else if (im.includes('sonnet')) { e.modelCounts.other--; e.modelCounts.sonnet++; }
      else if (im.includes('haiku'))  { e.modelCounts.other--; e.modelCounts.haiku++; }
    }
    e.durations_ms.push(dur);
    e.costs_usd.push(cost);
    e.turns.push(taskTurns);
    e.toolErrors.push(errs);
    e.toolCalls.push(taskCalls);
    e.totalCost         += cost;
    e.totalDuration_ms  += dur;
    e.totalTurns        += taskTurns;
    e.totalToolErrors   += errs;
  }
  return Object.values(stageMap).sort((a, b) => {
    if (a.stage === '(no phase)') return 1;
    if (b.stage === '(no phase)') return -1;
    const na = Number(a.stage), nb = Number(b.stage);
    if (!isNaN(na) && !isNaN(nb)) return na - nb;
    return a.stage.localeCompare(b.stage);
  });
}

function _rcFmtMs(ms) {
  if (ms >= 3600000) return (ms / 3600000).toFixed(1) + 'h';
  if (ms >= 60000)   return (ms / 60000).toFixed(1) + 'm';
  if (ms >= 1000)    return (ms / 1000).toFixed(1) + 's';
  return Math.round(ms) + 'ms';
}
function _rcFmtCost(v) { return '$' + v.toFixed(v < 0.01 ? 5 : 3); }
function _rcFmtN(v)    { return String(Math.round(v)); }
function _rcFmtTurns(v){ return v % 1 === 0 ? String(v) : v.toFixed(1); }

function _renderDotPlot(values, globalMax, color, plotW, plotH, fmtFn) {
  if (!values.length) {
    return `<svg width="${plotW}" height="${plotH}"><text x="4" y="${plotH/2+4}" fill="#d1d5db" font-size="10">no data</text></svg>`;
  }
  const padL = 4, padR = 12, padT = 2, padB = 3;
  const w = plotW - padL - padR;
  const h = plotH - padT - padB;
  const NUM_BINS = 30;
  function vx(v) { return padL + (globalMax > 0 ? (v / globalMax) * w : 0); }

  // Build histogram bins
  const bins = new Array(NUM_BINS).fill(0);
  const binLabels = new Array(NUM_BINS).fill(null); // store representative value for tooltip
  for (const v of values) {
    const bi = globalMax > 0 ? Math.min(NUM_BINS - 1, Math.floor((v / globalMax) * NUM_BINS)) : 0;
    bins[bi]++;
    if (binLabels[bi] === null) binLabels[bi] = v;
  }
  const maxBin = Math.max(1, ...bins);
  const binW = w / NUM_BINS;

  // Parse color to get RGB for blending (color is hex like #3b82f6)
  function hexToRgb(hex) {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return [r,g,b];
  }
  function blendToWhite(hex, t) { // t=0 → white, t=1 → color
    const [r,g,b] = hexToRgb(hex);
    const ri = Math.round(255 + (r-255)*t), gi = Math.round(255 + (g-255)*t), bi = Math.round(255 + (b-255)*t);
    return `rgb(${ri},${gi},${bi})`;
  }

  let bars = '';
  for (let i = 0; i < NUM_BINS; i++) {
    if (!bins[i]) continue;
    const density = bins[i] / maxBin;            // 0..1
    const barH = Math.max(1, density * h);
    const x = padL + i * binW;
    const y = padT + h - barH;
    // Color intensity proportional to count: sparse bins = washed out, dense bins = full color
    const fillColor = blendToWhite(color, 0.25 + 0.75 * density);
    const binStart = (i / NUM_BINS) * globalMax;
    const binEnd   = ((i + 1) / NUM_BINS) * globalMax;
    const tip = fmtFn ? `${fmtFn(binStart)}–${fmtFn(binEnd)}: ${bins[i]}` : `${bins[i]}`;
    bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1,binW-0.5).toFixed(1)}" height="${barH.toFixed(1)}" fill="${fillColor}" rx="1"><title>${tip}</title></rect>`;
  }

  const baseline = `<line x1="${padL}" y1="${padT + h}" x2="${plotW - padR}" y2="${padT + h}" stroke="#e5e7eb" stroke-width="1"/>`;
  const avg  = values.reduce((s, v) => s + v, 0) / values.length;
  const avgX = vx(avg);
  const avgLine = `<line x1="${avgX}" y1="${padT}" x2="${avgX}" y2="${padT + h}" stroke="${color}" stroke-width="2" stroke-dasharray="3,2" opacity="0.9"><title>avg: ${fmtFn ? fmtFn(avg) : avg}</title></line>`;
  return `<svg width="${plotW}" height="${plotH}">${baseline}${bars}${avgLine}</svg>`;
}

function _renderMetricSection(stageData, metricKey, title, fmtFn) {
  const PLOT_W = 340, PLOT_H = 32;
  const stageNames = stageData.map(e => e.stage);
  const allVals = stageData.flatMap(e => e[metricKey]);
  const globalMax = Math.max(1, ...allVals);
  const totalAll = allVals.reduce((s, v) => s + v, 0);
  const countAll = allVals.length;
  let html = `<div class="rc-section"><div class="rc-section-title">${title}</div>`;
  html += `<div class="rc-stat-cards">
    <div class="rc-stat-card"><label>Total</label><value>${fmtFn(totalAll)}</value></div>
    <div class="rc-stat-card"><label>Avg / task</label><value>${countAll ? fmtFn(totalAll / countAll) : '—'}</value></div>
    <div class="rc-stat-card"><label>Tasks</label><value>${countAll}</value><small>with transcript</small></div>
  </div>`;
  for (let i = 0; i < stageData.length; i++) {
    const e = stageData[i];
    const vals = e[metricKey];
    const color = _stageColor(e.stage, stageNames);
    const avg = vals.length ? fmtFn(vals.reduce((a, b) => a + b, 0) / vals.length) : '—';
    const tot = vals.length ? fmtFn(vals.reduce((a, b) => a + b, 0)) : '—';
    html += `<div class="rc-stage-row">
      <div class="rc-stage-label" title="${esc(e.stage)}">${esc(e.stage)}</div>
      <div class="rc-stage-chart">${_renderDotPlot(vals, globalMax, color, PLOT_W, PLOT_H, fmtFn)}</div>
      <div class="rc-stage-ann">avg ${avg} · tot ${tot} · n=${vals.length}</div>
    </div>`;
  }
  html += `<div class="rc-axis-hint">← 0 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${fmtFn(globalMax)} max →</div>`;
  html += `</div>`;
  return html;
}

function _renderGroupedBar(perStageValues, stageLabels, colors) {
  const W = 200, H = 72;
  const padT = 6, padB = 20, padL = 6, padR = 6;
  const n  = stageLabels.length;
  const chartW = W - padL - padR;
  const barW   = Math.max(4, Math.min(28, chartW / n - 4));
  const gap    = (chartW - barW * n) / (n + 1);
  const maxVal = Math.max(1, ...perStageValues);
  const chartH = H - padT - padB;
  let svg = '';
  for (let i = 0; i < n; i++) {
    const v    = perStageValues[i];
    const barH = (v / maxVal) * chartH;
    const x    = padL + gap * (i + 1) + barW * i;
    const y    = padT + chartH - barH;
    svg += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW}" height="${Math.max(1, barH).toFixed(1)}" fill="${colors[i]}" rx="2" opacity="0.85"><title>${esc(stageLabels[i])}: ${v}</title></rect>`;
    const lbl = stageLabels[i].length > 5 ? stageLabels[i].slice(0, 5) : stageLabels[i];
    svg += `<text x="${(x + barW / 2).toFixed(1)}" y="${H - 4}" text-anchor="middle" fill="#9ca3af" font-size="9">${esc(lbl)}</text>`;
  }
  svg += `<line x1="${padL}" y1="${padT + chartH}" x2="${W - padR}" y2="${padT + chartH}" stroke="#e5e7eb" stroke-width="1"/>`;
  svg += `<text x="${padL}" y="${padT + 9}" fill="#d1d5db" font-size="9">${maxVal}</text>`;
  return `<svg width="${W}" height="${H}">${svg}</svg>`;
}

function _renderToolSection(stageData) {
  const stageNames = stageData.map(e => e.stage);
  const colors     = stageData.map((e, i) => _stageColor(e.stage, stageNames));
  const allTools   = new Set();
  stageData.forEach(e => Object.keys(e.toolBreakdown).forEach(t => allTools.add(t)));
  const toolList = [...allTools].sort();
  if (!toolList.length) return '';
  let html = `<div class="rc-section"><div class="rc-section-title">Tool Calls by Tool</div><div class="rc-tool-grid">`;
  for (const tool of toolList) {
    const perStage = stageData.map(e => e.toolBreakdown[tool] || 0);
    const total    = perStage.reduce((a, b) => a + b, 0);
    html += `<div class="rc-tool-card">
      <div class="rc-tool-card-title">${esc(tool)} <span style="font-weight:400;color:#9ca3af">(${total} total)</span></div>
      ${_renderGroupedBar(perStage, stageNames, colors)}
    </div>`;
  }
  html += `</div></div>`;
  return html;
}

function _renderModelSection(stageData) {
  const MODEL_COLORS = { opus: '#6d28d9', sonnet: '#1d4ed8', haiku: '#0e7490', other: '#6b7280' };
  const MODEL_ORDER  = ['opus', 'sonnet', 'haiku', 'other'];
  const BAR_W = 300, BAR_H = 14;
  let html = `<div class="rc-section"><div class="rc-section-title">Model Distribution</div>`;
  for (const e of stageData) {
    const total = e.taskCount || 1;
    let bars = '', xOff = 0;
    for (const m of MODEL_ORDER) {
      const n = e.modelCounts[m] || 0;
      if (!n) continue;
      const w = Math.max(1, Math.round((n / total) * BAR_W));
      bars += `<rect x="${xOff}" y="0" width="${w}" height="${BAR_H}" fill="${MODEL_COLORS[m]}" rx="2"><title>${m}: ${n}</title></rect>`;
      xOff += w;
    }
    const counts = MODEL_ORDER.filter(m => e.modelCounts[m])
      .map(m => `<span style="color:${MODEL_COLORS[m]};font-weight:600">${m}</span> ${e.modelCounts[m]}`).join(' · ');
    html += `<div class="rc-stage-row">
      <div class="rc-stage-label" title="${esc(e.stage)}">${esc(e.stage)}</div>
      <div class="rc-stage-chart"><svg width="${BAR_W}" height="${BAR_H}" style="border-radius:3px;overflow:hidden">${bars}</svg></div>
      <div class="rc-stage-ann" style="font-size:11px">${counts || '<span style="color:#d1d5db">none</span>'}</div>
    </div>`;
  }
  const legend = MODEL_ORDER.map(m =>
    `<span><span style="display:inline-block;width:10px;height:10px;background:${MODEL_COLORS[m]};border-radius:2px;margin-right:4px;vertical-align:middle"></span>${m}</span>`
  ).join('');
  html += `<div style="display:flex;gap:14px;padding-top:8px;padding-left:92px;font-size:11px;color:var(--text-muted)">${legend}</div>`;
  html += `</div>`;
  return html;
}

function _renderSummaryCards(stageData) {
  const totCost  = stageData.reduce((s, e) => s + e.totalCost, 0);
  const totDur   = stageData.reduce((s, e) => s + e.totalDuration_ms, 0);
  const totTurns = stageData.reduce((s, e) => s + e.totalTurns, 0);
  const totErrs  = stageData.reduce((s, e) => s + e.totalToolErrors, 0);
  const totTasks = stageData.reduce((s, e) => s + e.taskCount, 0);
  const txTasks  = stageData.reduce((s, e) => s + e.txTaskCount, 0);
  const nStages  = stageData.length;
  const errStyle = totErrs > 0 ? 'color:#dc2626' : '';
  return `<div class="rc-stat-cards" style="margin-bottom:28px">
    <div class="rc-stat-card"><label>Stages</label><value>${nStages}</value></div>
    <div class="rc-stat-card"><label>Total Tasks</label><value>${totTasks}</value><small>${txTasks} with transcript</small></div>
    <div class="rc-stat-card"><label>Total Cost</label><value>${_rcFmtCost(totCost)}</value></div>
    <div class="rc-stat-card"><label>Total Duration</label><value>${_rcFmtMs(totDur)}</value></div>
    <div class="rc-stat-card"><label>Total Turns</label><value>${totTurns}</value></div>
    <div class="rc-stat-card"><label>Tool Errors</label><value style="${errStyle}">${totErrs}</value></div>
  </div>`;
}

// ── Time-split helpers ──────────────────────────────────────
let _rcSplitTs = null; // epoch ms or null

function _taskTimestamp(task) {
  const ts = task.completed_at || task.created_at;
  return ts ? new Date(ts).getTime() : null;
}

// Saved split points in localStorage
function _getSavedSplits() {
  try { return JSON.parse(localStorage.getItem('tl0_rc_saved_splits') || '[]'); } catch(_) { return []; }
}
function _setSavedSplits(arr) {
  try { localStorage.setItem('tl0_rc_saved_splits', JSON.stringify(arr)); } catch(_) {}
}
function _addSavedSplit(val) {
  const splits = _getSavedSplits();
  if (!splits.includes(val)) {
    splits.push(val);
    splits.sort();
    _setSavedSplits(splits);
  }
}
function _removeSavedSplit(val) {
  _setSavedSplits(_getSavedSplits().filter(v => v !== val));
}

function _fmtSplitChipLabel(val) {
  const d = new Date(val);
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const dy = String(d.getDate()).padStart(2, '0');
  const hr = String(d.getHours()).padStart(2, '0');
  const mn = String(d.getMinutes()).padStart(2, '0');
  return `${mo}/${dy} ${hr}:${mn}`;
}

function _renderSavedSplitChips() {
  const container = document.getElementById('rc-saved-splits');
  if (!container) return;
  const splits = _getSavedSplits();
  if (!splits.length) { container.innerHTML = ''; return; }
  const currentVal = document.getElementById('rc-split-dt').value;
  let html = '<span class="rc-saved-label">Saved:</span>';
  for (const val of splits) {
    const isActive = val === currentVal;
    html += `<span class="rc-saved-chip${isActive ? ' active' : ''}" onclick="applySavedSplit('${val}')" title="${val}">`;
    html += _fmtSplitChipLabel(val);
    html += `<span class="rc-chip-x" onclick="event.stopPropagation(); deleteSavedSplit('${val}')">&times;</span>`;
    html += `</span>`;
  }
  container.innerHTML = html;
}

function applySavedSplit(val) {
  const el = document.getElementById('rc-split-dt');
  el.value = val;
  onRcSplitChange();
}

function deleteSavedSplit(val) {
  _removeSavedSplit(val);
  _renderSavedSplitChips();
}

function _applySplitUI(val) {
  _rcSplitTs = new Date(val).getTime();
  document.getElementById('rc-split-dt').value = val;
  document.getElementById('rc-split-clear-btn').style.display = '';
  document.getElementById('rc-split-hint').textContent = '';
  _renderSavedSplitChips();
}

function onRcSplitChange() {
  const el = document.getElementById('rc-split-dt');
  const val = el.value;
  if (val) {
    _rcSplitTs = new Date(val).getTime();
    document.getElementById('rc-split-clear-btn').style.display = '';
    document.getElementById('rc-split-hint').textContent = '';
    _addSavedSplit(val);
  } else {
    clearRcSplit();
    return;
  }
  try { localStorage.setItem('tl0_rc_split', val || ''); } catch(_) {}
  _renderSavedSplitChips();
  renderReport();
}
function clearRcSplit() {
  _rcSplitTs = null;
  document.getElementById('rc-split-dt').value = '';
  document.getElementById('rc-split-clear-btn').style.display = 'none';
  document.getElementById('rc-split-hint').textContent = 'Set a split point to compare before / after';
  try { localStorage.setItem('tl0_rc_split', ''); } catch(_) {}
  _renderSavedSplitChips();
  renderReport();
}
// Restore saved split on load
try {
  const saved = localStorage.getItem('tl0_rc_split');
  requestAnimationFrame(() => {
    if (saved) { _applySplitUI(saved); }
    _renderSavedSplitChips();
  });
} catch(_) {}

function _splitTasksByTime(tasks, splitTs) {
  const before = [], after = [];
  for (const t of tasks) {
    const ts = _taskTimestamp(t);
    if (ts === null || ts < splitTs) before.push(t);
    else after.push(t);
  }
  return { before, after };
}

function _rcDelta(valBefore, valAfter, fmtFn, lowerIsBetter) {
  if (!valBefore || !valAfter) return '';
  const diff = valAfter - valBefore;
  const pct = valBefore !== 0 ? Math.round((diff / valBefore) * 100) : 0;
  if (pct === 0) return `<span class="rc-delta neutral">0%</span>`;
  const sign = pct > 0 ? '+' : '';
  const cls = (lowerIsBetter ? pct < 0 : pct > 0) ? 'better' : 'worse';
  return `<span class="rc-delta ${cls}">${sign}${pct}%</span>`;
}

function _renderSplitSummaryCards(beforeData, afterData) {
  function _totals(data) {
    return {
      cost: data.reduce((s, e) => s + e.totalCost, 0),
      dur:  data.reduce((s, e) => s + e.totalDuration_ms, 0),
      turns: data.reduce((s, e) => s + e.totalTurns, 0),
      errs: data.reduce((s, e) => s + e.totalToolErrors, 0),
      tasks: data.reduce((s, e) => s + e.taskCount, 0),
      tx:   data.reduce((s, e) => s + e.txTaskCount, 0),
    };
  }
  const b = _totals(beforeData), a = _totals(afterData);
  const bAvgCost = b.tx ? b.cost / b.tx : 0, aAvgCost = a.tx ? a.cost / a.tx : 0;
  const bAvgDur  = b.tx ? b.dur / b.tx : 0,  aAvgDur  = a.tx ? a.dur / a.tx : 0;
  const bAvgTurns = b.tx ? b.turns / b.tx : 0, aAvgTurns = a.tx ? a.turns / a.tx : 0;

  function card(label, bVal, aVal, fmtFn, lowerIsBetter) {
    return `<div class="rc-stat-card">
      <label>${label}</label>
      <value>${fmtFn(aVal)}${_rcDelta(bVal, aVal, fmtFn, lowerIsBetter)}</value>
      <small>was ${fmtFn(bVal)}</small>
    </div>`;
  }

  return `<div class="rc-stat-cards" style="margin-bottom:28px">
    <div class="rc-stat-card"><label>Before</label><value>${b.tasks}</value><small>${b.tx} with transcript</small></div>
    <div class="rc-stat-card"><label>After</label><value>${a.tasks}</value><small>${a.tx} with transcript</small></div>
    ${card('Avg Cost', bAvgCost, aAvgCost, _rcFmtCost, true)}
    ${card('Avg Duration', bAvgDur, aAvgDur, _rcFmtMs, true)}
    ${card('Avg Turns', bAvgTurns, aAvgTurns, _rcFmtTurns, true)}
    ${card('Tool Errors', b.errs, a.errs, _rcFmtN, true)}
  </div>`;
}

const RC_BEFORE_COLOR = '#3b82f6';
const RC_AFTER_COLOR  = '#10b981';

function _renderSplitMetricSection(beforeData, afterData, metricKey, title, fmtFn) {
  const PLOT_W = 340, PLOT_H = 32;
  const allValsB = beforeData.flatMap(e => e[metricKey]);
  const allValsA = afterData.flatMap(e => e[metricKey]);
  const globalMax = Math.max(1, ...allValsB, ...allValsA);
  const totalB = allValsB.reduce((s, v) => s + v, 0);
  const totalA = allValsA.reduce((s, v) => s + v, 0);
  const avgB = allValsB.length ? totalB / allValsB.length : 0;
  const avgA = allValsA.length ? totalA / allValsA.length : 0;

  let html = `<div class="rc-section"><div class="rc-section-title">${title}</div>`;
  html += `<div class="rc-stat-cards">
    <div class="rc-stat-card"><label>Before avg</label><value>${allValsB.length ? fmtFn(avgB) : '—'}</value><small>n=${allValsB.length}</small></div>
    <div class="rc-stat-card"><label>After avg</label><value>${allValsA.length ? fmtFn(avgA) : '—'}${_rcDelta(avgB, avgA, fmtFn, true)}</value><small>n=${allValsA.length}</small></div>
    <div class="rc-stat-card"><label>Before total</label><value>${fmtFn(totalB)}</value></div>
    <div class="rc-stat-card"><label>After total</label><value>${fmtFn(totalA)}${_rcDelta(totalB, totalA, fmtFn, true)}</value></div>
  </div>`;

  // Collect all stage names across both sets
  const stageSet = new Set();
  beforeData.forEach(e => stageSet.add(e.stage));
  afterData.forEach(e => stageSet.add(e.stage));
  const stageNames = [...stageSet].sort((a, b) => {
    if (a === '(no phase)') return 1;
    if (b === '(no phase)') return -1;
    const na = Number(a), nb = Number(b);
    if (!isNaN(na) && !isNaN(nb)) return na - nb;
    return a.localeCompare(b);
  });

  for (const stage of stageNames) {
    const bEntry = beforeData.find(e => e.stage === stage);
    const aEntry = afterData.find(e => e.stage === stage);
    const bVals = bEntry ? bEntry[metricKey] : [];
    const aVals = aEntry ? aEntry[metricKey] : [];
    const bAvg = bVals.length ? fmtFn(bVals.reduce((a, b) => a + b, 0) / bVals.length) : '—';
    const aAvg = aVals.length ? fmtFn(aVals.reduce((a, b) => a + b, 0) / aVals.length) : '—';
    html += `<div class="rc-split-group">
      <div class="rc-split-group-label">${esc(stage)}</div>
      <div class="rc-stage-row">
        <div class="rc-stage-label"><span class="rc-split-tag before">before</span></div>
        <div class="rc-stage-chart">${_renderDotPlot(bVals, globalMax, RC_BEFORE_COLOR, PLOT_W, PLOT_H, fmtFn)}</div>
        <div class="rc-stage-ann">avg ${bAvg} · n=${bVals.length}</div>
      </div>
      <div class="rc-stage-row">
        <div class="rc-stage-label"><span class="rc-split-tag after">after</span></div>
        <div class="rc-stage-chart">${_renderDotPlot(aVals, globalMax, RC_AFTER_COLOR, PLOT_W, PLOT_H, fmtFn)}</div>
        <div class="rc-stage-ann">avg ${aAvg} · n=${aVals.length}</div>
      </div>
    </div>`;
  }
  html += `<div class="rc-axis-hint">← 0 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${fmtFn(globalMax)} max →</div>`;
  html += `</div>`;
  return html;
}

function _renderSplitToolSection(beforeData, afterData) {
  const allTools = new Set();
  beforeData.forEach(e => Object.keys(e.toolBreakdown).forEach(t => allTools.add(t)));
  afterData.forEach(e => Object.keys(e.toolBreakdown).forEach(t => allTools.add(t)));
  const toolList = [...allTools].sort();
  if (!toolList.length) return '';

  const stageSet = new Set();
  beforeData.forEach(e => stageSet.add(e.stage));
  afterData.forEach(e => stageSet.add(e.stage));
  const stageNames = [...stageSet];

  let html = `<div class="rc-section"><div class="rc-section-title">Tool Calls by Tool</div><div class="rc-tool-grid">`;
  for (const tool of toolList) {
    const bTotal = beforeData.reduce((s, e) => s + (e.toolBreakdown[tool] || 0), 0);
    const aTotal = afterData.reduce((s, e) => s + (e.toolBreakdown[tool] || 0), 0);
    const labels = ['Before', 'After'];
    const vals   = [bTotal, aTotal];
    const colors = [RC_BEFORE_COLOR, RC_AFTER_COLOR];
    html += `<div class="rc-tool-card">
      <div class="rc-tool-card-title">${esc(tool)} <span style="font-weight:400;color:#9ca3af">${aTotal} after · ${bTotal} before</span></div>
      ${_renderGroupedBar(vals, labels, colors)}
    </div>`;
  }
  html += `</div></div>`;
  return html;
}

function _renderSplitModelSection(beforeData, afterData) {
  const MODEL_COLORS = { opus: '#6d28d9', sonnet: '#1d4ed8', haiku: '#0e7490', other: '#6b7280' };
  const MODEL_ORDER  = ['opus', 'sonnet', 'haiku', 'other'];
  const BAR_W = 300, BAR_H = 14;
  let html = `<div class="rc-section"><div class="rc-section-title">Model Distribution</div>`;

  function renderRow(label, tagClass, data) {
    for (const e of data) {
      const total = e.taskCount || 1;
      let bars = '', xOff = 0;
      for (const m of MODEL_ORDER) {
        const n = e.modelCounts[m] || 0;
        if (!n) continue;
        const w = Math.max(1, Math.round((n / total) * BAR_W));
        bars += `<rect x="${xOff}" y="0" width="${w}" height="${BAR_H}" fill="${MODEL_COLORS[m]}" rx="2"><title>${m}: ${n}</title></rect>`;
        xOff += w;
      }
      const counts = MODEL_ORDER.filter(m => e.modelCounts[m])
        .map(m => `<span style="color:${MODEL_COLORS[m]};font-weight:600">${m}</span> ${e.modelCounts[m]}`).join(' · ');
      html += `<div class="rc-stage-row">
        <div class="rc-stage-label"><span class="rc-split-tag ${tagClass}">${label}</span></div>
        <div class="rc-stage-chart"><svg width="${BAR_W}" height="${BAR_H}" style="border-radius:3px;overflow:hidden">${bars}</svg></div>
        <div class="rc-stage-ann" style="font-size:11px">${counts || '<span style="color:#d1d5db">none</span>'}</div>
      </div>`;
    }
  }

  const stageSet = new Set();
  beforeData.forEach(e => stageSet.add(e.stage));
  afterData.forEach(e => stageSet.add(e.stage));

  for (const stage of stageSet) {
    const bEntries = beforeData.filter(e => e.stage === stage);
    const aEntries = afterData.filter(e => e.stage === stage);
    html += `<div class="rc-split-group"><div class="rc-split-group-label">${esc(stage)}</div>`;
    renderRow('before', 'before', bEntries);
    renderRow('after', 'after', aEntries);
    html += `</div>`;
  }

  const legend = MODEL_ORDER.map(m =>
    `<span><span style="display:inline-block;width:10px;height:10px;background:${MODEL_COLORS[m]};border-radius:2px;margin-right:4px;vertical-align:middle"></span>${m}</span>`
  ).join('');
  html += `<div style="display:flex;gap:14px;padding-top:8px;padding-left:92px;font-size:11px;color:var(--text-muted)">${legend}</div>`;
  html += `</div>`;
  return html;
}

async function renderReport() {
  if (state.view !== 'report') return;
  const contentEl = document.getElementById('report-content');
  const loadingEl = document.getElementById('report-loading');
  if (!contentEl) return;

  const tasks = getFiltered();

  if (_rcSplitTs) {
    // ── Split mode ──
    const { before, after } = _splitTasksByTime(tasks, _rcSplitTs);
    const beforeData = _buildStageMetrics(before);
    const afterData  = _buildStageMetrics(after);

    if (!beforeData.length && !afterData.length) {
      contentEl.innerHTML = '<div class="rc-no-data">No tasks match current filters.</div>';
      return;
    }

    let html = _renderSplitSummaryCards(beforeData, afterData);
    html += _renderSplitMetricSection(beforeData, afterData, 'durations_ms', 'Latency', _rcFmtMs);
    html += _renderSplitMetricSection(beforeData, afterData, 'turns',        'Turns',   _rcFmtTurns);
    html += _renderSplitMetricSection(beforeData, afterData, 'costs_usd',    'Cost (USD)', _rcFmtCost);
    html += _renderSplitMetricSection(beforeData, afterData, 'toolErrors',   'Tool Errors', _rcFmtN);
    html += _renderSplitMetricSection(beforeData, afterData, 'toolCalls',    'Total Tool Calls', _rcFmtN);
    html += _renderSplitToolSection(beforeData, afterData);
    html += _renderSplitModelSection(beforeData, afterData);
    contentEl.innerHTML = html;
  } else {
    // ── Normal mode ──
    const stageData = _buildStageMetrics(tasks);
    if (!stageData.length) {
      contentEl.innerHTML = '<div class="rc-no-data">No tasks match current filters.</div>';
      return;
    }
    let html = _renderSummaryCards(stageData);
    html += _renderMetricSection(stageData, 'durations_ms', 'Latency', _rcFmtMs);
    html += _renderMetricSection(stageData, 'turns',        'Turns',   _rcFmtTurns);
    html += _renderMetricSection(stageData, 'costs_usd',    'Cost (USD)', _rcFmtCost);
    html += _renderMetricSection(stageData, 'toolErrors',   'Tool Errors', _rcFmtN);
    html += _renderMetricSection(stageData, 'toolCalls',    'Total Tool Calls', _rcFmtN);
    html += _renderToolSection(stageData);
    html += _renderModelSection(stageData);
    contentEl.innerHTML = html;
  }
}

// ── Table view ───────────────────────────────────────────────
let _tableSort = { col: null, dir: 'asc' };

const TABLE_COLUMNS = [
  { key: 'title',            label: 'Task',            type: 'text',   default: true },
  { key: 'status',           label: 'Status',          type: 'badge',  default: true },
  { key: 'model',            label: 'Model',           type: 'badge',  default: true },
  { key: 'duration',         label: 'Duration',        type: 'num',    default: true },
  { key: 'cost',             label: 'Cost',            type: 'num',    default: true },
  { key: 'turns',            label: 'Turns',           type: 'num',    default: true },
  { key: 'tool_errors',      label: 'Tool Errors',     type: 'num',    default: true },
  { key: 'merge_conflicts',  label: 'Merge Conflicts', type: 'num',    default: false },
  { key: 'Read',             label: 'Read',            type: 'tool',   default: true },
  { key: 'Edit',             label: 'Edit',            type: 'tool',   default: false },
  { key: 'Write',            label: 'Write',           type: 'tool',   default: false },
  { key: 'Bash',             label: 'Bash',            type: 'tool',   default: true },
  { key: 'Glob',             label: 'Glob',            type: 'tool',   default: false },
  { key: 'Grep',             label: 'Grep',            type: 'tool',   default: false },
  { key: 'Task',             label: 'Task (subtask)',  type: 'tool',   default: false },
  { key: 'WebFetch',         label: 'WebFetch',        type: 'tool',   default: false },
  { key: 'other_tools',      label: 'Other Tools',     type: 'num',    default: false },
  { key: 'commit',           label: 'Commit',          type: 'commit', default: true },
  { key: 'completed_at',     label: 'Completed',       type: 'time',   default: true },
  { key: 'tags',             label: 'Tags',            type: 'tags',   default: false },
];

// Track which columns are visible
let _visibleCols = new Set(TABLE_COLUMNS.filter(c => c.default).map(c => c.key));
// Restore from localStorage if available
try {
  const saved = JSON.parse(localStorage.getItem('tl0_table_cols') || 'null');
  if (Array.isArray(saved)) _visibleCols = new Set(saved);
} catch (_) {}

function _persistCols() {
  localStorage.setItem('tl0_table_cols', JSON.stringify([..._visibleCols]));
}

const KNOWN_TOOLS = ['Read','Edit','Write','Bash','Glob','Grep','WebFetch'];

function _getTableVal(task, ts, col) {
  switch (col.key) {
    case 'title':           return task.title || '';
    case 'status':          return task.status || '';
    case 'model':           return task.model || '';
    case 'duration':        return ts ? (ts.total_duration_ms || 0) : 0;
    case 'cost':            return ts ? (ts.total_cost_usd || 0) : 0;
    case 'turns': {
      if (!ts || !ts.invocations) return 0;
      return ts.invocations.reduce((s, inv) => s + (inv.num_turns || 0), 0);
    }
    case 'tool_errors':     return ts ? (ts.total_tool_errors || 0) : 0;
    case 'merge_conflicts': return ts ? (ts.merge_conflict_count || 0) : 0;
    case 'commit':          return task.merge_sha || '';
    case 'completed_at':    return task.completed_at || '';
    case 'tags':            return (task.tags || []).join(', ');
    case 'Task':            return (task.tasks_created || []).length;
    case 'other_tools': {
      if (!ts || !ts.invocations) return 0;
      let count = 0;
      for (const inv of ts.invocations) {
        if (!inv.tool_usage) continue;
        for (const [name, n] of Object.entries(inv.tool_usage)) {
          if (!KNOWN_TOOLS.includes(name)) count += n;
        }
      }
      return count;
    }
    default: {
      // Tool columns
      if (!ts || !ts.invocations) return 0;
      let count = 0;
      for (const inv of ts.invocations) {
        if (inv.tool_usage && inv.tool_usage[col.key]) count += inv.tool_usage[col.key];
      }
      return count;
    }
  }
}

function _fmtDuration(ms) {
  if (!ms) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return m + 'm ' + rem + 's';
  const h = Math.floor(m / 60);
  return h + 'h ' + (m % 60) + 'm';
}

function _fmtCost(usd) {
  if (!usd) return '—';
  return '$' + usd.toFixed(2);
}

function _fmtRelTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  return days + 'd ago';
}

function _fmtCell(task, ts, col) {
  const val = _getTableVal(task, ts, col);
  // data attributes for filter context menu
  const fAttr = `data-filter-col="${col.key}" data-filter-task="${task.id}"`;
  switch (col.key) {
    case 'title':
      return `<td class="task-name-cell" onclick="tableClickTask('${task.id}')" title="${(task.title||'').replace(/"/g,'&quot;')}">${_esc(task.title || '(untitled)')}</td>`;
    case 'status': {
      const cls = val === 'in-progress' ? 'in-progress' : val;
      return `<td ${fAttr} style="cursor:pointer"><span class="badge badge-${cls}" style="${_statusBadgeStyle(val)}">${val}</span></td>`;
    }
    case 'model':
      return val ? `<td ${fAttr} style="cursor:pointer"><span class="badge badge-${val}">${val}</span></td>` : `<td ${fAttr} style="cursor:pointer">—</td>`;
    case 'duration':
      return `<td class="num-cell" ${fAttr} style="cursor:pointer">${_fmtDuration(val)}</td>`;
    case 'cost':
      return `<td class="num-cell" ${fAttr} style="cursor:pointer">${_fmtCost(val)}</td>`;
    case 'completed_at':
      return `<td ${fAttr} style="cursor:pointer" title="${val}">${_fmtRelTime(val)}</td>`;
    case 'tags':
      return `<td>${(task.tags||[]).map(t => `<span class="d-tag" onclick="event.stopPropagation(); toggleTag('${_esc(t)}')">${_esc(t)}</span>`).join(' ')}</td>`;
    case 'commit': {
      if (!val) return `<td class="num-cell" style="color:#d1d5db">—</td>`;
      const short = val.slice(0, 8);
      const cellId = 'ds-' + short;
      if (_diffStatCache[val]) {
        const d = _diffStatCache[val];
        const label = d.files != null ? d.files + ' file' + (d.files !== 1 ? 's' : '') : short;
        return `<td class="num-cell"><span id="${cellId}" class="sha-badge" onclick="event.stopPropagation();showDiff('${_esc(val)}')" title="View diff" style="cursor:pointer">${label}</span></td>`;
      }
      fetch('/api/diff-stat/' + encodeURIComponent(val))
        .then(r => r.json())
        .then(d => {
          _diffStatCache[val] = d;
          const el = document.getElementById(cellId);
          if (el) el.textContent = d.files != null ? d.files + ' file' + (d.files !== 1 ? 's' : '') : short;
        }).catch(() => {});
      return `<td class="num-cell"><span id="${cellId}" class="sha-badge" onclick="event.stopPropagation();showDiff('${_esc(val)}')" title="View diff" style="cursor:pointer">${short}</span></td>`;
    }
    case 'merge_conflicts':
      if (val > 0) return `<td class="num-cell merge-yes" ${fAttr} style="cursor:pointer">${val}</td>`;
      return `<td class="num-cell merge-no" ${fAttr} style="cursor:pointer">—</td>`;
    case 'tool_errors':
      if (val > 0) return `<td class="num-cell" ${fAttr} style="cursor:pointer;color:#dc2626;font-weight:600">${val}</td>`;
      return `<td class="num-cell" ${fAttr} style="cursor:pointer;color:#9ca3af">—</td>`;
    default:
      // Numeric (tool counts, turns, etc.)
      return val ? `<td class="num-cell" ${fAttr} style="cursor:pointer">${val}</td>` : `<td class="num-cell" ${fAttr} style="cursor:pointer;color:#d1d5db">0</td>`;
  }
}

function _statusBadgeStyle(status) {
  const map = {
    'pending':     'background:#fff7ed;color:#c2410c;',
    'claimed':     'background:#eff6ff;color:#1d4ed8;',
    'in-progress': 'background:#f0fdf4;color:#15803d;',
    'done':        'background:#f0fdf4;color:#166534;',
    'stuck':       'background:#fff1f2;color:#be123c;',
  };
  return map[status] || '';
}

function _esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function renderTable() {
  const tableEl = document.getElementById('task-table');
  const tbody = tableEl.querySelector('tbody');
  const thead = tableEl.querySelector('thead tr');

  const filtered = getFiltered();
  const visCols = TABLE_COLUMNS.filter(c => _visibleCols.has(c.key));

  // Build rows with sort values
  let rows = filtered.map(task => {
    const ts = task.transcript || null;
    return { task, ts, _sortVals: {} };
  });

  // Apply column filters
  rows = _applyTableFilters(rows);

  document.getElementById('table-result-count').textContent = `${rows.length} tasks`;

  // Render filter pills
  _renderTableFilterPills();

  // Sort
  if (_tableSort.col) {
    const col = TABLE_COLUMNS.find(c => c.key === _tableSort.col);
    if (col) {
      rows.forEach(r => { r._sortVal = _getTableVal(r.task, r.ts, col); });
      const dir = _tableSort.dir === 'asc' ? 1 : -1;
      rows.sort((a, b) => {
        const va = a._sortVal, vb = b._sortVal;
        if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
        return String(va).localeCompare(String(vb)) * dir;
      });
    }
  }

  // Render header
  thead.innerHTML = visCols.map(col => {
    const isSorted = _tableSort.col === col.key;
    const arrow = isSorted ? (_tableSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    const arrowCls = isSorted ? 'sort-arrow active' : 'sort-arrow';
    return `<th onclick="tableSort('${col.key}')">${col.label}<span class="${arrowCls}">${arrow}</span></th>`;
  }).join('');

  // Render body
  tbody.innerHTML = rows.map(({task, ts}) =>
    '<tr>' + visCols.map(col => _fmtCell(task, ts, col)).join('') + '</tr>'
  ).join('');

  // Attach filter click delegation on tbody
  tbody.onclick = function(e) {
    const td = e.target.closest('td[data-filter-col]');
    if (!td) return;
    const colKey = td.dataset.filterCol;
    const taskId = td.dataset.filterTask;
    const col = TABLE_COLUMNS.find(c => c.key === colKey);
    const task = taskMap[taskId];
    if (!col || !task) return;
    const ts = task ? (task.transcript || null) : null;
    _showColFilterMenu(e, task, ts, col);
  };

  // Render column picker
  renderColPicker();
}

function tableSort(key) {
  if (_tableSort.col === key) {
    if (_tableSort.dir === 'desc') _tableSort.dir = 'asc';
    else if (_tableSort.dir === 'asc') { _tableSort.col = null; _tableSort.dir = 'desc'; }
  } else {
    _tableSort.col = key;
    _tableSort.dir = 'desc';
  }
  renderTable();
}

function tableClickTask(id) {
  setView('tree');
  selectTask(id);
}

function toggleColPicker() {
  const menu = document.getElementById('col-picker-menu');
  menu.style.display = menu.style.display === 'none' ? '' : 'none';
}

function renderColPicker() {
  const menu = document.getElementById('col-picker-menu');
  menu.innerHTML = TABLE_COLUMNS.map(col => {
    const checked = _visibleCols.has(col.key) ? 'checked' : '';
    return `<label><input type="checkbox" ${checked} onchange="toggleCol('${col.key}', this.checked)"> ${col.label}</label>`;
  }).join('');
}

// ── Column Filters ──────────────────────────────────────────

const _OP_LABELS = { lte: '\u2264', eq: '=', gte: '\u2265', neq: '\u2260' };
const _OP_NAMES  = { lte: 'Less or equal', eq: 'Equal', gte: 'Greater or equal', neq: 'Not equal' };

function _formatFilterDisplay(col, val) {
  if (col.key === 'duration') return _fmtDuration(val);
  if (col.key === 'cost') return _fmtCost(val);
  if (col.key === 'completed_at') return _fmtRelTime(val);
  return String(val);
}

function _showColFilterMenu(e, task, ts, col) {
  e.stopPropagation();
  _closeColFilterMenu();
  const rawVal = _getTableVal(task, ts, col);
  const display = _formatFilterDisplay(col, rawVal);

  const menu = document.createElement('div');
  menu.className = 'col-filter-menu';
  menu.id = 'col-filter-menu';
  // Store value on menu element to avoid HTML attribute quoting issues
  const items = Object.entries(_OP_LABELS).map(([op, sym]) =>
    `<div class="cfm-item" data-op="${op}">` +
    `<span class="cfm-op">${sym}</span> ${_OP_NAMES[op]}</div>`
  ).join('');
  menu.innerHTML = `<div class="cfm-header">${_esc(col.label)}: ${_esc(display)}</div>` + items;
  menu._filterCol = col.key;
  menu._filterVal = rawVal;
  menu.querySelectorAll('.cfm-item').forEach(item => {
    item.addEventListener('click', () => _addColFilter(menu._filterCol, item.dataset.op, menu._filterVal));
  });

  document.body.appendChild(menu);

  // Position near click, clamped to viewport
  const rect = menu.getBoundingClientRect();
  let x = e.clientX, y = e.clientY + 4;
  if (x + rect.width > window.innerWidth) x = window.innerWidth - rect.width - 8;
  if (y + rect.height > window.innerHeight) y = e.clientY - rect.height - 4;
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';

  // Close on outside click
  setTimeout(() => document.addEventListener('click', _closeColFilterMenu, { once: true }), 0);
}

function _closeColFilterMenu() {
  const m = document.getElementById('col-filter-menu');
  if (m) m.remove();
}

function _addColFilter(colKey, op, value) {
  _closeColFilterMenu();
  const col = TABLE_COLUMNS.find(c => c.key === colKey);
  if (!col) return;
  // Remove existing filter on same col+op to replace it
  state.tableFilters = state.tableFilters.filter(f => !(f.col === colKey && f.op === op));
  state.tableFilters.push({ col: colKey, op, value, display: _formatFilterDisplay(col, value) });
  persist();
  updateClearFiltersButton();
  renderTable();
}

function _removeColFilter(idx) {
  state.tableFilters.splice(idx, 1);
  persist();
  updateClearFiltersButton();
  renderTable();
}

function _applyTableFilters(rows) {
  if (!state.tableFilters.length) return rows;
  return rows.filter(({task, ts}) => {
    for (const f of state.tableFilters) {
      const col = TABLE_COLUMNS.find(c => c.key === f.col);
      if (!col) continue;
      const val = _getTableVal(task, ts, col);
      const cmp = typeof val === 'number' && typeof f.value === 'number'
        ? val - f.value
        : String(val).localeCompare(String(f.value));
      switch (f.op) {
        case 'lte': if (cmp > 0) return false; break;
        case 'eq':  if (cmp !== 0) return false; break;
        case 'gte': if (cmp < 0) return false; break;
        case 'neq': if (cmp === 0) return false; break;
      }
    }
    return true;
  });
}

function _renderTableFilterPills() {
  const container = document.getElementById('table-filter-pills');
  if (!container) return;
  if (!state.tableFilters.length) { container.innerHTML = ''; return; }
  container.innerHTML = state.tableFilters.map((f, i) => {
    const col = TABLE_COLUMNS.find(c => c.key === f.col);
    const label = col ? col.label : f.col;
    return `<span class="table-filter-pill">${_esc(label)} ${_OP_LABELS[f.op]} ${_esc(f.display)}<span class="pill-x" onclick="_removeColFilter(${i})">&times;</span></span>`;
  }).join('');
}

function toggleCol(key, on) {
  if (on) _visibleCols.add(key);
  else _visibleCols.delete(key);
  _persistCols();
  renderTable();
}

// Close column picker on outside click
document.addEventListener('click', e => {
  const wrap = document.getElementById('col-picker-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('col-picker-menu').style.display = 'none';
  }
});

// ── Event wiring ─────────────────────────────────────────────
document.querySelectorAll('#status-chips .chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('#status-chips .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.statusFilter = chip.dataset.status;
    persist();
    renderTaskList();
  });
});

document.querySelectorAll('#model-chips .chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('#model-chips .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.modelFilter = chip.dataset.model;
    persist();
    renderTaskList();
  });
});

let searchTimer;
document.getElementById('search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = e.target.value;
    persist(true);
    renderTaskList();
  }, 180);
});

document.addEventListener('keydown', e => {
  const search = document.getElementById('search');
  if (e.key === '/' && document.activeElement !== search) {
    e.preventDefault();
    search.focus();
    search.select();
  }
  if (e.key === 'Escape' && document.activeElement === search) {
    search.value = '';
    state.search = '';
    persist(true);
    renderTaskList();
    search.blur();
  }
  if (e.altKey && e.key === 'ArrowLeft')  { e.preventDefault(); history.back(); }
  if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); history.forward(); }
});

// ── applyStateToUI ────────────────────────────────────────────
function applyStateToUI() {
  document.querySelectorAll('#status-chips .chip').forEach(c =>
    c.classList.toggle('active', c.dataset.status === state.statusFilter)
  );
  document.querySelectorAll('#model-chips .chip').forEach(c =>
    c.classList.toggle('active', c.dataset.model === state.modelFilter)
  );
  const searchEl = document.getElementById('search');
  if (searchEl) searchEl.value = state.search;
  _applyView(state.view);
  document.getElementById('sidebar').classList.toggle('hidden', !state.sidebarVisible);
  updateViewDropdownItems();
  if (state.selectedId) {
    document.querySelectorAll('.task-item').forEach(el =>
      el.classList.toggle('selected', el.dataset.id === state.selectedId)
    );
  }
}

// ── Boot ─────────────────────────────────────────────────────
loadSavedState();
applyStateToUI();
_initChartTimeFilter();

// Close view dropdown on outside click
document.addEventListener('click', e => {
  const wrap = document.getElementById('view-dropdown-wrap');
  if (wrap && !wrap.contains(e.target)) closeViewDropdown();
});

loadTasks();
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# Favicon SVG (TL0 text on a colored background)
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
# Transcript summary builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_transcript_messages(task_id: str, filename: str) -> list:
    """Extract the conversation messages from a transcript JSONL file."""
    filepath = TRANSCRIPTS_FOLDER / task_id / filename
    if not filepath.exists():
        return []

    events = []
    for line in filepath.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    messages = []
    # Track tool_use IDs to tool names for labeling results
    tool_names: dict[str, str] = {}
    # Track which tool_use IDs we've already seen content for (assistant messages
    # can be streamed across multiple events)
    seen_assistant_ids: set[str] = set()

    for e in events:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            # Deduplicate: each assistant message ID appears multiple times as blocks
            # stream in one at a time. Merge blocks across events for the same ID.
            msg_id = msg.get("id", "")
            if msg_id and msg_id in seen_assistant_ids:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("_msg_id") == msg_id:
                        merged = messages[i]["content"]
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            bid = block.get("id")
                            btype = block.get("type")
                            if bid:
                                found = False
                                for j, mb in enumerate(merged):
                                    if isinstance(mb, dict) and mb.get("id") == bid:
                                        merged[j] = block
                                        found = True
                                        break
                                if not found:
                                    merged.append(block)
                            else:
                                found = False
                                for j, mb in enumerate(merged):
                                    if isinstance(mb, dict) and mb.get("type") == btype and not mb.get("id"):
                                        merged[j] = block
                                        found = True
                                        break
                                if not found:
                                    merged.append(block)
                        break
            else:
                if msg_id:
                    seen_assistant_ids.add(msg_id)
                messages.append({"role": "assistant", "content": list(content), "_msg_id": msg_id})

            # Track tool names
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_names[block.get("id", "")] = block.get("name", "unknown")

        elif e.get("type") == "user":
            msg = e.get("message", {})
            content = msg.get("content", [])
            # Handle string content (the original user prompt/command)
            if isinstance(content, str):
                if content.strip():
                    messages.append({"role": "user", "text": content})
                continue
            if not isinstance(content, list):
                continue
            # Check if this user message has text blocks (prompt) vs tool_result blocks
            has_text = any(
                isinstance(b, dict) and b.get("type") == "text"
                for b in content
            )
            if has_text:
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                combined = "\n".join(text_parts)
                if combined.strip():
                    messages.append({"role": "user", "text": combined})
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id", "")
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            b.get("text", "") for b in result_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    elif not isinstance(result_content, str):
                        result_content = str(result_content)
                    # Truncate very large results
                    if len(result_content) > 3000:
                        result_content = result_content[:3000] + "\n… (truncated)"
                    messages.append({
                        "role": "tool_result",
                        "tool_use_id": tool_use_id,
                        "tool_name": tool_names.get(tool_use_id, "Tool"),
                        "text": result_content,
                    })

    # Clean up internal _msg_id fields
    for m in messages:
        m.pop("_msg_id", None)

    return messages


def _shorten_path(filepath: str, cwd: str) -> str:
    """Strip cwd prefix and worktree paths to produce a short relative path."""
    if not filepath:
        return ""
    # Strip .task-worktrees/<hash>/ pattern
    m = re.search(r'\.task-worktrees/[0-9a-f]+/(.+)', filepath)
    if m:
        return m.group(1)
    if cwd and filepath.startswith(cwd):
        rel = filepath[len(cwd):]
        return rel.lstrip("/")
    # Just return the last 2-3 path components
    parts = filepath.split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return filepath


def _summarize_tool_result(tool_name: str, result_text: str, is_error: bool) -> str:
    """Extract a short summary string from a tool result."""
    if is_error:
        first_line = result_text.split("\n")[0][:60] if result_text else "error"
        return first_line
    if not result_text:
        return ""
    lines = result_text.split("\n")
    non_empty = [l for l in lines if l.strip()]
    if tool_name == "Read":
        return f"{len(non_empty)} lines"
    if tool_name in ("Glob", "Grep"):
        if non_empty:
            return f"{len(non_empty)} matches"
        return "0 matches"
    if tool_name in ("Edit", "Write"):
        if "has been updated" in result_text or "created" in result_text:
            return ""
        return result_text.split("\n")[0][:60]
    if tool_name == "Bash":
        if not non_empty:
            return ""
        if len(non_empty) == 1:
            return non_empty[0][:80]
        return f"{len(non_empty)} lines"
    if tool_name in ("WebSearch", "WebFetch"):
        if not non_empty:
            return ""
        return f"{len(non_empty)} lines"
    return ""


def _build_transcript_timeline(task_id: str, filename: str) -> list:
    """Build a compact timeline of actions from a transcript JSONL file.

    Returns a list of timeline entry dicts, each with:
      kind: "tool"|"thinking"|"text"|"user"
      tool: tool name (for kind=tool)
      icon: emoji character
      label: primary display text
      meta: secondary info (line count, match count, etc.)
      is_error: bool
      detail_input: full tool input (for expansion)
      detail_output: full tool result (for expansion)
    """
    filepath = TRANSCRIPTS_FOLDER / task_id / filename
    if not filepath.exists():
        return []

    events = []
    for line in filepath.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Extract cwd from init event
    cwd = ""
    for e in events:
        if e.get("type") == "system" and e.get("subtype") == "init":
            cwd = e.get("cwd", "")
            break

    # Collect tool_use blocks and tool_result blocks, keyed by tool_use_id
    tool_uses: dict[str, dict] = {}  # id -> {name, input}
    tool_results: dict[str, dict] = {}  # id -> {text, is_error}

    # Collect messages in order (deduplicated assistant messages)
    messages = []
    seen_assistant_ids: set[str] = set()

    for e in events:
        if e.get("type") == "assistant":
            msg = e.get("message", {})
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            msg_id = msg.get("id", "")
            if msg_id and msg_id in seen_assistant_ids:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("_msg_id") == msg_id:
                        merged = messages[i]["content"]
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            bid = block.get("id")
                            btype = block.get("type")
                            if bid:
                                found = False
                                for j, mb in enumerate(merged):
                                    if isinstance(mb, dict) and mb.get("id") == bid:
                                        merged[j] = block
                                        found = True
                                        break
                                if not found:
                                    merged.append(block)
                            else:
                                found = False
                                for j, mb in enumerate(merged):
                                    if isinstance(mb, dict) and mb.get("type") == btype and not mb.get("id"):
                                        merged[j] = block
                                        found = True
                                        break
                                if not found:
                                    merged.append(block)
                        break
            else:
                if msg_id:
                    seen_assistant_ids.add(msg_id)
                messages.append({"role": "assistant", "content": list(content), "_msg_id": msg_id})
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses[block.get("id", "")] = {
                        "name": block.get("name", "unknown"),
                        "input": block.get("input", {}),
                    }
        elif e.get("type") == "user":
            msg = e.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, str):
                if content.strip():
                    messages.append({"role": "user", "text": content})
                continue
            if not isinstance(content, list):
                continue
            has_text = any(
                isinstance(b, dict) and b.get("type") == "text"
                for b in content
            )
            if has_text:
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                combined = "\n".join(text_parts)
                if combined.strip():
                    messages.append({"role": "user", "text": combined})
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tuid = block.get("tool_use_id", "")
                    rc = block.get("content", "")
                    if isinstance(rc, list):
                        rc = "\n".join(
                            b.get("text", "") for b in rc
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    elif not isinstance(rc, str):
                        rc = str(rc)
                    tool_results[tuid] = {
                        "text": rc,
                        "is_error": bool(block.get("is_error")),
                    }

    # Build timeline entries
    timeline = []
    _TOOL_ICONS = {
        "Bash": "\U0001f5a5",      # 🖥️
        "Read": "\U0001f4d6",      # 📖
        "Edit": "\u270f\ufe0f",    # ✏️
        "Write": "\U0001f4dd",     # 📝
        "Glob": "\U0001f50d",      # 🔍
        "Grep": "\U0001f50e",      # 🔎
        "Agent": "\U0001f916",     # 🤖
        "WebSearch": "\U0001f310", # 🌐
        "WebFetch": "\U0001f517",  # 🔗
        "ToolSearch": "\U0001f527",# 🔧
        "TodoWrite": "\U0001f4cb", # 📋
    }

    for msg in messages:
        if msg.get("role") == "user":
            text = msg.get("text", "")
            first_line = text.split("\n")[0][:120]
            timeline.append({
                "kind": "user",
                "icon": "\U0001f464",  # 👤
                "tool": "",
                "label": first_line,
                "meta": "",
                "is_error": False,
                "detail_input": "",
                "detail_output": text[:5000] if len(text) > 120 else "",
            })
            continue

        content = msg.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            bt = block.get("type")

            if bt == "thinking":
                thinking_text = block.get("thinking", "")
                if not thinking_text:
                    continue
                first_line = thinking_text.split("\n")[0][:120]
                timeline.append({
                    "kind": "thinking",
                    "icon": "\U0001f4ad",  # 💭
                    "tool": "",
                    "label": first_line,
                    "meta": f"{len(thinking_text)} chars",
                    "is_error": False,
                    "detail_input": "",
                    "detail_output": thinking_text[:5000],
                })

            elif bt == "text":
                text = block.get("text", "")
                if not text:
                    continue
                first_line = text.split("\n")[0][:120]
                timeline.append({
                    "kind": "text",
                    "icon": "\U0001f4ac",  # 💬
                    "tool": "",
                    "label": first_line,
                    "meta": "",
                    "is_error": False,
                    "detail_input": "",
                    "detail_output": text[:5000] if len(text) > 120 else "",
                })

            elif bt == "tool_use":
                tuid = block.get("id", "")
                name = block.get("name", "unknown")
                inp = block.get("input", {})
                result = tool_results.get(tuid, {})
                result_text = result.get("text", "")
                is_error = result.get("is_error", False)
                icon = _TOOL_ICONS.get(name, "\u2699\ufe0f")  # ⚙️

                # Tool-specific label and meta
                label = ""
                meta = ""
                detail_input = ""

                if name == "Bash":
                    label = inp.get("description", "") or inp.get("command", "")[:80]
                    detail_input = inp.get("command", "")
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "Read":
                    fp = _shorten_path(inp.get("file_path", ""), cwd)
                    meta_parts = []
                    if inp.get("offset") or inp.get("limit"):
                        if inp.get("offset") and inp.get("limit"):
                            meta_parts.append(f"lines {inp['offset']}-{inp['offset']+inp['limit']}")
                        elif inp.get("limit"):
                            meta_parts.append(f"{inp['limit']} lines")
                    result_summary = _summarize_tool_result(name, result_text, is_error)
                    if result_summary and not meta_parts:
                        meta_parts.append(result_summary)
                    label = fp
                    meta = ", ".join(meta_parts)
                elif name == "Edit":
                    fp = _shorten_path(inp.get("file_path", ""), cwd)
                    old_len = len(inp.get("old_string", ""))
                    new_len = len(inp.get("new_string", ""))
                    label = fp
                    if inp.get("replace_all"):
                        meta = f"replace all ({old_len}\u2192{new_len} chars)"
                    else:
                        meta = f"{old_len}\u2192{new_len} chars"
                    detail_input = f"--- old ({old_len} chars) ---\n{inp.get('old_string', '')}\n\n+++ new ({new_len} chars) +++\n{inp.get('new_string', '')}"
                elif name == "Write":
                    fp = _shorten_path(inp.get("file_path", ""), cwd)
                    content_len = len(inp.get("content", ""))
                    label = fp
                    meta = f"{content_len} chars"
                    detail_input = inp.get("content", "")[:3000]
                elif name == "Glob":
                    label = inp.get("pattern", "")
                    if inp.get("path"):
                        label += f" in {_shorten_path(inp['path'], cwd)}"
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "Grep":
                    pat = inp.get("pattern", "")
                    path = _shorten_path(inp.get("path", ""), cwd)
                    label = f"'{pat}'"
                    if path:
                        label += f" in {path}"
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "Agent":
                    label = inp.get("description", "")
                    st = inp.get("subagent_type", "")
                    if st:
                        label = f"[{st}] {label}"
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "WebSearch":
                    label = inp.get("query", "")
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "WebFetch":
                    url = inp.get("url", "")
                    # Shorten URL: strip scheme, truncate
                    url_short = re.sub(r'^https?://(www\.)?', '', url)
                    if len(url_short) > 60:
                        url_short = url_short[:57] + "..."
                    label = url_short
                    meta = _summarize_tool_result(name, result_text, is_error)
                elif name == "ToolSearch":
                    continue  # internal plumbing, skip in timeline
                elif name == "TodoWrite":
                    continue  # internal plumbing, skip in timeline
                else:
                    label = json.dumps(inp)[:80]
                    meta = _summarize_tool_result(name, result_text, is_error)

                if not detail_input:
                    detail_input = json.dumps(inp, indent=2)

                # Truncate detail output
                detail_output = result_text[:5000] if result_text else ""

                timeline.append({
                    "kind": "tool",
                    "icon": icon,
                    "tool": name,
                    "label": label,
                    "meta": meta,
                    "is_error": is_error,
                    "detail_input": detail_input,
                    "detail_output": detail_output,
                })

    return timeline


# ──────────────────────────────────────────────────────────────────────────────
# HTTP server
# ──────────────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    page_title: str = "tl0 Task Viewer"
    header_bg: str = "#111827"
    favicon_svg: str = _build_favicon_svg("#111827")
    code_repo: str = ""
    github_repo_url: str = ""

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            rendered = HTML.replace('{{PAGE_TITLE}}', html.escape(self.page_title)) \
                          .replace('{{HEADER_BG}}', self.header_bg) \
                          .replace('{{GITHUB_REPO_URL}}', self.github_repo_url) \
                          .replace('{{SHARED_MODAL_CSS}}', SHARED_MODAL_CSS) \
                          .replace('{{SHARED_MODAL_JS}}', SHARED_MODAL_JS)
            body = rendered.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/favicon.svg':
            body = self.favicon_svg.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/tasks':
            from tl0.common import _get_index
            tasks = _get_index().get_all_tasks()
            body  = json.dumps(tasks).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path.startswith('/api/loop-log/'):
            task_id = path.split('/')[-1]
            log_path = TRANSCRIPTS_FOLDER / task_id / 'loop.log'
            if log_path.exists():
                body = log_path.read_text().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        elif path.startswith('/api/transcript-messages/'):
            parts = path.split('/')
            # /api/transcript-messages/<task_id>/<filename>
            if len(parts) >= 5:
                task_id = parts[3]
                filename = parts[4]
                try:
                    messages = _build_transcript_messages(task_id, filename)
                    body = json.dumps(messages).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    err = json.dumps({"error": str(exc), "task_id": task_id, "filename": filename}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
            else:
                err = json.dumps({"error": "Bad request", "path": path}).encode('utf-8')
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(err)))
                self.end_headers()
                self.wfile.write(err)

        elif path.startswith('/api/transcript-timeline/'):
            parts = path.split('/')
            # /api/transcript-timeline/<task_id>/<filename>
            if len(parts) >= 5:
                task_id = parts[3]
                filename = parts[4]
                try:
                    timeline = _build_transcript_timeline(task_id, filename)
                    body = json.dumps(timeline).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    err = json.dumps({"error": str(exc), "task_id": task_id, "filename": filename}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
            else:
                err = json.dumps({"error": "Bad request", "path": path}).encode('utf-8')
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(err)))
                self.end_headers()
                self.wfile.write(err)

        elif path.startswith('/api/transcript-raw/'):
            parts = path.split('/')
            # /api/transcript-raw/<task_id>/<filename>
            if len(parts) >= 5:
                task_id = parts[3]
                filename = parts[4]
                try:
                    filepath = TRANSCRIPTS_FOLDER / task_id / filename
                    events = []
                    if filepath.exists():
                        for line in filepath.read_text().splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                events.append({"type": "parse_error", "raw": line[:500]})
                    body = json.dumps(events).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    err = json.dumps({"error": str(exc)}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
            else:
                err = json.dumps({"error": "Bad request"}).encode('utf-8')
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(err)))
                self.end_headers()
                self.wfile.write(err)

        elif path.startswith('/api/diff-stat/'):
            sha = path.split('/')[-1]
            if not re.fullmatch(r'[0-9a-fA-F]{6,40}', sha):
                self.send_response(400)
                self.end_headers()
                return
            if not self.code_repo:
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

        elif path.startswith('/api/diff/'):
            sha = path.split('/')[-1]
            # Validate SHA is hex only (prevent command injection)
            if not re.fullmatch(r'[0-9a-fA-F]{6,40}', sha):
                self.send_response(400)
                self.end_headers()
                return
            if not self.code_repo:
                self.send_response(500)
                body = b'Code repo not resolved'
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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
            diff_text = diff_text.replace('\r\n', '\n').replace('\r', '\n')
            body = diff_text.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def _respond_json(self, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path

        # POST /api/tasks/<id>/delete  — body: {"include_children": bool}
        m = re.fullmatch(r'/api/tasks/([0-9a-fA-F-]{32,36})/delete', path)
        if m:
            task_id = m.group(1)
            try:
                length = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(length) or b'{}')
                include_children = bool(payload.get('include_children', False))
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Invalid JSON body')
                return

            try:
                all_tasks = load_all_tasks()
                task_by_id = {t['id']: t for t in all_tasks}

                if task_id not in task_by_id:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'Task not found')
                    return

                # Collect IDs to delete via BFS over created_by relationships
                ids_to_delete = set()
                queue = [task_id]
                while queue:
                    current = queue.pop()
                    if current in ids_to_delete:
                        continue
                    ids_to_delete.add(current)
                    if include_children:
                        for t in all_tasks:
                            if t.get('created_by') == current and t['id'] not in ids_to_delete:
                                queue.append(t['id'])

                # Delete task files
                for tid in ids_to_delete:
                    p = TASKS_FOLDER / f"{tid}.json"
                    if p.exists():
                        p.unlink()

                # Update remaining tasks: strip deleted refs from blocked_by and created_by
                for t in all_tasks:
                    if t['id'] in ids_to_delete:
                        continue
                    changed = False
                    orig_blocked = t.get('blocked_by', [])
                    new_blocked = [b for b in orig_blocked if b not in ids_to_delete]
                    if new_blocked != orig_blocked:
                        t['blocked_by'] = new_blocked
                        changed = True
                    if t.get('created_by') in ids_to_delete:
                        t['created_by'] = None
                        changed = True
                    if changed:
                        path_t = TASKS_FOLDER / f"{t['id']}.json"
                        with open(path_t, 'w') as f:
                            json.dump(t, f, indent=2)
                            f.write('\n')

                title = task_by_id[task_id].get('title', task_id)[:60]
                suffix = f' (+{len(ids_to_delete)-1} children)' if len(ids_to_delete) > 1 else ''
                git_commit(f'Delete task: {title}{suffix}')

                body = json.dumps({'ok': True, 'deleted': list(ids_to_delete)}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):  # suppress access log noise
        pass


def _find_free_port() -> int:
    """Ask the OS for a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Open the task viewer in your browser')
    parser.add_argument('--port', type=int, default=0,
                        help='Local port to serve on (default: random free port)')
    parser.add_argument('--no-open', action='store_true',
                        help="Don't auto-open the browser")
    args = parser.parse_args(argv)

    port = args.port or _find_free_port()

    # Derive page title from the current directory name
    dir_name = Path.cwd().name
    page_title = f"{dir_name} — tl0 Task Viewer"

    # Load config for optional viewer_color
    config = load_config()
    header_bg = config.get("viewer_color", "#111827")

    # Resolve code repo path and GitHub URL
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
            # Convert git@github.com:user/repo.git or https://github.com/user/repo.git to https URL
            m = re.match(r'git@github\.com:(.+?)(?:\.git)?$', remote_url)
            if m:
                github_repo_url = f'https://github.com/{m.group(1)}'
            else:
                m = re.match(r'https://github\.com/(.+?)(?:\.git)?$', remote_url)
                if m:
                    github_repo_url = f'https://github.com/{m.group(1)}'
        except Exception:
            pass

    # Configure handler with dynamic values
    Handler.page_title = page_title
    Handler.header_bg = header_bg
    Handler.favicon_svg = _build_favicon_svg(header_bg)
    Handler.code_repo = code_repo
    Handler.github_repo_url = github_repo_url

    server = HTTPServer(('127.0.0.1', port), Handler)
    url    = f'http://localhost:{port}'

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    print(f'Task viewer → {url}  (Ctrl+C to stop)')

    def _request_shutdown(signum, frame):
        server._BaseServer__shutdown_request = True
        # Next signal should force-exit immediately
        signal.signal(signal.SIGINT, lambda s, f: os._exit(1))
        signal.signal(signal.SIGTERM, lambda s, f: os._exit(1))
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print('\nStopped.')


if __name__ == '__main__':
    main()
