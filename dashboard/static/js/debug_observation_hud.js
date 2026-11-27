/**
 * Intelligent Tracker - Interactive Debug Observation HUD (IT_DEBUG_MODE=1).
 * Self-initializes by probing /api/system/debug/summary; strict no-op when disabled.
 */
(function () {
  'use strict';
  const MAX_CRUMBS = 30;
  const SUMMARY_URL = '/api/system/debug/summary?limit=1';
  const OBSERVATION_URL = '/api/system/debug/observation';
  const crumbs = [];
  let enabled = false;
  let installed = false;
  let rootEl = null;

  function pushBreadcrumb(entry) {
    if (!entry || typeof entry !== 'object') return;
    crumbs.push(Object.assign({ ts: Date.now() }, entry));
    while (crumbs.length > MAX_CRUMBS) crumbs.shift();
  }

  function getActiveTab() {
    const active = document.querySelector && document.querySelector('.nav-tab.active');
    const attr = active && active.getAttribute && active.getAttribute('data-tab');
    return attr ? String(attr) : (String((window.location && window.location.hash) || '').replace(/^#/, '').split('?')[0] || 'unknown');
  }

  function describeTarget(el) {
    if (!el || !el.tagName) return 'unknown';
    const tag = String(el.tagName).toLowerCase();
    const id = el.id ? `#${el.id}` : '';
    const tab = el.getAttribute && el.getAttribute('data-tab');
    const cls = typeof el.className === 'string'
      ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((c) => `.${c}`).join('') : '';
    return `${tag}${id || cls}${tab ? `[data-tab=${tab}]` : ''}`.slice(0, 120);
  }

  function wrapFetch() {
    const orig = window.fetch || (typeof fetch === 'function' ? fetch : null);
    if (typeof orig !== 'function') return;
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : String((input && input.url) || '');
      const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      const skip = url.indexOf('/api/system/debug/') !== -1;
      return Promise.resolve(orig.call(window, input, init)).then((res) => {
        if (!skip && res && res.ok === false) pushBreadcrumb({ type: 'fetch_error', method, url: url.slice(0, 160), status: Number(res.status || 0) });
        return res;
      }, (err) => {
        if (!skip) pushBreadcrumb({ type: 'fetch_error', method, url: url.slice(0, 160), status: 0, error: String((err && err.message) || err).slice(0, 120) });
        throw err;
      });
    };
  }

  function installInterceptors() {
    if (installed) return;
    installed = true;
    document.addEventListener('click', (ev) => {
      const target = ev && ev.target;
      if (rootEl && rootEl.contains && rootEl.contains(target)) return;
      const label = String((target && (target.textContent || target.title)) || '').trim().replace(/\s+/g, ' ').slice(0, 60);
      pushBreadcrumb({ type: 'click', target: describeTarget(target), label });
    }, true);
    window.addEventListener('hashchange', () => {
      pushBreadcrumb({ type: 'nav', tab: getActiveTab(), url: String((window.location && window.location.hash) || '') });
    });
    window.addEventListener('error', (ev) => {
      const msg = (ev && (ev.message || (ev.error && ev.error.message))) || 'Script error';
      pushBreadcrumb({ type: 'error', message: String(msg).slice(0, 160), line: Number((ev && ev.lineno) || 0) });
    });
    wrapFetch();
  }

  async function submitObservation(note) {
    const clean = String(note || '').trim();
    if (!clean) return { ok: false, error: 'Observation note cannot be empty' };
    const fetchFn = window.fetch || (typeof fetch === 'function' ? fetch : null);
    if (typeof fetchFn !== 'function') return { ok: false, error: 'fetch unavailable' };
    const loc = window.location || {};
    const payload = {
      note: clean, tab: getActiveTab(), url: `${loc.pathname || '/'}${loc.search || ''}${loc.hash || ''}`,
      breadcrumbs: crumbs.slice(-MAX_CRUMBS),
      viewport: { width: Number(window.innerWidth || 0), height: Number(window.innerHeight || 0) },
    };
    const res = await fetchFn(OBSERVATION_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const data = res && typeof res.json === 'function' ? await res.json().catch(() => ({})) : {};
    return { ok: Boolean(res && res.ok), status: Number((res && res.status) || 0), data };
  }

  function makeEl(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function mountHud() {
    if (rootEl || !document.body || typeof document.createElement !== 'function') return;
    if (document.head && typeof document.head.appendChild === 'function') {
      document.head.appendChild(makeEl('style', '',
        '.debug-obs-hud{position:fixed;right:16px;bottom:16px;z-index:9999;font-family:Inter,sans-serif;display:flex;flex-direction:column;align-items:flex-end;gap:8px;}' +
        '.debug-obs-pill{background:#b45309;color:#fff;border:1px solid #f59e0b;border-radius:999px;padding:8px 14px;font-size:12px;font-weight:600;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35);}' +
        '.debug-obs-panel{width:300px;background:#111827;color:#f3f4f6;border:1px solid #f59e0b;border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px;box-shadow:0 8px 24px rgba(0,0,0,.45);}' +
        '.debug-obs-panel[hidden]{display:none;}.debug-obs-input{width:100%;min-height:68px;background:#1f2937;color:#f9fafb;border:1px solid #374151;border-radius:6px;padding:8px;font-size:12px;resize:vertical;}' +
        '.debug-obs-row{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11px;color:#9ca3af;}'));
    }
    rootEl = makeEl('div', 'debug-obs-hud');
    const panel = makeEl('div', 'debug-obs-panel');
    panel.hidden = true;
    const input = makeEl('textarea', 'debug-obs-input');
    input.placeholder = 'Describe what you observed on this screen...';
    const row = makeEl('div', 'debug-obs-row');
    const status = makeEl('span', '');
    const saveBtn = makeEl('button', 'debug-obs-pill', 'Save');
    saveBtn.type = 'button';
    row.appendChild(status); row.appendChild(saveBtn);
    panel.appendChild(input); panel.appendChild(row);
    const pill = makeEl('button', 'debug-obs-pill', 'Log Observation');
    pill.type = 'button';
    pill.addEventListener('click', () => {
      panel.hidden = !panel.hidden;
      status.textContent = `${crumbs.length} crumbs`;
      if (!panel.hidden && input.focus) input.focus();
    });
    saveBtn.addEventListener('click', async () => {
      const out = await submitObservation(input.value).catch((e) => ({ ok: false, error: String(e) }));
      status.textContent = out.ok ? 'Recorded!' : (out.error || `Error ${out.status}`);
      if (out.ok) { input.value = ''; panel.hidden = true; }
    });
    rootEl.appendChild(panel); rootEl.appendChild(pill);
    document.body.appendChild(rootEl);
  }

  async function init() {
    if (enabled) return true;
    const fetchFn = window.fetch || (typeof fetch === 'function' ? fetch : null);
    if (typeof fetchFn !== 'function') return false;
    try {
      const res = await fetchFn(SUMMARY_URL);
      if (!res || !res.ok) return false;
      const data = await res.json();
      if (!data || !data.debug_mode) return false;
      enabled = true; installInterceptors(); mountHud();
      return true;
    } catch (_err) { return false; }
  }

  window.DebugObservationHUD = { init, submitObservation, pushBreadcrumb, getBreadcrumbs: () => crumbs.slice(), isEnabled: () => enabled };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { init(); });
  else init();
})();
