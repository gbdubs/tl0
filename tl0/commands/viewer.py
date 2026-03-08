#!/usr/bin/env python3
"""Open a web-based task viewer in the default browser.

Usage:
    python3 util/viewer.py [--port PORT] [--no-open]
"""

import argparse
import html
import json
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
.log-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.45);
  z-index: 1000; display: flex; align-items: center; justify-content: center;
}
.log-panel {
  background: #1e1e1e; color: #d4d4d4; border-radius: 12px;
  width: min(90vw, 900px); max-height: 85vh; display: flex; flex-direction: column;
  box-shadow: 0 25px 50px rgba(0,0,0,.5);
}
.log-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #333; flex-shrink: 0;
}
.log-panel-header h3 { color: #e5e7eb; font-size: 14px; font-weight: 600; margin: 0; }
.log-panel-close {
  background: none; border: none; color: #9ca3af; font-size: 20px;
  cursor: pointer; padding: 4px 8px; border-radius: 4px;
}
.log-panel-close:hover { background: #333; color: white; }
.log-panel-body {
  flex: 1; overflow: auto; padding: 12px 16px;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
  line-height: 1.6; white-space: pre-wrap; word-break: break-all;
}
.log-btn {
  padding: 3px 8px; border-radius: 5px; cursor: pointer;
  background: transparent; border: 1px solid var(--border); color: var(--text);
  font-size: 11px; transition: background 0.1s;
}
.log-btn:hover { background: var(--hover-bg, #f3f4f6); }

/* ── Diff viewer ──────────────────────────────────────────── */
.diff-panel {
  display: flex; flex-direction: column;
  background: #ffffff; color: var(--text);
}
.diff-panel .log-panel-header { border-bottom: 1px solid var(--border); }
.diff-panel .log-panel-header h3 { color: var(--text); }
.diff-panel .log-panel-close { color: var(--text-muted); }
.diff-panel .log-panel-close:hover { background: #f3f4f6; color: var(--text); }
.diff-panel .log-panel-body { padding: 0; overflow: auto; flex: 1; background: #ffffff; }
.diff-file { border-bottom: 1px solid var(--border); }
.diff-file-header {
  padding: 4px 10px; background: #f7f7f7; border-bottom: 1px solid var(--border);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 12px; font-weight: 600; color: var(--text);
  display: flex; align-items: center; gap: 6px;
}
.diff-file-header .diff-tag {
  font-size: 10px; font-weight: 600; padding: 1px 5px; border-radius: 3px;
}
.diff-tag-added { background: #dfd; color: #1a7f37; }
.diff-tag-deleted { background: #fee; color: #cf222e; }
.diff-tag-modified { background: #fff8c5; color: #9a6700; }
.diff-code {
  margin: 0; padding: 0; font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px; line-height: 1.45; overflow-x: auto;
}
.diff-code table { border-collapse: collapse; width: 100%; }
.diff-code td { padding: 0; vertical-align: top; white-space: pre; }
.diff-code .diff-ln {
  width: 1px; min-width: 40px; padding: 0 8px; text-align: right;
  color: rgba(0,0,0,0.3); border-right: 1px solid #eee; user-select: none;
  background: #fafafa;
}
.diff-code .diff-text { padding: 0 10px; }
.diff-line-add { background: #e6ffec; }
.diff-line-add .diff-ln { background: #ccffd8; }
.diff-line-del { background: #ffebe9; }
.diff-line-del .diff-ln { background: #ffd7d5; }
.diff-line-hunk { background: #f1f8ff; color: rgba(0,0,0,0.4); }
.diff-line-hunk .diff-ln { background: #ddf4ff; }
.sha-badge {
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
  background: #f3f4f6; border: 1px solid var(--border); border-radius: 4px;
  padding: 2px 8px; cursor: pointer; color: var(--accent);
  transition: background 0.1s;
}
.sha-badge:hover { background: #e5e7eb; }
.sha-github-link {
  font-size: 11px; color: var(--text-muted); margin-left: 8px;
  text-decoration: none;
}
.sha-github-link:hover { color: var(--accent); text-decoration: underline; }

/* ── Conversation viewer ──────────────────────────────────── */
.conv-panel {
  background: white; color: var(--text); border-radius: 12px;
  width: min(92vw, 1000px); max-height: 90vh; display: flex; flex-direction: column;
  box-shadow: 0 25px 50px rgba(0,0,0,.5);
}
.conv-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.conv-panel-header h3 { font-size: 14px; font-weight: 600; margin: 0; }
.conv-tab-bar {
  display: flex; gap: 0; border-bottom: 1px solid var(--border); flex-shrink: 0;
  padding: 0 16px;
}
.conv-tab {
  padding: 8px 16px; font-size: 13px; font-weight: 500; cursor: pointer;
  border-bottom: 2px solid transparent; color: var(--muted); background: none;
  border-top: none; border-left: none; border-right: none;
}
.conv-tab:hover { color: var(--text); }
.conv-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.conv-panel-body { flex: 1; overflow: auto; padding: 16px; }
.conv-tab-content { display: none; }
.conv-tab-content.active { display: block; }
.conv-raw-json {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; font-size: 12px;
  line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  color: var(--text);
}
.conv-raw-event {
  margin-bottom: 4px; padding: 8px 10px; background: #f9fafb;
  border: 1px solid var(--border); border-radius: 6px;
  cursor: pointer; font-size: 12px;
}
.conv-raw-event:hover { background: #f0f4f8; }
.conv-raw-event-summary {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace; font-size: 12px;
  color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.conv-raw-event-body {
  display: none; margin-top: 8px; font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  font-size: 12px; white-space: pre-wrap; word-break: break-word;
  max-height: 400px; overflow: auto;
}
.conv-msg {
  margin-bottom: 12px; border-radius: 8px; padding: 10px 14px;
  font-size: 13px; line-height: 1.6;
}
.conv-msg.user {
  background: #f9fafb; border: 1px solid var(--border);
}
.conv-msg-role {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 6px;
}
.conv-msg.user .conv-msg-role { color: #6b7280; }
.conv-msg-text { white-space: pre-wrap; word-break: break-word; }
.conv-tool-use {
  background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px;
  padding: 8px 10px; margin-top: 6px; font-size: 12px;
}
.conv-tool-name {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-weight: 600; color: #0369a1; font-size: 12px;
}
.conv-tool-input {
  margin-top: 4px; font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; line-height: 1.5; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 200px; overflow-y: auto;
  background: white; border-radius: 4px; padding: 6px 8px;
}
.conv-tool-result {
  background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px;
  padding: 8px 10px; margin-top: 6px; font-size: 12px;
}
.conv-tool-result-header {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-weight: 600; color: #15803d; font-size: 11px; margin-bottom: 4px;
}
.conv-tool-result-body {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; line-height: 1.5; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 200px; overflow-y: auto;
  background: white; border-radius: 4px; padding: 6px 8px;
}
.conv-tool-toggle {
  font-size: 11px; color: var(--accent); cursor: pointer;
  margin-top: 4px; user-select: none;
}
.conv-tool-toggle:hover { text-decoration: underline; }
.conv-thinking {
  background: #fef9c3; border: 1px solid #fde68a; border-radius: 6px;
  padding: 8px 10px; margin-top: 6px; font-size: 12px;
}
.conv-thinking-label {
  font-size: 11px; font-weight: 600; color: #92400e;
}
.conv-thinking-preview {
  font-weight: 400; color: #78716c; font-style: italic;
}
.conv-thinking-body {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; line-height: 1.5; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 300px; overflow-y: auto;
  background: #fffbeb; border-radius: 4px; padding: 6px 8px; margin-top: 4px;
}
.conv-unknown-block {
  background: #fce4ec; border: 1px solid #f48fb1; border-radius: 6px;
  padding: 8px 10px; margin-top: 6px; font-size: 12px;
}
.conv-unknown-block-label {
  font-size: 11px; font-weight: 600; color: #880e4f;
}
.conv-unknown-block-label code {
  background: #f8bbd0; padding: 1px 4px; border-radius: 3px; font-size: 11px;
}
.conv-unknown-block-body {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; line-height: 1.5; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 300px; overflow-y: auto;
  background: #fce4ec; border-radius: 4px; padding: 6px 8px; margin-top: 4px;
}
.conv-user-full {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px; line-height: 1.5; color: #374151;
  white-space: pre-wrap; word-break: break-word;
  max-height: 300px; overflow-y: auto;
  background: white; border-radius: 4px; padding: 6px 8px; margin-top: 4px;
}
.conv-user-preview { color: #6b7280; }
.conv-tool-pair {
  border: 1px solid var(--border); border-radius: 6px;
  margin-top: 6px; overflow: hidden;
}
.conv-tool-pair .conv-tool-use {
  border: none; border-radius: 0; margin-top: 0;
  border-bottom: 1px solid #e5e7eb;
}
.conv-tool-result-inline {
  border: none; border-radius: 0; margin-top: 0;
  background: #f0fdf4;
}
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

<script>window.__GITHUB_REPO_URL__ = '{{GITHUB_REPO_URL}}';window.__SUPERVISOR_ENABLED__ = false;window.__SUPERVISOR_API_BASE__ = '';</script>
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

// ── Transcript cache & helpers ────────────────────────────────
const _transcriptCache = {};
async function fetchTranscript(taskId) {
  if (_transcriptCache[taskId]) return _transcriptCache[taskId];
  try {
    const res = await fetch('/api/transcripts/' + taskId);
    if (!res.ok) return null;
    const data = await res.json();
    _transcriptCache[taskId] = data;
    return data;
  } catch (_) { return null; }
}

async function showInvocationDetail(taskId, filename) {
  try {
    const res = await fetch(`/api/transcript-messages/${taskId}/${filename}`);
    if (!res.ok) {
      const errText = await res.text().catch(() => res.statusText);
      console.error(`Transcript load failed (${res.status}): ${errText}`);
      alert(`Failed to load transcript: ${res.status} ${res.statusText}`);
      return;
    }
    const messages = await res.json();
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    let body = '';
    let blockCounter = 0;
    // Pre-index tool results by tool_use_id so we can render them inline
    const toolResults = {};
    messages.forEach(msg => {
      if (msg.role === 'tool_result' && msg.tool_use_id) {
        toolResults[msg.tool_use_id] = msg;
      }
    });
    function renderToolResult(toolUseId) {
      const r = toolResults[toolUseId];
      if (!r) return '';
      const resultId = 'tr-' + toolUseId;
      let h = `<div class="conv-tool-result conv-tool-result-inline">`;
      h += `<div class="conv-tool-result-body" id="${resultId}" style="display:none">${esc(r.text)}</div>`;
      h += `<div class="conv-tool-toggle" onclick="toggleConvEl('${resultId}')">Show output</div>`;
      h += `</div>`;
      return h;
    }
    messages.forEach(msg => {
      if (msg.role === 'user') {
        body += `<div class="conv-msg user"><div class="conv-msg-role">User</div>`;
        const userTextId = 'ut-' + (blockCounter++);
        const preview = (msg.text || '').split('\\n')[0].substring(0, 120);
        body += `<div class="conv-msg-text conv-user-preview">${esc(preview)}</div>`;
        body += `<div class="conv-user-full" id="${userTextId}" style="display:none">${esc(msg.text)}</div>`;
        body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${userTextId}')">Show full message</div>`;
        body += `</div>`;
      } else if (msg.role === 'assistant') {
        (msg.content || []).forEach(block => {
          if (block.type === 'thinking' && block.thinking) {
            const thinkId = 'th-' + (blockCounter++);
            const preview = block.thinking.split('\\n')[0].substring(0, 100);
            body += `<div class="conv-thinking">`;
            body += `<div class="conv-thinking-label">Thinking: <span class="conv-thinking-preview">${esc(preview)}</span></div>`;
            body += `<div class="conv-thinking-body" id="${thinkId}" style="display:none">${esc(block.thinking)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${thinkId}')">Show thinking</div>`;
            body += `</div>`;
          } else if (block.type === 'text' && block.text) {
            body += `<div class="conv-msg-text">${esc(block.text)}</div>`;
          } else if (block.type === 'tool_use') {
            const inputStr = JSON.stringify(block.input, null, 2);
            const inputId = 'ti-' + block.id;
            body += `<div class="conv-tool-pair">`;
            body += `<div class="conv-tool-use">`;
            body += `<span class="conv-tool-name">${esc(block.name)}</span>`;
            body += `<div class="conv-tool-input" id="${inputId}" style="display:none">${esc(inputStr)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${inputId}')">Show input</div>`;
            body += `</div>`;
            body += renderToolResult(block.id);
            body += `</div>`;
          } else {
            const unknownId = 'unk-' + (blockCounter++);
            const raw = JSON.stringify(block, null, 2);
            body += `<div class="conv-unknown-block">`;
            body += `<div class="conv-unknown-block-label">Unhandled block: <code>${esc(block.type || 'unknown')}</code></div>`;
            body += `<div class="conv-unknown-block-body" id="${unknownId}" style="display:none">${esc(raw)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${unknownId}')">Show raw</div>`;
            body += `</div>`;
          }
        });
      }
      // tool_result messages are rendered inline above, skip standalone rendering
    });
    overlay.innerHTML = `<div class="conv-panel">
      <div class="conv-panel-header">
        <h3>Execution — ${esc(filename)}</h3>
        <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">✕</button>
      </div>
      <div class="conv-tab-bar">
        <button class="conv-tab active" data-tab="conversation" onclick="switchConvTab(this)">Conversation</button>
        <button class="conv-tab" data-tab="raw-json" onclick="switchConvTab(this)">Raw JSON</button>
      </div>
      <div class="conv-panel-body">
        <div class="conv-tab-content active" id="tab-conversation">${body}</div>
        <div class="conv-tab-content" id="tab-raw-json"><div class="conv-raw-json">Loading…</div></div>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    // Lazy-load raw JSON when that tab is first activated
    overlay._rawLoaded = false;
    overlay._taskId = taskId;
    overlay._filename = filename;
  } catch (_) {}
}

function switchConvTab(btn) {
  const panel = btn.closest('.conv-panel');
  panel.querySelectorAll('.conv-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const tabName = btn.dataset.tab;
  panel.querySelectorAll('.conv-tab-content').forEach(c => c.classList.remove('active'));
  panel.querySelector('#tab-' + tabName).classList.add('active');
  if (tabName === 'raw-json') {
    const overlay = panel.closest('.log-overlay');
    if (!overlay._rawLoaded) {
      overlay._rawLoaded = true;
      loadRawJson(overlay._taskId, overlay._filename, panel.querySelector('#tab-raw-json'));
    }
  }
}

async function loadRawJson(taskId, filename, container) {
  try {
    const res = await fetch(`/api/transcript-raw/${taskId}/${filename}`);
    if (!res.ok) { container.innerHTML = '<div class="conv-raw-json">Failed to load raw JSON.</div>'; return; }
    const events = await res.json();
    let html = '';
    events.forEach((evt, i) => {
      const evtType = evt.type || 'unknown';
      const summary = JSON.stringify(evt).substring(0, 150);
      const full = JSON.stringify(evt, null, 2);
      const bodyId = 'raw-evt-' + i;
      html += `<div class="conv-raw-event" onclick="toggleConvEl('${bodyId}')">`;
      html += `<div class="conv-raw-event-summary"><strong>${i}</strong> &nbsp; <code>${esc(evtType)}</code> &nbsp; ${esc(summary)}</div>`;
      html += `<div class="conv-raw-event-body" id="${bodyId}">${esc(full)}</div>`;
      html += `</div>`;
    });
    container.innerHTML = `<div class="conv-raw-json">${html}</div>`;
  } catch (e) {
    container.innerHTML = '<div class="conv-raw-json">Error loading raw JSON.</div>';
  }
}

function toggleConvEl(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const toggle = el.nextElementSibling || el.parentElement.querySelector('.conv-tool-toggle');
  if (el.style.display === 'none') {
    el.style.display = 'block';
    if (toggle && toggle.classList.contains('conv-tool-toggle')) toggle.textContent = toggle.textContent.replace('Show', 'Hide');
  } else {
    el.style.display = 'none';
    if (toggle && toggle.classList.contains('conv-tool-toggle')) toggle.textContent = toggle.textContent.replace('Hide', 'Show');
  }
}

async function showLoopLog(taskId) {
  try {
    const res = await fetch('/api/loop-log/' + taskId);
    if (!res.ok) return;
    const text = await res.text();
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="log-panel">
      <div class="log-panel-header">
        <h3>Loop Log — ${taskId.slice(0,8)}</h3>
        <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">✕</button>
      </div>
      <div class="log-panel-body">${esc(text)}</div>
    </div>`;
    document.body.appendChild(overlay);
  } catch (_) {}
}

function renderDiffHtml(diffText) {
  const lines = diffText.split('\n');
  let html = '';
  let currentFile = null;
  let fileLines = [];
  function flushFile() {
    if (!currentFile) return;
    const tag = currentFile.tag;
    const tagCls = tag === 'Added' ? 'diff-tag-added' : tag === 'Deleted' ? 'diff-tag-deleted' : 'diff-tag-modified';
    html += `<div class="diff-file"><div class="diff-file-header"><span>${esc(currentFile.name)}</span><span class="diff-tag ${tagCls}">${tag}</span></div>`;
    html += '<div class="diff-code"><table>';
    for (const fl of fileLines) {
      const cls = fl.type === '+' ? 'diff-line-add' : fl.type === '-' ? 'diff-line-del' : fl.type === '@' ? 'diff-line-hunk' : '';
      const ln = fl.ln !== null ? fl.ln : '';
      html += `<tr class="${cls}"><td class="diff-ln">${ln}</td><td class="diff-text">${esc(fl.text)}</td></tr>`;
    }
    html += '</table></div></div>';
    fileLines = [];
  }
  let newLn = 0;
  for (const line of lines) {
    if (line.startsWith('diff --git ')) {
      flushFile();
      const m = line.match(/b\/(.+)$/);
      currentFile = { name: m ? m[1] : '?', tag: 'Modified' };
    } else if (line.startsWith('new file')) {
      if (currentFile) currentFile.tag = 'Added';
    } else if (line.startsWith('deleted file')) {
      if (currentFile) currentFile.tag = 'Deleted';
    } else if (line.startsWith('@@')) {
      const m = line.match(/\+(\d+)/);
      newLn = m ? parseInt(m[1]) : 1;
      fileLines.push({ type: '@', ln: null, text: line });
    } else if (line.startsWith('+') && !line.startsWith('+++')) {
      fileLines.push({ type: '+', ln: newLn++, text: line.slice(1) });
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      fileLines.push({ type: '-', ln: null, text: line.slice(1) });
    } else if (currentFile && !line.startsWith('\\') && !line.startsWith('index ') && !line.startsWith('---') && !line.startsWith('+++')) {
      if (line.length > 0 || fileLines.length > 0) {
        fileLines.push({ type: ' ', ln: newLn++, text: line.startsWith(' ') ? line.slice(1) : line });
      }
    }
  }
  flushFile();
  return html;
}

async function showDiff(sha) {
  try {
    const res = await fetch('/api/diff/' + encodeURIComponent(sha));
    if (!res.ok) { alert('Failed to load diff'); return; }
    const text = await res.text();
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="log-panel diff-panel" style="width:min(95vw,1400px);max-height:90vh">
      <div class="log-panel-header">
        <h3>Diff — ${esc(sha.slice(0,8))}</h3>
        <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">✕</button>
      </div>
      <div class="log-panel-body">${renderDiffHtml(text)}</div>
    </div>`;
    document.body.appendChild(overlay);
  } catch (_) {}
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
  _allTranscripts = null; // invalidate transcript cache
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

  // Execution summary (loaded async)
  html += `<div id="exec-section-${task.id.slice(0,8)}"></div>`;
  if (task.status === 'claimed' || task.status === 'done') {
    const taskEvents = task.events && task.events.length ? task.events : null;
    fetchTranscript(task.id).then(tx => {
      const el = document.getElementById('exec-section-' + task.id.slice(0,8));
      if (!el || !tx || !tx.has_transcript) return;
      let s = '<div class="d-section"><div class="d-label" onclick="toggleSection(this)"><span>Execution</span></div>';
      s += '<div class="d-section-body">';
      if (taskEvents) s += renderEventTimeline(taskEvents);
      s += renderExecSection(tx, task.id);
      s += '</div></div>';
      el.innerHTML = s;
    });
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

function inferStatusAt(task, t) {
  if (t < new Date(task.created_at).getTime()) return null;
  if (task.completed_at && t >= new Date(task.completed_at).getTime()) return 'done';
  if (task.claimed_at && t >= new Date(task.claimed_at).getTime()) {
    // Use current status for claimed/in-progress/stuck distinction
    if (task.status === 'stuck') return 'stuck';
    if (task.status === 'in-progress' || task.status === 'done') return 'in-progress';
    return 'claimed';
  }
  return 'pending';
}

function buildTimeline(tasks) {
  // Collect all event timestamps
  const times = new Set();
  tasks.forEach(t => {
    if (t.created_at)   times.add(new Date(t.created_at).getTime());
    if (t.claimed_at)   times.add(new Date(t.claimed_at).getTime());
    if (t.completed_at) times.add(new Date(t.completed_at).getTime());
  });
  const sorted = [...times].filter(t => !isNaN(t)).sort((a, b) => a - b);
  if (sorted.length === 0) return [];

  return sorted.map(t => {
    const counts = { pending: 0, claimed: 0, 'in-progress': 0, done: 0, stuck: 0 };
    tasks.forEach(task => {
      const s = inferStatusAt(task, t);
      if (s) counts[s]++;
    });
    return { time: t, ...counts };
  });
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

function _buildStageMetrics(tasks, txMap) {
  const stageMap = {};
  for (const task of tasks) {
    const stageTag = (task.tags || []).find(t => t.startsWith('stage:'));
    const stage = stageTag ? stageTag.replace('stage:', '') : '(no stage)';
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
    const tx = txMap[task.id];
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
    if (a.stage === '(no stage)') return 1;
    if (b.stage === '(no stage)') return -1;
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
  const padL = 4, padR = 12;
  const w = plotW - padL - padR;
  const cy = plotH * 0.6;
  const r  = 4;
  function vx(v) { return padL + (globalMax > 0 ? (v / globalMax) * w : 0); }
  // Bucket by rounded pixel for jitter
  const buckets = {};
  let dots = '';
  for (const v of values) {
    const x = Math.round(vx(v));
    buckets[x] = (buckets[x] || 0);
    const jitter = buckets[x] * (r * 2.2);
    const y = Math.max(r + 1, cy - jitter);
    buckets[x]++;
    dots += `<circle cx="${x}" cy="${y}" r="${r}" fill="${color}" opacity="0.72"><title>${fmtFn ? fmtFn(v) : v}</title></circle>`;
  }
  const baseline = `<line x1="${padL}" y1="${cy + r + 2}" x2="${plotW - padR}" y2="${cy + r + 2}" stroke="#e5e7eb" stroke-width="1"/>`;
  const avg  = values.reduce((s, v) => s + v, 0) / values.length;
  const avgX = vx(avg);
  const avgLine = `<line x1="${avgX}" y1="${cy - r - 2}" x2="${avgX}" y2="${cy + r + 2}" stroke="${color}" stroke-width="2.5" opacity="0.9"/>`;
  return `<svg width="${plotW}" height="${plotH}">${baseline}${avgLine}${dots}</svg>`;
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

async function renderReport() {
  if (state.view !== 'report') return;
  const contentEl = document.getElementById('report-content');
  const loadingEl = document.getElementById('report-loading');
  if (!contentEl) return;

  if (!_allTranscripts) {
    loadingEl.style.display = '';
    contentEl.innerHTML = '';
    try {
      const res = await fetch('/api/all-transcripts');
      _allTranscripts = await res.json();
    } catch (_) { _allTranscripts = {}; }
    loadingEl.style.display = 'none';
  }

  const tasks     = getFiltered();
  const stageData = _buildStageMetrics(tasks, _allTranscripts);

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

// ── Table view ───────────────────────────────────────────────
let _allTranscripts = null;
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
  { key: 'Edit',             label: 'Edit',            type: 'tool',   default: true },
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
      fetch('/api/diff-stat/' + encodeURIComponent(val))
        .then(r => r.json())
        .then(d => {
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

async function renderTable() {
  const tableEl = document.getElementById('task-table');
  const tbody = tableEl.querySelector('tbody');
  const thead = tableEl.querySelector('thead tr');

  // Load transcript data if not cached
  if (!_allTranscripts) {
    tbody.innerHTML = `<tr><td colspan="99" id="table-loading">Loading transcript data…</td></tr>`;
    thead.innerHTML = '';
    try {
      const res = await fetch('/api/all-transcripts');
      _allTranscripts = await res.json();
    } catch (_) {
      _allTranscripts = {};
    }
  }

  const filtered = getFiltered();
  const visCols = TABLE_COLUMNS.filter(c => _visibleCols.has(c.key));

  // Build rows with sort values
  let rows = filtered.map(task => {
    const ts = _allTranscripts[task.id] || null;
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
    const ts = _allTranscripts ? (_allTranscripts[taskId] || null) : null;
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
            # Deduplicate: Claude Code streams partial assistant messages,
            # so the same message ID appears multiple times. We keep the last one.
            msg_id = msg.get("id", "")
            if msg_id and msg_id in seen_assistant_ids:
                # Replace the last assistant entry that has the same id
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("_msg_id") == msg_id:
                        messages[i] = {"role": "assistant", "content": content, "_msg_id": msg_id}
                        break
            else:
                if msg_id:
                    seen_assistant_ids.add(msg_id)
                messages.append({"role": "assistant", "content": content, "_msg_id": msg_id})

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


def _build_transcript_summary(task_id: str) -> dict:
    """Build a JSON-serialisable summary of transcript data for a task."""
    transcript_dir = TRANSCRIPTS_FOLDER / task_id
    if not transcript_dir.is_dir():
        return {"has_transcript": False}

    loop_log = transcript_dir / "loop.log"
    jsonl_files = sorted(transcript_dir.glob("*.jsonl"))

    invocations = []
    total_cost = 0.0
    total_duration = 0

    for jf in jsonl_files:
        events = []
        for line in jf.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        inv: dict = {"file": jf.name, "num_events": len(events)}

        # Count tool usage from assistant events; count tool errors from user events
        tool_counts: dict[str, int] = {}
        tool_error_count = 0
        for e in events:
            if e.get("type") == "assistant" and isinstance(e.get("message", {}).get("content"), list):
                for block in e["message"]["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tool_counts[name] = tool_counts.get(name, 0) + 1
            elif e.get("type") == "user" and isinstance(e.get("message", {}).get("content"), list):
                for block in e["message"]["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        if block.get("is_error"):
                            tool_error_count += 1
        if tool_counts:
            inv["tool_usage"] = tool_counts
        inv["tool_errors"] = tool_error_count

        # Extract result event data
        for e in reversed(events):
            if e.get("type") == "result":
                inv["num_turns"] = e.get("num_turns", 0)
                inv["duration_ms"] = e.get("duration_ms", 0)
                inv["cost_usd"] = e.get("total_cost_usd", 0)
                total_cost += inv["cost_usd"]
                total_duration += inv["duration_ms"]
                # Model from modelUsage
                mu = e.get("modelUsage", {})
                if mu:
                    inv["model"] = next(iter(mu), None)
                # Result preview
                result = e.get("result", "")
                if isinstance(result, list):
                    result = " ".join(
                        b.get("text", "") for b in result
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                if result:
                    inv["result_preview"] = result[:200]
                break

        invocations.append(inv)

    # Count merge-conflict resolution attempts (files named *-merge-conflict.jsonl)
    merge_conflict_count = sum(
        1 for jf in jsonl_files if "merge-conflict" in jf.name
    )

    total_tool_errors = sum(inv.get("tool_errors", 0) for inv in invocations)

    return {
        "has_transcript": True,
        "has_loop_log": loop_log.exists(),
        "loop_log_lines": len(loop_log.read_text().splitlines()) if loop_log.exists() else 0,
        "invocations": invocations,
        "total_cost_usd": total_cost,
        "total_duration_ms": total_duration,
        "merge_conflict_count": merge_conflict_count,
        "total_tool_errors": total_tool_errors,
    }


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
                          .replace('{{GITHUB_REPO_URL}}', self.github_repo_url)
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
            raw = load_all_tasks()
            # Inject derived fields so the frontend can treat them as plain properties
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
                t["source"]        = t.get("created_by") or "human"
                tasks.append(t)
            # Derive tasks_created by scanning created_by references
            for t in tasks:
                t["tasks_created"] = [o["id"] for o in tasks if o.get("created_by") == t["id"]]
            body  = json.dumps(tasks).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/all-transcripts':
            # Bulk transcript summaries for all tasks (used by table view)
            result = {}
            if TRANSCRIPTS_FOLDER.is_dir():
                for td in TRANSCRIPTS_FOLDER.iterdir():
                    if td.is_dir():
                        result[td.name] = _build_transcript_summary(td.name)
            body = json.dumps(result).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path.startswith('/api/transcripts/'):
            task_id = path.split('/')[-1]
            summary = _build_transcript_summary(task_id)
            body = json.dumps(summary).encode('utf-8')
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

    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        server.serve_forever()
    finally:
        print('\nStopped.')


if __name__ == '__main__':
    main()
