"""Shared CSS and JS for diff/transcript modals used by both viewer and supervisor."""

# CSS for modal overlays, diff viewer, conversation/transcript viewer, and timeline.
# These styles assume CSS variables --bg, --border, --text, --text-muted, --accent are defined.
SHARED_MODAL_CSS = r"""
/* ── Modal overlay & panels ───────────────────────────────── */
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
.log-panel-header-actions {
  display: flex; align-items: center; gap: 8px;
}
.log-copy-btn {
  background: #2d2d2d; border: 1px solid #555; color: #d4d4d4; font-size: 12px;
  padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit;
  transition: background 0.15s, border-color 0.15s;
}
.log-copy-btn:hover { background: #3a3a3a; border-color: #777; color: white; }
.log-copy-btn.copied { background: #166534; border-color: #22c55e; color: #bbf7d0; }
.log-panel-body {
  flex: 1; overflow: auto; padding: 12px 16px;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 12px;
  line-height: 1.6; white-space: pre-wrap; word-break: break-all;
}
.log-panel-body.log-lines-body { padding: 0; }
.log-line {
  padding: 1px 16px; cursor: pointer; border-left: 3px solid transparent;
  white-space: pre-wrap; word-break: break-all;
}
.log-line:hover { background: #2a2a2a; }
.log-line.selected { background: #1e3a5f; border-left-color: #3b82f6; }
.log-line::selection, .log-line *::selection { background: #264f78; }

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

/* ── Conversation viewer ──────────────────────────────────── */
.conv-panel {
  background: white; color: var(--text); border-radius: 12px;
  width: min(92vw, 1000px); height: 90vh; display: flex; flex-direction: column;
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
  border-bottom: 2px solid transparent; color: var(--text-muted); background: none;
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
  color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
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

/* ── Compact timeline view ─────────────────────────────────── */
.tl-row {
  display: flex; align-items: baseline; gap: 6px;
  padding: 2px 8px; font-size: 12px; line-height: 1.5;
  border-radius: 4px; cursor: pointer; min-height: 22px;
}
.tl-row:hover { background: #f0f4f8; }
.tl-row.tl-error { background: #fef2f2; }
.tl-row.tl-error:hover { background: #fee2e2; }
.tl-icon { width: 16px; text-align: center; flex-shrink: 0; font-size: 13px; }
.tl-tool {
  font-weight: 600; font-size: 11px; min-width: 50px; flex-shrink: 0;
  font-family: 'SFMono-Regular', Consolas, monospace; color: #0369a1;
}
.tl-label {
  flex: 1; color: #374151; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.tl-label code {
  background: #f3f4f6; padding: 0 3px; border-radius: 3px;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px;
}
.tl-meta {
  color: #9ca3af; font-size: 11px; flex-shrink: 0; white-space: nowrap;
}
.tl-meta.tl-meta-err { color: #dc2626; font-weight: 600; }
.tl-time {
  color: #9ca3af; font-size: 10px; flex-shrink: 0; white-space: nowrap;
  font-family: 'SFMono-Regular', Consolas, monospace;
  min-width: 36px; text-align: right;
}
.tl-row.tl-thinking { opacity: 0.55; }
.tl-row.tl-thinking .tl-label { font-style: italic; }
.tl-row.tl-text .tl-label { color: #1f2937; }
.tl-row.tl-user .tl-label { color: #6b7280; }
.tl-detail {
  display: none; margin: 0 0 4px 22px; padding: 6px 10px;
  background: #f9fafb; border: 1px solid var(--border); border-radius: 6px;
  font-family: 'SFMono-Regular', Consolas, monospace; font-size: 11px;
  line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  max-height: 400px; overflow-y: auto;
}
.tl-detail-section {
  margin-bottom: 6px;
}
.tl-detail-heading {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.5px; color: #9ca3af; margin-bottom: 2px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.tl-diff-old { background: #fecaca; padding: 1px 2px; border-radius: 2px; }
.tl-diff-new { background: #bbf7d0; padding: 1px 2px; border-radius: 2px; }
"""

# JS for diff/transcript modals. Uses window._modalApiBase for fetch URL prefix.
# Depends on an esc() function being defined in the page.
SHARED_MODAL_JS = r"""
// ── Shared modal: API base prefix ────────────────────────────
// Set to '' for viewer, '/viewer' for supervisor
if (typeof window._modalApiBase === 'undefined') window._modalApiBase = '';

// ── Shared modal: HTML escape helper (no-op if already defined) ──
if (typeof window._modalEsc === 'undefined') {
  window._modalEsc = function(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  };
}

// ── Diff modal ───────────────────────────────────────────────
function renderDiffHtml(diffText) {
  const _e = window._modalEsc;
  const lines = diffText.split('\n');
  let html = '';
  let currentFile = null;
  let fileLines = [];
  function flushFile() {
    if (!currentFile) return;
    const tag = currentFile.tag;
    const tagCls = tag === 'Added' ? 'diff-tag-added' : tag === 'Deleted' ? 'diff-tag-deleted' : 'diff-tag-modified';
    html += `<div class="diff-file"><div class="diff-file-header"><span>${_e(currentFile.name)}</span><span class="diff-tag ${tagCls}">${tag}</span></div>`;
    html += '<div class="diff-code"><table>';
    for (const fl of fileLines) {
      const cls = fl.type === '+' ? 'diff-line-add' : fl.type === '-' ? 'diff-line-del' : fl.type === '@' ? 'diff-line-hunk' : '';
      const ln = fl.ln !== null ? fl.ln : '';
      html += `<tr class="${cls}"><td class="diff-ln">${ln}</td><td class="diff-text">${_e(fl.text)}</td></tr>`;
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
  const _e = window._modalEsc;
  try {
    const res = await fetch(window._modalApiBase + '/api/diff/' + encodeURIComponent(sha));
    if (!res.ok) { alert('Failed to load diff'); return; }
    const text = await res.text();
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="log-panel diff-panel" style="width:min(95vw,1400px);max-height:90vh">
      <div class="log-panel-header">
        <h3>Diff — ${_e(sha.slice(0,8))}</h3>
        <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">✕</button>
      </div>
      <div class="log-panel-body">${renderDiffHtml(text)}</div>
    </div>`;
    document.body.appendChild(overlay);
  } catch (_) {}
}

// ── Transcript / conversation modal ──────────────────────────

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

function _fmtTimestamp(ms) {
  if (ms == null || ms < 0) return '';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m + ':' + String(s).padStart(2, '0');
}

function renderTimeline(entries) {
  const _e = window._modalEsc;
  let html = '';
  entries.forEach((e, i) => {
    const errCls = e.is_error ? ' tl-error' : '';
    const kindCls = e.kind === 'thinking' ? ' tl-thinking' : e.kind === 'text' ? ' tl-text' : e.kind === 'user' ? ' tl-user' : '';
    const hasDetail = e.detail_input || e.detail_output;
    const detailId = 'tld-' + i;
    html += `<div class="tl-row${errCls}${kindCls}" ${hasDetail ? `onclick="toggleConvEl('${detailId}')"` : ''}>`;
    html += `<span class="tl-icon">${e.icon}</span>`;
    if (e.tool) {
      html += `<span class="tl-tool">${_e(e.tool)}</span>`;
    }
    html += `<span class="tl-label">${_e(e.label)}</span>`;
    if (e.meta) {
      const metaCls = e.is_error ? 'tl-meta tl-meta-err' : 'tl-meta';
      html += `<span class="${metaCls}">${_e(e.meta)}</span>`;
    }
    if (e.timestamp_ms != null) {
      html += `<span class="tl-time">${_fmtTimestamp(e.timestamp_ms)}</span>`;
    }
    html += `</div>`;
    if (hasDetail) {
      html += `<div class="tl-detail" id="${detailId}">`;
      if (e.detail_input) {
        html += `<div class="tl-detail-section"><div class="tl-detail-heading">Input</div>${_e(e.detail_input)}</div>`;
      }
      if (e.detail_output) {
        html += `<div class="tl-detail-section"><div class="tl-detail-heading">Output</div>${_e(e.detail_output)}</div>`;
      }
      html += `</div>`;
    }
  });
  return html || '<div style="color:#9ca3af;padding:12px">No actions recorded.</div>';
}

async function showInvocationDetail(taskId, filename) {
  const _e = window._modalEsc;
  try {
    const tlRes = await fetch(`${window._modalApiBase}/api/transcript-timeline/${taskId}/${filename}`);
    let timelineHtml = '';
    if (tlRes.ok) {
      const timeline = await tlRes.json();
      timelineHtml = renderTimeline(timeline);
    } else {
      timelineHtml = '<div style="color:#9ca3af;padding:12px">Failed to load timeline.</div>';
    }
    const overlay = document.createElement('div');
    overlay.className = 'log-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="conv-panel">
      <div class="conv-panel-header">
        <h3>Execution — ${_e(filename)}</h3>
        <button class="log-panel-close" onclick="this.closest('.log-overlay').remove()">\u2715</button>
      </div>
      <div class="conv-tab-bar">
        <button class="conv-tab active" data-tab="chat" onclick="switchConvTab(this)">Chat</button>
        <button class="conv-tab" data-tab="raw-json" onclick="switchConvTab(this)">Raw JSON</button>
      </div>
      <div class="conv-panel-body">
        <div class="conv-tab-content active" id="tab-chat">${timelineHtml}</div>
        <div class="conv-tab-content" id="tab-raw-json"><div class="conv-raw-json">Loading\u2026</div></div>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    overlay._rawLoaded = false;
    overlay._taskId = taskId;
    overlay._filename = filename;
  } catch (_) {}
}

async function loadConversation(taskId, filename, container) {
  const _e = window._modalEsc;
  try {
    const res = await fetch(`${window._modalApiBase}/api/transcript-messages/${taskId}/${filename}`);
    if (!res.ok) { container.innerHTML = '<div style="color:#dc2626;padding:12px">Failed to load conversation.</div>'; return; }
    const messages = await res.json();
    let body = '';
    let blockCounter = 0;
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
      h += `<div class="conv-tool-result-body" id="${resultId}" style="display:none">${_e(r.text)}</div>`;
      h += `<div class="conv-tool-toggle" onclick="toggleConvEl('${resultId}')">Show output</div>`;
      h += `</div>`;
      return h;
    }
    messages.forEach(msg => {
      if (msg.role === 'user') {
        body += `<div class="conv-msg user"><div class="conv-msg-role">User</div>`;
        const userTextId = 'ut-' + (blockCounter++);
        const preview = (msg.text || '').split('\\n')[0].substring(0, 120);
        body += `<div class="conv-msg-text conv-user-preview">${_e(preview)}</div>`;
        body += `<div class="conv-user-full" id="${userTextId}" style="display:none">${_e(msg.text)}</div>`;
        body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${userTextId}')">Show full message</div>`;
        body += `</div>`;
      } else if (msg.role === 'assistant') {
        (msg.content || []).forEach(block => {
          if (block.type === 'thinking' && block.thinking) {
            const thinkId = 'th-' + (blockCounter++);
            const preview = block.thinking.split('\\n')[0].substring(0, 100);
            body += `<div class="conv-thinking">`;
            body += `<div class="conv-thinking-label">Thinking: <span class="conv-thinking-preview">${_e(preview)}</span></div>`;
            body += `<div class="conv-thinking-body" id="${thinkId}" style="display:none">${_e(block.thinking)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${thinkId}')">Show thinking</div>`;
            body += `</div>`;
          } else if (block.type === 'text' && block.text) {
            body += `<div class="conv-msg-text">${_e(block.text)}</div>`;
          } else if (block.type === 'tool_use') {
            const inputStr = JSON.stringify(block.input, null, 2);
            const inputId = 'ti-' + block.id;
            body += `<div class="conv-tool-pair">`;
            body += `<div class="conv-tool-use">`;
            body += `<span class="conv-tool-name">${_e(block.name)}</span>`;
            body += `<div class="conv-tool-input" id="${inputId}" style="display:none">${_e(inputStr)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${inputId}')">Show input</div>`;
            body += `</div>`;
            body += renderToolResult(block.id);
            body += `</div>`;
          } else {
            const unknownId = 'unk-' + (blockCounter++);
            const raw = JSON.stringify(block, null, 2);
            body += `<div class="conv-unknown-block">`;
            body += `<div class="conv-unknown-block-label">Unhandled block: <code>${_e(block.type || 'unknown')}</code></div>`;
            body += `<div class="conv-unknown-block-body" id="${unknownId}" style="display:none">${_e(raw)}</div>`;
            body += `<div class="conv-tool-toggle" onclick="toggleConvEl('${unknownId}')">Show raw</div>`;
            body += `</div>`;
          }
        });
      }
    });
    container.innerHTML = body || '<div style="color:#9ca3af;padding:12px">No messages.</div>';
  } catch (e) {
    container.innerHTML = '<div style="color:#dc2626;padding:12px">Error loading conversation.</div>';
  }
}

function switchConvTab(btn) {
  const panel = btn.closest('.conv-panel');
  panel.querySelectorAll('.conv-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const tabName = btn.dataset.tab;
  panel.querySelectorAll('.conv-tab-content').forEach(c => c.classList.remove('active'));
  panel.querySelector('#tab-' + tabName).classList.add('active');
  const overlay = panel.closest('.log-overlay');
  if (tabName === 'raw-json') {
    if (!overlay._rawLoaded) {
      overlay._rawLoaded = true;
      loadRawJson(overlay._taskId, overlay._filename, panel.querySelector('#tab-raw-json'));
    }
  }
}

async function loadRawJson(taskId, filename, container) {
  const _e = window._modalEsc;
  try {
    const res = await fetch(`${window._modalApiBase}/api/transcript-raw/${taskId}/${filename}`);
    if (!res.ok) { container.innerHTML = '<div class="conv-raw-json">Failed to load raw JSON.</div>'; return; }
    const events = await res.json();
    let html = '';
    events.forEach((evt, i) => {
      const evtType = evt.type || 'unknown';
      const summary = JSON.stringify(evt).substring(0, 150);
      const full = JSON.stringify(evt, null, 2);
      const bodyId = 'raw-evt-' + i;
      html += `<div class="conv-raw-event" onclick="toggleConvEl('${bodyId}')">`;
      html += `<div class="conv-raw-event-summary"><strong>${i}</strong> &nbsp; <code>${_e(evtType)}</code> &nbsp; ${_e(summary)}</div>`;
      html += `<div class="conv-raw-event-body" id="${bodyId}">${_e(full)}</div>`;
      html += `</div>`;
    });
    container.innerHTML = `<div class="conv-raw-json">${html}</div>`;
  } catch (e) {
    container.innerHTML = '<div class="conv-raw-json">Error loading raw JSON.</div>';
  }
}

// ── Latest transcript helper ─────────────────────────────────
// Fetches the task list, finds the latest transcript filename, and opens the modal.
async function showLatestTranscript(taskId) {
  try {
    const res = await fetch(window._modalApiBase + '/api/tasks');
    if (!res.ok) return;
    const tasks = await res.json();
    const task = tasks.find(t => t.id === taskId);
    if (task && task.transcript && task.transcript.invocations && task.transcript.invocations.length) {
      const lastInv = task.transcript.invocations[task.transcript.invocations.length - 1];
      showInvocationDetail(taskId, lastInv.file);
    } else {
      alert('No transcript found for this task.');
    }
  } catch (_) {}
}
"""
