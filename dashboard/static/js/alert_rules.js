/**
 * Intelligent Tracker - Alert Promotion Rules & Policy Controller.
 * Manages /api/alerts/rules CRUD and /api/alerts/policy default min_severity persistence.
 */
(function () {
  'use strict';

  const state = {
    rules: [],
    policy: { dwell_override: null, alert_sensitivity: 1.0, extra: {} },
    loaded: false,
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function renderRules() {
    const listEl = document.getElementById('alert-rules-list');
    const badgeEl = document.getElementById('alert-rules-count');
    if (badgeEl) badgeEl.textContent = `${state.rules.length} rule${state.rules.length !== 1 ? 's' : ''}`;
    if (!listEl) return;
    if (!state.rules.length) {
      listEl.innerHTML = '<div class="text-subtle" style="padding:8px 0;">No custom alert promotion rules configured.</div>';
      return;
    }
    listEl.innerHTML = state.rules.map((r) => {
      const id = Number(r.id);
      const conds = [
        r.event_type ? `type:${r.event_type}` : '',
        r.zone_id ? `zone:${r.zone_id}` : '',
        r.camera_id ? `cam:${r.camera_id}` : '',
        r.min_dwell_time !== null && r.min_dwell_time !== undefined ? `dwell>=${r.min_dwell_time}s` : '',
      ].filter(Boolean).join(' · ') || 'All events';
      const sevClass = r.target_severity === 'critical' ? 'badge-category restricted' : 'badge-category vip';
      return `<div class="alert-rule-row" data-rule-id="${id}" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border-subtle, rgba(255,255,255,0.08));">
        <div style="min-width:0;flex:1;">
          <strong>${escapeHtml(r.name)}</strong>
          <span class="${sevClass}" style="margin-left:6px;">${escapeHtml(String(r.target_severity || 'warning').toUpperCase())}</span>
          <span class="text-subtle" style="margin-left:8px;font-size:12px;">${escapeHtml(conds)}</span>
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <button type="button" class="btn btn-xs ${r.enabled ? 'btn-primary' : 'btn-outline'}" onclick="window.AlertRules?.toggleRule?.(${id}, ${!r.enabled})">${r.enabled ? 'Enabled' : 'Disabled'}</button>
          <button type="button" class="btn btn-xs btn-outline" onclick="window.AlertRules?.deleteRule?.(${id})">🗑</button>
        </div>
      </div>`;
    }).join('');
  }

  async function loadRules() {
    try {
      const res = await fetch('/api/alerts/rules');
      if (!res.ok) return state.rules;
      const data = await res.json();
      state.rules = Array.isArray(data?.rules) ? data.rules : [];
      renderRules();
      return state.rules;
    } catch (err) {
      console.debug('[AlertRules] Failed to load rules:', err);
      return state.rules;
    }
  }

  async function loadPolicy(applyToFilter = false) {
    try {
      const res = await fetch('/api/alerts/policy');
      if (!res.ok) return state.policy;
      const data = await res.json();
      state.policy = data?.policy || state.policy;
      const savedMin = String(state.policy?.extra?.min_severity || '').trim();
      const filterEl = document.getElementById('alerts-filter-min-severity');
      if (applyToFilter && filterEl && !filterEl.value && savedMin) {
        filterEl.value = savedMin;
      }
      const statusEl = document.getElementById('alert-policy-status');
      if (statusEl) {
        statusEl.textContent = savedMin ? `Default: ${savedMin}+` : 'Default: All';
      }
      return state.policy;
    } catch (err) {
      console.debug('[AlertRules] Failed to load policy:', err);
      return state.policy;
    }
  }

  async function createRuleFromForm() {
    const nameEl = document.getElementById('alert-rule-name');
    const name = String(nameEl?.value || '').trim();
    if (!name) return null;
    const dwellRaw = String(document.getElementById('alert-rule-min-dwell')?.value || '').trim();
    const minDwell = dwellRaw !== '' && Number.isFinite(Number(dwellRaw)) ? Number(dwellRaw) : null;
    const payload = {
      name,
      event_type: String(document.getElementById('alert-rule-event-type')?.value || '').trim(),
      zone_id: String(document.getElementById('alert-rule-zone')?.value || '').trim(),
      min_dwell_time: minDwell,
      target_severity: String(document.getElementById('alert-rule-severity')?.value || 'warning').trim() || 'warning',
      add_tags: String(document.getElementById('alert-rule-tags')?.value || '').trim(),
      enabled: true,
    };
    const res = await fetch('/api/alerts/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    ['alert-rule-name', 'alert-rule-event-type', 'alert-rule-zone', 'alert-rule-min-dwell', 'alert-rule-tags'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    await loadRules();
    window.showToast?.('Promotion Rule Added', `Created rule "${name}"`, 'success');
    return data?.rule || null;
  }

  async function toggleRule(ruleId, enabled) {
    const res = await fetch(`/api/alerts/rules/${encodeURIComponent(String(ruleId))}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    await loadRules();
    return data?.rule || null;
  }

  async function deleteRule(ruleId) {
    const res = await fetch(`/api/alerts/rules/${encodeURIComponent(String(ruleId))}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    await loadRules();
    return data;
  }

  async function saveDefaultMinSeverity(minSeverity = null) {
    const val = minSeverity !== null
      ? String(minSeverity || '').trim()
      : String(document.getElementById('alerts-filter-min-severity')?.value || '').trim();
    const res = await fetch('/api/alerts/policy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra: { min_severity: val } }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.policy = data?.policy || state.policy;
    const statusEl = document.getElementById('alert-policy-status');
    if (statusEl) statusEl.textContent = val ? `Default: ${val}+` : 'Default: All';
    window.showToast?.('Alert Policy Saved', val ? `Default min severity: ${val}+` : 'Default min severity: All', 'info');
    return state.policy;
  }

  function bindControls() {
    const bindOnce = (id, ev, fn) => {
      const el = document.getElementById(id);
      if (el && !el.dataset?.bound) {
        if (el.dataset) el.dataset.bound = '1';
        el.addEventListener?.(ev, fn);
      }
    };
    bindOnce('btn-alert-rule-add', 'click', () => createRuleFromForm());
    bindOnce('btn-alerts-save-policy', 'click', () => saveDefaultMinSeverity());
  }

  async function ensureLoaded(applyToFilter = true) {
    bindControls();
    if (state.loaded) return state;
    state.loaded = true;
    await Promise.all([loadRules(), loadPolicy(applyToFilter)]);
    return state;
  }

  window.AlertRules = {
    state,
    renderRules,
    loadRules,
    loadPolicy,
    createRuleFromForm,
    toggleRule,
    deleteRule,
    saveDefaultMinSeverity,
    bindControls,
    ensureLoaded,
  };
})();
