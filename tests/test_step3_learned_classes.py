"""Node VM UI tests for Step 3 Milestone 4: ClassesBadgesManager and deep-linking."""

import json
import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_PATH = os.path.join(REPO_ROOT, "dashboard", "static", "js", "classes_badges_manager.js")


def _run_node_harness(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node harness failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


_HARNESS_TEMPLATE = """
const fs = require('fs');
const vm = require('vm');
const panel = { id: 'gallery-category-crud-panel', style: { display: 'none' }, innerHTML: '', querySelector: () => null, querySelectorAll: () => [] };
const manageBtn = { id: 'btn-manage-categories', dataset: {}, addEventListener: () => {} };
const fetchCalls = [], badgeCalls = [], navCalls = [];
const sandbox = {
  console,
  window: {
    location: { hash: '#gallery?view=classes-badges' },
    addEventListener: () => {},
    showToast: () => {},
    App: { navigate: (tab) => navCalls.push(tab) },
    CategoryBadgeManager: {
      fetchCategories: async () => [{ id: 'staff', name: 'Staff', color: '#3B82F6' }],
      getCategories: () => [{ id: 'staff', name: 'Staff', color: '#3B82F6' }],
      renderBadgeHtml: (id) => `<span>${id}</span>`,
      saveCategory: async (isEdit, payload) => badgeCalls.push({ op: 'save', isEdit, payload }),
      deleteCategory: async (id) => badgeCalls.push({ op: 'delete', id }),
    },
  },
  document: {
    readyState: 'complete',
    getElementById: (id) => (id === 'gallery-category-crud-panel' ? panel : id === 'btn-manage-categories' ? manageBtn : null),
  },
  fetch: async (url, opts = {}) => {
    fetchCalls.push({ url, method: opts.method || 'GET', body: opts.body || null });
    if (url.startsWith('/api/cameras')) return { ok: true, json: async () => [{ id: 'cam_0', name: 'Front' }] };
    if (url.startsWith('/api/classes/overrides/cam_0') && (opts.method || 'GET') === 'GET') return { ok: true, json: async () => [{ coco_class: 'chair', action: 'suppress', relabel_to: '' }] };
    if (url.startsWith('/api/classes/overrides/cam_0') && opts.method === 'PUT') return { ok: true, json: async () => ({ coco_class: 'chair', action: 'suppress' }) };
    if (url === '/api/classes/learned' && (opts.method || 'GET') === 'GET') return { ok: true, json: async () => [{ id: 1, name: 'Delivery Box', color: '#06B6D4', threshold: 0.65, exemplar_count: 1 }] };
    if (url === '/api/classes/learned/1/exemplars') {
      const parsed = JSON.parse(opts.body || '{}');
      if (!parsed.force) return { ok: true, json: async () => ({ status: 'collision', enrolled: false, collisions: [{ kind: 'entity', id: 2, name: 'Alice', score: 0.91 }] }) };
      return { ok: true, json: async () => ({ status: 'ok', enrolled: true, exemplar_id: 9 }) };
    }
    return { ok: true, json: async () => ({}) };
  },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__JS_PATH__, 'utf8'), sandbox);
(async () => {
  const mgr = sandbox.window.ClassesBadgesManager;
  await mgr.open('coco');
  await mgr.saveOverride('cam_0', 'chair', 'suppress', '');
  mgr.switchSection('learned');
  const colRes = await mgr.enrollExemplar(1, { crop_base64: 'abc' });
  const hasBanner = panel.innerHTML.includes('cb-collision-banner');
  const forceRes = await mgr.enrollExemplar(1, { crop_base64: 'abc', force: true });
  mgr.switchSection('badges');
  const hasBadgesPane = panel.innerHTML.includes('data-section="badges"');
  await sandbox.window.CategoryBadgeManager.saveCategory(false, { id: 'vip', name: 'VIP' });
  console.log(JSON.stringify({
    navCalls, panelDisplay: panel.style.display, colStatus: colRes.status, hasBanner,
    forceEnrolled: forceRes.enrolled, hasBadgesPane, badgeCallsCount: badgeCalls.length,
    overridePutSeen: fetchCalls.some((c) => c.method === 'PUT' && c.url.includes('/api/classes/overrides/cam_0')),
  }));
})().catch((err) => { console.error(err); process.exit(1); });
"""


class TestClassesBadgesManagerUI(unittest.TestCase):
    """Verifies ClassesBadgesManager 3-tab switching, overrides, collisions, badges, and deep-links."""

    def test_classes_badges_manager_flows(self) -> None:
        result = _run_node_harness(_HARNESS_TEMPLATE.replace("__JS_PATH__", json.dumps(JS_PATH)))
        self.assertIn("tab-gallery", result["navCalls"])
        self.assertEqual(result["panelDisplay"], "block")
        self.assertEqual(result["colStatus"], "collision")
        self.assertTrue(result["hasBanner"])
        self.assertTrue(result["forceEnrolled"])
        self.assertTrue(result["hasBadgesPane"])
        self.assertEqual(result["badgeCallsCount"], 1)
        self.assertTrue(result["overridePutSeen"])


if __name__ == "__main__":
    unittest.main()
