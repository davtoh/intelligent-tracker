#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for Step 2 Milestone 3: Inline Category Quick-Create, Chip Picker & Preset UI."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"
BADGE_JS = STATIC_DIR / "js" / "category_badge_manager.js"
QUICK_JS = STATIC_DIR / "js" / "category_quick_create.js"
CHIP_JS = STATIC_DIR / "js" / "category_chip_picker.js"

_VM_PRELUDE = """
const fs = require('fs'), vm = require('vm');
const makeEl = (id, tag = 'div') => {
  const el = {
    id, tagName: tag.toUpperCase(), value: '', _html: '', textContent: '', style: {},
    options: [], children: [], listeners: {}, attrs: {}, dataset: {}, files: [], parentNode: null,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, f) { f === undefined ? (this._s.has(c) ? this._s.delete(c) : this._s.add(c)) : (f ? this._s.add(c) : this._s.delete(c)); },
      contains(c) { return this._s.has(c); },
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    dispatchEvent(ev) { (this.listeners[ev.type] || []).forEach((fn) => fn(ev)); return true; },
    getAttribute(k) { return this.attrs[k] ?? null; },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(v); },
    appendChild(c) { c.parentNode = this; this.children.push(c); if (c.tagName === 'OPTION') this.options.push(c); return c; },
    insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; if (i >= 0) this.children.splice(i, 0, c); else this.children.push(c); return c; },
    querySelectorAll(sel) {
      if (sel.startsWith('.')) { const cls = sel.slice(1); return this.children.filter((c) => (c.className || '').includes(cls)); }
      return [];
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    closest() { return null; }, click() { this.dispatchEvent({ type: 'click' }); },
  };
  return el;
};
"""


def _run_vm(script_paths, body: str) -> dict:
    sources = ", ".join(json.dumps(str(p)) for p in script_paths)
    harness = _VM_PRELUDE + f"""
const byId = new Map(), docListeners = {{}};
const getOrMake = (id, tag = 'div') => {{ if (!byId.has(id)) byId.set(id, makeEl(id, tag)); return byId.get(id); }};
class CustomEvent {{ constructor(type, opts = {{}}) {{ this.type = type; this.detail = opts.detail || null; }} }}
class Event {{ constructor(type) {{ this.type = type; }} }}
const document = {{
  readyState: 'complete',
  getElementById: (id) => byId.get(id) || null,
  querySelectorAll: (sel) => sel === '[data-category-select]' ? Array.from(byId.values()).filter((e) => e.dataset.categorySelect === 'true') : [],
  querySelector: () => null,
  createElement: (tag) => makeEl('tmp_' + Math.random().toString(36).slice(2, 7), tag),
  addEventListener: (t, fn) => (docListeners[t] = docListeners[t] || []).push(fn),
  dispatchEvent: (ev) => {{ (docListeners[ev.type] || []).forEach((fn) => fn(ev)); return true; }},
}};
const window = {{ document, showToast() {{}}, setTimeout, clearTimeout }};
const ctx = vm.createContext({{ window, document, console, CustomEvent, Event, getOrMake, makeEl, byId, fetch: async () => ({{ ok: true, json: async () => [] }}), URL: {{ createObjectURL: () => 'blob:1' }}, Blob: function(){{}} }});
for (const p of [{sources}]) vm.runInContext(fs.readFileSync(p, 'utf8'), ctx);
vm.runInContext(`(async () => {{ {body} }})().then((r) => console.log(JSON.stringify(r))).catch((e) => {{ console.error(e); process.exit(1); }});`, ctx);
"""
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(proc.stdout.strip())


class TestStep2CategoryStaticContracts(unittest.TestCase):
    """Static checks for stripped residential options, budgets, and fallback."""

    def test_no_legacy_residential_options_or_css_and_budgets(self) -> None:
        entity_html = (STATIC_DIR / "partials" / "modals" / "entity_modals.html").read_text(encoding="utf-8")
        studio_html = (STATIC_DIR / "partials" / "modals" / "studio_modals.html").read_text(encoding="utf-8")
        badges_css = (STATIC_DIR / "css" / "badges.css").read_text(encoding="utf-8")
        index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        canvas_js = (STATIC_DIR / "js" / "interactive_canvas.js").read_text(encoding="utf-8")

        for legacy in ("family_car", "delivery_truck", "cleaning_crew", "guard_dog"):
            self.assertNotIn(legacy, entity_html)
            self.assertNotIn(legacy, studio_html)
            self.assertNotIn(legacy, badges_css)
        for sel_id in ("tag-category-select", "enroll-category-select", "quick-enroll-category-select"):
            self.assertIn(f'id="{sel_id}" class="form-input" data-category-select', entity_html)
        self.assertIn('id="modal-zone-category-select" class="form-input" data-category-select', studio_html)
        self.assertLess(len(entity_html.splitlines()), 240)
        self.assertLess(len(index_html.splitlines()), 180)
        self.assertIn("|| 'asset'", canvas_js)


@unittest.skipUnless(shutil.which("node"), "Node.js required for VM frontend tests")
class TestStep2CategoryUI(unittest.TestCase):
    """Node VM tests for quick-create, chip picker sync, and preset export/import."""

    def test_inline_quick_create_syncs_selects_and_dispatches_event(self) -> None:
        body = """
        const parent = makeEl('group');
        const tagSel = getOrMake('tag-category-select', 'select');
        tagSel.setAttribute('data-category-select', 'true');
        parent.appendChild(tagSel);
        const enrollSel = getOrMake('enroll-category-select', 'select');
        enrollSel.setAttribute('data-category-select', 'true');
        let cats = [{ id: 'person', name: 'Person', color: '#94a3b8', badge_icon: '' }];
        const posts = [];
        fetch = async (url, opts) => {
          if (opts && opts.method === 'POST') {
            const p = JSON.parse(opts.body); posts.push({ url, p }); cats = [...cats, p];
            return { ok: true, json: async () => ({ status: 'created', category: p }) };
          }
          return { ok: true, json: async () => cats };
        };
        let changedCount = 0;
        document.addEventListener('categories:changed', () => { changedCount += 1; });
        await window.CategoryBadgeManager.init();
        await window.CategoryQuickCreate.createCategoryInline(tagSel, { id: 'contractor', name: 'Contractor', color: '#10b981' });
        return { posts, tagVal: tagSel.value, enrollHtml: enrollSel.innerHTML, changedCount };
        """
        out = _run_vm([BADGE_JS, QUICK_JS], body)
        self.assertEqual(out["posts"][0]["url"], "/api/rsac/categories")
        self.assertEqual(out["tagVal"], "contractor")
        self.assertIn("Contractor", out["enrollHtml"])
        self.assertGreaterEqual(out["changedCount"], 1)

    def test_chip_picker_syncs_three_inputs_and_reacts_to_categories_changed(self) -> None:
        body = """
        const ids = ['cam-tracked-categories-input', 'batch-tracked-categories-input', 'feed-tracked-categories-input'];
        const bars = {};
        ids.forEach((id) => {
          const p = makeEl('grp_' + id);
          const inp = getOrMake(id, 'input');
          p.appendChild(inp);
          const bar = makeEl('bar_' + id);
          bar.className = 'class-presets-bar';
          p.appendChild(bar);
          bars[id] = bar;
        });
        const initial = [{ id: 'vip', name: 'VIP' }, { id: 'staff', name: 'Staff' }];
        fetch = async () => ({ ok: true, json: async () => initial });
        await window.CategoryBadgeManager.init();
        window.CategoryChipPicker.toggleCategory(byId.get('batch-tracked-categories-input'), 'vip');
        window.CategoryChipPicker.toggleCategory(byId.get('feed-tracked-categories-input'), 'staff');
        document.dispatchEvent(new CustomEvent('categories:changed', { detail: { categories: [...initial, { id: 'contractor', name: 'Contractor' }] } }));
        return {
          batchVal: byId.get('batch-tracked-categories-input').value,
          feedVal: byId.get('feed-tracked-categories-input').value,
          camBar: bars['cam-tracked-categories-input'].innerHTML,
          batchBar: bars['batch-tracked-categories-input'].innerHTML,
        };
        """
        out = _run_vm([BADGE_JS, CHIP_JS], body)
        self.assertEqual(out["batchVal"], "vip")
        self.assertEqual(out["feedVal"], "staff")
        self.assertIn("Contractor", out["camBar"])
        self.assertIn("Contractor", out["batchBar"])

    def test_preset_export_and_import_triggers(self) -> None:
        body = """
        const panel = getOrMake('gallery-category-crud-panel');
        let cats = [{ id: 'person', name: 'Person', color: '#94a3b8', badge_icon: '' }];
        const calls = [];
        fetch = async (url, opts) => {
          calls.push({ url, method: opts?.method || 'GET' });
          if (url === '/api/rsac/categories/export') return { ok: true, json: async () => ({ format: 'intelligent-tracker.categories', version: 1, categories: cats }) };
          if (url === '/api/rsac/categories/import') { cats = [...cats, { id: 'contractor', name: 'Contractor', color: '#10b981', badge_icon: '' }]; return { ok: true, json: async () => ({ imported: 1, deleted: 0, skipped: [] }) }; }
          return { ok: true, json: async () => cats };
        };
        let changed = 0;
        document.addEventListener('categories:changed', () => { changed += 1; });
        await window.CategoryBadgeManager.init();
        const exported = await window.CategoryBadgeManager.exportCategories();
        const imported = await window.CategoryBadgeManager.importCategories({ categories: [{ id: 'contractor', name: 'Contractor' }] }, 'merge');
        return { panelHtml: panel.innerHTML, exported, imported, calls, changed };
        """
        out = _run_vm([BADGE_JS], body)
        self.assertIn("btn-cat-export", out["panelHtml"])
        self.assertIn("btn-cat-import", out["panelHtml"])
        self.assertEqual(out["exported"]["version"], 1)
        self.assertEqual(out["imported"]["imported"], 1)
        self.assertTrue(any(c["url"] == "/api/rsac/categories/export" for c in out["calls"]))
        self.assertTrue(any(c["url"] == "/api/rsac/categories/import" for c in out["calls"]))
        self.assertGreaterEqual(out["changed"], 1)


if __name__ == "__main__":
    unittest.main()
