/**
 * Intelligent Tracker - Dynamic Semantic Category Badge Manager.
 * Fetches/caches /api/rsac/categories, syncs dropdowns and gallery filter pills,
 * and powers inline Category Badge CRUD inside #tab-gallery.
 */
(function () {
  'use strict';

  let cachedCategories = [];
  let onGalleryFilterChange = null;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(title, body, type);
  }

  function getBadgeMeta(catId) {
    const clean = String(catId || 'person').trim().toLowerCase();
    const found = cachedCategories.find((c) => String(c.id).toLowerCase() === clean);
    return found || { id: clean, name: clean, color: '#94a3b8', badge_icon: '', description: '' };
  }

  function renderBadgeHtml(catId) {
    const meta = getBadgeMeta(catId);
    const icon = meta.badge_icon ? `${escapeHtml(meta.badge_icon)} ` : '';
    const style = meta.color ? ` style="--badge-color: ${escapeHtml(meta.color)};"` : '';
    return `<span class="badge-category ${escapeHtml(meta.id)}"${style}>${icon}${escapeHtml(meta.name || meta.id)}</span>`;
  }

  function dispatchChanged() {
    if (typeof document.dispatchEvent !== 'function' || typeof CustomEvent !== 'function') return;
    document.dispatchEvent(new CustomEvent('categories:changed', { detail: { categories: cachedCategories.slice() } }));
  }

  async function fetchCategories(forceRefresh = false) {
    if (!forceRefresh && cachedCategories.length > 0) return cachedCategories;
    try {
      const res = await fetch('/api/rsac/categories');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) cachedCategories = data;
      }
    } catch (err) {
      console.warn('CategoryBadgeManager: failed to fetch categories:', err);
    }
    return cachedCategories;
  }

  function syncSelect(selectEl, options = {}) {
    if (!selectEl || !cachedCategories.length) return;
    const prev = selectEl.value;
    const prefix = options.includeAll ? '<option value="">All Categories</option>' : '';
    const opts = cachedCategories.map((c) => {
      const icon = c.badge_icon ? `${escapeHtml(c.badge_icon)} ` : '';
      return `<option value="${escapeHtml(c.id)}">${icon}${escapeHtml(c.name)} (${escapeHtml(c.id)})</option>`;
    });
    selectEl.innerHTML = prefix + opts.join('');
    if (prev && Array.from(selectEl.options || []).some((o) => o.value === prev)) {
      selectEl.value = prev;
    }
  }

  function bindFilterPillClicks(container) {
    container.querySelectorAll('.filter-pill').forEach((pill) => {
      pill.addEventListener('click', () => {
        container.querySelectorAll('.filter-pill').forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');
        if (typeof onGalleryFilterChange === 'function') onGalleryFilterChange();
        else window.GalleryTimeline?.renderGalleryGrid?.();
      });
    });
  }

  function syncGalleryFilterPills(container) {
    if (!container || !cachedCategories.length) return;
    const active = container.querySelector('.filter-pill.active')?.getAttribute('data-category') || '';
    const pills = [`<button class="filter-pill${active === '' ? ' active' : ''}" data-category="">All</button>`];
    cachedCategories.forEach((c) => {
      const isAct = active === c.id ? ' active' : '';
      const icon = c.badge_icon ? `${escapeHtml(c.badge_icon)} ` : '';
      pills.push(
        `<button class="filter-pill${isAct}" data-category="${escapeHtml(c.id)}" style="--badge-color: ${escapeHtml(c.color || '#94a3b8')}">${icon}${escapeHtml(c.name)}</button>`
      );
    });
    container.innerHTML = pills.join('');
    bindFilterPillClicks(container);
  }

  function syncAllTargets() {
    const seen = new Set();
    const targets = [
      ['enroll-category-select', false],
      ['tag-category-select', false],
      ['quick-enroll-category-select', false],
      ['modal-zone-category-select', true],
    ];
    targets.forEach(([id, includeAll]) => {
      const el = document.getElementById(id);
      if (el) { seen.add(el); syncSelect(el, { includeAll }); }
    });
    document.querySelectorAll?.('[data-category-select]')?.forEach((el) => {
      if (seen.has(el)) return;
      const includeAll = el.dataset?.includeAll === 'true' || el.id === 'modal-zone-category-select';
      syncSelect(el, { includeAll });
    });
    syncGalleryFilterPills(document.getElementById('gallery-category-filters'));
    window.CategoryChipPicker?.syncAll?.(cachedCategories);
    renderCrudPanel();
  }

  async function saveCategory(isEdit, payload) {
    const url = isEdit ? `/api/rsac/categories/${encodeURIComponent(payload.id)}` : '/api/rsac/categories';
    const method = isEdit ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Category save failed');
    await fetchCategories(true);
    syncAllTargets();
    dispatchChanged();
    showToast('Category Saved', `Badge "${payload.name}" updated.`, 'success');
  }

  async function deleteCategory(catId) {
    const res = await fetch(`/api/rsac/categories/${encodeURIComponent(catId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Delete category failed');
    await fetchCategories(true);
    syncAllTargets();
    dispatchChanged();
    showToast('Category Removed', `Badge "${catId}" deleted.`, 'info');
  }

  async function exportCategories() {
    const res = await fetch('/api/rsac/categories/export');
    if (!res.ok) throw new Error('Category export failed');
    const data = await res.json();
    if (typeof Blob === 'function' && typeof URL?.createObjectURL === 'function' && typeof document.createElement === 'function') {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'categories_preset.json';
      a.click?.();
    }
    return data;
  }

  async function importCategories(payload, mode = 'merge') {
    const categories = Array.isArray(payload) ? payload : (payload?.categories || []);
    const res = await fetch('/api/rsac/categories/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ categories, mode: mode || 'merge' }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Category import failed');
    const summary = await res.json();
    await fetchCategories(true);
    syncAllTargets();
    dispatchChanged();
    showToast('Categories Imported', `Imported ${summary.imported ?? 0} categories (${mode}).`, 'success');
    return summary;
  }

  function buildCrudRowHtml(c) {
    return `
      <div class="cat-crud-row" data-cat-id="${escapeHtml(c.id)}" style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;background:rgba(15,23,42,0.5);">
        ${renderBadgeHtml(c.id)}
        <input type="text" class="form-input cat-edit-name" value="${escapeHtml(c.name)}" style="flex:1;min-width:90px;padding:3px 6px;font-size:12px;" />
        <input type="color" class="cat-edit-color" value="${escapeHtml(c.color || '#3B82F6')}" title="Badge Color" style="width:30px;height:26px;border:none;background:none;cursor:pointer;" />
        <input type="text" class="form-input cat-edit-icon" value="${escapeHtml(c.badge_icon || '')}" placeholder="Icon" style="width:46px;padding:3px 6px;font-size:12px;" />
        <button type="button" class="btn btn-xs btn-outline btn-cat-save" data-id="${escapeHtml(c.id)}">Save</button>
        <button type="button" class="btn btn-xs btn-outline btn-cat-del" data-id="${escapeHtml(c.id)}" style="color:#ef4444;">✕</button>
      </div>`;
  }

  function renderCrudPanel() {
    const panel = document.getElementById('gallery-category-crud-panel');
    if (!panel) return;
    panel.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
        <strong>Semantic Category Badges</strong>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <button type="button" class="btn btn-xs btn-outline" id="btn-cat-export">⬇ Export Preset</button>
          <select id="cat-import-mode" class="form-input" style="width:auto;font-size:11px;padding:2px 6px;"><option value="merge">Merge</option><option value="replace">Replace</option></select>
          <button type="button" class="btn btn-xs btn-outline" id="btn-cat-import">⬆ Import Preset</button>
          <input type="file" id="cat-import-file" accept=".json,application/json" style="display:none;" />
          <button type="button" class="btn btn-xs btn-outline" id="btn-close-cat-crud">Close</button>
        </div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">
        <input type="text" id="cat-new-id" class="form-input" placeholder="slug (e.g. contractor)" style="width:130px;font-size:12px;" />
        <input type="text" id="cat-new-name" class="form-input" placeholder="Display Name" style="flex:1;min-width:120px;font-size:12px;" />
        <input type="color" id="cat-new-color" value="#3B82F6" style="width:32px;height:30px;border:none;background:none;" />
        <input type="text" id="cat-new-icon" class="form-input" placeholder="🏷️" style="width:48px;font-size:12px;" />
        <button type="button" class="btn btn-xs btn-primary" id="btn-cat-create">➕ Add Badge</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;max-height:220px;overflow-y:auto;">
        ${cachedCategories.map(buildCrudRowHtml).join('')}
      </div>`;
    bindCrudPanelEvents(panel);
    bindPresetEvents(panel);
  }

  function bindPresetEvents(panel) {
    panel.querySelector('#btn-cat-export')?.addEventListener('click', async () => {
      try { await exportCategories(); } catch (e) { showToast('Export Error', e.message, 'error'); }
    });
    const fileInput = panel.querySelector('#cat-import-file');
    panel.querySelector('#btn-cat-import')?.addEventListener('click', () => fileInput?.click?.());
    fileInput?.addEventListener('change', async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      try {
        const parsed = JSON.parse(await file.text());
        const mode = panel.querySelector('#cat-import-mode')?.value || 'merge';
        await importCategories(parsed, mode);
      } catch (e) {
        showToast('Import Error', e.message, 'error');
      } finally {
        fileInput.value = '';
      }
    });
  }

  function bindCrudPanelEvents(panel) {
    panel.querySelector('#btn-close-cat-crud')?.addEventListener('click', () => { panel.style.display = 'none'; });
    panel.querySelector('#btn-cat-create')?.addEventListener('click', async () => {
      const id = (panel.querySelector('#cat-new-id')?.value || '').trim().toLowerCase();
      const name = (panel.querySelector('#cat-new-name')?.value || '').trim();
      const color = panel.querySelector('#cat-new-color')?.value || '#3B82F6';
      const badge_icon = (panel.querySelector('#cat-new-icon')?.value || '').trim();
      if (!id || !name) return showToast('Validation', 'Badge slug and name are required.', 'warning');
      try { await saveCategory(false, { id, name, color, badge_icon, description: '' }); } catch (e) { showToast('Error', e.message, 'error'); }
    });
    panel.querySelectorAll('.btn-cat-save').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const row = btn.closest('.cat-crud-row');
        const id = btn.getAttribute('data-id');
        const name = (row?.querySelector('.cat-edit-name')?.value || '').trim();
        const color = row?.querySelector('.cat-edit-color')?.value || '#3B82F6';
        const badge_icon = (row?.querySelector('.cat-edit-icon')?.value || '').trim();
        if (!name) return;
        try { await saveCategory(true, { id, name, color, badge_icon, description: '' }); } catch (e) { showToast('Error', e.message, 'error'); }
      });
    });
    panel.querySelectorAll('.btn-cat-del').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try { await deleteCategory(btn.getAttribute('data-id')); } catch (e) { showToast('Error', e.message, 'error'); }
      });
    });
  }

  async function init(filterCb) {
    if (typeof filterCb === 'function') onGalleryFilterChange = filterCb;
    document.getElementById('btn-manage-categories')?.addEventListener('click', async () => {
      const panel = document.getElementById('gallery-category-crud-panel');
      if (!panel) return;
      const opening = panel.style.display === 'none' || !panel.style.display;
      if (opening) { await fetchCategories(true); renderCrudPanel(); }
      panel.style.display = opening ? 'block' : 'none';
    });
    await fetchCategories(true);
    syncAllTargets();
  }

  window.CategoryBadgeManager = {
    init,
    fetchCategories,
    getCategories: () => cachedCategories.slice(),
    getBadgeMeta,
    renderBadgeHtml,
    syncSelect,
    syncAllTargets,
    saveCategory,
    deleteCategory,
    exportCategories,
    importCategories,
    dispatchChanged,
  };
})();
