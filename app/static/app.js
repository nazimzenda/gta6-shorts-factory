/* ==========================================================================
   Founder Control Tower · dashboard client
   Vanilla ES2022. No build step, no external dependencies.
   ========================================================================== */
'use strict';

const API = '/api';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const state = {
  view: 'home',
  summary: null,
  approvalsFilter: 'pending',
  ws: null,
  wsRetry: null,
  token: localStorage.getItem('founderToken') || '',
  posts: [],
  mcpServers: [],
  busy: false,
};

const VIEW_META = {
  home: { eyebrow: 'COMMAND CENTER', title: 'Founder Home' },
  ceo: { eyebrow: 'STRATEGY & ORCHESTRATION', title: 'AI CEO Office' },
  departments: { eyebrow: 'PEOPLE & QUEUES', title: 'Departments' },
  flow: { eyebrow: 'ENTERPRISE BUILDING · LIVE HANDOFFS', title: 'Operations Building' },
  projects: { eyebrow: 'PORTFOLIO', title: 'Projects & Businesses' },
  production: { eyebrow: 'LOCAL MEDIA FACTORY', title: 'Production Board' },
  approvals: { eyebrow: 'FOUNDER AUTHORITY', title: 'Approval Queue' },
  assets: { eyebrow: 'PROVENANCE', title: 'Assets & Rights' },
  integrations: { eyebrow: 'MCP · PROVIDERS · PLATFORMS', title: 'Integrations' },
  cua: { eyebrow: 'GUARDED AUTOMATION', title: 'CUA Sessions' },
  pipeline: { eyebrow: 'ZERO-KEY AUTOMATION', title: 'CUA Shorts Pipeline' },
  analytics: { eyebrow: 'PERFORMANCE & FINANCE', title: 'Analytics & Finance' },
};

const ICONS = {
  home: '<path d="M3 10.6 12 3.5l9 7.1"/><path d="M5.2 9.4V20.5h13.6V9.4"/><path d="M9.5 20.5v-6h5v6"/>',
  ceo: '<circle cx="12" cy="8" r="3.2"/><path d="M5 21c.4-4 3.1-6.2 7-6.2s6.6 2.2 7 6.2"/>',
  dept: '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
  flow: '<circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7.2 6h9.6M6.3 8l4.5 8M17.7 8l-4.5 8"/>',
  projects: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h4l2 2h7A2.5 2.5 0 0 1 21 9.5v8A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z"/>',
  production: '<rect x="3" y="5" width="18" height="14" rx="2.2"/><path d="m10 9 5.5 3-5.5 3z"/>',
  approvals: '<path d="m4.5 12.5 5 5L19.5 7"/>',
  assets: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="m4.5 16 5-5 4 4 2-2 4 4.5"/><circle cx="16.5" cy="8.5" r="1.4"/>',
  plug: '<path d="M9 2.8v5.4M15 2.8v5.4"/><path d="M6.2 8.2h11.6v2.6a5.8 5.8 0 0 1-11.6 0z"/><path d="M12 16.6v4.6"/>',
  cua: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  pipeline: '<path d="M4 6h6v5H4z"/><path d="M14 3h6v5h-6z"/><path d="M14 14h6v7h-6z"/><path d="M10 8.5h4M10 16h4M7 11v5"/>',
  analytics: '<path d="M4 19.5V4.5"/><path d="M4 19.5h16"/><path d="m7 15.5 4-4 3 3 5-6.5"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.home}</svg>`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
const h = escapeHtml;

function truncate(value, limit = 80) {
  const text = String(value ?? '');
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}…` : text;
}
function titleCase(value) {
  return String(value ?? '').replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
function fmtNum(value) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return h(value);
  return n.toLocaleString('en-US');
}
function fmtMoney(value) {
  const n = Number(value || 0);
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
}
function fmtPct(value) {
  if (value === null || value === undefined) return '—';
  return `${Number(value).toFixed(1)}%`;
}
function parseDate(value) {
  if (!value) return null;
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)) return new Date(`${text.replace(' ', 'T')}Z`);
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}
function fmtDate(value) {
  const date = parseDate(value);
  if (!date) return '—';
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function fmtDay(value) {
  const date = parseDate(value);
  if (!date) return '—';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function timeAgo(value) {
  const date = parseDate(value);
  if (!date) return '—';
  const seconds = Math.max(1, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
function statusBadge(status) {
  const key = String(status || 'unknown').toLowerCase().replace(/[^a-z0-9_]/g, '');
  return `<span class="badge status-${key}">${h(titleCase(status || 'unknown'))}</span>`;
}
function riskBadge(risk) {
  const cls = risk === 'high' ? 'red' : risk === 'medium' ? 'amber' : 'green';
  return `<span class="badge ${cls}">${h(risk || 'low')} risk</span>`;
}
function emptyState(message, glyph = '◇') {
  return `<div class="empty"><span class="big">${glyph}</span><span>${h(message)}</span></div>`;
}
function errorState(message) {
  return `<div class="error-state"><strong>Could not load this view</strong><span>${h(message)}</span><button class="btn sm mt-8" data-action="refresh">Retry</button></div>`;
}
function pills(values, className = 'tag') {
  if (!values || !values.length) return '<span class="faint small">None</span>';
  return values.map((value) => `<span class="${className}">${h(value)}</span>`).join(' ');
}
function jsonPretty(value) {
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}
function bytes(value) {
  const n = Number(value || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/* -------------------------------------------------------------------- API */
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers['X-Founder-Token'] = state.token;
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== 'string') {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }
  const response = await fetch(`${API}${path}`, { ...options, headers, body });
  let payload = null;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) {
    const error = new Error(payload?.detail || `Request failed with status ${response.status}`);
    error.status = response.status;
    error.code = payload?.code;
    if (response.status === 401) {
      error.message = 'Founder token required. Set FOUNDER_TOKEN and localStorage founderToken.';
    }
    throw error;
  }
  return payload;
}

/* ------------------------------------------------------------------- toast */
function toast(message, type = 'info', timeout = 4200) {
  const root = $('#toast-root');
  const element = document.createElement('div');
  element.className = `toast ${type}`;
  element.textContent = message;
  root.appendChild(element);
  setTimeout(() => {
    element.style.opacity = '0';
    element.style.transform = 'translateY(6px)';
    element.style.transition = 'all 180ms ease';
    setTimeout(() => element.remove(), 200);
  }, timeout);
}

/* ------------------------------------------------------------------ chrome */
function setView(view) {
  if (!VIEW_META[view]) view = 'home';
  state.view = view;
  const meta = VIEW_META[view];
  $('#view-title').textContent = meta.title;
  $('#view-eyebrow').textContent = meta.eyebrow;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  if (window.location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  renderView();
}

function updateChrome(summary) {
  if (!summary) return;
  state.summary = summary;
  const pending = Number(summary.pending_approvals || 0);
  const badge = $('#approval-badge');
  badge.textContent = pending > 99 ? '99+' : String(pending);
  badge.hidden = pending === 0;

  const stopped = Boolean(summary.emergency_stop);
  const pill = $('#system-pill');
  pill.classList.toggle('stopped', stopped);
  pill.innerHTML = `<span class="system-dot"></span> ${stopped ? 'EMERGENCY STOP' : 'OPERATIONAL'}`;
  const stopButton = $('#stop-button');
  stopButton.classList.toggle('engaged', stopped);
  $('#stop-label').textContent = stopped ? 'RESUME OPERATIONS' : 'EMERGENCY STOP';

  const local = $('#flag-local');
  local.className = `flag ${summary.local_processing_enabled ? 'on' : 'off'}`;
  local.textContent = summary.local_processing_enabled ? 'LOCAL ON' : 'LOCAL OFF';

  const everygen = $('#flag-everygen');
  everygen.className = `flag ${summary.everygen_enabled ? 'on' : 'off'}`;
  everygen.textContent = summary.everygen_enabled ? (summary.everygen_mock ? 'EVERYGEN MOCK' : 'EVERYGEN LIVE') : 'EVERYGEN OFF';

  const cua = $('#flag-cua');
  cua.className = `flag ${summary.cua_enabled ? 'warn' : 'off'}`;
  cua.textContent = summary.cua_enabled ? 'CUA ON' : 'CUA OFF';

  const publish = $('#flag-publish');
  publish.className = `flag ${summary.publishing_dry_run ? 'warn' : summary.publishing_enabled ? 'on' : 'off'}`;
  publish.textContent = summary.publishing_dry_run ? 'PUBLISH DRY' : summary.publishing_enabled ? 'PUBLISH ON' : 'PUBLISH OFF';

  updateHomeLive(summary);
}

function updateHomeLive(summary) {
  if (state.view !== 'home') return;
  const set = (selector, value) => { const element = $(selector); if (element) element.textContent = value; };
  set('#kpi-initiatives', fmtNum(summary.active_initiatives));
  set('#kpi-approvals', fmtNum(summary.pending_approvals));
  set('#kpi-workers', `${fmtNum(summary.active_workers)}`);
  set('#kpi-workers-total', ` / ${fmtNum(summary.workers_total)}`);
  set('#kpi-qc', summary.quality?.qc_pass_rate != null ? fmtPct(summary.quality.qc_pass_rate) : '—');
  set('#kpi-spend', fmtMoney(summary.finance?.total_cost_usd));
  set('#kpi-budget', `${fmtMoney(summary.finance?.provider_remaining_usd)} left`);
  set('#kpi-posts', fmtNum(summary.publishing?.posts));
  set('#kpi-views', `${fmtNum(summary.publishing?.views)} views`);
  const score = healthScore(summary);
  const ring = $('#health-ring');
  if (ring) ring.style.setProperty('--pct', score);
  set('#health-score', String(score));
}

async function refreshSummary() {
  try {
    const summary = await api('/dashboard/summary');
    updateChrome(summary);
    return summary;
  } catch (error) {
    return null;
  }
}

function connectSocket() {
  clearTimeout(state.wsRetry);
  try {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/dashboard`);
    state.ws = socket;
    socket.addEventListener('open', () => {
      $('#ws-state').classList.remove('offline');
      $('#ws-label').textContent = 'LIVE FEED';
    });
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === 'summary') updateChrome(payload);
      } catch { /* ignore malformed frame */ }
    });
    socket.addEventListener('close', () => {
      $('#ws-state').classList.add('offline');
      $('#ws-label').textContent = 'RECONNECTING';
      state.wsRetry = setTimeout(connectSocket, 3200);
    });
    socket.addEventListener('error', () => socket.close());
  } catch {
    $('#ws-state').classList.add('offline');
  }
}

function clockTick() {
  const now = new Date();
  $('#clock').textContent = now.toLocaleTimeString('en-GB', { hour12: false });
}
setInterval(clockTick, 1000);
clockTick();

/* ------------------------------------------------------------------- modal */
function openModal(title, subtitle, body, options = {}) {
  const root = $('#modal-root');
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal" role="dialog" aria-modal="true" aria-label="${h(title)}" style="${options.wide ? 'width:min(960px,100%)' : ''}">
        <div class="modal-head">
          <div><h3>${h(title)}</h3>${subtitle ? `<p>${h(subtitle)}</p>` : ''}</div>
          <button class="modal-close" data-action="close-modal" aria-label="Close">×</button>
        </div>
        <div class="modal-body">${body}</div>
      </div>
    </div>`;
  const backdrop = $('.modal-backdrop', root);
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) closeModal();
  });
}
function closeModal() { $('#modal-root').innerHTML = ''; }
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });

/* ------------------------------------------------------------------ routing */
const renderers = {
  home: renderHome,
  ceo: renderCEO,
  departments: renderDepartments,
  flow: renderFlow,
  projects: renderProjects,
  production: renderProduction,
  approvals: renderApprovals,
  assets: renderAssets,
  integrations: renderIntegrations,
  cua: renderCUA,
  pipeline: renderPipeline,
  analytics: renderAnalytics,
};

let renderSequence = 0;
async function renderView() {
  const sequence = ++renderSequence;
  const main = $('#view');
  main.innerHTML = `<div class="loading-grid"><div class="skeleton tall"></div><div class="skeleton"></div><div class="skeleton"></div></div>`;
  try {
    const html = await renderers[state.view]();
    if (sequence === renderSequence) main.innerHTML = html;
  } catch (error) {
    if (sequence === renderSequence) main.innerHTML = errorState(error.message);
  }
}

function navigate(view) { setView(view); }

/* -------------------------------------------------------------------- home */
function healthScore(summary) {
  let score = 100;
  score -= Number(summary.pending_approvals || 0) * 2;
  score -= Number(summary.quality?.qc_failed || 0) * 5;
  score -= Number(summary.quality?.rights_expired || 0) * 10;
  score -= Number(summary.task_counts?.dead_letter || 0) * 9;
  score -= Number(summary.variant_counts?.render_failed || 0) * 4;
  if (summary.emergency_stop) score -= 30;
  return Math.max(4, Math.min(100, Math.round(score)));
}

function alertHTML(alert) {
  const glyph = alert.severity === 'critical' ? '⛔' : alert.severity === 'warning' ? '⚠️' : 'ℹ️';
  return `<div class="alert ${h(alert.severity)}"><span class="icon">${glyph}</span><div><strong>${h(alert.title)}</strong><span>${h(alert.detail)}</span></div></div>`;
}

function approvalSubjectLine(approval) {
  const subject = approval.subject;
  if (!subject) return truncate(approval.subject_id, 70);
  if (approval.type === 'rights') return `${subject.owner || 'Unknown owner'} · ${subject.license_type || 'license'}`;
  if (approval.type === 'final_video') return `${subject.title || 'Untitled'} · ${titleCase(subject.style || '')}`;
  if (approval.type === 'provider_quote') return `${titleCase(subject.request?.kind || 'provider')} · ${subject.credits || 0} credits · ${fmtMoney(subject.cost_usd)}`;
  if (approval.type === 'publish_final') return `${titleCase(subject.platform || 'platform')} · ${titleCase(subject.status || '')}`;
  if (approval.type === 'cua_session') return `${subject.target || 'target'} · ${subject.mode || 'mode'}`;
  if (approval.type === 'initiative_plan') return truncate(subject.objective || 'Initiative plan', 80);
  if (approval.type === 'mcp_tool') return `${subject.name || 'tool'} · ${subject.risk || 'low'} risk`;
  return truncate(approval.subject_id, 70);
}

function approvalCard(approval, compact = false) {
  const glyph = {
    rights: '⚖️', final_video: '🎬', provider_quote: '💳', publish_final: '🚀',
    cua_session: '🖥️', initiative_plan: '🧭', mcp_tool: '🔌', script: '✍️',
  }[approval.type] || '✅';
  const pending = approval.status === 'pending';
  return `<div class="approval-card">
    <div class="approval-icon">${glyph}</div>
    <div>
      <div class="approval-title">${h(approvalSubjectLine(approval))}</div>
      <div class="approval-meta">
        ${statusBadge(approval.type)}
        <span>by ${h(approval.requested_by || 'ceo')}</span>
        <span>${timeAgo(approval.created_at)}</span>
        ${approval.decided_by ? `<span>decided by ${h(approval.decided_by)}</span>` : ''}
      </div>
      ${approval.reason && !compact ? `<div class="approval-reason">${h(approval.reason)}</div>` : ''}
    </div>
    <div class="approval-actions">
      ${pending ? `
        <button class="btn green sm" data-action="approve-approval" data-id="${h(approval.id)}">Approve</button>
        <button class="btn red sm" data-action="reject-approval" data-id="${h(approval.id)}">Reject</button>
      ` : statusBadge(approval.status)}
      <button class="btn ghost sm" data-action="open-approval" data-id="${h(approval.id)}">Inspect</button>
    </div>
  </div>`;
}

function activityItem(event) {
  const action = String(event.action || '');
  const color = action.includes('approved') || action.includes('completed') || action.includes('succeeded')
    ? 'green'
    : action.includes('rejected') || action.includes('failed') || action.includes('emergency')
      ? 'red'
      : action.includes('requested') || action.includes('created')
        ? 'pink'
        : '';
  const label = titleCase(action.replaceAll('_', ' '));
  const detail = event.payload && Object.keys(event.payload).length
    ? truncate(Object.entries(event.payload).map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`).join(' · '), 110)
    : event.target;
  return `<div class="timeline-item">
    <span class="timeline-dot ${color}"></span>
    <div class="timeline-body">
      <div class="timeline-title">${h(label)}</div>
      <div class="timeline-sub">${h(event.actor || 'system')} · ${h(detail)}</div>
    </div>
    <span class="timeline-time">${timeAgo(event.occurred_at)}</span>
  </div>`;
}

async function renderHome() {
  const [summary, approvals, activity] = await Promise.all([
    api('/dashboard/summary'),
    api('/approvals?status=pending'),
    api('/dashboard/activity?limit=9'),
  ]);
  state.summary = summary;
  updateChrome(summary);
  const score = healthScore(summary);
  const finance = summary.finance || {};
  const quality = summary.quality || {};
  const publishing = summary.publishing || {};
  const tasks = summary.task_counts || {};
  const variants = summary.variant_counts || {};
  const budgetUsed = Number(finance.provider_budget_usd || 0) ? Math.min(100, (Number(finance.provider_spend_usd || 0) / Number(finance.provider_budget_usd)) * 100) : 0;
  const stageBars = [
    ['Queued', tasks.queued || 0, ''],
    ['Running', tasks.running || 0, 'violet'],
    ['Completed', tasks.completed || 0, 'green'],
    ['Dead letter', tasks.dead_letter || 0, ''],
  ];
  const maxTask = Math.max(1, ...stageBars.map(([, value]) => value));
  const variantBars = [
    ['Drafts', variants.draft || 0, ''],
    ['QC passed', (variants.qc_passed || 0) + (variants.in_review || 0), 'green'],
    ['Approved', variants.approved || 0, 'violet'],
    ['Published', variants.published || 0, 'green'],
  ];
  const maxVariant = Math.max(1, ...variantBars.map(([, value]) => value));

  return `
    <section class="hero">
      <div class="hero-main">
        <div class="hero-kicker">${summary.emergency_stop ? 'INCIDENT RESPONSE · ALL WORK PAUSED' : 'FOUNDER / DAILY OPERATIONS'}</div>
        <h2>${summary.emergency_stop ? 'The factory is stopped. Resume only when the risk is understood.' : 'Rights-cleared shorts, under your control.'}</h2>
        <p>${summary.emergency_stop
          ? 'Mutating actions are locked. Review the audit trail, resolve the incident, then resume operations.'
          : 'The AI CEO proposes. Workers produce evidence. Nothing paid or published moves without a founder approval record.'}</p>
        <div class="hero-actions">
          <button class="btn primary" data-action="go" data-view="ceo">Send strategic objective</button>
          <button class="btn" data-action="go" data-view="approvals">Review approvals ${approvals.length ? `· ${approvals.length}` : ''}</button>
          <button class="btn ghost" data-action="go" data-view="production">Open production</button>
        </div>
      </div>
      <div class="card health-card">
        <div class="ring" id="health-ring" style="--pct:${score}">
          <div class="center"><strong id="health-score">${score}</strong><span>COMPANY HEALTH</span></div>
        </div>
        <div class="small muted">${summary.emergency_stop ? 'Emergency stop engaged' : approvals.length ? `${approvals.length} decision${approvals.length === 1 ? '' : 's'} waiting` : 'No founder decisions waiting'}</div>
        <div class="pill-row">
          <span class="badge ${summary.local_processing_enabled ? 'green' : 'red'}">Local ${summary.local_processing_enabled ? 'on' : 'off'}</span>
          <span class="badge ${summary.everygen_enabled ? 'amber' : ''}">Everygen ${summary.everygen_enabled ? (summary.everygen_mock ? 'mock' : 'live') : 'off'}</span>
          <span class="badge ${summary.cua_enabled ? 'violet' : ''}">CUA ${summary.cua_enabled ? 'armed' : 'off'}</span>
        </div>
      </div>
    </section>

    ${summary.alerts?.length ? `<div class="alert-stack mt-16" style="margin-bottom:18px">${summary.alerts.map(alertHTML).join('')}</div>` : ''}

    <div class="kpi-grid">
      <div class="kpi" style="--accent:var(--pink)"><div class="label">Active initiatives</div><div class="value" id="kpi-initiatives">${fmtNum(summary.active_initiatives)}</div><div class="hint">${(summary.approvals_by_type?.initiative_plan || 0)} plan approval${(summary.approvals_by_type?.initiative_plan || 0) === 1 ? '' : 's'}</div></div>
      <div class="kpi" style="--accent:var(--orange)"><div class="label">Approvals waiting</div><div class="value" id="kpi-approvals">${fmtNum(summary.pending_approvals)}</div><div class="hint">Founder authority gate</div></div>
      <div class="kpi" style="--accent:var(--violet)"><div class="label">Active workers</div><div class="value"><span id="kpi-workers">${fmtNum(summary.active_workers)}</span><small id="kpi-workers-total">/ ${fmtNum(summary.workers_total)}</small></div><div class="hint">Across ${summary.departments?.length || 0} departments</div></div>
      <div class="kpi" style="--accent:var(--mint)"><div class="label">QC pass rate</div><div class="value" id="kpi-qc">${quality.qc_pass_rate != null ? fmtPct(quality.qc_pass_rate) : '—'}</div><div class="hint">${quality.qc_passed || 0} passed · ${quality.qc_failed || 0} failed</div></div>
      <div class="kpi" style="--accent:var(--orange)"><div class="label">Recorded spend</div><div class="value" id="kpi-spend">${fmtMoney(finance.total_cost_usd)}</div><div class="hint" id="kpi-budget">${fmtMoney(finance.provider_remaining_usd)} provider credit left</div></div>
      <div class="kpi" style="--accent:var(--blue)"><div class="label">Published posts</div><div class="value" id="kpi-posts">${fmtNum(publishing.posts)}</div><div class="hint" id="kpi-views">${fmtNum(publishing.views)} views</div></div>
    </div>

    <div class="grid-2-1">
      <div class="card">
        <div class="card-head">
          <div><h3>Founder approval queue</h3><div class="sub">Consequential actions wait here. The CEO cannot approve its own work.</div></div>
          <button class="btn ghost sm" data-action="go" data-view="approvals">View all</button>
        </div>
        ${approvals.length ? `<div class="approval-list">${approvals.slice(0, 5).map((approval) => approvalCard(approval, true)).join('')}</div>` : emptyState('Approval queue is clear.', '✓')}
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h3>Production pulse</h3><div class="sub">Live work and quality stages</div></div></div>
          ${stageBars.map(([label, value, tone]) => `<div class="bar-row"><span>${label}</span><div class="progress ${tone}"><span style="width:${Math.round((value / maxTask) * 100)}%"></span></div><strong>${value}</strong></div>`).join('')}
          <div class="split-line"></div>
          ${variantBars.map(([label, value, tone]) => `<div class="bar-row"><span>${label}</span><div class="progress ${tone}"><span style="width:${Math.round((value / maxVariant) * 100)}%"></span></div><strong>${value}</strong></div>`).join('')}
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Provider budget</h3><div class="sub">Quote before spend</div></div><span class="mono tiny">${fmtMoney(finance.provider_spend_usd)} / ${fmtMoney(finance.provider_budget_usd)}</span></div>
          <div class="progress ${budgetUsed > 85 ? '' : 'green'}"><span style="width:${Math.max(1, budgetUsed)}%"></span></div>
          <div class="between mt-8"><span class="small muted">Everygen credits</span><span class="small">${fmtMoney(finance.provider_remaining_usd)} remaining</span></div>
          <div class="pill-row mt-8"><span class="badge ${summary.everygen_enabled ? 'amber' : ''}">${summary.everygen_enabled ? 'Provider enabled' : 'Provider disabled'}</span><span class="badge ${summary.publishing_dry_run ? 'violet' : ''}">Publishing ${summary.publishing_dry_run ? 'dry-run' : 'live'}</span></div>
        </div>
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Recent activity</h3><div class="sub">Append-only audit trail</div></div><button class="btn ghost sm" data-action="go" data-view="analytics">Reports</button></div>
        ${activity.length ? `<div class="timeline">${activity.map(activityItem).join('')}</div>` : emptyState('No activity yet. Send an objective to the CEO.')}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Publishing calendar</h3><div class="sub">Approved jobs waiting for the right moment</div></div><span class="badge">${publishing.upcoming?.length || 0} scheduled</span></div>
        ${publishing.upcoming?.length ? `<div class="publish-calendar">${publishing.upcoming.map((job) => `<div class="calendar-row"><span class="calendar-date">${job.schedule_at ? fmtDay(job.schedule_at) : 'READY'}</span><div><div class="calendar-title">${h(job.title || job.video_variant_id)}</div><div class="calendar-sub">${titleCase(job.platform)} · ${h(job.status)}</div></div>${statusBadge(job.status)}</div>`).join('')}</div>` : emptyState('No publishing jobs yet. Approve a final video to schedule one.')}
        <div class="split-line"></div>
        <div class="between"><span class="small muted">Maintenance</span><button class="btn ghost sm" data-action="backup">Create database backup</button></div>
      </div>
    </div>
  `;
}

/* --------------------------------------------------------------------- CEO */
async function renderCEO() {
  const [initiatives, report, tasks] = await Promise.all([
    api('/initiatives'),
    api('/ceo/report'),
    api('/tasks?status=queued'),
  ]);
  const planPending = initiatives.filter((item) => item.status === 'plan_pending');
  return `
    <div class="section-head">
      <div><h2>Convert a founder objective into governed work</h2><p>The CEO decomposes strategy into department tasks. You accept or reject the plan before any queue starts.</p></div>
      <div class="actions"><button class="btn ghost" data-action="tick-ceo">Run next queued tasks</button></div>
    </div>
    <div class="grid-2-1">
      <div class="card">
        <div class="card-head"><div><h3>New strategic instruction</h3><div class="sub">The objective is stored as an initiative with a full task DAG.</div></div><span class="badge pink">CEO</span></div>
        <form data-form="ceo">
          <div class="field"><label for="ceo-objective">Objective</label><textarea id="ceo-objective" name="objective" placeholder="Example: Produce three rights-cleared GTA 6 reaction shorts this week, review the strongest candidate, and prepare a YouTube schedule." required minlength="3"></textarea><span class="help">Avoid instructions that require unlicensed footage or automatic publishing.</span></div>
          <div class="form-grid mt-8">
            <div class="field"><label for="ceo-risk">Risk assessment</label><select id="ceo-risk" name="risk_level"><option value="">Let the CEO infer</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></div>
            <div class="field"><label>Approval policy</label><input value="Plan requires founder acceptance" disabled /></div>
          </div>
          <div class="form-actions"><button class="btn primary" type="submit">Deploy plan to CEO office</button><button class="btn ghost" type="reset">Clear</button></div>
        </form>
      </div>
      <div class="card">
        <div class="card-head"><div><h3>CEO report</h3><div class="sub">Throughput, quality, and blockers</div></div><span class="badge blue">LIVE</span></div>
        <div class="stat-strip" style="grid-template-columns:repeat(2,1fr)">
          <div class="stat"><div class="n">${fmtNum(report.throughput?.tasks_total)}</div><div class="l">Tasks total</div></div>
          <div class="stat"><div class="n">${fmtPct(report.throughput?.completion_rate)}</div><div class="l">Completion rate</div></div>
          <div class="stat"><div class="n">${fmtNum(report.throughput?.pending_approvals)}</div><div class="l">Approvals waiting</div></div>
          <div class="stat"><div class="n">${fmtMoney(report.finance?.total_cost_usd)}</div><div class="l">Recorded spend</div></div>
        </div>
        <div class="split-line"></div>
        <div class="small muted">Recommendations</div>
        <div class="alert-stack mt-8">${(report.recommendations || []).map((item) => `<div class="alert info"><span class="icon">→</span><div><strong>${h(item)}</strong></div></div>`).join('')}</div>
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Initiatives</h3><div class="sub">${planPending.length} plan${planPending.length === 1 ? '' : 's'} awaiting founder acceptance</div></div><span class="badge">${initiatives.length} total</span></div>
        ${initiatives.length ? `<div class="stack">${initiatives.map(initiativeCard).join('')}</div>` : emptyState('No initiatives yet. Send the first strategic objective.')}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Queued work</h3><div class="sub">Tasks ready for the worker runtime</div></div><button class="btn violet sm" data-action="tick-ceo">Execute next 5</button></div>
        ${tasks.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Task</th><th>Department</th><th>Priority</th><th></th></tr></thead><tbody>${tasks.slice(0, 12).map((task) => `<tr><td><div class="small">${h(truncate(task.title, 52))}</div><div class="tiny faint">${h(task.type)}</div></td><td>${statusBadge(task.department)}</td><td class="mono tiny">P${task.priority}</td><td><button class="btn xs green" data-action="run-task" data-id="${h(task.id)}">Run</button></td></tr>`).join('')}</tbody></table></div>` : emptyState('No queued tasks. Accept a plan or create a manual task.')}
        <div class="split-line"></div>
        <button class="btn ghost sm" data-action="create-task-modal">Create manual task</button>
      </div>
    </div>
    <div class="note mt-16"><strong>Guardrail:</strong> the CEO can plan, draft, and route work, but it cannot approve its own high-risk actions. Paid generation, credentials, and final publishing always route here.</div>
  `;
}

function initiativeCard(initiative) {
  const counts = initiative.task_counts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value), 0);
  const completed = Number(counts.completed || 0);
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const pending = initiative.status === 'plan_pending';
  return `<div class="card" style="padding:15px">
    <div class="between" style="align-items:flex-start">
      <div style="min-width:0"><div class="small muted">${h(initiative.id.slice(0, 8))} · ${timeAgo(initiative.created_at)}</div><div style="font-weight:600;font-size:13px;margin-top:3px">${h(truncate(initiative.objective, 120))}</div></div>
      <div class="pill-row">${statusBadge(initiative.status)}${riskBadge(initiative.risk_level)}</div>
    </div>
    <div class="small muted mt-8">${h(initiative.plan?.rationale || '')}</div>
    <div class="between mt-8"><span class="tiny faint">${completed}/${total} tasks complete</span><span class="mono tiny">${pct}%</span></div>
    <div class="progress mt-8"><span style="width:${pct}%"></span></div>
    <div class="btn-row mt-8">
      ${pending ? `<button class="btn green sm" data-action="decide-initiative" data-id="${h(initiative.id)}" data-decision="accepted">Accept plan</button><button class="btn red sm" data-action="decide-initiative" data-id="${h(initiative.id)}" data-decision="rejected">Reject</button>` : ''}
      <button class="btn ghost sm" data-action="open-initiative" data-id="${h(initiative.id)}">Inspect plan</button>
      ${initiative.status === 'active' ? `<button class="btn violet sm" data-action="tick-ceo">Run queued</button>` : ''}
    </div>
  </div>`;
}

/* -------------------------------------------------------------- departments */
async function renderDepartments() {
  const departments = await api('/departments');
  const workers = departments.flatMap((department) => department.workers || []);
  const active = workers.filter((worker) => worker.status === 'active').length;
  const openTasks = departments.reduce((sum, department) => sum + Number(department.open_tasks || 0), 0);
  return `
    <div class="section-head">
      <div><h2>An illustrated enterprise, backed by real records</h2><p>Every avatar opens the worker's assignment, status, evidence, permissions, and last action. Pausing a department stops its queue.</p></div>
      <div class="actions"><button class="btn" data-action="go" data-view="flow">Open department flow</button><button class="btn ghost" data-action="refresh">Refresh</button></div>
    </div>
    <div class="stat-strip mt-16" style="margin-bottom:16px">
      <div class="stat"><div class="n">${departments.length}</div><div class="l">Departments</div></div>
      <div class="stat"><div class="n">${workers.length}</div><div class="l">Workers</div></div>
      <div class="stat"><div class="n">${active}</div><div class="l">Active</div></div>
      <div class="stat"><div class="n">${openTasks}</div><div class="l">Open tasks</div></div>
    </div>
    <div class="department-grid">
      ${departments.map((department) => departmentCard(department)).join('')}
    </div>
  `;
}

function departmentCard(department) {
  const workers = department.workers || [];
  const activeWorkers = workers.filter((worker) => worker.status === 'active').length;
  const paused = department.paused || department.status === 'paused';
  return `<div class="card department-card">
    <div class="department-head">
      <div><h3>${h(department.name)}</h3><p>${h(department.description)}</p></div>
      <div class="pill-row">${statusBadge(department.status)}<span class="badge">${activeWorkers}/${workers.length} active</span></div>
    </div>
    <div class="department-body">
      ${department.manager ? `<div class="manager-row"><span class="avatar">${h(department.manager.avatar)}</span><div><div class="small" style="font-weight:600">${h(department.manager.name)}</div><div class="tiny muted">Manager · ${h(department.manager.role)}</div></div></div>` : ''}
      <div class="bar-row"><span>Queue</span><div class="progress ${department.open_tasks ? '' : 'green'}"><span style="width:${Math.min(100, Number(department.open_tasks || 0) * 12)}%"></span></div><strong>${department.open_tasks || 0} open</strong></div>
      <div class="worker-list mt-8">
        ${workers.map((worker) => `<div class="worker-row">
          <span class="avatar sm">${h(worker.avatar)}</span>
          <div class="who">
            <div class="name">${h(worker.name)} ${worker.status !== 'active' ? statusBadge(worker.status) : ''}</div>
            <div class="role">${h(worker.role)}${worker.current_task_title ? ` · ${h(truncate(worker.current_task_title, 34))}` : ''}</div>
            <div class="caps">${(worker.capabilities || []).slice(0, 3).map((cap) => `<span class="cap">${h(cap)}</span>`).join('')}</div>
          </div>
          <button class="btn xs ghost" data-action="open-worker" data-id="${h(worker.id)}">Open</button>
          ${worker.status === 'active'
            ? `<button class="btn xs red" data-action="pause-worker" data-id="${h(worker.id)}" title="Pause worker">Ⅱ</button>`
            : `<button class="btn xs green" data-action="resume-worker" data-id="${h(worker.id)}" title="Resume worker">▶</button>`}
        </div>`).join('')}
      </div>
      <div class="split-line"></div>
      <div class="between">
        <span class="tiny faint">${department.completed_tasks || 0} completed tasks</span>
        <button class="btn sm ${paused ? 'green' : 'ghost'}" data-action="toggle-department" data-id="${h(department.id)}" data-paused="${paused}">${paused ? 'Resume department' : 'Pause department'}</button>
      </div>
    </div>
  </div>`;
}

/* ------------------------------------------------------------ department flow */
const FLOW_POSITIONS = {
  research: { x: 205, y: 92 },
  creative: { x: 795, y: 155 },
  production: { x: 205, y: 218 },
  engineering: { x: 795, y: 281 },
  analytics: { x: 205, y: 344 },
  operations: { x: 795, y: 407 },
  publishing: { x: 205, y: 470 },
};

const FLOW_COLORS = { flow: '#ff3d8b', feedback: '#37e6b0', support: '#8b5cf6' };
const FLOW_FLOORS = [
  ['08', 'FOUNDER / CEO', 'Operational command'],
  ['07', 'RESEARCH & RIGHTS', 'Trend research, compliance'],
  ['06', 'CREATIVE', 'Format strategy, copywriting'],
  ['05', 'PRODUCTION', 'Asset creation, execution'],
  ['04', 'ENGINEERING & AUTOMATION', 'Pipeline engineering, tools'],
  ['03', 'ANALYTICS', 'Performance audit, reporting'],
  ['02', 'OPERATIONS & FINANCE', 'Queue manager, budgeting'],
  ['01', 'PUBLISHING', 'Metadata writing, scheduling'],
];

function flowEdgePath(edge) {
  const from = FLOW_POSITIONS[edge.source];
  const to = FLOW_POSITIONS[edge.target];
  if (!from || !to) return null;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const trim = 76;
  const sx = from.x + (dx / length) * trim;
  const sy = from.y + (dy / length) * trim;
  const ex = to.x - (dx / length) * trim;
  const ey = to.y - (dy / length) * trim;
  const c1x = sx + dx * 0.34;
  const c1y = sy + dy * 0.1;
  const c2x = ex - dx * 0.34;
  const c2y = ey - dy * 0.1;
  return {
    d: `M ${sx.toFixed(1)} ${sy.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${ex.toFixed(1)} ${ey.toFixed(1)}`,
    labelX: ((sx + ex) / 2).toFixed(1),
    labelY: ((sy + ey) / 2 - 7).toFixed(1),
  };
}

function flowNodeHTML(node, bottleneckId) {
  const position = FLOW_POSITIONS[node.id];
  if (!position) return '';
  const paused = node.paused || node.status === 'paused';
  const classes = ['flow-node'];
  if (node.id === bottleneckId) classes.push('bottleneck');
  if (paused) classes.push('paused');
  return `<button type="button" class="${classes.join(' ')}" data-action="open-department" data-id="${h(node.id)}" style="left:${(position.x / 10).toFixed(2)}%;top:${(position.y / 5.6).toFixed(2)}%">
    <div class="flow-node-head">
      <span class="flow-avatar">${h(node.manager?.avatar || '🏢')}</span>
      <span class="flow-node-status ${paused ? 'paused' : 'active'}"><i></i>${paused ? 'PAUSED' : 'ACTIVE'}</span>
    </div>
    <div class="flow-node-name">${h(node.name)}</div>
    <div class="flow-node-sub">${h(node.manager?.name || 'No manager')}</div>
    <div class="flow-node-stats"><span>${node.active_workers}/${node.worker_count} workers</span><span>${node.open_tasks} open</span></div>
    <div class="flow-node-io"><span>IN ${node.incoming}</span><span>OUT ${node.outgoing}</span><span>DONE ${node.completed_tasks}</span></div>
  </button>`;
}

async function renderFlow() {
  const data = await api('/departments/interactions');
  const summary = data.summary || {};
  const bottleneck = summary.bottleneck;
  const maxLoad = Math.max(1, ...data.nodes.map((node) => node.load || 0));
  const edges = data.edges || [];
  const nodeName = (id) => data.nodes.find((node) => node.id === id)?.name || id;
  const svgEdges = edges.map((edge) => {
    const path = flowEdgePath(edge);
    if (!path) return '';
    const active = edge.active > 0;
    const cls = ['flow-edge', edge.kind, active ? 'active' : '', edge.count === 0 ? 'baseline' : ''].filter(Boolean).join(' ');
    const width = Math.min(4.2, 1.4 + (edge.count || 0) * 0.35);
    return `<g class="${cls}">
      <title>${h(edge.label)} · ${edge.count} handoffs · ${edge.active} live · ${edge.completed} completed</title>
      <path d="${path.d}" stroke-width="${width}" marker-end="url(#arrow-${edge.kind})" />
      ${edge.count ? `<text class="flow-edge-label" x="${path.labelX}" y="${path.labelY}">${edge.count}</text>` : ''}
    </g>`;
  }).join('');
  return `
    <div class="section-head">
      <div><h2>Inside the enterprise building</h2><p>Each department is represented as an operating room. Animated lines are live handoffs through the building; dashed lines are support relationships that keep production unblocked.</p></div>
      <div class="actions"><button class="btn primary" data-action="run-handoffs">Run next handoffs</button><button class="btn ghost" data-action="go" data-view="departments">Department cards</button><button class="btn ghost" data-action="refresh">Refresh</button></div>
    </div>
    <div class="stat-strip" style="margin-bottom:16px">
      <div class="stat"><div class="n">${summary.cross_department_links || 0}</div><div class="l">Live cross-dept links</div></div>
      <div class="stat"><div class="n">${summary.active_handoffs || 0}</div><div class="l">Active handoffs</div></div>
      <div class="stat"><div class="n">${summary.completed_handoffs || 0}</div><div class="l">Completed handoffs</div></div>
      <div class="stat"><div class="n">${summary.queued_tasks || 0}</div><div class="l">Queued tasks</div></div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h3>Department interaction map</h3><div class="sub">${bottleneck ? `Bottleneck: ${h(bottleneck.name)} · ${bottleneck.load} open task${bottleneck.load === 1 ? '' : 's'}` : 'No bottleneck detected'}</div></div>
        <div class="flow-legend"><span><i style="border-color:var(--pink)"></i>Work handoff</span><span><i style="border-color:var(--mint)"></i>Feedback</span><span><i style="border-color:var(--violet);border-top-style:dashed"></i>Support</span></div>
      </div>
      <div class="flow-scroll">
        <div class="building-shell">
          <div class="building-roof" aria-hidden="true"><span>ENTERPRISE OPERATIONS CENTER</span><i></i><i></i><i></i></div>
          <div class="building-floor-labels" aria-hidden="true">
            ${FLOW_FLOORS.map(([floor, name]) => `<span><b>${floor}F</b>${name}</span>`).join('')}
          </div>
          <div class="building-map">
          <div class="building-command" aria-hidden="true"><strong>FOUNDER / CEO</strong><span>OPERATIONAL COMMAND</span><i></i></div>
          <div class="building-core" aria-hidden="true"><span>LIVE<br>DATA<br>CORE</span></div>
          <div class="building-floor-decks" aria-hidden="true">${FLOW_FLOORS.slice(1).map(([, name]) => `<span><b>${h(name)}</b></span>`).join('')}</div>
          <div class="building-entrance" aria-hidden="true"><span>MAIN LOBBY</span><i></i><i></i><i></i></div>
          <div class="flow-map">
          <div class="flow-map-grid" aria-hidden="true"></div>
          <svg class="flow-svg" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-label="Department interaction map">
            <defs>
              ${Object.entries(FLOW_COLORS).map(([kind, color]) => `<marker id="arrow-${kind}" markerWidth="9" markerHeight="9" refX="7.5" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L9,4.5 L0,9 z" fill="${color}"/></marker>`).join('')}
            </defs>
            ${svgEdges}
          </svg>
          ${data.nodes.map((node) => flowNodeHTML(node, bottleneck?.id)).join('')}
          </div>
          </div>
        </div>
      </div>
      <div class="note violet mt-16"><strong>Reading the flow:</strong> Research clears the source and brief; Creative turns the angle into a package; Production renders and QCs; Publishing schedules; Analytics feeds learning back to Creative and Research. Engineering and Operations support every lane.</div>
    </div>
    <div class="grid-2-1 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Live handoff log</h3><div class="sub">Cross-department task dependencies, newest first</div></div><span class="badge">${data.handoffs?.length || 0}</span></div>
        ${data.handoffs?.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>From</th><th>To</th><th>Task</th><th>Source</th><th>Target</th><th>Updated</th></tr></thead><tbody>${data.handoffs.map((handoff) => `<tr>
          <td><span class="flow-dept-chip">${h(handoff.source_name)}</span></td>
          <td><span class="flow-dept-chip target">${h(handoff.target_name)}</span></td>
          <td>${h(truncate(handoff.title, 52))}<div class="tiny faint">${h(truncate(handoff.depends_on, 70))}</div></td>
          <td>${statusBadge(handoff.source_status)}</td>
          <td>${statusBadge(handoff.target_status)}</td>
          <td class="tiny muted">${timeAgo(handoff.updated_at)}</td>
        </tr>`).join('')}</tbody></table></div>` : emptyState('No cross-department handoffs yet. Accept a CEO plan and run the next handoffs.', '⇄')}
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h3>Department load</h3><div class="sub">Open work by lane</div></div></div>
          ${[...data.nodes].sort((a, b) => b.load - a.load).map((node) => `<div class="bar-row" style="grid-template-columns:120px minmax(0,1fr) 56px">
            <span>${h(node.name)}</span>
            <div class="progress ${node.id === bottleneck?.id ? '' : 'green'}"><span style="width:${Math.round((node.load / maxLoad) * 100)}%"></span></div>
            <strong>${node.load} open</strong>
          </div>`).join('')}
          <div class="split-line"></div>
          <div class="between"><span class="small muted">Busiest handoff</span><span class="small">${summary.busiest_edge ? `${h(nodeName(summary.busiest_edge.source))} → ${h(nodeName(summary.busiest_edge.target))}` : '—'}</span></div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Department bus</h3><div class="sub">Latest task events</div></div><span class="badge">LIVE</span></div>
          ${data.bus?.length ? `<div class="timeline">${data.bus.slice(0, 10).map((event) => `<div class="timeline-item">
            <span class="timeline-dot ${event.event_type === 'completed' ? 'green' : event.event_type === 'failed' ? 'red' : 'pink'}"></span>
            <div class="timeline-body"><div class="timeline-title">${h(titleCase(event.event_type))} · ${h(event.department_name)}</div><div class="timeline-sub">${h(truncate(event.title, 72))}</div></div>
            <span class="timeline-time">${timeAgo(event.occurred_at)}</span>
          </div>`).join('')}</div>` : emptyState('No department events yet.', '📡')}
        </div>
      </div>
    </div>`;
}

async function openDepartmentModal(departmentId) {
  try {
    const departments = await api('/departments');
    const department = departments.find((item) => item.id === departmentId);
    if (!department) throw new Error('Department not found');
    const workers = department.workers || [];
    openModal(department.name, department.description, `
      <div class="between"><div class="flex items-center gap-10"><span class="avatar" style="width:44px;height:44px;font-size:20px">${h(department.manager?.avatar || '🏢')}</span><div><div class="small" style="font-weight:600">${h(department.manager?.name || 'No manager')}</div><div class="tiny muted">${h(department.manager?.role || '')}</div></div></div>${statusBadge(department.status)}</div>
      <div class="stat-strip mt-16" style="grid-template-columns:repeat(3,1fr)"><div class="stat"><div class="n">${department.worker_count}</div><div class="l">Workers</div></div><div class="stat"><div class="n">${department.open_tasks}</div><div class="l">Open tasks</div></div><div class="stat"><div class="n">${department.completed_tasks}</div><div class="l">Completed</div></div></div>
      <div class="split-line"></div><div class="small muted">Workers</div>
      <div class="worker-list mt-8" style="max-height:300px">${workers.map((worker) => `<div class="worker-row"><span class="avatar sm">${h(worker.avatar)}</span><div class="who"><div class="name">${h(worker.name)} ${worker.status !== 'active' ? statusBadge(worker.status) : ''}</div><div class="role">${h(worker.role)}</div><div class="caps">${(worker.capabilities || []).slice(0, 4).map((cap) => `<span class="cap">${h(cap)}</span>`).join('')}</div></div></div>`).join('')}</div>
      <div class="form-actions"><button class="btn ${department.paused ? 'green' : 'ghost'}" data-action="toggle-department" data-id="${h(department.id)}" data-paused="${department.paused}">${department.paused ? 'Resume department' : 'Pause department'}</button><button class="btn ghost" data-action="close-modal">Close</button></div>`, { wide: true });
  } catch (error) { toast(error.message, 'error'); }
}

/* ----------------------------------------------------------------- projects */
async function renderProjects() {
  const [businesses, initiatives] = await Promise.all([api('/businesses'), api('/initiatives')]);
  const main = businesses[0];
  const active = initiatives.filter((item) => item.status === 'active');
  const rules = main?.brand_rules || {};
  return `
    <div class="section-head"><div><h2>One tower, multiple businesses</h2><p>Shared assets and isolated workspaces. The first business is GTA 6 Clips; the core system is not rewritten for the next one.</p></div><div class="actions"><button class="btn ghost" data-action="create-business-modal">Add business</button></div></div>
    <div class="grid-2-1">
      <div class="card">
        <div class="card-head"><div><h3>${h(main?.name || 'No business')}</h3><div class="sub">Primary workspace · ${main?.departments || 0} departments · ${main?.initiatives || 0} initiatives</div></div><span class="badge green">ACTIVE</span></div>
        <div class="brand-rule-grid">
          <div class="brand-rule"><div class="k">Voice</div><div class="v">${h(rules.voice || '—')}</div></div>
          <div class="brand-rule"><div class="k">Target format</div><div class="v">${h(rules.target_format || '—')}</div></div>
          <div class="brand-rule"><div class="k">Attribution</div><div class="v">${h(rules.attribution || '—')}</div></div>
          <div class="brand-rule"><div class="k">Approval rule</div><div class="v">${h(rules.approval_rule || '—')}</div></div>
        </div>
        <div class="split-line"></div>
        <div class="small muted">Banned claims and practices</div>
        <div class="pill-row mt-8">${pills(rules.banned || [])}</div>
        <div class="note violet mt-16"><strong>Brand guardian:</strong> every script, cover, title, and caption is checked against these rules before founder review. Attribution is stored with the rights record, not added as an afterthought.</div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><div><h3>Workspace health</h3><div class="sub">Isolation and provenance</div></div></div>
          <div class="stat-strip" style="grid-template-columns:1fr 1fr"><div class="stat"><div class="n">${active.length}</div><div class="l">Active initiatives</div></div><div class="stat"><div class="n">${initiatives.length}</div><div class="l">Total initiatives</div></div></div>
          <div class="note green mt-16">Every asset, render, approval, and cost is scoped to this workspace and recorded in the local database.</div>
        </div>
        <div class="card"><div class="card-head"><div><h3>Future businesses</h3><div class="sub">Ready for the next game or creator partnership</div></div></div>
          <div class="small muted">Second game workspace</div><div class="tiny faint">Create a new business and reuse the same pipeline, rights gates, and approval queue.</div>
          <div class="split-line"></div>
          <div class="small muted">Creator partnership studio</div><div class="tiny faint">Source records, attribution, and revenue experiments stay isolated per partnership.</div>
        </div>
      </div>
    </div>
    <div class="card mt-16">
      <div class="card-head"><div><h3>Initiatives</h3><div class="sub">Strategy in flight</div></div></div>
      ${initiatives.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Objective</th><th>Risk</th><th>Status</th><th>Tasks</th><th>Created</th><th></th></tr></thead><tbody>${initiatives.map((item) => {
        const total = Object.values(item.task_counts || {}).reduce((sum, value) => sum + Number(value), 0);
        const completed = Number(item.task_counts?.completed || 0);
        return `<tr><td>${h(truncate(item.objective, 70))}</td><td>${riskBadge(item.risk_level)}</td><td>${statusBadge(item.status)}</td><td class="mono tiny">${completed}/${total}</td><td class="tiny muted">${fmtDate(item.created_at)}</td><td><button class="btn xs ghost" data-action="open-initiative" data-id="${h(item.id)}">Inspect</button></td></tr>`;
      }).join('')}</tbody></table></div>` : emptyState('No initiatives yet.')}
    </div>`;
}

/* --------------------------------------------------------------- production */
function assetCard(asset) {
  return `<div class="stage-card">
    <div class="title">${h(truncate(asset.filename || asset.id, 48))}</div>
    <div class="meta">${statusBadge(asset.status)}${asset.valid_rights ? '<span class="badge green">RIGHTS OK</span>' : '<span class="badge red">NO RIGHTS</span>'}</div>
    <div class="meta mt-8"><span>${asset.duration ? `${Number(asset.duration).toFixed(1)}s` : 'duration ?'}</span><span>·</span><span>${asset.candidates || 0} candidates</span><span>·</span><span>${asset.variants || 0} variants</span></div>
    <div class="actions">
      <button class="btn xs ${asset.valid_rights ? 'violet' : 'ghost'}" data-action="analyze-asset" data-id="${h(asset.id)}" ${asset.valid_rights ? '' : 'disabled title="Approve rights first"'}>Analyze</button>
      <button class="btn xs ghost" data-action="add-rights-modal" data-id="${h(asset.id)}">Rights</button>
      <button class="btn xs ghost" data-action="open-asset" data-id="${h(asset.id)}">Inspect</button>
    </div>
  </div>`;
}

function candidateCard(candidate) {
  return `<div class="stage-card">
    <div class="title">${h(truncate(candidate.hook || 'Untitled moment', 52))}</div>
    <div class="meta">${statusBadge(candidate.status)}<span>${(candidate.start_ms / 1000).toFixed(1)}s → ${(candidate.end_ms / 1000).toFixed(1)}s</span></div>
    <div class="score mt-8"><span>SCORE</span><div class="progress"><span style="width:${Math.round(Number(candidate.score || 0) * 100)}%"></span></div><strong>${Number(candidate.score || 0).toFixed(2)}</strong></div>
    <div class="tiny faint mt-8">${h(truncate(candidate.reason || '', 70))}</div>
    <div class="actions"><button class="btn xs primary" data-action="create-variants" data-id="${h(candidate.id)}">Create variants</button></div>
  </div>`;
}

function variantCard(variant) {
  return `<div class="stage-card">
    <div class="title">${h(truncate(variant.title, 52))}</div>
    <div class="meta">${statusBadge(variant.status)}<span>${h(titleCase(variant.style))}</span></div>
    <div class="meta mt-8"><span>QC ${h(variant.qc_status)}</span>${variant.render_uri ? '<span>· file ready</span>' : ''}</div>
    <div class="actions">
      ${['draft', 'render_failed', 'render_blocked', 'qc_failed'].includes(variant.status) ? `<button class="btn xs violet" data-action="render-variant" data-id="${h(variant.id)}">${variant.render_uri ? 'Re-render' : 'Render'}</button>` : ''}
      ${variant.render_uri && ['pending', 'failed', 'blocked'].includes(variant.qc_status) ? `<button class="btn xs green" data-action="qc-variant" data-id="${h(variant.id)}">${variant.qc_status === 'pending' ? 'Run QC' : 'Re-run QC'}</button>` : ''}
      ${variant.qc_status === 'passed' && variant.status === 'qc_passed' ? `<button class="btn xs primary" data-action="submit-review" data-id="${h(variant.id)}">Founder review</button>` : ''}
      ${variant.render_uri ? `<button class="btn xs ghost" data-action="open-variant" data-id="${h(variant.id)}">Preview</button>` : ''}
      ${variant.qc_status === 'passed' ? `<button class="btn xs ghost" data-action="publish-modal" data-id="${h(variant.id)}">Publish</button>` : ''}
    </div>
  </div>`;
}

async function renderProduction() {
  const [assets, candidates, variants, renderJobs, publishingJobs, posts, system] = await Promise.all([
    api('/assets'),
    api('/candidates'),
    api('/variants'),
    api('/render-jobs'),
    api('/publishing/jobs'),
    api('/publishing/posts'),
    api('/system/status'),
  ]);
  const intake = assets.filter((asset) => ['pending_rights', 'rights_pending', 'rights_approved', 'rights_rejected'].includes(asset.status));
  const analyzed = assets.filter((asset) => asset.status === 'analyzed');
  const variantsEditing = variants.filter((variant) => ['draft', 'rendered', 'render_failed', 'render_blocked', 'qc_failed'].includes(variant.status));
  const review = variants.filter((variant) => ['qc_passed', 'in_review'].includes(variant.status));
  const approved = variants.filter((variant) => ['approved', 'published', 'rejected'].includes(variant.status));
  const mediaReady = system.media_tools?.available;
  return `
    <div class="section-head"><div><h2>From local source to approval-ready short</h2><p>Ingest, analyze, create materially different drafts, render 9:16 locally, QC, then submit to the founder. Every step is evidence-backed.</p></div><div class="actions"><button class="btn ghost" data-action="refresh">Refresh board</button></div></div>
    ${!mediaReady ? `<div class="note danger" style="margin-bottom:16px"><strong>ffmpeg / ffprobe not detected.</strong> Ingest and metadata still work, but rendering and QC are blocked until both tools are installed.</div>` : ''}
    <div class="grid-2" style="margin-bottom:16px">
      <div class="card">
        <div class="card-head"><div><h3>Ingest a founder-owned file</h3><div class="sub">Hash, probe, and register provenance before analysis.</div></div></div>
        <form data-form="ingest"><div class="form-grid"><div class="field full"><label>Local path</label><input name="path" placeholder="/home/founder/footage/gta6-clip.mp4" required /></div><div class="field"><label>Owner</label><input name="owner" value="founder" /></div><div class="field"><label>Source URL (optional)</label><input name="source_url" placeholder="https://…" /></div></div><div class="form-actions"><button class="btn primary" type="submit">Ingest source</button></div></form>
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Upload source</h3><div class="sub">Stored locally under data/uploads. Unknown rights cannot render.</div></div></div>
        <form data-form="upload"><div class="upload-zone"><input type="file" name="file" required accept="video/*,audio/*,image/*" /><div class="tiny faint mt-8">Max ${Math.round(512)} MB · local only</div></div><div class="form-grid mt-8"><div class="field"><label>Owner</label><input name="owner" value="founder" /></div><div class="field"><label>Source URL</label><input name="source_url" placeholder="https://…" /></div></div><div class="form-actions"><button class="btn" type="submit">Upload and register</button></div></form>
      </div>
    </div>
    <div class="kanban">
      <div class="kanban-col"><div class="kanban-head"><h4>Intake · ${intake.length}</h4><span class="kanban-count">RIGHTS</span></div><div class="kanban-body">${intake.length ? intake.map(assetCard).join('') : emptyState('No sources waiting.', '📥')}</div></div>
      <div class="kanban-col"><div class="kanban-head"><h4>Analyzed · ${analyzed.length}</h4><span class="kanban-count">SOURCE</span></div><div class="kanban-body">${analyzed.length ? analyzed.map(assetCard).join('') : emptyState('Analyze an approved source.', '🎞️')}</div></div>
      <div class="kanban-col"><div class="kanban-head"><h4>Candidates · ${candidates.length}</h4><span class="kanban-count">SCORE</span></div><div class="kanban-body">${candidates.length ? candidates.map(candidateCard).join('') : emptyState('No highlight candidates.', '🔦')}</div></div>
      <div class="kanban-col"><div class="kanban-head"><h4>Edit &amp; QC · ${variantsEditing.length}</h4><span class="kanban-count">RENDER</span></div><div class="kanban-body">${variantsEditing.length ? variantsEditing.map(variantCard).join('') : emptyState('Create variants from a candidate.', '📱')}</div></div>
      <div class="kanban-col"><div class="kanban-head"><h4>Founder review · ${review.length}</h4><span class="kanban-count">APPROVAL</span></div><div class="kanban-body">${review.length ? review.map(variantCard).join('') : emptyState('No drafts in review.', '🎬')}</div></div>
      <div class="kanban-col"><div class="kanban-head"><h4>Approved · ${approved.length}</h4><span class="kanban-count">PUBLISH</span></div><div class="kanban-body">${approved.length ? approved.map(variantCard).join('') : emptyState('Approve a final video to unlock publishing.', '✅')}</div></div>
    </div>
    <div class="grid-2 mt-16">
      <div class="card"><div class="card-head"><div><h3>Publishing jobs</h3><div class="sub">Final video + publish approval are both enforced</div></div><span class="badge">${publishingJobs.length}</span></div>
        ${publishingJobs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Variant</th><th>Platform</th><th>Status</th><th>Schedule</th><th></th></tr></thead><tbody>${publishingJobs.slice(0, 8).map((job) => `<tr><td class="tiny">${h(truncate(job.variant?.title || job.video_variant_id, 38))}</td><td>${h(titleCase(job.platform))}</td><td>${statusBadge(job.status)}${job.post ? ` ${statusBadge(job.post.status)}` : ''}</td><td class="tiny muted">${job.schedule_at ? fmtDate(job.schedule_at) : 'immediate'}</td><td><div class="actions">${['ready', 'scheduled', 'published'].includes(job.status) && !job.post ? `<button class="btn xs green" data-action="publish-job" data-id="${h(job.id)}">Publish</button>` : ''}${job.post ? `<button class="btn xs ghost" data-action="reconcile-job" data-id="${h(job.id)}">Reconcile</button>` : ''}${job.status === 'pending_approval' ? `<button class="btn xs amber" data-action="go" data-view="approvals">Approve</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>` : emptyState('No publishing jobs yet. Approve a final video, then use Publish on its card.')}
      </div>
      <div class="card"><div class="card-head"><div><h3>Render jobs</h3><div class="sub">Local ffmpeg evidence</div></div><span class="badge">${renderJobs.length}</span></div>
        ${renderJobs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Error</th></tr></thead><tbody>${renderJobs.slice(0, 8).map((job) => `<tr><td class="mono tiny">${h(job.id.slice(0, 8))}</td><td>${statusBadge(job.status)}</td><td class="mono tiny">${job.progress || 0}%</td><td class="tiny muted">${h(truncate(job.error || '', 65))}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No render jobs yet.')}
      </div>
    </div>
    <div class="card mt-16"><div class="card-head"><div><h3>Published posts</h3><div class="sub">Dry-run unless explicitly enabled</div></div><span class="badge">${posts.length}</span></div>
      ${posts.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Platform</th><th>Post</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${posts.slice(0, 8).map((post) => `<tr><td>${h(titleCase(post.platform))}</td><td class="mono tiny">${h(post.external_post_id || '—')}</td><td>${statusBadge(post.status)}</td><td class="tiny muted">${fmtDate(post.created_at)}</td><td><a class="btn xs ghost" href="${h(post.url || '#')}" target="_blank" rel="noreferrer">Open</a></td></tr>`).join('')}</tbody></table></div>` : emptyState('No posts published yet.')}
    </div>`;
}

/* --------------------------------------------------------------- approvals */
async function renderApprovals() {
  const approvals = await api('/approvals');
  const filter = state.approvalsFilter;
  const visible = filter === 'all' ? approvals : approvals.filter((approval) => approval.status === filter);
  const counts = { pending: 0, approved: 0, rejected: 0 };
  approvals.forEach((approval) => { if (counts[approval.status] !== undefined) counts[approval.status] += 1; });
  return `
    <div class="section-head"><div><h2>One queue for consequential actions</h2><p>Rights, paid quotes, final videos, CUA sessions, and publishing. The founder is the only approver.</p></div><div class="actions"><button class="btn ghost" data-action="refresh">Refresh queue</button></div></div>
    <div class="stat-strip mt-16" style="margin-bottom:16px">
      <div class="stat"><div class="n">${counts.pending}</div><div class="l">Pending</div></div>
      <div class="stat"><div class="n">${counts.approved}</div><div class="l">Approved</div></div>
      <div class="stat"><div class="n">${counts.rejected}</div><div class="l">Rejected</div></div>
      <div class="stat"><div class="n">${approvals.length}</div><div class="l">All decisions</div></div>
    </div>
    <div class="tabs">${['pending', 'approved', 'rejected', 'all'].map((key) => `<button class="tab ${filter === key ? 'active' : ''}" data-action="approval-filter" data-filter="${key}">${titleCase(key)}</button>`).join('')}</div>
    <div class="card">
      <div class="card-head"><div><h3>${titleCase(filter)} approvals</h3><div class="sub">${visible.length} record${visible.length === 1 ? '' : 's'}</div></div><span class="badge ${filter === 'pending' ? 'amber' : filter === 'approved' ? 'green' : filter === 'rejected' ? 'red' : ''}">${visible.length}</span></div>
      ${visible.length ? `<div class="approval-list">${visible.map((approval) => approvalCard(approval)).join('')}</div>` : emptyState('Nothing in this state.', '✓')}
    </div>
    <div class="note mt-16"><strong>Approval policy:</strong> approving a plan queues tasks; approving a quote permits one provider job; approving a final video permits a publishing job; approving a publish job permits one dry-run or live publish action. Every decision is recorded with an audit event.</div>`;
}

/* -------------------------------------------------------------- assets/rights */
function rightsRow(record) {
  return `<tr>
    <td>${h(record.owner)}<div class="tiny faint">${h(record.license_type)}</div></td>
    <td class="mono tiny">${h((record.platforms || []).join(', ') || 'all')}</td>
    <td>${record.commercial_use ? '<span class="badge green">COMMERCIAL</span>' : '<span class="badge red">NON-COMMERCIAL</span>'}</td>
    <td>${statusBadge(record.status)}${record.expired ? '<div class="expired-note">expired</div>' : ''}</td>
    <td class="tiny muted">${record.expires_at ? fmtDate(record.expires_at) : '—'}</td>
    <td class="tiny muted">${h(truncate(record.attribution || record.proof_uri || '—', 36))}</td>
    <td class="tiny muted">${h(record.filename || record.source_asset_id)}</td>
  </tr>`;
}

async function renderAssets() {
  const [assets, rights] = await Promise.all([api('/assets'), api('/rights')]);
  const approved = rights.filter((record) => record.status === 'approved' && record.commercial_use && !record.expired);
  return `
    <div class="section-head"><div><h2>Provenance before production</h2><p>Every source records owner, license, platforms, commercial use, attribution, expiry, proof, and approval. Unknown rights never enter rendering.</p></div><div class="actions"><button class="btn ghost" data-action="refresh">Refresh</button></div></div>
    <div class="stat-strip mt-16" style="margin-bottom:16px">
      <div class="stat"><div class="n">${assets.length}</div><div class="l">Source assets</div></div>
      <div class="stat"><div class="n">${rights.length}</div><div class="l">Rights records</div></div>
      <div class="stat"><div class="n">${approved.length}</div><div class="l">Approved commercial</div></div>
      <div class="stat"><div class="n">${rights.filter((record) => record.status === 'pending').length}</div><div class="l">Awaiting review</div></div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-head"><div><h3>Upload local source</h3><div class="sub">The file is stored on this machine only.</div></div><span class="badge">LOCAL</span></div>
        <form data-form="upload"><div class="upload-zone"><input type="file" name="file" required accept="video/*,audio/*,image/*" /><div class="tiny faint mt-8">After upload, add a rights record and approve it in the queue.</div></div><div class="form-grid mt-8"><div class="field"><label>Owner</label><input name="owner" value="founder" /></div><div class="field"><label>Source URL</label><input name="source_url" placeholder="https://…" /></div></div><div class="form-actions"><button class="btn primary" type="submit">Upload source</button></div></form>
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Register a local path</h3><div class="sub">Useful for founder recordings already on disk.</div></div><span class="badge">INGEST</span></div>
        <form data-form="ingest"><div class="field"><label>File path</label><input name="path" placeholder="/home/founder/footage/source.mp4" required /></div><div class="form-grid mt-8"><div class="field"><label>Owner</label><input name="owner" value="founder" /></div><div class="field"><label>Source URL</label><input name="source_url" placeholder="https://…" /></div></div><div class="form-actions"><button class="btn" type="submit">Register path</button></div></form>
      </div>
    </div>
    <div class="card mt-16">
      <div class="card-head"><div><h3>Source assets</h3><div class="sub">Hash, technical metadata, rights state, and pipeline actions</div></div><span class="badge">${assets.length}</span></div>
      ${assets.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>File</th><th>Status</th><th>Rights</th><th>Duration</th><th>Hash</th><th>Created</th><th></th></tr></thead><tbody>${assets.map((asset) => `<tr>
        <td>${h(asset.filename || asset.id)}<div class="tiny faint">${h(truncate(asset.path || '', 48))}</div></td>
        <td>${statusBadge(asset.status)}</td>
        <td>${asset.valid_rights ? '<span class="badge green">VALID</span>' : '<span class="badge red">BLOCKED</span>'}</td>
        <td class="mono tiny">${asset.duration ? `${Number(asset.duration).toFixed(1)}s` : '—'}</td>
        <td class="mono tiny">${h((asset.sha256 || '').slice(0, 12))}…</td>
        <td class="tiny muted">${fmtDate(asset.created_at)}</td>
        <td><div class="actions"><button class="btn xs ghost" data-action="open-asset" data-id="${h(asset.id)}">Inspect</button><button class="btn xs ghost" data-action="add-rights-modal" data-id="${h(asset.id)}">Add rights</button><button class="btn xs violet" data-action="analyze-asset" data-id="${h(asset.id)}" ${asset.valid_rights ? '' : 'disabled'}>Analyze</button></div></td>
      </tr>`).join('')}</tbody></table></div>` : emptyState('No source assets yet. Upload or register a founder-owned file.')}
    </div>
    <div class="card mt-16">
      <div class="card-head"><div><h3>Rights records</h3><div class="sub">Approval is required before an asset can be analyzed, rendered, or published.</div></div><span class="badge">${rights.length}</span></div>
      ${rights.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Owner</th><th>Platforms</th><th>Commercial</th><th>Status</th><th>Expires</th><th>Attribution / proof</th><th>Asset</th></tr></thead><tbody>${rights.map(rightsRow).join('')}</tbody></table></div>` : emptyState('No rights records yet. Add rights to a source asset.')}
    </div>`;
}

/* -------------------------------------------------------------- integrations */
async function renderIntegrations() {
  const [providers, quotes, jobs, servers, tools, calls, accounts] = await Promise.all([
    api('/providers'),
    api('/providers/everygen/quotes'),
    api('/providers/everygen/jobs'),
    api('/mcp/servers'),
    api('/mcp/tools'),
    api('/mcp/tool-calls'),
    api('/publishing/accounts'),
  ]);
  state.mcpServers = servers;
  const everygen = providers.everygen || {};
  const local = providers.local?.media_tools || {};
  return `
    <div class="section-head"><div><h2>Typed integrations, explicit boundaries</h2><p>MCP is the control plane. Everygen is optional and quote-gated. CUA is a guarded fallback. Live publishing stays dry-run until reviewed.</p></div><div class="actions"><button class="btn ghost" data-action="refresh">Refresh</button></div></div>
    <div class="grid-3">
      <div class="card integration-card">
        <div class="integration-head"><div class="integration-logo">🎬</div><span class="badge ${local.available ? 'green' : 'red'}">${local.available ? 'READY' : 'MISSING'}</span></div>
        <div><h3>Local media tools</h3><div class="tiny muted">ffmpeg + ffprobe · no external calls</div></div>
        <div class="kv"><dt>ffmpeg</dt><dd class="mono tiny">${h(local.ffmpeg || 'not found')}</dd><dt>ffprobe</dt><dd class="mono tiny">${h(local.ffprobe || 'not found')}</dd></div>
        <div class="note green">Rendering, QC, and captions run locally even when every provider is disabled.</div>
      </div>
      <div class="card integration-card">
        <div class="integration-head"><div class="integration-logo">✨</div><span class="badge ${everygen.enabled ? 'amber' : ''}">${everygen.enabled ? (everygen.mock ? 'MOCK MODE' : 'LIVE MODE') : 'DISABLED'}</span></div>
        <div><h3>Everygen.ai</h3><div class="tiny muted">Optional remote creative provider</div></div>
        <div class="kv"><dt>Budget</dt><dd>${fmtMoney(everygen.budget_usd)}</dd><dt>Spent</dt><dd>${fmtMoney(everygen.spent_usd)}</dd><dt>Remaining</dt><dd>${fmtMoney(everygen.remaining_usd)}</dd><dt>Live adapter</dt><dd>${everygen.live_adapter_configured ? 'configured' : 'not configured'}</dd></div>
        <div class="note ${everygen.enabled ? '' : 'danger'}">${everygen.enabled ? 'Quotes are required before any generation job. Mock mode never contacts the provider.' : 'Disabled by configuration. Local production continues normally.'}</div>
      </div>
      <div class="card integration-card">
        <div class="integration-head"><div class="integration-logo">🔌</div><span class="badge ${servers.length ? 'green' : ''}">${servers.length} SERVERS</span></div>
        <div><h3>MCP gateway</h3><div class="tiny muted">Registry, scopes, risk, and audit</div></div>
        <div class="stat-strip" style="grid-template-columns:1fr 1fr"><div class="stat"><div class="n">${tools.length}</div><div class="l">Tools</div></div><div class="stat"><div class="n">${calls.length}</div><div class="l">Calls</div></div></div>
        <div class="note violet">Live MCP transport is disabled in this local build. Calls are recorded for audit until a verified server adapter is configured.</div>
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Everygen quote</h3><div class="sub">Quote before spend. A founder approval is created automatically.</div></div><span class="badge ${everygen.enabled ? 'amber' : ''}">${everygen.enabled ? 'ENABLED' : 'DISABLED'}</span></div>
        <form data-form="provider-quote">
          <div class="form-grid">
            <div class="field"><label>Kind</label><select name="kind"><option value="image">Image</option><option value="video" selected>Video</option><option value="voice">Voice</option></select></div>
            <div class="field"><label>Duration (seconds)</label><input name="duration_seconds" type="number" min="0" step="1" value="15" /></div>
            <div class="field full"><label>Prompt / request</label><textarea name="prompt" placeholder="A stylized thumbnail concept for a rights-cleared reaction short…" required></textarea></div>
          </div>
          <div class="form-actions"><button class="btn primary" type="submit" ${everygen.enabled ? '' : 'disabled'}>Request quote</button><span class="tiny faint">No paid call is made by requesting a quote.</span></div>
        </form>
        ${quotes.length ? `<div class="split-line"></div><div class="small muted">Quotes</div><div class="table-wrap mt-8"><table class="table"><thead><tr><th>Kind</th><th>Credits</th><th>Cost</th><th>Status</th><th></th></tr></thead><tbody>${quotes.slice(0, 8).map((quote) => `<tr><td>${h(quote.request?.kind || '—')}</td><td class="mono tiny">${quote.credits}</td><td class="mono tiny">${fmtMoney(quote.cost_usd)}</td><td>${statusBadge(quote.status)}</td><td><div class="actions"><button class="btn xs ghost" data-action="open-quote" data-id="${h(quote.id)}">Inspect</button>${quote.status === 'approved' ? `<button class="btn xs amber" data-action="provider-job" data-id="${h(quote.id)}">Create job</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>` : ''}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Provider jobs</h3><div class="sub">Mock mode advances one step per poll</div></div><span class="badge">${jobs.length}</span></div>
        ${jobs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Provider</th><th>Status</th><th>Mock</th><th>Result</th><th></th></tr></thead><tbody>${jobs.slice(0, 8).map((job) => `<tr><td class="mono tiny">${h(job.provider)}</td><td>${statusBadge(job.status)}</td><td>${job.mock ? '<span class="badge amber">MOCK</span>' : '<span class="badge red">LIVE</span>'}</td><td class="tiny muted">${h(truncate(job.result_uri || job.error || '—', 36))}</td><td><div class="actions">${!['succeeded', 'failed', 'cancelled'].includes(job.status) ? `<button class="btn xs violet" data-action="poll-provider" data-id="${h(job.id)}">Poll</button><button class="btn xs red" data-action="cancel-provider" data-id="${h(job.id)}">Cancel</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>` : emptyState('No provider jobs yet.')}
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>MCP registry</h3><div class="sub">Register servers and tools; high-risk calls need approval.</div></div><span class="badge">${servers.length}</span></div>
        <form data-form="mcp-server"><div class="form-grid"><div class="field"><label>Name</label><input name="name" placeholder="local-tools" required /></div><div class="field"><label>Transport</label><select name="transport"><option>stdio</option><option>http</option><option>sse</option><option>streamable-http</option></select></div><div class="field full"><label>Endpoint</label><input name="endpoint" placeholder="stdio://local-tools" required /></div></div><div class="form-actions"><button class="btn violet" type="submit">Register server</button></div></form>
        ${servers.length ? `<div class="split-line"></div><div class="stack">${servers.map((server) => `<div class="approval-card"><div class="approval-icon">🔌</div><div><div class="approval-title">${h(server.name)}</div><div class="approval-meta">${statusBadge(server.status)}<span>${h(server.transport)}</span><span>${server.tool_count} tools</span><span>${server.call_count} calls</span></div><div class="tiny faint">${h(server.endpoint)}</div></div><div class="approval-actions"><button class="btn xs ghost" data-action="mcp-connect" data-id="${h(server.id)}">Check health</button><button class="btn xs ghost" data-action="mcp-tool-modal" data-id="${h(server.id)}">Add tool</button></div></div>`).join('')}</div>` : emptyState('No MCP servers registered.')}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Tool calls</h3><div class="sub">Every invocation is hashed and recorded</div></div><span class="badge">${calls.length}</span></div>
        ${tools.length ? `<div class="form-actions" style="margin-top:0;margin-bottom:10px"><button class="btn sm violet" data-action="mcp-call-modal">Invoke a tool</button></div><div class="table-wrap"><table class="table"><thead><tr><th>Tool</th><th>Risk</th><th>Server</th><th>State</th></tr></thead><tbody>${tools.map((tool) => `<tr><td class="mono tiny">${h(tool.name)}</td><td><span class="badge ${tool.risk === 'high' ? 'red' : tool.risk === 'medium' ? 'amber' : 'green'}">${h(tool.risk)}</span></td><td class="tiny">${h(tool.server?.name || '')}</td><td>${tool.enabled ? '<span class="badge green">ENABLED</span>' : '<span class="badge red">DISABLED</span>'}</td></tr>`).join('')}</tbody></table></div>` : emptyState('Register a server and add a tool.')}
        ${calls.length ? `<div class="split-line"></div><div class="small muted">Recent calls</div><div class="timeline mt-8">${calls.slice(0, 6).map((call) => `<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><div class="timeline-title">${h(call.tool_name)}</div><div class="timeline-sub">${h(call.status)} · ${h((call.output_ref || '').slice(0, 60))}</div></div><span class="timeline-time">${timeAgo(call.created_at)}</span></div>`).join('')}</div>` : ''}
      </div>
    </div>

    <div class="grid-2 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Publishing accounts</h3><div class="sub">Credential references only; secrets stay outside the repository.</div></div><span class="badge ${providers.publishing?.dry_run ? 'violet' : ''}">${providers.publishing?.dry_run ? 'DRY-RUN' : 'LIVE'}</span></div>
        <form data-form="publishing-account"><div class="form-grid"><div class="field"><label>Platform</label><select name="platform"><option value="youtube">YouTube</option><option value="tiktok">TikTok</option></select></div><div class="field"><label>Display name</label><input name="display_name" placeholder="GTA 6 Clips" required /></div><div class="field full"><label>Credential reference (never a secret)</label><input name="credential_ref" placeholder="vault://youtube/main" /></div></div><div class="form-actions"><button class="btn" type="submit">Add account</button></div></form>
        ${accounts.length ? `<div class="table-wrap mt-16"><table class="table"><thead><tr><th>Platform</th><th>Account</th><th>Credential ref</th><th>Status</th></tr></thead><tbody>${accounts.map((account) => `<tr><td>${h(titleCase(account.platform))}</td><td>${h(account.display_name)}</td><td class="mono tiny">${h(account.credential_ref || '—')}</td><td>${statusBadge(account.status)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No publishing accounts configured.')}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Integration safety</h3><div class="sub">The boundaries are enforced in code</div></div><span class="badge red">HARD GATES</span></div>
        <div class="alert-stack">
          <div class="alert info"><span class="icon">✓</span><div><strong>MCP before CUA</strong><span>Structured tools are preferred; CUA is observe/draft only.</span></div></div>
          <div class="alert warning"><span class="icon">✓</span><div><strong>Quote before spend</strong><span>No provider job without an approved quote and budget headroom.</span></div></div>
          <div class="alert warning"><span class="icon">✓</span><div><strong>Approval before publish</strong><span>Final video and publish job both require founder decisions.</span></div></div>
          <div class="alert info"><span class="icon">✓</span><div><strong>Dry-run by default</strong><span>No live platform API is contacted until an adapter is configured and reviewed.</span></div></div>
        </div>
      </div>
    </div>`;
}

/* ---------------------------------------------------------------------- CUA */
async function renderCUA() {
  const [sessions, actions, providers] = await Promise.all([
    api('/cua/sessions'),
    api('/cua/actions'),
    api('/providers'),
  ]);
  const cuaConfig = providers.cua || {};
  const active = sessions.filter((session) => session.status === 'active').length;
  return `
    <div class="section-head"><div><h2>Guarded computer use</h2><p>Allowlisted domains, per-session capability tokens, action limits, expiry, evidence files, and an emergency stop. Publishing is never available here.</p></div><div class="actions"><button class="btn red" data-action="cua-emergency">CUA emergency stop</button></div></div>
    <div class="note ${cuaConfig.enabled ? 'green' : 'danger'}" style="margin-bottom:16px"><strong>CUA is ${cuaConfig.enabled ? 'enabled for observe/draft sessions' : 'disabled by configuration'}.</strong> ${cuaConfig.enabled ? `Allowed domains: ${h((cuaConfig.allowed_domains || []).join(', '))}. Max ${cuaConfig.max_actions} actions · ${cuaConfig.session_minutes} minute sessions.` : 'Enable CUA_ENABLED only after the policy review and sandbox test pass.'}</div>
    <div class="stat-strip" style="margin-bottom:16px">
      <div class="stat"><div class="n">${sessions.length}</div><div class="l">Sessions</div></div>
      <div class="stat"><div class="n">${active}</div><div class="l">Active</div></div>
      <div class="stat"><div class="n">${actions.length}</div><div class="l">Recorded actions</div></div>
      <div class="stat"><div class="n">${(cuaConfig.allowed_domains || []).length}</div><div class="l">Allowlisted domains</div></div>
    </div>
    <div class="grid-2-1">
      <div class="card">
        <div class="card-head"><div><h3>Sessions</h3><div class="sub">Requests wait for founder approval before activation.</div></div><span class="badge">${sessions.length}</span></div>
        ${sessions.length ? `<div class="stack">${sessions.map((session) => `<div class="card" style="padding:14px">
          <div class="between" style="align-items:flex-start"><div><div class="approval-title">${h(session.target)}</div><div class="approval-meta">${statusBadge(session.status)}<span class="badge ${session.mode === 'draft' ? 'amber' : 'blue'}">${h(session.mode)}</span><span>${session.actions_used}/${session.max_actions} actions</span>${session.expires_at ? `<span>expires ${fmtDate(session.expires_at)}</span>` : ''}</div></div><div class="approval-actions">
            ${session.activation_required ? `<button class="btn xs amber" data-action="go" data-view="approvals">Approve in queue</button><button class="btn xs ghost" data-action="cua-activate" data-id="${h(session.id)}">Activate</button>` : ''}
            ${session.status === 'active' ? `<button class="btn xs violet" data-action="cua-action-modal" data-id="${h(session.id)}" data-mode="${h(session.mode)}">Record action</button><button class="btn xs red" data-action="cua-stop" data-id="${h(session.id)}">Stop</button>` : ''}
            <button class="btn xs ghost" data-action="open-cua" data-id="${h(session.id)}">Inspect</button>
          </div></div>
          ${session.approval ? `<div class="tiny faint mt-8">Approval ${h(session.approval.status)} · ${h(session.id.slice(0, 8))} · evidence under data/evidence</div>` : ''}
        </div>`).join('')}</div>` : emptyState('No CUA sessions. Create a request below.')}
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h3>Request a session</h3><div class="sub">Observe is read-only. Draft adds form interaction.</div></div><span class="badge ${cuaConfig.enabled ? 'amber' : ''}">${cuaConfig.enabled ? 'ARMED' : 'OFF'}</span></div>
          <form data-form="cua"><div class="field"><label>Target URL or domain</label><input name="target" placeholder="https://studio.youtube.com" required /></div><div class="field mt-8"><label>Mode</label><select name="mode"><option value="observe">Observe (read-only)</option><option value="draft">Draft (fill, click, hover)</option></select></div><div class="form-actions"><button class="btn primary" type="submit" ${cuaConfig.enabled ? '' : 'disabled'}>Create approval request</button></div></form>
          <div class="note danger mt-16"><strong>Never available:</strong> publish, delete, payment, CAPTCHA bypass, rate-limit bypass, credential entry.</div>
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Recent actions</h3><div class="sub">Evidence files are written locally</div></div><span class="badge">${actions.length}</span></div>
          ${actions.length ? `<div class="timeline">${actions.slice(0, 8).map((action) => `<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><div class="timeline-title">${h(action.action_type)}</div><div class="timeline-sub">${h(truncate(action.target || action.evidence_uri || '', 90))}</div></div><span class="timeline-time">${timeAgo(action.created_at)}</span></div>`).join('')}</div>` : emptyState('No CUA actions recorded.')}
        </div>
      </div>
    </div>`;
}

/* ----------------------------------------------------------------- pipeline */
async function renderPipeline() {
  const [status, links, generations, posts, runs] = await Promise.all([
    api('/pipeline/status'),
    api('/pipeline/links?limit=8'),
    api('/pipeline/generations?limit=8'),
    api('/pipeline/posts?limit=8'),
    api('/pipeline/runs?limit=5'),
  ]);
  const db = status.db || {};
  const config = status.settings || {};
  const sandbox = status.sandbox || {};
  const linkStats = db.links || {};
  const generationStats = db.generations || {};
  const postStats = db.posts || {};
  const totalLinks = Object.values(linkStats).reduce((sum, value) => sum + Number(value || 0), 0);
  const totalReady = Number(generationStats.ready || 0) + Number(generationStats.partially_published || 0);
  const totalPublished = Number(postStats.published || 0);
  const viewer = status.view_url || sandbox.view || '';
  const sandboxState = sandbox.state || (sandbox.ok ? 'unknown' : 'offline');
  const isClip = (config.mode || 'generate') === 'clip';
  return `
    <div class="section-head"><div><h2>Zero-key CUA automation</h2><p>${isClip ? 'YouTube discovery → local yt-dlp highlight clipping → YouTube Shorts + TikTok. Free, no Everygen credits.' : 'YouTube discovery → Everygen Shorts Studio → download → YouTube Shorts + TikTok.'} The owner's signed-in Cua VM is the only browser; no platform API keys are used.</p></div><div class="actions"><a class="btn ghost" href="/api/pipeline/showcase" target="_blank" rel="noopener">Clip showcase</a><button class="btn ghost" data-action="refresh">Refresh</button>${viewer ? `<a class="btn primary" href="${h(viewer)}" target="_blank" rel="noopener">Open CUA viewer</a>` : ''}</div></div>
    <div class="note ${sandboxState === 'running' || sandboxState === 'ready' ? 'green' : 'danger'}" style="margin-bottom:16px"><strong>Mode: ${isClip ? 'CLIP (free local FFmpeg)' : 'GENERATE (Everygen)'}.</strong> CUA sandbox: ${h(sandboxState)}. ${sandboxState === 'running' || sandboxState === 'ready' ? 'Signed-in sessions are reused; the pipeline never asks for passwords.' : 'Start or recover the sandbox with <code>python -m pipeline.run prepare</code>.'} Live posting is ${config.live_default ? '<strong>enabled by default</strong>' : '<strong>off by default</strong>'}.</div>
    <div class="stat-strip" style="margin-bottom:16px">
      <div class="stat"><div class="n">${fmtNum(totalLinks)}</div><div class="l">Discovered links</div></div>
      <div class="stat"><div class="n">${fmtNum(totalReady)}</div><div class="l">Shorts ready</div></div>
      <div class="stat"><div class="n">${fmtNum(totalPublished)}</div><div class="l">Published posts</div></div>
      <div class="stat"><div class="n">${fmtNum(generationStats.published || 0)}</div><div class="l">Fully published</div></div>
      <div class="stat"><div class="n">${fmtNum(postStats.dry_run || 0)}</div><div class="l">Dry-run checks</div></div>
    </div>
    <div class="grid-2-1">
      <div class="card">
        <div class="card-head"><div><h3>Latest discovered sources</h3><div class="sub">Ranked public YouTube results; no account or API key</div></div><span class="badge">${links.length}</span></div>
        ${links.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Source</th><th>Views</th><th>Status</th><th>Discovered</th></tr></thead><tbody>${links.map((link) => `<tr><td><div class="approval-title">${h(truncate(link.title || link.url, 64))}</div><div class="tiny mono muted">${h(truncate(link.url, 78))}</div></td><td class="tiny">${h(link.view_count || '—')}</td><td>${statusBadge(link.status)}${link.error ? `<div class="tiny faint">${h(truncate(link.error, 60))}</div>` : ''}</td><td class="tiny muted">${timeAgo(link.discovered_at)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No sources yet. Run: python -m pipeline.run discover')}
      </div>
      <div class="stack">
        ${isClip ? `<div class="card">
          <div class="card-head"><div><h3>Add YouTube sources</h3><div class="sub">One link per line — multiple people or streams</div></div><span class="badge green">CLIP</span></div>
          <form data-form="pipeline-clip">
            <div class="field"><label>YouTube links</label><textarea name="urls" rows="4" placeholder="https://www.youtube.com/watch?v=..." required></textarea></div>
            <div class="form-grid mt-8">
              <div class="field"><label>Clips per source</label><input name="count" type="number" min="1" max="6" value="${fmtNum(config.clip_count || 2)}" /></div>
              <div class="field"><label>Rights</label><label class="tiny"><input type="checkbox" name="rights_ack" required /> I have permission to reuse these videos</label></div>
            </div>
            <div class="form-actions"><button class="btn primary" type="submit">Queue &amp; clip</button></div>
          </form>
        </div>` : ''}
        <div class="card">
          ${isClip ? `<div class="card-head"><div><h3>Clip settings</h3><div class="sub">Local yt-dlp + FFmpeg, no credits</div></div><span class="badge green">FREE</span></div>
          <div class="mini-grid">
            <div><div class="l">Clips / source</div><div class="v">${fmtNum(config.clip_count)}</div></div>
            <div><div class="l">Clip length</div><div class="v">${fmtNum(config.clip_min_seconds)}–${fmtNum(config.clip_max_seconds)}s</div></div>
            <div><div class="l">Quality</div><div class="v">${fmtNum(config.clip_quality)}p</div></div>
            <div><div class="l">Layout</div><div class="v">${h(config.clip_layout || 'streamer')}</div></div>
            <div><div class="l">Overlays</div><div class="v">${config.clip_show_title || config.clip_show_captions ? [config.clip_show_title ? 'title' : '', config.clip_show_captions ? 'captions' : ''].filter(Boolean).join(' + ') : 'clean'}</div></div>
            <div><div class="l">Rights ack</div><div class="v">${config.rights_ack ? 'confirmed' : 'required'}</div></div>
          </div>` : `<div class="card-head"><div><h3>Everygen settings</h3><div class="sub">Browser-driven Shorts Studio</div></div><span class="badge violet">${h(config.everygen_format || 'GTA 6')}</span></div>
          <div class="mini-grid">
            <div><div class="l">Format</div><div class="v">${h(config.everygen_format || '—')}</div></div>
            <div><div class="l">Variants / link</div><div class="v">${fmtNum(config.variants_per_link)}</div></div>
            <div><div class="l">Shorts / cycle</div><div class="v">${fmtNum(config.max_shorts_per_cycle)}</div></div>
            <div><div class="l">Credit budget</div><div class="v">${config.everygen_budget_credits ? fmtNum(config.everygen_budget_credits) : 'unlimited'}</div></div>
          </div>`}
        </div>
        <div class="card">
          <div class="card-head"><div><h3>Publishing guard rails</h3><div class="sub">Per-platform caps are enforced before upload</div></div><span class="badge ${config.live_default ? 'amber' : 'green'}">${config.live_default ? 'LIVE' : 'DRY RUN'}</span></div>
          <div class="mini-grid">
            <div><div class="l">Platforms</div><div class="v">${h((config.platforms || []).join(', ') || '—')}</div></div>
            <div><div class="l">YouTube / day</div><div class="v">${fmtNum(config.daily_limit_youtube)}</div></div>
            <div><div class="l">TikTok / day</div><div class="v">${fmtNum(config.daily_limit_tiktok)}</div></div>
            <div><div class="l">Sandbox</div><div class="v">${h(sandboxState)}</div></div>
          </div>
          <div class="note info mt-16"><strong>Run it:</strong> ${isClip ? '<code>python -m pipeline.run clip --url &lt;youtube-link&gt; --rights-ack</code> for one source, or <code>python -m pipeline.run cycle --mode clip --live</code> to repeat.' : '<code>python -m pipeline.run cycle</code> for a dry run, <code>python -m pipeline.run cycle --live</code> to publish, or <code>python -m pipeline.run worker --live</code> to repeat on an interval.'}</div>
        </div>
      </div>
    </div>
    <div class="card mt-16">
      <div class="card-head"><div><h3>${isClip ? 'Local clips' : 'Generated shorts'}</h3><div class="sub">${isClip ? 'YouTube highlights rendered vertically, waiting for or completing publishing' : 'Everygen downloads waiting for or completing publishing'}</div></div><span class="badge">${generations.length}</span></div>
      ${generations.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>#</th><th>Source</th><th>Variant</th><th>Status</th><th>Credits</th><th>File</th><th>Play</th><th>Updated</th></tr></thead><tbody>${generations.map((generation) => `<tr><td class="mono tiny">${h(generation.id)}</td><td class="mono tiny">${h(generation.link_id)}</td><td class="mono tiny">${h(generation.variant)}</td><td>${statusBadge(generation.status)}${generation.error ? `<div class="tiny faint">${h(truncate(generation.error, 70))}</div>` : ''}</td><td class="tiny">${generation.credits ? fmtNum(generation.credits) : '—'}</td><td class="tiny mono">${h(truncate(generation.host_path || '—', 52))}</td><td>${(generation.host_path || '').split('/').pop() ? `<a class="btn xs ghost" href="/api/pipeline/videos/${encodeURIComponent((generation.host_path || '').split('/').pop())}" target="_blank" rel="noopener">Play</a>` : '—'}</td><td class="tiny muted">${timeAgo(generation.updated_at)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No generated clips yet.')}
    </div>
    <div class="grid-2-1 mt-16">
      <div class="card">
        <div class="card-head"><div><h3>Publish attempts</h3><div class="sub">One row per platform, never duplicated</div></div><span class="badge">${posts.length}</span></div>
        ${posts.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Generation</th><th>Platform</th><th>Status</th><th>Attempts</th><th>Updated</th></tr></thead><tbody>${posts.map((post) => `<tr><td class="mono tiny">${h(post.generation_id)}</td><td>${h(titleCase(post.platform))}</td><td>${statusBadge(post.status)}${post.error ? `<div class="tiny faint">${h(truncate(post.error, 70))}</div>` : ''}${post.remote_hint ? `<div class="tiny mono faint">${h(truncate(post.remote_hint, 70))}</div>` : ''}</td><td class="tiny">${fmtNum(post.attempts)}</td><td class="tiny muted">${timeAgo(post.updated_at)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No publish attempts yet.')}
      </div>
      <div class="card">
        <div class="card-head"><div><h3>Recent cycles</h3><div class="sub">Run state persists even after a crash</div></div><span class="badge">${runs.length}</span></div>
        ${runs.length ? `<div class="timeline">${runs.map((run) => `<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><div class="timeline-title">${h(run.mode)} · ${statusBadge(run.status)}</div><div class="timeline-sub mono tiny">${h(run.id)}</div>${run.error ? `<div class="tiny faint">${h(truncate(run.error, 90))}</div>` : ''}</div><span class="timeline-time">${timeAgo(run.started_at)}</span></div>`).join('')}</div>` : emptyState('No pipeline runs yet.')}
      </div>
    </div>`;
}

/* ---------------------------------------------------------------- analytics */
function chartSVG(series) {
  const width = 760;
  const height = 180;
  const pad = 28;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const maxTasks = Math.max(1, ...series.map((point) => point.tasks_completed || 0));
  const maxCost = Math.max(0.01, ...series.map((point) => point.cost_usd || 0));
  const step = series.length > 1 ? innerW / (series.length - 1) : innerW;
  const barStep = innerW / Math.max(1, series.length);
  const coords = series.map((point, index) => {
    const x = pad + index * step;
    const y = pad + innerH - ((point.cost_usd || 0) / maxCost) * innerH * 0.82;
    return [x, y];
  });
  const line = coords.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${(pad + innerW).toFixed(1)},${(pad + innerH).toFixed(1)} L${pad},${(pad + innerH).toFixed(1)} Z`;
  const bars = series.map((point, index) => {
    const barH = ((point.tasks_completed || 0) / maxTasks) * innerH * 0.55;
    const x = pad + index * barStep + barStep * 0.28;
    const y = pad + innerH - barH;
    return `<rect class="bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(3, barStep * 0.44).toFixed(1)}" height="${barH.toFixed(1)}" rx="2" />`;
  }).join('');
  const grid = [0, 0.25, 0.5, 0.75, 1].map((fraction) => `<line class="grid-line" x1="${pad}" x2="${width - pad}" y1="${(pad + innerH * fraction).toFixed(1)}" y2="${(pad + innerH * fraction).toFixed(1)}" />`).join('');
  const labels = series.map((point, index) => {
    if (series.length > 8 && index % 2 !== 0) return '';
    const x = pad + index * step;
    return `<text class="axis" x="${x.toFixed(1)}" y="${height - 7}" text-anchor="middle">${h(String(point.date).slice(5))}</text>`;
  }).join('');
  return `<div class="chart"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Daily tasks and spend">
    <defs><linearGradient id="chart-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff3d8b" stop-opacity="0.28"/><stop offset="1" stop-color="#ff3d8b" stop-opacity="0"/></linearGradient></defs>
    ${grid}${bars}<path class="area" d="${area}" /><path class="line" d="${line}" />${labels}
  </svg></div><div class="legend"><span><i style="background:var(--orange)"></i>Tasks completed</span><span><i style="background:var(--pink)"></i>Recorded cost</span></div>`;
}

async function renderAnalytics() {
  const [summary, costs, posts, snapshots, daily, weekly] = await Promise.all([
    api('/analytics/summary'),
    api('/analytics/costs?limit=50'),
    api('/publishing/posts'),
    api('/analytics/snapshots'),
    api('/reports/daily'),
    api('/reports/weekly'),
  ]);
  state.posts = posts;
  const publishing = summary.publishing || {};
  const finance = summary.finance || {};
  const quality = summary.quality || {};
  const styles = summary.experiments || [];
  const maxViews = Math.max(1, ...styles.map((style) => style.views || 0));
  return `
    <div class="section-head"><div><h2>Performance, cost, and learning</h2><p>Views and retention are entered from permitted platform exports. Costs are recorded with provenance. Revenue is never assumed.</p></div><div class="actions"><button class="btn ghost" data-action="backup">Backup database</button><button class="btn primary" data-action="export-report">Export founder report</button></div></div>
    <div class="kpi-grid" style="grid-template-columns:repeat(5,minmax(0,1fr))">
      <div class="kpi" style="--accent:var(--blue)"><div class="label">Views</div><div class="value">${fmtNum(publishing.views)}</div><div class="hint">${publishing.posts} posts · ${publishing.simulated_posts} simulated</div></div>
      <div class="kpi" style="--accent:var(--mint)"><div class="label">Avg retention</div><div class="value">${publishing.average_retention != null ? fmtPct(publishing.average_retention) : '—'}</div><div class="hint">Latest snapshot per post</div></div>
      <div class="kpi" style="--accent:var(--violet)"><div class="label">Follows / 1k</div><div class="value">${publishing.follows_per_thousand_views != null ? Number(publishing.follows_per_thousand_views).toFixed(2) : '—'}</div><div class="hint">${fmtNum(publishing.follows)} follows</div></div>
      <div class="kpi" style="--accent:var(--orange)"><div class="label">Recorded spend</div><div class="value">${fmtMoney(finance.total_cost_usd)}</div><div class="hint">Provider ${fmtMoney(finance.provider_spend_usd)}</div></div>
      <div class="kpi" style="--accent:var(--pink)"><div class="label">QC pass rate</div><div class="value">${quality.qc_pass_rate != null ? fmtPct(quality.qc_pass_rate) : '—'}</div><div class="hint">${quality.qc_failed} failures</div></div>
    </div>
    <div class="grid-2-1">
      <div class="card"><div class="card-head"><div><h3>Last 14 days</h3><div class="sub">Tasks completed and recorded cost</div></div><span class="badge">LOCAL</span></div>${chartSVG(summary.daily || [])}</div>
      <div class="card"><div class="card-head"><div><h3>Cost breakdown</h3><div class="sub">Every event is attributable</div></div><span class="badge">USD</span></div>
        ${Object.keys(finance.by_category || {}).length ? Object.entries(finance.by_category).map(([category, amount]) => `<div class="bar-row"><span>${h(titleCase(category))}</span><div class="progress"><span style="width:${Math.min(100, (amount / Math.max(1, finance.total_cost_usd)) * 100)}%"></span></div><strong>${fmtMoney(amount)}</strong></div>`).join('') : emptyState('No costs recorded.')}
        <div class="split-line"></div>
        <div class="between"><span class="small muted">Provider budget left</span><span class="small">${fmtMoney(finance.provider_remaining_usd)}</span></div>
      </div>
    </div>
    <div class="grid-2 mt-16">
      <div class="card"><div class="card-head"><div><h3>Style performance</h3><div class="sub">Compare materially different creative directions</div></div><span class="badge">${styles.length} styles</span></div>
        ${styles.length ? styles.map((style) => `<div class="bar-row" style="grid-template-columns:120px minmax(0,1fr) 70px"><span>${h(titleCase(style.style))}</span><div class="progress violet"><span style="width:${Math.round((style.views / maxViews) * 100)}%"></span></div><strong>${fmtNum(style.views)}</strong></div>`).join('') : emptyState('Publish and import analytics to compare styles.')}
        <div class="split-line"></div>
        <div class="note violet">Views are only as trustworthy as the imported export. No platform account is connected in dry-run mode.</div>
      </div>
      <div class="card"><div class="card-head"><div><h3>Reports</h3><div class="sub">Daily and weekly operating summaries</div></div><span class="badge">AUDITED</span></div>
        <div class="stat-strip" style="grid-template-columns:1fr 1fr"><div class="stat"><div class="n">${daily.tasks_completed}</div><div class="l">Tasks today</div></div><div class="stat"><div class="n">${daily.approvals_decided}</div><div class="l">Decisions today</div></div><div class="stat"><div class="n">${daily.posts_created}</div><div class="l">Posts today</div></div><div class="stat"><div class="n">${fmtMoney(daily.spend_usd)}</div><div class="l">Spend today</div></div></div>
        <div class="split-line"></div>
        <div class="small muted">Weekly summary</div>
        <div class="kv mt-8"><dt>Tasks completed</dt><dd>${weekly.tasks_completed}</dd><dt>Approvals</dt><dd>${weekly.approvals_decided}</dd><dt>Posts</dt><dd>${weekly.posts_created}</dd><dt>Spend</dt><dd>${fmtMoney(weekly.spend_usd)}</dd><dt>Cost / post</dt><dd>${fmtMoney(weekly.cost_per_post_usd)}</dd></div>
      </div>
    </div>
    <div class="card mt-16"><div class="card-head"><div><h3>Published posts</h3><div class="sub">Add a snapshot from a permitted platform export</div></div><button class="btn sm violet" data-action="snapshot-modal" ${posts.length ? '' : 'disabled'}>Add snapshot</button></div>
      ${posts.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Platform</th><th>Post ID</th><th>Status</th><th>Snapshots</th><th>Created</th><th></th></tr></thead><tbody>${posts.map((post) => `<tr><td>${h(titleCase(post.platform))}</td><td class="mono tiny">${h(post.external_post_id || '—')}</td><td>${statusBadge(post.status)}</td><td class="mono tiny">${post.snapshots || 0}</td><td class="tiny muted">${fmtDate(post.created_at)}</td><td><button class="btn xs ghost" data-action="snapshot-modal" data-id="${h(post.id)}">Add snapshot</button></td></tr>`).join('')}</tbody></table></div>` : emptyState('No posts yet. Approve and publish a final video first.')}
    </div>
    <div class="grid-2 mt-16">
      <div class="card"><div class="card-head"><div><h3>Cost ledger</h3><div class="sub">Local rendering is recorded at zero cost</div></div><button class="btn ghost xs" data-action="cost-modal">Record cost</button></div>
        ${costs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Provider</th><th>Category</th><th>Amount</th><th>Note</th><th>When</th></tr></thead><tbody>${costs.slice(0, 12).map((cost) => `<tr><td>${h(cost.provider)}</td><td>${h(titleCase(cost.category))}</td><td class="mono tiny">${fmtMoney(cost.amount)}</td><td class="tiny muted">${h(truncate(cost.note || '—', 50))}</td><td class="tiny muted">${fmtDate(cost.created_at)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No cost events.')}
      </div>
      <div class="card"><div class="card-head"><div><h3>Analytics snapshots</h3><div class="sub">Latest imports</div></div><span class="badge">${snapshots.length}</span></div>
        ${snapshots.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Post</th><th>Views</th><th>Retention</th><th>Captured</th></tr></thead><tbody>${snapshots.slice(0, 10).map((snapshot) => `<tr><td class="mono tiny">${h(snapshot.external_post_id || snapshot.platform_post_id.slice(0, 8))}</td><td class="mono tiny">${fmtNum(snapshot.views)}</td><td class="mono tiny">${snapshot.retention != null ? fmtPct(snapshot.retention) : '—'}</td><td class="tiny muted">${fmtDate(snapshot.captured_at)}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No analytics snapshots imported.')}
      </div>
    </div>`;
}

/* ----------------------------------------------------------------- actions */
async function afterChange(message) {
  if (message) toast(message, 'success');
  closeModal();
  await refreshSummary();
  await renderView();
}

async function postAction(path, body, message) {
  await api(path, { method: 'POST', body: body ?? {} });
  await afterChange(message);
}

function openDecisionModal(approvalId, status) {
  const approve = status === 'approved';
  openModal(approve ? 'Approve record' : 'Reject record', 'The decision is written to the append-only audit trail.', `
    <form data-form="decision">
      <input type="hidden" name="id" value="${h(approvalId)}" />
      <input type="hidden" name="status" value="${h(status)}" />
      <div class="field"><label>Decision note (optional)</label><textarea name="note" placeholder="${approve ? 'Why is this safe to proceed?' : 'What must change before resubmission?'}"></textarea></div>
      <div class="note ${approve ? 'green' : 'danger'} mt-16"><strong>${approve ? 'Approval unlocks the next step.' : 'Rejection blocks the action.'}</strong> ${approve ? 'Paid quotes and publishing remain separately gated.' : 'The requester must create a new record or correct the evidence.'}</div>
      <div class="form-actions"><button class="btn ${approve ? 'green' : 'red'}" type="submit">${approve ? 'Approve' : 'Reject'}</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openRightsModal(assetId) {
  openModal('Add rights record', 'Unknown or expired rights never enter production.', `
    <form data-form="rights">
      <input type="hidden" name="source_asset_id" value="${h(assetId)}" />
      <div class="form-grid">
        <div class="field"><label>Owner / creator</label><input name="owner" placeholder="Founder" required /></div>
        <div class="field"><label>License type</label><input name="license_type" placeholder="owned / licensed / written permission" required /></div>
        <div class="field"><label>Proof URI</label><input name="proof_uri" placeholder="file:///… or contract reference" /></div>
        <div class="field"><label>Expires at (optional)</label><input name="expires_at" type="date" /></div>
        <div class="field full"><label>Attribution requirement</label><input name="attribution" placeholder="Credit @creator in the caption" /></div>
        <div class="field full"><label>Takedown contact</label><input name="takedown_contact" placeholder="rights@example.com" /></div>
      </div>
      <div class="field mt-8"><label>Platforms</label><div class="pill-row"><label class="check-row" style="padding-top:0"><input type="checkbox" name="platform_youtube" checked /> YouTube</label><label class="check-row" style="padding-top:0"><input type="checkbox" name="platform_tiktok" checked /> TikTok</label></div></div>
      <label class="check-row"><input type="checkbox" name="commercial_use" checked /> Commercial use is permitted and documented</label>
      <div class="form-actions"><button class="btn primary" type="submit">Create rights record + approval</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openPublishModal(variantId) {
  api('/publishing/accounts').then((accounts) => {
    openModal('Create publishing job', 'A final-video approval and a publish approval are both required.', `
      <form data-form="publish-job">
        <input type="hidden" name="video_variant_id" value="${h(variantId)}" />
        <div class="form-grid">
          <div class="field"><label>Platform</label><select name="platform"><option value="youtube">YouTube</option><option value="tiktok">TikTok</option></select></div>
          <div class="field"><label>Account</label><select name="account_id"><option value="">Dry-run default</option>${accounts.map((account) => `<option value="${h(account.id)}">${h(account.display_name)} · ${h(account.platform)}</option>`).join('')}</select></div>
          <div class="field full"><label>Schedule at (optional ISO timestamp)</label><input name="schedule_at" placeholder="2026-11-08T18:00:00Z" /></div>
        </div>
        <div class="note mt-16"><strong>Dry-run:</strong> creating the job is safe. Publishing requires a separate approval and does not contact a platform unless live mode is enabled.</div>
        <div class="form-actions"><button class="btn primary" type="submit">Create job + approval request</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
      </form>`);
  }).catch((error) => toast(error.message, 'error'));
}

function openSnapshotModal(postId) {
  const posts = state.posts || [];
  openModal('Import analytics snapshot', 'Use a permitted platform export. Views are not invented.', `
    <form data-form="snapshot">
      <div class="field"><label>Post</label><select name="platform_post_id" required>${posts.map((post) => `<option value="${h(post.id)}" ${post.id === postId ? 'selected' : ''}>${h(post.platform)} · ${h(post.external_post_id || post.id.slice(0, 8))}</option>`).join('')}</select></div>
      <div class="form-grid mt-8">
        <div class="field"><label>Views</label><input name="views" type="number" min="0" value="0" /></div>
        <div class="field"><label>Likes</label><input name="likes" type="number" min="0" value="0" /></div>
        <div class="field"><label>Comments</label><input name="comments" type="number" min="0" value="0" /></div>
        <div class="field"><label>Shares</label><input name="shares" type="number" min="0" value="0" /></div>
        <div class="field"><label>Follows</label><input name="follows" type="number" min="0" value="0" /></div>
        <div class="field"><label>Retention %</label><input name="retention" type="number" min="0" max="100" step="0.1" /></div>
        <div class="field"><label>Watch time (minutes)</label><input name="watch_time" type="number" min="0" step="0.1" /></div>
        <div class="field"><label>Captured at</label><input name="captured_at" type="datetime-local" /></div>
      </div>
      <div class="form-actions"><button class="btn primary" type="submit">Record snapshot</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openInvokeToolModal() {
  const servers = state.mcpServers || [];
  if (!servers.length) { toast('Register an MCP server first.', 'error'); return; }
  openModal('Invoke MCP tool', 'High-risk tools require an approved mcp_tool record.', `
    <form data-form="mcp-call">
      <div class="form-grid">
        <div class="field"><label>Server</label><select name="server_id">${servers.map((server) => `<option value="${h(server.id)}">${h(server.name)}</option>`).join('')}</select></div>
        <div class="field"><label>Tool name</label><input name="tool_name" placeholder="lookup" required /></div>
        <div class="field full"><label>Payload (JSON)</label><textarea name="payload">{"query": "gta 6"}</textarea></div>
        <div class="field full"><label>Approval ID (high-risk tools only)</label><input name="approval_id" placeholder="optional" /></div>
      </div>
      <div class="note violet mt-16">Live MCP transport is disabled in this build. The call is hashed and recorded; no external tool is executed.</div>
      <div class="form-actions"><button class="btn violet" type="submit">Record tool call</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openMCPToolModal(serverId) {
  openModal('Register MCP tool', 'Scope the tool and assign a risk level.', `
    <form data-form="mcp-tool">
      <input type="hidden" name="server_id" value="${h(serverId)}" />
      <div class="form-grid">
        <div class="field"><label>Tool name</label><input name="name" placeholder="lookup_asset" required /></div>
        <div class="field"><label>Risk</label><select name="risk"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High (approval required)</option></select></div>
        <div class="field full"><label>Description</label><input name="description" placeholder="What does this tool do?" /></div>
        <div class="field full"><label>Input schema (JSON)</label><textarea name="input_schema">{}</textarea></div>
      </div>
      <div class="form-actions"><button class="btn violet" type="submit">Register tool</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openCUAActionModal(sessionId, mode) {
  const token = localStorage.getItem(`cua:${sessionId}`) || '';
  const observeActions = ['navigate', 'screenshot', 'read', 'scroll'];
  const draftActions = [...observeActions, 'click', 'fill', 'keypress', 'hover'];
  const actions = mode === 'observe' ? observeActions : draftActions;
  openModal('Record CUA action', 'The action is checked against the allowlist, mode, token, and action limit.', `
    <form data-form="cua-action">
      <input type="hidden" name="session_id" value="${h(sessionId)}" />
      <div class="form-grid">
        <div class="field"><label>Action</label><select name="action_type">${actions.map((action) => `<option value="${h(action)}">${h(titleCase(action))}</option>`).join('')}</select></div>
        <div class="field"><label>Target URL (optional)</label><input name="target" placeholder="https://studio.youtube.com/…" /></div>
        <div class="field full"><label>Capability token</label><input name="token" value="${h(token)}" placeholder="Returned once when the session activates" required /></div>
        <div class="field full"><label>Result (JSON)</label><textarea name="result">{"ok": true}</textarea></div>
      </div>
      <div class="note danger mt-16">Publishing, payment, deletion, credential entry, and CAPTCHA bypass are never available.</div>
      <div class="form-actions"><button class="btn violet" type="submit">Record action</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div>
    </form>`);
}

function openInitiativeModal(initiative) {
  const tasks = initiative.tasks || [];
  openModal('Initiative plan', initiative.objective, `
    <div class="kv">
      <dt>Status</dt><dd>${statusBadge(initiative.status)} ${riskBadge(initiative.risk_level)}</dd>
      <dt>Rationale</dt><dd>${h(initiative.plan?.rationale || '—')}</dd>
      <dt>Policy</dt><dd>${h(initiative.plan?.approval_policy || '—')}</dd>
      <dt>Created</dt><dd>${fmtDate(initiative.created_at)}</dd>
    </div>
    <div class="split-line"></div>
    <div class="small muted">Task DAG</div>
    <div class="table-wrap mt-8"><table class="table"><thead><tr><th>Task</th><th>Department</th><th>Status</th><th>Worker</th><th></th></tr></thead><tbody>${tasks.map((task) => `<tr><td>${h(task.title)}</td><td>${statusBadge(task.department)}</td><td>${statusBadge(task.status)}</td><td class="tiny">${h(task.worker_name || task.worker || '—')}</td><td>${['queued', 'retry'].includes(task.status) ? `<button class="btn xs green" data-action="run-task" data-id="${h(task.id)}">Run</button>` : ''}</td></tr>`).join('')}</tbody></table></div>
    <div class="form-actions"><button class="btn ghost" data-action="close-modal">Close</button></div>`);
}

async function openApprovalModal(approvalId) {
  try {
    const approval = await api(`/approvals/${approvalId}`);
    openModal('Approval record', `${titleCase(approval.type)} · ${approval.status}`, `
      <div class="kv"><dt>Subject</dt><dd>${h(approvalSubjectLine(approval))}</dd><dt>Requested by</dt><dd>${h(approval.requested_by)}</dd><dt>Reason</dt><dd>${h(approval.reason || '—')}</dd><dt>Created</dt><dd>${fmtDate(approval.created_at)}</dd><dt>Decided</dt><dd>${approval.decided_at ? `${fmtDate(approval.decided_at)} by ${h(approval.decided_by || 'founder')}` : '—'}</dd></div>
      <div class="split-line"></div><div class="small muted">Subject record</div><pre class="caption-box mt-8">${h(jsonPretty(approval.subject))}</pre>
      <div class="form-actions">${approval.status === 'pending' ? `<button class="btn green" data-action="approve-approval" data-id="${h(approval.id)}">Approve</button><button class="btn red" data-action="reject-approval" data-id="${h(approval.id)}">Reject</button>` : ''}<button class="btn ghost" data-action="close-modal">Close</button></div>`);
  } catch (error) { toast(error.message, 'error'); }
}

async function openVariantModal(variantId) {
  try {
    const variant = await api(`/variants/${variantId}`);
    const checks = variant.qc_report?.checks || {};
    openModal('Variant preview', variant.title, `
      <div class="grid-2">
        <div>${variant.render_uri ? `<video class="media-preview" controls preload="metadata" src="/api/variants/${encodeURIComponent(variant.id)}/file"></video>` : emptyState('No rendered file yet.', '🎬')}</div>
        <div>
          <div class="kv"><dt>Style</dt><dd>${h(titleCase(variant.style))}</dd><dt>Status</dt><dd>${statusBadge(variant.status)}</dd><dt>QC</dt><dd>${statusBadge(variant.qc_status)}</dd><dt>Candidate</dt><dd class="mono tiny">${h(variant.candidate_id)}</dd><dt>Approval</dt><dd>${variant.approval ? statusBadge(variant.approval.status) : 'not submitted'}</dd></div>
          <div class="split-line"></div><div class="small muted">Script</div><div class="tiny mt-8">${h(variant.script)}</div>
          <div class="small muted mt-8">Caption</div><div class="caption-box mt-8">${h(variant.caption_text || '—')}</div>
          <div class="form-actions">${variant.caption_uri ? `<a class="btn xs ghost" href="/api/variants/${encodeURIComponent(variant.id)}/captions" target="_blank" rel="noreferrer">Open SRT</a>` : ''}</div>
        </div>
      </div>
      <div class="split-line"></div><div class="small muted">QC checks</div>
      <div class="table-wrap mt-8"><table class="table"><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>${Object.entries(checks).map(([name, check]) => `<tr><td>${h(titleCase(name))}</td><td>${check.passed ? '<span class="badge green">PASS</span>' : '<span class="badge red">FAIL</span>'}</td><td class="tiny muted">${h(truncate(check.detail, 80))}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">QC has not run.</td></tr>'}</tbody></table></div>
      <div class="form-actions"><button class="btn ghost" data-action="close-modal">Close</button></div>`, { wide: true });
  } catch (error) { toast(error.message, 'error'); }
}

async function openWorkerModal(workerId) {
  try {
    const workers = await api('/workers');
    const worker = workers.find((row) => row.id === workerId);
    if (!worker) throw new Error('Worker not found');
    openModal(worker.name, `${worker.role} · ${worker.department_name}`, `
      <div class="flex gap-10 items-center"><span class="avatar" style="width:52px;height:52px;font-size:24px">${h(worker.avatar)}</span><div><div class="small">${statusBadge(worker.status)}</div><div class="tiny muted mt-8">Last action: ${h(worker.last_action || '—')}</div></div></div>
      <div class="split-line"></div>
      <div class="kv"><dt>Worker ID</dt><dd class="mono tiny">${h(worker.id)}</dd><dt>Department</dt><dd>${h(worker.department_name || worker.department_id)}</dd><dt>Current task</dt><dd>${h(worker.current_task_title || '—')}</dd><dt>Permissions</dt><dd>${pills(worker.permissions || [])}</dd><dt>Capabilities</dt><dd>${pills(worker.capabilities || [])}</dd></div>
      <div class="form-actions">${worker.status === 'active' ? `<button class="btn red" data-action="pause-worker" data-id="${h(worker.id)}">Pause worker</button>` : `<button class="btn green" data-action="resume-worker" data-id="${h(worker.id)}">Resume worker</button>`}<button class="btn ghost" data-action="close-modal">Close</button></div>`);
  } catch (error) { toast(error.message, 'error'); }
}

async function openAssetModal(assetId) {
  try {
    const asset = await api(`/assets/${assetId}`);
    const rights = asset.rights || [];
    openModal('Source asset', asset.filename || asset.id, `
      <div class="kv"><dt>Status</dt><dd>${statusBadge(asset.status)}</dd><dt>Path</dt><dd class="mono tiny">${h(asset.path || '—')}</dd><dt>SHA-256</dt><dd class="mono tiny">${h(asset.sha256 || '—')}</dd><dt>Duration</dt><dd>${asset.duration ? `${Number(asset.duration).toFixed(2)}s` : '—'}</dd><dt>Dimensions</dt><dd>${asset.width && asset.height ? `${asset.width}×${asset.height}` : '—'}</dd><dt>Size</dt><dd>${bytes(asset.size_bytes)}</dd><dt>Owner</dt><dd>${h(asset.owner || '—')}</dd><dt>Source URL</dt><dd>${h(asset.source_url || '—')}</dd></div>
      <div class="split-line"></div><div class="small muted">Rights records</div>
      ${rights.length ? `<div class="table-wrap mt-8"><table class="table"><thead><tr><th>Owner</th><th>License</th><th>Status</th><th>Commercial</th></tr></thead><tbody>${rights.map((record) => `<tr><td>${h(record.owner)}</td><td>${h(record.license_type)}</td><td>${statusBadge(record.status)}</td><td>${record.commercial_use ? 'yes' : 'no'}</td></tr>`).join('')}</tbody></table></div>` : emptyState('No rights record. Add one before analysis.')}
      <div class="form-actions"><button class="btn violet" data-action="add-rights-modal" data-id="${h(asset.id)}">Add rights</button>${asset.valid_rights ? `<button class="btn" data-action="analyze-asset" data-id="${h(asset.id)}">Analyze</button>` : ''}<a class="btn ghost" href="/api/assets/${encodeURIComponent(asset.id)}/file" target="_blank" rel="noreferrer">Open file</a><button class="btn ghost" data-action="close-modal">Close</button></div>`, { wide: true });
  } catch (error) { toast(error.message, 'error'); }
}

/* --------------------------------------------------------------- form logic */
function formValues(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  return values;
}
function intOrNull(value) { return value === '' || value === undefined || value === null ? null : Number(value); }

const FORMS = {
  async ceo(form) {
    const values = formValues(form);
    const initiative = await api('/ceo/instructions', { method: 'POST', body: { objective: values.objective, risk_level: values.risk_level || null } });
    toast(`Plan created with ${initiative.tasks?.length || 0} tasks. Accept it to queue work.`, 'success');
    await refreshSummary();
    await renderView();
  },
  async ingest(form) {
    const values = formValues(form);
    const asset = await api('/assets/ingest', { method: 'POST', body: { path: values.path, owner: values.owner || 'founder', source_url: values.source_url || null } });
    toast(`Source ingested: ${truncate(asset.filename || asset.id, 40)}`, 'success');
    await refreshSummary();
    await renderView();
  },
  async upload(form) {
    const data = new FormData(form);
    const file = data.get('file');
    if (!file || !file.size) throw new Error('Choose a file to upload.');
    await api('/assets/upload', { method: 'POST', body: data });
    toast('Source uploaded. Add and approve a rights record next.', 'success');
    await refreshSummary();
    await renderView();
  },
  async rights(form) {
    const values = formValues(form);
    const platforms = [];
    if (form.elements.platform_youtube?.checked) platforms.push('youtube');
    if (form.elements.platform_tiktok?.checked) platforms.push('tiktok');
    const rights = await api('/rights', { method: 'POST', body: {
      source_asset_id: values.source_asset_id,
      owner: values.owner,
      license_type: values.license_type,
      commercial_use: Boolean(form.elements.commercial_use?.checked),
      proof_uri: values.proof_uri || null,
      platforms,
      attribution: values.attribution || null,
      takedown_contact: values.takedown_contact || null,
      expires_at: values.expires_at || null,
    } });
    toast(`Rights record created. Approval ${rights.approval?.id?.slice(0, 8) || ''} is waiting.`, 'success');
    await afterChange();
  },
  async task(form) {
    const values = formValues(form);
    await api('/tasks', { method: 'POST', body: { title: values.title, department: values.department, worker: values.worker || null, type: values.type || 'general', priority: Number(values.priority || 3), input_ref: values.input_ref || null } });
    toast('Task created.', 'success');
    await afterChange();
  },
  async business(form) {
    const values = formValues(form);
    await api('/businesses', { method: 'POST', body: { name: values.name, brand_rules: { voice: values.voice || '' } } });
    toast('Business workspace created.', 'success');
    await afterChange();
  },
  async 'publish-job'(form) {
    const values = formValues(form);
    const job = await api('/publishing/jobs', { method: 'POST', body: { video_variant_id: values.video_variant_id, platform: values.platform, account_id: values.account_id || null, schedule_at: values.schedule_at || null } });
    toast(`Publishing job created. Approval ${job.approval?.id?.slice(0, 8) || ''} is waiting.`, 'success');
    await afterChange();
  },
  async 'provider-quote'(form) {
    const values = formValues(form);
    const quote = await api('/providers/everygen/quotes', { method: 'POST', body: { request: { kind: values.kind, duration_seconds: Number(values.duration_seconds || 0), prompt: values.prompt } } });
    toast(`Quote created: ${quote.credits} credits · ${fmtMoney(quote.cost_usd)}. Approve it in the queue.`, 'success');
    await refreshSummary();
    await renderView();
  },
  async 'mcp-server'(form) {
    const values = formValues(form);
    await api('/mcp/servers', { method: 'POST', body: { name: values.name, endpoint: values.endpoint, transport: values.transport, scopes: [] } });
    toast('MCP server registered.', 'success');
    await renderView();
  },
  async 'mcp-tool'(form) {
    const values = formValues(form);
    let schema = {};
    try { schema = JSON.parse(values.input_schema || '{}'); } catch { throw new Error('Input schema must be valid JSON.'); }
    await api('/mcp/tools', { method: 'POST', body: { server_id: values.server_id, name: values.name, description: values.description, input_schema: schema, risk: values.risk } });
    toast('MCP tool registered.', 'success');
    await afterChange();
  },
  async 'mcp-call'(form) {
    const values = formValues(form);
    let payload = {};
    try { payload = JSON.parse(values.payload || '{}'); } catch { throw new Error('Payload must be valid JSON.'); }
    const call = await api('/mcp/tool-calls', { method: 'POST', body: { server_id: values.server_id, tool_name: values.tool_name, payload, approval_id: values.approval_id || null } });
    toast(`Tool call recorded: ${call.status}.`, 'success');
    closeModal();
    await renderView();
  },
  async 'pipeline-clip'(form) {
    const values = formValues(form);
    const urls = String(values.urls || '')
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (!urls.length) throw new Error('Add at least one YouTube URL.');
    if (!form.elements.rights_ack?.checked) throw new Error('Confirm the rights acknowledgement first.');
    const result = await api('/pipeline/clip', {
      method: 'POST',
      body: { urls, count: Number(values.count || 2), rights_ack: true },
    });
    toast(`Clip job queued for ${urls.length} source(s). Job ${result.job_id}.`, 'success');
    await afterChange();
    setTimeout(() => { renderView().catch(() => {}); }, 6000);
  },
  async cua(form) {
    const values = formValues(form);
    const session = await api('/cua/sessions', { method: 'POST', body: { target: values.target, mode: values.mode } });
    toast(`CUA request created. Approval ${session.approval?.id?.slice(0, 8) || ''} is waiting.`, 'success');
    await refreshSummary();
    await renderView();
  },
  async 'cua-action'(form) {
    const values = formValues(form);
    let result = {};
    try { result = JSON.parse(values.result || '{}'); } catch { throw new Error('Result must be valid JSON.'); }
    await api(`/cua/sessions/${values.session_id}/actions`, { method: 'POST', body: { action_type: values.action_type, target: values.target || null, result, token: values.token } });
    toast('CUA action recorded with local evidence.', 'success');
    closeModal();
    await renderView();
  },
  async snapshot(form) {
    const values = formValues(form);
    await api('/analytics/snapshots', { method: 'POST', body: {
      platform_post_id: values.platform_post_id,
      views: Number(values.views || 0), likes: Number(values.likes || 0), comments: Number(values.comments || 0),
      shares: Number(values.shares || 0), follows: Number(values.follows || 0),
      retention: intOrNull(values.retention), watch_time: intOrNull(values.watch_time),
      captured_at: values.captured_at ? new Date(values.captured_at).toISOString() : null,
    } });
    toast('Analytics snapshot recorded.', 'success');
    await afterChange();
  },
  async cost(form) {
    const values = formValues(form);
    await api('/analytics/costs', { method: 'POST', body: { provider: values.provider, category: values.category, amount: Number(values.amount || 0), note: values.note || null } });
    toast('Cost event recorded.', 'success');
    await afterChange();
  },
  async decision(form) {
    const values = formValues(form);
    await api(`/approvals/${values.id}/decision`, { method: 'POST', body: { status: values.status, note: values.note || null } });
    await afterChange(`Approval ${values.status}.`);
  },
  async 'publishing-account'(form) {
    const values = formValues(form);
    await api('/publishing/accounts', { method: 'POST', body: { platform: values.platform, display_name: values.display_name, credential_ref: values.credential_ref || null } });
    toast('Publishing account added.', 'success');
    await renderView();
  },
};

/* ------------------------------------------------------------ click actions */
const ACTIONS = {
  'close-modal': () => closeModal(),
  go: (_, element) => navigate(element.dataset.view),
  refresh: () => renderView(),
  'toggle-stop': async () => {
    const stopped = Boolean(state.summary?.emergency_stop);
    if (!stopped && !window.confirm('Engage emergency stop? All mutating API actions will be blocked.')) return;
    if (stopped) await api('/system/resume', { method: 'POST' });
    else await api('/system/emergency-stop', { method: 'POST' });
    toast(stopped ? 'Operations resumed.' : 'Emergency stop engaged. All work is blocked.', stopped ? 'success' : 'error');
    await afterChange();
  },
  'approve-approval': (id) => openDecisionModal(id, 'approved'),
  'reject-approval': (id) => openDecisionModal(id, 'rejected'),
  'open-approval': (id) => openApprovalModal(id),
  'approval-filter': (_, element) => { state.approvalsFilter = element.dataset.filter; renderView(); },
  'run-task': async (id) => { await postAction(`/tasks/${id}/run`, {}, 'Task executed; inspect evidence in the task detail.'); },
  'retry-task': async (id) => { await postAction(`/tasks/${id}/retry`, {}, 'Task returned to the queue.'); },
  'cancel-task': async (id) => { if (window.confirm('Cancel this task?')) await postAction(`/tasks/${id}/cancel`, {}, 'Task cancelled.'); },
  'tick-ceo': async () => {
    const result = await api('/ceo/tick', { method: 'POST', body: { limit: 5 } });
    toast(`CEO tick: ${result.run} run · ${result.skipped} skipped.`, 'success');
    await afterChange();
  },
  'decide-initiative': async (id, element) => {
    const decision = element.dataset.decision;
    await postAction(`/initiatives/${id}/decision`, { decision }, `Plan ${decision}.`);
  },
  'open-initiative': async (id) => {
    try { openInitiativeModal(await api(`/initiatives/${id}`)); } catch (error) { toast(error.message, 'error'); }
  },
  'toggle-department': async (id, element) => {
    const paused = element.dataset.paused === 'true';
    await postAction(`/departments/${id}/pause`, { paused: !paused }, paused ? 'Department resumed.' : 'Department paused.');
  },
  'pause-worker': async (id) => {
    await api(`/workers/${id}`, { method: 'PATCH', body: { status: 'paused' } });
    await afterChange('Worker paused.');
  },
  'resume-worker': async (id) => {
    await api(`/workers/${id}`, { method: 'PATCH', body: { status: 'active' } });
    await afterChange('Worker resumed.');
  },
  'open-worker': (id) => openWorkerModal(id),
  'open-department': (id) => openDepartmentModal(id),
  'run-handoffs': async () => {
    const result = await api('/ceo/tick', { method: 'POST', body: { limit: 5 } });
    toast(`Handoff tick: ${result.run} executed · ${result.skipped} waiting.`, result.run ? 'success' : 'info');
    await afterChange();
  },
  'analyze-asset': async (id) => {
    toast('Analyzing locally…', 'info');
    await api(`/assets/${id}/analyze`, { method: 'POST' });
    await afterChange('Analysis complete. Candidate moments created.');
  },
  'add-rights-modal': (id) => openRightsModal(id),
  'open-asset': (id) => openAssetModal(id),
  'create-variants': async (id) => {
    const variants = await api(`/candidates/${id}/variants`, { method: 'POST', body: {} });
    toast(`${variants.length} materially different drafts created.`, 'success');
    await afterChange();
  },
  'render-variant': async (id, element) => {
    element.disabled = true;
    toast('Rendering 9:16 locally. This can take a moment…', 'info');
    try {
      await api(`/variants/${id}/render`, { method: 'POST', body: {} });
      await afterChange('Render complete. Run QC next.');
    } catch (error) {
      element.disabled = false;
      throw error;
    }
  },
  'qc-variant': async (id) => { await postAction(`/variants/${id}/qc`, {}, 'QC complete.'); },
  'submit-review': async (id) => { await postAction(`/variants/${id}/submit-review`, {}, 'Submitted to the founder approval queue.'); },
  'open-variant': (id) => openVariantModal(id),
  'publish-modal': (id) => openPublishModal(id),
  'publish-job': async (id) => { await postAction(`/publishing/jobs/${id}/publish`, {}, 'Publish action completed in dry-run mode.'); },
  'reconcile-job': async (id) => { await postAction(`/publishing/jobs/${id}/reconcile`, {}, 'Post reconciled.'); },
  'provider-job': async (id) => { await postAction('/providers/everygen/jobs', { quote_id: id }, 'Provider job created.'); },
  'poll-provider': async (id) => { await postAction(`/providers/everygen/jobs/${id}/poll`, {}, 'Provider job polled.'); },
  'cancel-provider': async (id) => { await postAction(`/providers/everygen/jobs/${id}/cancel`, {}, 'Provider job cancelled.'); },
  'open-quote': async (id) => {
    try {
      const quotes = await api('/providers/everygen/quotes');
      const quote = quotes.find((row) => row.id === id);
      openModal('Provider quote', `${quote?.provider || 'provider'} · ${quote?.credits || 0} credits`, `<pre class="caption-box">${h(jsonPretty(quote))}</pre><div class="form-actions"><button class="btn ghost" data-action="close-modal">Close</button></div>`);
    } catch (error) { toast(error.message, 'error'); }
  },
  'mcp-connect': async (id) => { await postAction(`/mcp/servers/${id}/connect`, {}, 'MCP health check recorded.'); },
  'mcp-tool-modal': (id) => openMCPToolModal(id),
  'mcp-call-modal': () => openInvokeToolModal(),
  'cua-activate': async (id) => {
    const session = await api(`/cua/sessions/${id}/activate`, { method: 'POST' });
    if (session.capability_token) {
      localStorage.setItem(`cua:${id}`, session.capability_token);
      openModal('Session activated', 'Copy the capability token now. It is not returned again.', `
        <div class="note green"><strong>Token:</strong> <span class="code">${h(session.capability_token)}</span></div>
        <div class="kv mt-16"><dt>Target</dt><dd>${h(session.target)}</dd><dt>Mode</dt><dd>${h(session.mode)}</dd><dt>Expires</dt><dd>${fmtDate(session.expires_at)}</dd><dt>Max actions</dt><dd>${session.max_actions}</dd></div>
        <div class="form-actions"><button class="btn" data-action="copy-token" data-token="${h(session.capability_token)}">Copy token</button><button class="btn ghost" data-action="close-modal">Close</button></div>`);
    }
    await refreshSummary();
    await renderView();
  },
  'copy-token': async (_, element) => {
    try { await navigator.clipboard.writeText(element.dataset.token || ''); toast('Token copied.', 'success'); }
    catch { toast('Copy failed. Select the token manually.', 'error'); }
  },
  'cua-action-modal': (id, element) => openCUAActionModal(id, element.dataset.mode),
  'cua-stop': async (id) => { await postAction(`/cua/sessions/${id}/stop`, {}, 'CUA session stopped.'); },
  'cua-emergency': async () => {
    if (!window.confirm('Stop all CUA sessions and clear capability tokens?')) return;
    await postAction('/cua/emergency-stop', {}, 'CUA emergency stop engaged.');
  },
  'open-cua': async (id) => {
    try {
      const session = await api(`/cua/sessions/${id}`);
      openModal('CUA session', session.target, `<div class="kv"><dt>Status</dt><dd>${statusBadge(session.status)}</dd><dt>Mode</dt><dd>${h(session.mode)}</dd><dt>Actions</dt><dd>${session.actions_used}/${session.max_actions}</dd><dt>Expires</dt><dd>${session.expires_at ? fmtDate(session.expires_at) : 'not activated'}</dd><dt>Evidence</dt><dd class="mono tiny">${h(session.evidence_dir || '—')}</dd></div><div class="split-line"></div><pre class="caption-box">${h(jsonPretty(session.actions))}</pre><div class="form-actions"><button class="btn ghost" data-action="close-modal">Close</button></div>`, { wide: true });
    } catch (error) { toast(error.message, 'error'); }
  },
  'snapshot-modal': (id) => openSnapshotModal(id),
  'cost-modal': () => openModal('Record cost', 'Every cost event is attributable to a provider, category, and note.', `<form data-form="cost"><div class="form-grid"><div class="field"><label>Provider</label><input name="provider" value="local" required /></div><div class="field"><label>Category</label><select name="category"><option value="render">Render</option><option value="paid_generation">Paid generation</option><option value="publishing">Publishing</option><option value="infrastructure">Infrastructure</option><option value="other">Other</option></select></div><div class="field"><label>Amount USD</label><input name="amount" type="number" min="0" step="0.01" value="0" /></div><div class="field"><label>Note</label><input name="note" placeholder="What was purchased?" /></div></div><div class="form-actions"><button class="btn primary" type="submit">Record cost</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div></form>`),
  'export-report': async () => {
    const report = await api('/reports/export', { method: 'POST' });
    toast(`Founder report written to ${report.path}`, 'success', 8000);
  },
  backup: async () => {
    const backup = await api('/system/backup', { method: 'POST' });
    toast(`Backup created: ${backup.path} (${bytes(backup.bytes)}).`, 'success', 7000);
  },
  'create-business-modal': () => openModal('Add business workspace', 'Isolated initiatives, assets, costs, and approvals.', `<form data-form="business"><div class="field"><label>Business name</label><input name="name" placeholder="Creator partnership studio" required /></div><div class="field mt-8"><label>Brand voice</label><input name="voice" placeholder="Respectful, curious, high-energy" /></div><div class="form-actions"><button class="btn primary" type="submit">Create workspace</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div></form>`),
  'create-task-modal': async () => {
    const departments = await api('/departments');
    openModal('Create manual task', 'Tasks without a worker remain in the queue for the CEO to assign.', `<form data-form="task"><div class="form-grid"><div class="field full"><label>Title</label><input name="title" required placeholder="Review source rights for batch 03" /></div><div class="field"><label>Department</label><select name="department">${departments.map((department) => `<option value="${h(department.id)}">${h(department.name)}</option>`).join('')}</select></div><div class="field"><label>Worker (optional)</label><input name="worker" placeholder="rights-officer" /></div><div class="field"><label>Type</label><input name="type" value="general" /></div><div class="field"><label>Priority</label><select name="priority"><option>1</option><option selected>3</option><option>5</option></select></div><div class="field full"><label>Input reference (asset / variant id)</label><input name="input_ref" placeholder="optional" /></div></div><div class="form-actions"><button class="btn primary" type="submit">Create task</button><button class="btn ghost" type="button" data-action="close-modal">Cancel</button></div></form>`);
  },
};

/* ------------------------------------------------------------ event binding */
document.addEventListener('click', async (event) => {
  const navItem = event.target.closest('.nav-item');
  if (navItem) { navigate(navItem.dataset.view); return; }
  const trigger = event.target.closest('[data-action]');
  if (!trigger) return;
  const action = trigger.dataset.action;
  const handler = ACTIONS[action];
  if (!handler) return;
  event.preventDefault();
  if (trigger.disabled) return;
  const previous = trigger.innerHTML;
  if (trigger.tagName === 'BUTTON' && !['close-modal', 'go', 'approval-filter', 'open-approval', 'open-variant', 'open-worker', 'open-department', 'open-asset', 'add-rights-modal', 'publish-modal', 'open-initiative', 'open-cua', 'cua-action-modal', 'mcp-tool-modal', 'mcp-call-modal', 'snapshot-modal', 'cost-modal', 'create-task-modal', 'create-business-modal', 'open-quote', 'copy-token', 'toggle-stop'].includes(action)) {
    trigger.disabled = true;
    trigger.innerHTML = '<span class="spinner"></span>';
  }
  try {
    await handler(trigger.dataset.id, trigger, event);
  } catch (error) {
    toast(error.message || 'Action failed.', 'error');
    if (trigger.isConnected) {
      trigger.disabled = false;
      trigger.innerHTML = previous;
    }
  } finally {
    if (trigger.isConnected && !['toggle-stop', 'close-modal', 'go', 'approval-filter'].includes(action)) {
      trigger.disabled = false;
      trigger.innerHTML = previous;
    }
  }
});

document.addEventListener('submit', async (event) => {
  const form = event.target.closest('form[data-form]');
  if (!form) return;
  event.preventDefault();
  const handler = FORMS[form.dataset.form];
  if (!handler) return;
  const submit = form.querySelector('button[type="submit"]');
  const previous = submit?.innerHTML;
  if (submit) { submit.disabled = true; submit.innerHTML = '<span class="spinner"></span> Working…'; }
  try {
    await handler(form);
  } catch (error) {
    toast(error.message || 'Form submission failed.', 'error');
    if (submit) { submit.disabled = false; submit.innerHTML = previous; }
  }
});

/* -------------------------------------------------------------------- boot */
$$('[data-icon]').forEach((element) => { element.innerHTML = icon(element.dataset.icon); });

window.addEventListener('hashchange', () => {
  const view = window.location.hash.replace('#', '') || 'home';
  if (VIEW_META[view] && view !== state.view) setView(view);
});

(async function boot() {
  const initial = window.location.hash.replace('#', '') || 'home';
  state.view = VIEW_META[initial] ? initial : 'home';
  const meta = VIEW_META[state.view];
  $('#view-title').textContent = meta.title;
  $('#view-eyebrow').textContent = meta.eyebrow;
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === state.view));
  await refreshSummary();
  await renderView();
  connectSocket();
})();
