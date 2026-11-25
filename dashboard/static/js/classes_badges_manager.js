/**
 * Intelligent Tracker - Unified Classes & Badges Sub-View Manager.
 * Elevates #gallery-category-crud-panel (#gallery?view=classes-badges) into 3 tabs:
 *   1. COCO Detector Classes + per-camera suppress/relabel rules
 *   2. Learned Exemplar Classes (with collision guard)
 *   3. Semantic Category Badges (delegates CRUD to CategoryBadgeManager)
 */
(function () {
  'use strict';

  const DEFAULT_COCO_CLASSES = [
    'person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'dog', 'cat',
    'backpack', 'handbag', 'suitcase', 'cell phone', 'laptop', 'bottle',
  ];

  const state = {
    activeSection: 'coco',
    selectedCameraId: 'cam_0',
    cameras: [],
    overrides: [],
    learnedClasses: [],
    pendingCollision: null,
  };

  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(title, body, type);
  }

  async function loadCameras() {
    try {
      const res = await fetch('/api/cameras');
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data?.cameras || []);
        state.cameras = list.map((c) => ({ id: c.id || c.camera_id || 'cam_0', name: c.name || c.id || 'cam_0' }));
        if (state.cameras.length && !state.cameras.some((c) => c.id === state.selectedCameraId)) {
          state.selectedCameraId = state.cameras[0].id;
        }
      }
    } catch (_) { /* ignore */ }
  }

  async function loadOverrides(cameraId) {
    const cam = cameraId || state.selectedCameraId || 'cam_0';
    state.selectedCameraId = cam;
    try {
      const res = await fetch(`/api/classes/overrides/${encodeURIComponent(cam)}`);
      if (res.ok) state.overrides = await res.json();
    } catch (_) { state.overrides = []; }
    return state.overrides;
  }

  async function saveOverride(cameraId, cocoClass, action, relabelTo = '') {
    const res = await fetch(`/api/classes/overrides/${encodeURIComponent(cameraId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coco_class: cocoClass, action, relabel_to: relabelTo }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to save override');
    await loadOverrides(cameraId);
    renderPanel();
    toast('Override Saved', `${cocoClass} -> ${action} on ${cameraId}`, 'success');
  }

  async function deleteOverride(cameraId, cocoClass) {
    const res = await fetch(
      `/api/classes/overrides/${encodeURIComponent(cameraId)}/${encodeURIComponent(cocoClass)}`,
      { method: 'DELETE' }
    );
    if (!res.ok) throw new Error('Failed to delete override');
    await loadOverrides(cameraId);
    renderPanel();
  }

  async function loadLearnedClasses() {
    try {
      const res = await fetch('/api/classes/learned');
      if (res.ok) state.learnedClasses = await res.json();
    } catch (_) { state.learnedClasses = []; }
    return state.learnedClasses;
  }

  async function createLearnedClass(payload) {
    const res = await fetch('/api/classes/learned', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to create learned class');
    await loadLearnedClasses();
    renderPanel();
    toast('Learned Class Created', `Added "${payload.name}"`, 'success');
  }

  async function deleteLearnedClass(classId) {
    const res = await fetch(`/api/classes/learned/${encodeURIComponent(classId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete learned class');
    await loadLearnedClasses();
    renderPanel();
  }

  async function enrollExemplar(classId, payload) {
    const res = await fetch(`/api/classes/learned/${encodeURIComponent(classId)}/exemplars`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Exemplar enrollment failed');
    if (data.status === 'collision' && !data.enrolled) {
      state.pendingCollision = { classId, payload, collisions: data.collisions || [] };
      renderPanel();
      return data;
    }
    state.pendingCollision = null;
    await loadLearnedClasses();
    renderPanel();
    toast('Exemplar Enrolled', 'Visual exemplar saved to learned class.', 'success');
    return data;
  }

  function renderCocoSection() {
    const camOpts = (state.cameras.length ? state.cameras : [{ id: state.selectedCameraId, name: state.selectedCameraId }])
      .map((c) => `<option value="${esc(c.id)}"${c.id === state.selectedCameraId ? ' selected' : ''}>${esc(c.name)}</option>`)
      .join('');
    const cocoOpts = DEFAULT_COCO_CLASSES.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    const rows = state.overrides.length
      ? state.overrides.map((o) => `
          <div class="cb-item-row" data-coco-class="${esc(o.coco_class)}">
            <div class="cb-item-meta">
              <strong>${esc(o.coco_class)}</strong>
              <span>${esc(o.action)}${o.relabel_to ? ` → ${esc(o.relabel_to)}` : ''}</span>
            </div>
            <button type="button" class="btn btn-xs btn-outline cb-del-override" data-coco="${esc(o.coco_class)}">✕</button>
          </div>`).join('')
      : '<div class="empty-state" style="padding:8px;">No per-camera COCO overrides configured.</div>';
    return `
      <div class="cb-section-pane${state.activeSection === 'coco' ? ' active' : ''}" data-section="coco">
        <div class="cb-form-row">
          <select id="cb-coco-camera" class="form-input" style="width:140px;font-size:12px;">${camOpts}</select>
          <select id="cb-coco-class" class="form-input" style="width:130px;font-size:12px;">${cocoOpts}</select>
          <select id="cb-coco-action" class="form-input" style="width:110px;font-size:12px;">
            <option value="suppress">Suppress</option>
            <option value="relabel">Relabel</option>
          </select>
          <input type="text" id="cb-coco-relabel" class="form-input" placeholder="Relabel target" style="flex:1;min-width:110px;font-size:12px;" />
          <button type="button" class="btn btn-xs btn-primary" id="cb-save-override">Save Rule</button>
        </div>
        <div class="cb-list" id="cb-overrides-list">${rows}</div>
      </div>`;
  }

  function renderLearnedSection() {
    const collisionHtml = state.pendingCollision
      ? `<div class="cb-collision-banner" id="cb-collision-banner">
           <span>⚠️ Visual collision detected with ${esc(state.pendingCollision.collisions.map((c) => `${c.name} (${Math.round(c.score * 100)}%)`).join(', '))}.</span>
           <div style="display:flex;gap:6px;">
             <button type="button" class="btn btn-xs btn-primary" id="cb-collision-force">Enroll Anyway</button>
             <button type="button" class="btn btn-xs btn-outline" id="cb-collision-cancel">Cancel</button>
           </div>
         </div>`
      : '';
    const rows = state.learnedClasses.length
      ? state.learnedClasses.map((lc) => `
          <div class="cb-item-row" data-class-id="${esc(lc.id)}">
            <div class="cb-item-meta">
              <span class="cb-color-dot" style="background:${esc(lc.color || '#06B6D4')};"></span>
              <strong>${esc(lc.name)}</strong>
              <span style="opacity:0.75;font-size:11px;">(${lc.exemplar_count || 0} exemplars · thr ${lc.threshold})</span>
            </div>
            <button type="button" class="btn btn-xs btn-outline cb-del-learned" data-id="${esc(lc.id)}">✕</button>
          </div>`).join('')
      : '<div class="empty-state" style="padding:8px;">No learned exemplar classes yet.</div>';
    return `
      <div class="cb-section-pane${state.activeSection === 'learned' ? ' active' : ''}" data-section="learned">
        ${collisionHtml}
        <div class="cb-form-row">
          <input type="text" id="cb-learned-name" class="form-input" placeholder="Class name (e.g. Delivery Box)" style="flex:1;min-width:140px;font-size:12px;" />
          <input type="text" id="cb-learned-parent" class="form-input" placeholder="Parent COCO (optional)" style="width:140px;font-size:12px;" />
          <input type="color" id="cb-learned-color" value="#06B6D4" style="width:32px;height:30px;border:none;background:none;" />
          <button type="button" class="btn btn-xs btn-primary" id="cb-create-learned">➕ Add Class</button>
        </div>
        <div class="cb-list" id="cb-learned-list">${rows}</div>
      </div>`;
  }

  function renderBadgesSection() {
    const cats = window.CategoryBadgeManager?.getCategories?.() || [];
    const rows = cats.map((c) => `
      <div class="cb-item-row" data-badge-id="${esc(c.id)}">
        <div class="cb-item-meta">
          ${window.CategoryBadgeManager?.renderBadgeHtml ? window.CategoryBadgeManager.renderBadgeHtml(c.id) : esc(c.name)}
        </div>
        <button type="button" class="btn btn-xs btn-outline cb-del-badge" data-id="${esc(c.id)}">✕</button>
      </div>`).join('');
    return `
      <div class="cb-section-pane${state.activeSection === 'badges' ? ' active' : ''}" data-section="badges">
        <div class="cb-form-row">
          <input type="text" id="cb-badge-id" class="form-input" placeholder="slug (e.g. contractor)" style="width:130px;font-size:12px;" />
          <input type="text" id="cb-badge-name" class="form-input" placeholder="Badge Name" style="flex:1;min-width:120px;font-size:12px;" />
          <input type="color" id="cb-badge-color" value="#3B82F6" style="width:32px;height:30px;border:none;background:none;" />
          <button type="button" class="btn btn-xs btn-primary" id="cb-create-badge">➕ Add Badge</button>
        </div>
        <div class="cb-list" id="cb-badges-list">${rows}</div>
      </div>`;
  }

  function renderPanel() {
    const panel = document.getElementById('gallery-category-crud-panel');
    if (!panel) return;
    panel.innerHTML = `
      <div class="cb-subview-header">
        <div class="cb-subview-tabs" role="tablist">
          <button type="button" class="cb-tab-btn${state.activeSection === 'coco' ? ' active' : ''}" data-cb-tab="coco">🎯 COCO Overrides</button>
          <button type="button" class="cb-tab-btn${state.activeSection === 'learned' ? ' active' : ''}" data-cb-tab="learned">🧠 Learned Classes</button>
          <button type="button" class="cb-tab-btn${state.activeSection === 'badges' ? ' active' : ''}" data-cb-tab="badges">🏷️ Semantic Badges</button>
        </div>
        <button type="button" class="btn btn-xs btn-outline" id="cb-close-panel">Close</button>
      </div>
      ${renderCocoSection()}
      ${renderLearnedSection()}
      ${renderBadgesSection()}`;
    bindPanelEvents(panel);
  }

  function bindPanelEvents(panel) {
    panel.querySelector('#cb-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
    panel.querySelectorAll('[data-cb-tab]').forEach((btn) => {
      btn.addEventListener('click', () => switchSection(btn.getAttribute('data-cb-tab')));
    });
    panel.querySelector('#cb-coco-camera')?.addEventListener('change', (e) => {
      loadOverrides(e.target.value).then(() => renderPanel());
    });
    panel.querySelector('#cb-save-override')?.addEventListener('click', async () => {
      const cam = panel.querySelector('#cb-coco-camera')?.value || state.selectedCameraId;
      const cls = panel.querySelector('#cb-coco-class')?.value || '';
      const act = panel.querySelector('#cb-coco-action')?.value || 'suppress';
      const rel = (panel.querySelector('#cb-coco-relabel')?.value || '').trim();
      try { await saveOverride(cam, cls, act, rel); } catch (e) { toast('Error', e.message, 'error'); }
    });
    panel.querySelectorAll('.cb-del-override').forEach((btn) => {
      btn.addEventListener('click', () => deleteOverride(state.selectedCameraId, btn.getAttribute('data-coco')));
    });
    panel.querySelector('#cb-create-learned')?.addEventListener('click', async () => {
      const name = (panel.querySelector('#cb-learned-name')?.value || '').trim();
      const parent = (panel.querySelector('#cb-learned-parent')?.value || '').trim();
      const color = panel.querySelector('#cb-learned-color')?.value || '#06B6D4';
      if (!name) return toast('Validation', 'Learned class name is required.', 'warning');
      try { await createLearnedClass({ name, parent_coco_class: parent, color }); } catch (e) { toast('Error', e.message, 'error'); }
    });
    panel.querySelectorAll('.cb-del-learned').forEach((btn) => {
      btn.addEventListener('click', () => deleteLearnedClass(btn.getAttribute('data-id')));
    });
    panel.querySelector('#cb-collision-force')?.addEventListener('click', async () => {
      if (!state.pendingCollision) return;
      const { classId, payload } = state.pendingCollision;
      await enrollExemplar(classId, { ...payload, force: true });
    });
    panel.querySelector('#cb-collision-cancel')?.addEventListener('click', () => {
      state.pendingCollision = null;
      renderPanel();
    });
    panel.querySelector('#cb-create-badge')?.addEventListener('click', async () => {
      const id = (panel.querySelector('#cb-badge-id')?.value || '').trim().toLowerCase();
      const name = (panel.querySelector('#cb-badge-name')?.value || '').trim();
      const color = panel.querySelector('#cb-badge-color')?.value || '#3B82F6';
      if (!id || !name) return toast('Validation', 'Badge slug and name are required.', 'warning');
      await window.CategoryBadgeManager?.saveCategory?.(false, { id, name, color, badge_icon: '', description: '' });
      renderPanel();
    });
    panel.querySelectorAll('.cb-del-badge').forEach((btn) => {
      btn.addEventListener('click', async () => {
        await window.CategoryBadgeManager?.deleteCategory?.(btn.getAttribute('data-id'));
        renderPanel();
      });
    });
  }

  function switchSection(section) {
    if (!['coco', 'learned', 'badges'].includes(section)) return;
    state.activeSection = section;
    renderPanel();
  }

  async function open(section) {
    if (section) state.activeSection = section;
    const panel = document.getElementById('gallery-category-crud-panel');
    if (!panel) return;
    panel.style.display = 'block';
    await Promise.all([loadCameras(), loadOverrides(state.selectedCameraId), loadLearnedClasses()]);
    if (window.CategoryBadgeManager?.fetchCategories) await window.CategoryBadgeManager.fetchCategories(true);
    renderPanel();
  }

  function checkDeepLink() {
    const hash = String(window.location?.hash || '');
    if (hash.includes('gallery') && hash.includes('view=classes-badges')) {
      window.App?.navigate?.('tab-gallery');
      open();
      return true;
    }
    return false;
  }

  function init() {
    const btn = document.getElementById('btn-manage-categories');
    if (btn && !btn.dataset.cbBound) {
      btn.dataset.cbBound = '1';
      btn.addEventListener('click', (e) => {
        e.stopImmediatePropagation?.();
        const panel = document.getElementById('gallery-category-crud-panel');
        if (!panel) return;
        const opening = panel.style.display === 'none' || !panel.style.display;
        if (opening) open();
        else panel.style.display = 'none';
      }, true);
    }
    window.addEventListener?.('hashchange', checkDeepLink);
    checkDeepLink();
  }

  window.ClassesBadgesManager = {
    init,
    open,
    switchSection,
    checkDeepLink,
    loadOverrides,
    saveOverride,
    deleteOverride,
    loadLearnedClasses,
    createLearnedClass,
    deleteLearnedClass,
    enrollExemplar,
    getState: () => ({ ...state }),
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
  }
})();
