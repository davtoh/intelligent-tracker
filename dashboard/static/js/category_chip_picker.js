/**
 * Category Chip Picker: syncs clickable category chips with comma-separated
 * tracked-categories inputs across Camera AI Config, Video Batch, and Feed modals.
 */
(function () {
  'use strict';

  const TARGET_INPUT_IDS = [
    'cam-tracked-categories-input',
    'batch-tracked-categories-input',
    'feed-tracked-categories-input',
  ];

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function parseInput(value) {
    return String(value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function toggleCategory(inputEl, catId) {
    if (!inputEl || !catId) return [];
    const cur = parseInput(inputEl.value);
    const idx = cur.indexOf(catId);
    if (idx >= 0) cur.splice(idx, 1);
    else cur.push(catId);
    inputEl.value = cur.join(', ');
    if (typeof inputEl.dispatchEvent === 'function' && typeof Event === 'function') {
      inputEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return cur;
  }

  function syncChipActiveStates(barEl, inputEl) {
    if (!barEl || !inputEl) return;
    const selected = new Set(parseInput(inputEl.value));
    barEl.querySelectorAll?.('.btn-cat-chip')?.forEach((btn) => {
      const cat = btn.getAttribute('data-cat');
      btn.classList?.toggle?.('active', selected.has(cat));
    });
  }

  function getOrCreateBar(inputEl) {
    const parent = inputEl.parentNode || inputEl.parentElement;
    if (!parent) return null;
    const existing = parent.querySelector?.(`.category-chip-picker-bar[data-chip-target="${inputEl.id}"]`)
      || parent.querySelector?.('.class-presets-bar');
    if (existing) {
      existing.classList?.add?.('category-chip-picker-bar');
      existing.setAttribute?.('data-chip-target', inputEl.id);
      return existing;
    }
    if (typeof document.createElement !== 'function') return null;
    const bar = document.createElement('div');
    bar.className = 'class-presets-bar category-chip-picker-bar';
    bar.setAttribute?.('data-chip-target', inputEl.id);
    if (typeof parent.insertBefore === 'function') parent.insertBefore(bar, inputEl.nextSibling || null);
    else parent.appendChild?.(bar);
    return bar;
  }

  function renderChips(barEl, inputEl, categories) {
    if (!barEl || !inputEl) return;
    const cats = Array.isArray(categories) ? categories : [];
    const selected = new Set(parseInput(inputEl.value));
    barEl.innerHTML = cats.map((c) => {
      const id = String(c.id || '').trim();
      const act = selected.has(id) ? ' active' : '';
      return `<button type="button" class="btn-tag-preset btn-cat-chip${act}" data-cat="${escapeHtml(id)}">${escapeHtml(c.name || id)}</button>`;
    }).join('');
    barEl.querySelectorAll?.('.btn-cat-chip')?.forEach((btn) => {
      btn.addEventListener('click', () => {
        toggleCategory(inputEl, btn.getAttribute('data-cat'));
        syncChipActiveStates(barEl, inputEl);
      });
    });
  }

  function mountForInput(inputId, categories) {
    const inputEl = document.getElementById(inputId);
    if (!inputEl) return null;
    const barEl = getOrCreateBar(inputEl);
    if (!barEl) return null;
    const cats = Array.isArray(categories) && categories.length
      ? categories
      : (window.CategoryBadgeManager?.getCategories?.() || []);
    renderChips(barEl, inputEl, cats);
    if (inputEl.dataset && inputEl.dataset.chipPickerBound !== 'true') {
      inputEl.dataset.chipPickerBound = 'true';
      inputEl.addEventListener?.('input', () => syncChipActiveStates(barEl, inputEl));
      inputEl.addEventListener?.('change', () => syncChipActiveStates(barEl, inputEl));
    }
    return barEl;
  }

  function syncAll(categories) {
    TARGET_INPUT_IDS.forEach((id) => mountForInput(id, categories));
  }

  if (typeof document !== 'undefined') {
    document.addEventListener?.('categories:changed', (e) => {
      syncAll(e?.detail?.categories);
    });
    if (document.readyState === 'loading') document.addEventListener?.('DOMContentLoaded', () => syncAll());
    else syncAll();
  }

  window.CategoryChipPicker = {
    TARGET_INPUT_IDS,
    parseInput,
    toggleCategory,
    mountForInput,
    syncAll,
  };
})();
