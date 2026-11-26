/**
 * Inline "+ New / Manage" quick-create controls beneath [data-category-select] dropdowns.
 */
(function () {
  'use strict';

  function slugify(text) {
    return String(text || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 48);
  }

  function showToast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(title, body, type);
  }

  function dispatchCategoriesChanged(categories) {
    if (typeof document.dispatchEvent !== 'function' || typeof CustomEvent !== 'function') return;
    document.dispatchEvent(new CustomEvent('categories:changed', { detail: { categories: categories || [] } }));
  }

  async function createCategoryInline(selectEl, payload) {
    const res = await fetch('/api/rsac/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Category create failed');
    }
    const data = await res.json().catch(() => ({}));
    const createdId = data?.category?.id || payload.id;
    let cats = [];
    if (window.CategoryBadgeManager?.fetchCategories) {
      cats = await window.CategoryBadgeManager.fetchCategories(true);
      window.CategoryBadgeManager.syncAllTargets?.();
    }
    if (selectEl) {
      const hasOpt = Array.from(selectEl.options || []).some((o) => o.value === createdId);
      if (!hasOpt && typeof document.createElement === 'function') {
        const opt = document.createElement('option');
        opt.value = createdId;
        opt.textContent = `${payload.name} (${createdId})`;
        selectEl.appendChild?.(opt);
      }
      selectEl.value = createdId;
      if (typeof selectEl.dispatchEvent === 'function' && typeof Event === 'function') {
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
    dispatchCategoriesChanged(cats);
    showToast('Category Created', `Added "${payload.name}" (${createdId}).`, 'success');
    return createdId;
  }

  function openManagePanel() {
    const panel = document.getElementById('gallery-category-crud-panel');
    if (panel) {
      panel.style.display = 'block';
      window.CategoryBadgeManager?.fetchCategories?.(true).then(() => {
        window.CategoryBadgeManager?.syncAllTargets?.();
      });
      panel.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    document.querySelector('[data-tab="tab-gallery"]')?.click?.();
  }

  function bindControls(wrap, selectEl) {
    const toggleBtn = wrap.querySelector('.btn-cat-quick-new');
    const manageBtn = wrap.querySelector('.btn-cat-quick-manage');
    const formBox = wrap.querySelector('.cat-quick-create-form');
    const nameInput = wrap.querySelector('.cat-qc-name');
    const slugInput = wrap.querySelector('.cat-qc-slug');
    const colorInput = wrap.querySelector('.cat-qc-color');
    const saveBtn = wrap.querySelector('.btn-cat-qc-save');
    const cancelBtn = wrap.querySelector('.btn-cat-qc-cancel');
    let slugEdited = false;

    slugInput?.addEventListener('input', () => { slugEdited = true; });
    nameInput?.addEventListener('input', () => {
      if (!slugEdited && slugInput) slugInput.value = slugify(nameInput.value);
    });
    toggleBtn?.addEventListener('click', () => {
      if (!formBox) return;
      const open = formBox.style.display === 'none' || !formBox.style.display;
      formBox.style.display = open ? 'flex' : 'none';
      if (open) nameInput?.focus?.();
    });
    cancelBtn?.addEventListener('click', () => { if (formBox) formBox.style.display = 'none'; });
    manageBtn?.addEventListener('click', openManagePanel);
    saveBtn?.addEventListener('click', async () => {
      const name = (nameInput?.value || '').trim();
      const id = slugify(slugInput?.value || name);
      const color = colorInput?.value || '#3B82F6';
      if (!id || !name) return showToast('Validation', 'Name and valid slug are required.', 'warning');
      try {
        await createCategoryInline(selectEl, { id, name, color, badge_icon: '', description: '' });
        if (nameInput) nameInput.value = '';
        if (slugInput) slugInput.value = '';
        slugEdited = false;
        if (formBox) formBox.style.display = 'none';
      } catch (err) {
        showToast('Category Error', err.message, 'error');
      }
    });
  }

  function attachToSelect(selectEl) {
    if (!selectEl || selectEl.dataset?.quickCreateMounted === 'true') return null;
    const parent = selectEl.parentNode;
    if (!parent || typeof document.createElement !== 'function') return null;
    if (selectEl.dataset) selectEl.dataset.quickCreateMounted = 'true';
    const wrap = document.createElement('div');
    wrap.className = 'cat-quick-create-wrap';
    wrap.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px;';
    wrap.innerHTML =
      '<div style="display:flex;gap:8px;align-items:center;">'
      + '<button type="button" class="btn btn-xs btn-outline btn-cat-quick-new">+ New</button>'
      + '<button type="button" class="btn btn-xs btn-outline btn-cat-quick-manage">Manage</button>'
      + '</div>'
      + '<div class="cat-quick-create-form" style="display:none;flex-wrap:wrap;gap:6px;align-items:center;">'
      + '<input type="text" class="form-input cat-qc-name" placeholder="Name (e.g. Contractor)" style="flex:1;min-width:110px;font-size:12px;padding:3px 6px;" />'
      + '<input type="text" class="form-input cat-qc-slug" placeholder="slug" style="width:96px;font-size:12px;padding:3px 6px;" />'
      + '<input type="color" class="cat-qc-color" value="#3B82F6" style="width:28px;height:26px;border:none;background:none;" />'
      + '<button type="button" class="btn btn-xs btn-primary btn-cat-qc-save">Save</button>'
      + '<button type="button" class="btn btn-xs btn-outline btn-cat-qc-cancel">Cancel</button>'
      + '</div>';
    if (typeof parent.insertBefore === 'function') parent.insertBefore(wrap, selectEl.nextSibling || null);
    else parent.appendChild?.(wrap);
    bindControls(wrap, selectEl);
    return wrap;
  }

  function mountAll(root = document) {
    root?.querySelectorAll?.('[data-category-select]')?.forEach((sel) => attachToSelect(sel));
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener?.('DOMContentLoaded', () => mountAll());
    else mountAll();
  }

  window.CategoryQuickCreate = { slugify, createCategoryInline, attachToSelect, mountAll };
})();
