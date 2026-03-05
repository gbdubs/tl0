#!/usr/bin/env python3
"""Open a web-based task viewer in the default browser.

Usage:
    python3 util/viewer.py [--port PORT] [--no-open]
"""

import argparse
import html
import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


from tl0.common import load_all_tasks, task_status, task_claimed_by, task_last_claimed_at, task_completed_at, task_created_at
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
#search {
  width: 100%; padding: 7px 10px;
  border: 1px solid var(--border); border-radius: 6px;
  font-size: 13px; outline: none; background: #fafbfc;
}
#search:focus { border-color: var(--accent); background: white; }

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
.tag-group { margin-bottom: 8px; }
.tag-group-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--text-muted); margin-bottom: 4px;
}
.tag-chips { display: flex; flex-wrap: wrap; gap: 3px; }
.tag-chip {
  padding: 2px 7px; border-radius: 10px; cursor: pointer;
  font-size: 11px; background: #f3f4f6; color: var(--text-muted);
  border: 1px solid transparent; transition: all 0.1s;
}
.tag-chip:hover { border-color: #9ca3af; }
.tag-chip.active { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
#tag-clear {
  font-size: 10px; color: var(--accent); cursor: pointer;
  float: right; margin-top: -2px;
}
#tag-clear:hover { text-decoration: underline; }

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
  width: 14px; min-width: 14px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 9px; flex-shrink: 0; margin-top: 1px;
}
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
#detail { flex: 1; overflow-y: auto; padding: 24px 28px; }
#empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 8px;
  color: var(--text-muted);
}
#empty-state .hint { font-size: 11px; color: #9ca3af; }

.d-title { font-size: 19px; font-weight: 600; line-height: 1.4; margin-bottom: 10px; }
.d-badges { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }
.d-badge {
  padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 500;
}

.d-section {
  background: white; border: 1px solid var(--border); border-radius: 8px;
  padding: 15px 16px; margin-bottom: 14px;
}
.d-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; color: var(--text-muted); margin-bottom: 10px;
}
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
  background: #f0fdf4; border-left: 3px solid #4ade80;
  padding: 12px; border-radius: 4px; font-size: 13px;
  line-height: 1.65; color: #166534;
}
.stuck-banner {
  background: #fff1f2; border-left: 3px solid #f87171;
  padding: 10px 12px; border-radius: 4px; font-size: 12px;
  color: #be123c; margin-bottom: 14px;
}

/* ── Nav buttons ───────────────────────────────────────────── */
.nav-btn {
  width: 28px; height: 28px; border-radius: 5px; cursor: pointer;
  background: #374151; border: 1px solid #4b5563; color: #e5e7eb;
  font-size: 15px; line-height: 1; display: flex; align-items: center;
  justify-content: center; transition: background 0.1s; flex-shrink: 0;
  padding: 0;
}
.nav-btn:hover:not(:disabled) { background: #4b5563; }
.nav-btn:disabled { opacity: 0.3; cursor: default; }

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

/* Scrollbars */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #9ca3af; }
</style>
</head>
<body>

<div id="header">
  <h1>Digest Task Viewer</h1>
  <button class="nav-btn" id="nav-back" onclick="navBack()" disabled title="Back (Alt+←)">←</button>
  <button class="nav-btn" id="nav-fwd"  onclick="navFwd()"  disabled title="Forward (Alt+→)">→</button>
  <div id="stats">Loading…</div>
  <button id="refresh-btn" onclick="refresh()">↺ Refresh</button>
</div>

<div id="app">
  <aside id="sidebar">
    <div id="controls">
      <input type="text" id="search" placeholder="Search title, description, ID… (press /)" autocomplete="off" spellcheck="false">
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
      <span id="tag-clear" style="display:none" onclick="clearTags()">Clear tags</span>
    </div>

    <div id="view-row">
      <span id="result-count"></span>
      <button class="view-btn active" data-view="tree" onclick="setView('tree')">Tree</button>
      <button class="view-btn" data-view="source" onclick="setView('source')">Source</button>
      <button class="view-btn" data-view="list" onclick="setView('list')">List</button>
      <button class="view-btn" data-view="chart" onclick="setView('chart')">Chart</button>
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
</div>
<div id="chart-tooltip"></div>

<script>
// ── State ────────────────────────────────────────────────────
let allTasks = [];
let taskMap  = {};

const state = {
  selectedId:          null,
  statusFilter:        'all',
  modelFilter:         'all',
  activeTags:          [],
  search:              '',
  view:                'tree',
  expandedNodes:       new Set(),
  detailExpandedNodes: new Set(),
};

// ── Navigation history (← →) ─────────────────────────────────
const navStack = [];
let   navPos   = -1;

function pushNav(id) {
  navStack.splice(navPos + 1);   // drop any forward history
  navStack.push(id);
  navPos = navStack.length - 1;
  history.pushState({ taskId: id }, '', '#' + id);
  updateNavBtns();
}
function navBack() {
  if (navPos <= 0) return;
  navPos--;
  const id = navStack[navPos];
  history.replaceState({ taskId: id }, '', '#' + id);
  updateNavBtns();
  _activateTask(id);
}
function navFwd() {
  if (navPos >= navStack.length - 1) return;
  navPos++;
  const id = navStack[navPos];
  history.replaceState({ taskId: id }, '', '#' + id);
  updateNavBtns();
  _activateTask(id);
}
function updateNavBtns() {
  document.getElementById('nav-back').disabled = navPos <= 0;
  document.getElementById('nav-fwd').disabled  = navPos >= navStack.length - 1;
}
// Handle browser native back/forward
window.addEventListener('popstate', e => {
  const id = e.state?.taskId || location.hash.slice(1);
  if (!id || !taskMap[id]) return;
  const idx = navStack.lastIndexOf(id);
  if (idx >= 0) navPos = idx;
  updateNavBtns();
  _activateTask(id);
});

// ── localStorage persistence ─────────────────────────────────
function loadSavedState() {
  try {
    const s = JSON.parse(localStorage.getItem('digest_viewer') || '{}');
    if (s.selectedId)   state.selectedId   = s.selectedId;
    if (s.statusFilter) state.statusFilter  = s.statusFilter;
    if (s.modelFilter)  state.modelFilter   = s.modelFilter;
    if (s.activeTags)   state.activeTags    = s.activeTags;
    if (s.search)       state.search        = s.search;
    if (s.view)         state.view          = s.view;
    if (s.expandedNodes)       state.expandedNodes       = new Set(s.expandedNodes);
    if (s.detailExpandedNodes) state.detailExpandedNodes = new Set(s.detailExpandedNodes);
  } catch (_) {}
}
function persist() {
  try {
    localStorage.setItem('digest_viewer', JSON.stringify({
      selectedId:    state.selectedId,
      statusFilter:  state.statusFilter,
      modelFilter:   state.modelFilter,
      activeTags:    state.activeTags,
      search:        state.search,
      view:          state.view,
      expandedNodes:       [...state.expandedNodes],
      detailExpandedNodes: [...state.detailExpandedNodes],
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
    if (state.view === 'chart') renderChart();
    else renderTaskList();
    if (_initialLoad) {
      _initialLoad = false;
      // URL hash takes priority over localStorage on first load
      const hashId = location.hash.slice(1);
      const initId = (hashId && taskMap[hashId]) ? hashId
                   : (state.selectedId && taskMap[state.selectedId]) ? state.selectedId
                   : null;
      if (initId) {
        navStack.push(initId);
        navPos = 0;
        history.replaceState({ taskId: initId }, '', '#' + initId);
        updateNavBtns();
        _activateTask(initId);
      }
    } else if (state.selectedId && taskMap[state.selectedId]) {
      // On refresh, re-render the open task in case data changed
      renderDetail(state.selectedId);
    }
  } catch (e) {
    document.getElementById('task-list').innerHTML =
      `<div class="no-results">Failed to load tasks: ${e.message}</div>`;
  }
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

  // Rebuild keeping the clear link
  const clearEl = document.getElementById('tag-clear');
  section.innerHTML = '';
  section.appendChild(clearEl);
  clearEl.style.display = state.activeTags.length ? 'block' : 'none';

  Object.keys(groups).sort().forEach(cat => {
    const tags = Object.entries(groups[cat]).sort((a, b) => b[1] - a[1]);
    const div  = document.createElement('div');
    div.className = 'tag-group';
    div.innerHTML = `<div class="tag-group-label">${esc(cat)} <span style="font-weight:400;opacity:.5">${tags.length}</span></div><div class="tag-chips"></div>`;
    const chips = div.querySelector('.tag-chips');
    tags.forEach(([tag, count]) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip' + (state.activeTags.includes(tag) ? ' active' : '');
      chip.textContent = tag.includes(':') ? tag.split(':')[1] : tag;
      chip.title = `${tag} (${count} tasks)`;
      chip.onclick = () => toggleTag(tag);
      chips.appendChild(chip);
    });
    section.appendChild(div);
  });
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
function setView(v) {
  state.view = v;
  persist();
  document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  const isChart = v === 'chart';
  document.getElementById('task-list-container').style.display = isChart ? 'none' : '';
  document.getElementById('detail').style.display = isChart ? 'none' : '';
  document.getElementById('chart-container').classList.toggle('visible', isChart);
  if (isChart) renderChart();
  else renderTaskList();
}

function renderTaskList() {
  if (state.view === 'chart') { renderChart(); return; }
  const filtered   = getFiltered();
  const container  = document.getElementById('task-list');
  container.innerHTML = '';
  document.getElementById('result-count').textContent = `${filtered.length} tasks`;

  if (filtered.length === 0) {
    container.innerHTML = '<div class="no-results">No tasks match the current filters.</div>';
    return;
  }

  // Use tree only when not actively searching / tag-filtering (so hierarchy is meaningful)
  const useTree = (state.view === 'tree' || state.view === 'source') && !state.search.trim() && state.activeTags.length === 0;

  if (useTree && state.view === 'source') {
    // Source tree: group tasks by what created them (source field)
    const filteredIds = new Set(filtered.map(t => t.id));
    const { roots, childrenOf } = buildSourceTree();
    const filteredRoots = roots
      .filter(id => filteredIds.has(id))
      .sort((a, b) => (taskMap[a]?.created_at || '').localeCompare(taskMap[b]?.created_at || ''));
    filteredRoots.forEach(id => renderSourceTree(taskMap[id], container, 0, filteredIds, childrenOf));
  } else if (useTree) {
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
    toggle.textContent = state.expandedNodes.has(task.id) ? '▾' : '▸';
    toggle.onclick = e => {
      e.stopPropagation();
      if (state.expandedNodes.has(task.id)) state.expandedNodes.delete(task.id);
      else state.expandedNodes.add(task.id);
      persist();
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
  el.onclick = () => selectTask(task.id);
  container.appendChild(el);
}

// ── Task selection & detail ──────────────────────────────────
function toggleDetailNode(id) {
  if (state.detailExpandedNodes.has(id)) state.detailExpandedNodes.delete(id);
  else state.detailExpandedNodes.add(id);
  persist();
  if (state.selectedId) renderDetail(state.selectedId);
}

function selectTask(id) {
  pushNav(id);
  _activateTask(id);
}
function _activateTask(id) {
  state.selectedId = id;
  persist();
  document.querySelectorAll('.task-item').forEach(el =>
    el.classList.toggle('selected', el.dataset.id === id)
  );
  renderDetail(id);
  const el = document.querySelector(`.task-item[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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

  // Header
  html += `<div class="d-title">${esc(task.title)}</div>`;
  html += `<div class="d-badges">`;
  html += `<span class="d-badge" style="background:${sbg};color:${sfg}">${task.status}</span>`;
  html += `<span class="d-badge badge-${task.model}">${task.model}</span>`;
  if (task.thinking) html += `<span class="d-badge badge-think">🧠 extended thinking</span>`;
  html += `<span style="font-size:11px;color:var(--text-muted);font-family:monospace">${task.id.slice(0,8)}</span>`;
  html += `</div>`;

  // Stuck banner
  if (task.status === 'stuck') {
    html += `<div class="stuck-banner">⚠️ This task is stuck. A resolution task should be created.</div>`;
  }

  // Open blockers banner
  if (openBlockers.length > 0) {
    html += `<div class="stuck-banner" style="background:#fff7ed;border-color:#fb923c;color:#c2410c">⛔ Blocked by ${openBlockers.length} unfinished task${openBlockers.length > 1 ? 's' : ''}.</div>`;
  }

  // Description
  html += `<div class="d-section">
    <div class="d-label">Description</div>
    <pre class="d-pre">${highlightText(task.description, state.search.trim())}</pre>
  </div>`;

  // Metadata
  html += `<div class="d-section"><div class="d-label">Metadata</div><div class="d-meta-grid">`;
  html += metaItem('Created', `${fmt(task.created_at)} ${agoStr(task.created_at)}`);
  html += metaItem('Updated', `${fmt(task.updated_at)} ${agoStr(task.updated_at)}`);
  if (task.claimed_by)   html += metaItem('Claimed by', esc(task.claimed_by));
  if (task.claimed_at)   html += metaItem('Claimed at', fmt(task.claimed_at));
  if (task.completed_at) html += metaItem('Completed',  `${fmt(task.completed_at)} ${agoStr(task.completed_at)}`);
  html += metaItem('Full ID', `<span style="font-family:monospace;font-size:11px">${task.id}</span>`);
  html += `</div></div>`;

  // Tags
  if ((task.tags || []).length) {
    html += `<div class="d-section"><div class="d-label">Tags</div><div class="d-tags">`;
    task.tags.forEach(tag => {
      html += `<span class="d-tag" onclick="jumpToTag('${escAttr(tag)}')" title="Filter by this tag">${esc(tag)}</span>`;
    });
    html += `</div></div>`;
  }

  // Result
  if (task.result) {
    html += `<div class="d-section"><div class="d-label">Result</div><div class="result-box">${esc(task.result)}</div></div>`;
  }

  // Source chain (progenitor trace)
  const sourceChain = getSourceChain(task.id);
  if (sourceChain.length > 0) {
    html += `<div class="d-section"><div class="d-label">Source Chain</div>`;
    // Show current task's immediate source
    const src = task.source;
    if (src === 'human') {
      html += `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">⌨ Created by human input</div>`;
    } else if (src && taskMap[src]) {
      html += `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Created by task execution:</div>`;
    }
    // Show the full ancestry chain
    sourceChain.forEach((entry, i) => {
      const indent = i * 16;
      const arrow = i > 0 ? '↳ ' : '';
      if (entry.type === 'human') {
        html += `<div style="padding-left:${indent}px;font-size:12px;margin:3px 0">
          ${arrow}<span style="color:var(--text-muted)">⌨ human input</span>
        </div>`;
      } else if (entry.task) {
        const t = entry.task;
        const isCurrent = t.id === task.id;
        if (isCurrent) {
          html += `<div style="padding-left:${indent}px;font-size:12px;margin:3px 0;font-weight:600">
            ${arrow}<span class="t-dot ${statusClass(t.status)}" style="width:7px;height:7px;border-radius:50%;display:inline-block;vertical-align:middle;margin-right:4px"></span>
            ${esc(t.title.length > 60 ? t.title.slice(0, 60) + '…' : t.title)}
            <span style="font-weight:400;color:var(--text-muted);font-family:monospace;font-size:10px">${t.id.slice(0,8)}</span>
          </div>`;
        } else {
          html += `<div style="padding-left:${indent}px;font-size:12px;margin:3px 0">
            ${arrow}<span class="task-link" onclick="selectTask('${t.id}')" style="display:inline-flex;margin:0;padding:3px 8px">
              <span class="t-dot ${statusClass(t.status)}" style="width:7px;height:7px;border-radius:50%;flex-shrink:0"></span>
              ${esc(t.title.length > 60 ? t.title.slice(0, 60) + '…' : t.title)}
            </span>
          </div>`;
        }
      }
    });
    html += `</div>`;
  }

  // Parent task
  if (task.parent_task) {
    html += `<div class="d-section"><div class="d-label">Parent Task</div>${taskLink(task.parent_task)}</div>`;
  }

  // Subtasks
  if ((task.tasks_created || []).length) {
    const subs     = task.tasks_created.map(id => taskMap[id]).filter(Boolean);
    const byStatus = {};
    subs.forEach(t => byStatus[t.status] = (byStatus[t.status]||0)+1);
    const summary  = Object.entries(byStatus).map(([s,c]) => `${c} ${s}`).join(', ');
    html += `<div class="d-section"><div class="d-label">Subtasks (${subs.length} direct · ${summary})</div>`;
    topoSort(task.tasks_created.slice()).forEach(id => { html += renderSubtaskTree(id, 0); });
    html += `</div>`;
  }

  // Blocked by
  if ((task.blocked_by || []).length) {
    html += `<div class="d-section"><div class="d-label">Blocked By (${task.blocked_by.length})</div>`;
    task.blocked_by.forEach(id => { html += taskLink(id); });
    html += `</div>`;
  }

  panel.innerHTML = html;
  panel.scrollTop = 0;
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
function getSourceChain(taskId) {
  const chain = [];
  const seen = new Set();
  let current = taskMap[taskId];
  while (current) {
    if (seen.has(current.id)) break;
    seen.add(current.id);
    chain.unshift({ type: 'task', task: current });
    const src = current.source;
    if (!src || src === 'human') {
      chain.unshift({ type: 'human' });
      break;
    }
    if (!taskMap[src]) break; // source task not found, stop
    current = taskMap[src];
  }
  return chain;
}

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

  // Compute intervals
  const intervals = [];
  for (let i = 1; i < timeline.length; i++) {
    intervals.push(timeline[i].time - timeline[i - 1].time);
  }
  // Median interval
  const sortedIntervals = [...intervals].sort((a, b) => a - b);
  const median = sortedIntervals[Math.floor(sortedIntervals.length / 2)];
  const threshold = median * 3;

  // Build collapsed x coordinates
  const result = [{ ...timeline[0], x: 0, gap: false }];
  let x = 0;
  const gapUnit = median || 1; // unit size for collapsed gaps
  for (let i = 1; i < timeline.length; i++) {
    const dt = timeline[i].time - timeline[i - 1].time;
    const isGap = dt > threshold && threshold > 0;
    if (isGap) {
      x += gapUnit; // compressed gap
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

  // Gap indicators
  let gapLines = '';
  collapsed.forEach(p => {
    if (p.gap) {
      const gx = sx(p.x);
      gapLines += `<line class="gap-indicator" x1="${gx}" y1="${pad.top}" x2="${gx}" y2="${pad.top + ch}"/>`;
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
    persist();
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
    persist();
    renderTaskList();
    search.blur();
  }
  if (e.altKey && e.key === 'ArrowLeft')  { e.preventDefault(); navBack(); }
  if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); navFwd();  }
});

// ── Boot ─────────────────────────────────────────────────────
loadSavedState();

// Restore UI state from saved state
if (state.statusFilter !== 'all') {
  document.querySelectorAll('#status-chips .chip').forEach(c =>
    c.classList.toggle('active', c.dataset.status === state.statusFilter)
  );
}
if (state.modelFilter !== 'all') {
  document.querySelectorAll('#model-chips .chip').forEach(c =>
    c.classList.toggle('active', c.dataset.model === state.modelFilter)
  );
}
if (state.search) document.getElementById('search').value = state.search;
if (state.view !== 'tree') {
  document.querySelectorAll('.view-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.view === state.view)
  );
}
if (state.view === 'chart') {
  document.getElementById('task-list-container').style.display = 'none';
  document.getElementById('detail').style.display = 'none';
  document.getElementById('chart-container').classList.add('visible');
}

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
# HTTP server
# ──────────────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    page_title: str = "tl0 Task Viewer"
    header_bg: str = "#111827"
    favicon_svg: str = _build_favicon_svg("#111827")

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            rendered = HTML.replace('{{PAGE_TITLE}}', html.escape(self.page_title)) \
                          .replace('{{HEADER_BG}}', self.header_bg)
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
                t["tasks_created"] = t.get("task_children", [])
                t["parent_task"]   = t.get("task_parent")
                tasks.append(t)
            body  = json.dumps(tasks).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
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

    # Configure handler with dynamic values
    Handler.page_title = page_title
    Handler.header_bg = header_bg
    Handler.favicon_svg = _build_favicon_svg(header_bg)

    server = HTTPServer(('127.0.0.1', port), Handler)
    url    = f'http://localhost:{port}'

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    print(f'Task viewer → {url}  (Ctrl+C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
