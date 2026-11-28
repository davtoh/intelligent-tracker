"""Step 4 Tests: Review Queue Pagination/Triage, Bulk-Dismiss & Toast Deep-Link."""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard import dependencies as deps
from dashboard.app import app
from intelligent_tracker.database import TrackerDB

ROOT = Path(__file__).resolve().parent.parent

_NODE_VM_REVIEW_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

function makeEl(id) {
  const listeners = {}, classes = new Set();
  const el = {
    id, value: '', textContent: '', innerHTML: '', disabled: false, style: {},
    attrs: {}, children: [], scrolled: false,
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c), toggle: (c, f) => (f ? classes.add(c) : classes.delete(c)),
    },
    setAttribute: (k, v) => { el.attrs[k] = String(v); },
    getAttribute: (k) => el.attrs[k] ?? null,
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    click: () => (listeners.click || []).forEach((fn) => fn()),
    scrollIntoView: () => { el.scrolled = true; },
    querySelector: () => null, querySelectorAll: () => el.children,
    insertAdjacentHTML: (_p, html) => { el.innerHTML = html + el.innerHTML; rebuildCards(el); },
  };
  return el;
}

function rebuildCards(container) {
  container.children = [...String(container.innerHTML || '').matchAll(/data-item-id="(\d+)"/g)].map((m) => {
    const card = makeEl(`card-${m[1]}`);
    card.setAttribute('data-item-id', m[1]);
    return card;
  });
}

const ids = [
  'review-queue-container', 'review-inbox-counter', 'header-review-badge', 'drawer-review-badge',
  'review-pagination-bar', 'review-page-prev', 'review-page-info', 'review-page-next',
  'btn-review-bulk-dismiss', 'review-filter-matched', 'review-filter-reason', 'review-sort-select',
];
const els = Object.fromEntries(ids.map((id) => [id, makeEl(id)]));
let _rawHtml = '';
Object.defineProperty(els['review-queue-container'], 'innerHTML', {
  get: () => _rawHtml,
  set: (v) => { _rawHtml = String(v); rebuildCards(els['review-queue-container']); },
});

const toasts = [], switchCalls = [], fetchUrls = [], historyPushes = [];
const sandbox = {
  console, URLSearchParams, setTimeout: () => {},
  document: { getElementById: (id) => els[id] || null, querySelectorAll: () => [], addEventListener: () => {} },
  window: {
    location: { hash: '' },
    history: { pushState: (_s, _t, h) => { historyPushes.push(h); sandbox.window.location.hash = h; } },
    switchTab: (tab, upd, opts) => switchCalls.push({ tab, upd, opts }),
    showToast: (title, body, type, actionText, onAction) => toasts.push({ title, body, type, actionText, onAction }),
    confirm: () => true,
  },
  fetch: async (url) => {
    fetchUrls.push(String(url));
    if (String(url).startsWith('/api/review/99')) {
      return { ok: true, json: async () => ({ id: 99, track_id: 99, camera_id: 'cam_1', similarity: 0.55, status: 'pending' }) };
    }
    const items = Array.from({ length: 50 }, (_, i) => ({
      id: i + 1, track_id: i + 1, camera_id: 'cam_1', similarity: 0.52, status: 'pending',
    }));
    return { ok: true, json: async () => ({ status: 'success', count: 50, total: 65, total_pending: 65, offset: 0, limit: 50, items }) };
  },
};
sandbox.window.document = sandbox.document;
sandbox.window.fetch = sandbox.fetch;
sandbox.window.App = { navigate: (tab, ref, opts) => sandbox.window.AppNavigation.navigate(tab, ref, opts) };
vm.createContext(sandbox);

for (const rel of ['dashboard/static/js/app_navigation.js', 'dashboard/static/js/review_queue_controls.js', 'dashboard/static/review_and_rsac.js']) {
  vm.runInContext(fs.readFileSync(path.join(process.env.IT_ROOT, rel), 'utf8'), sandbox);
}

(async () => {
  await sandbox.window.ReviewAndRSAC.loadQueue('pending');
  sandbox.window.ReviewAndRSAC.checkAlertEvents([
    { id: 'ev1', event_type: 'review_item_queued', review_id: 42, track_id: 42, camera_id: 'cam_1', similarity: 0.58 },
  ]);
  await toasts[0].onAction();
  const card42 = els['review-queue-container'].children.find((c) => c.getAttribute('data-item-id') === '42');
  const parsed = sandbox.window.AppNavigation.paramsToSourceRef(sandbox.window.AppNavigation.parseHash(historyPushes[0]).params);
  await sandbox.window.ReviewAndRSAC.openReviewItem(99);
  const card99 = els['review-queue-container'].children.find((c) => c.getAttribute('data-item-id') === '99');
  console.log(JSON.stringify({
    badgeAfterLoad: els['header-review-badge'].textContent,
    counterAfterLoad: els['review-inbox-counter'].textContent,
    pageInfo: els['review-page-info'].textContent,
    hash: historyPushes[0], parsedReviewId: parsed.reviewId,
    skipReviewAutoLoad: switchCalls[0]?.opts?.skipReviewAutoLoad,
    card42Highlighted: Boolean(card42 && card42.classList.contains('review-card-highlight') && card42.scrolled),
    card99Highlighted: Boolean(card99 && card99.classList.contains('review-card-highlight')),
    fetchedFallback99: fetchUrls.some((u) => u.includes('/api/review/99')),
  }));
})();
"""


class _RollbackSpyConn:
    """Proxy wrapping sqlite3.Connection to spy on rollback() after simulated error."""

    def __init__(self, real_conn: sqlite3.Connection) -> None:
        self._real = real_conn
        self.rolled_back = False

    def cursor(self):
        class _FailCursor:
            def execute(self, *_args, **_kwargs):
                raise sqlite3.OperationalError("simulated write failure")

            def close(self):
                pass

        return _FailCursor()

    def rollback(self):
        self.rolled_back = True
        self._real.rollback()

    def __getattr__(self, name: str):
        return getattr(self._real, name)


class TestReviewQueueRepository(unittest.TestCase):
    """Verify LearningMixin pagination, triage filters, sorting, and bulk-dismiss."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "review_triage.db"))
        self.addCleanup(self.db.close)
        for i in range(65):
            is_matched = (i % 3) == 0
            self.db.add_review_item(
                camera_id="cam_front", track_id=100 + i, crop_path=f"crop_{i}.jpg",
                suggested_entity_id=(1 if is_matched else None),
                suggested_name=("Alice" if is_matched else ""),
                similarity=round(0.45 + (i % 25) * 0.01, 4), status="pending",
                reason=("reported_wrong" if (i % 5) == 0 else "borderline"),
            )
        for j in range(5):
            self.db.add_review_item(
                camera_id="cam_front", track_id=900 + j, crop_path=f"old_{j}.jpg",
                similarity=0.5, status="dismissed",
            )

    def test_count_pagination_filters_and_sort(self) -> None:
        self.assertEqual(self.db.count_review_items(status="pending"), 65)
        page1 = self.db.list_review_items(status="pending", limit=50, offset=0)
        page2 = self.db.list_review_items(status="pending", limit=50, offset=50)
        self.assertEqual((len(page1), len(page2)), (50, 15))
        self.assertFalse({r["id"] for r in page1} & {r["id"] for r in page2})
        matched = self.db.list_review_items(status="pending", limit=100, matched="matched")
        unmatched = self.db.list_review_items(status="pending", limit=100, matched="unmatched")
        self.assertEqual(len(matched) + len(unmatched), 65)
        reported = self.db.list_review_items(status="pending", limit=100, reason="reported_wrong")
        self.assertEqual(len(reported), 13)
        oldest = self.db.list_review_items(status="pending", limit=5, sort="oldest")
        self.assertEqual([r["id"] for r in oldest], sorted(r["id"] for r in oldest))
        sim_desc = [float(r["similarity"]) for r in self.db.list_review_items(status="pending", limit=10, sort="sim_desc")]
        self.assertEqual(sim_desc, sorted(sim_desc, reverse=True))
        sim_asc = [float(r["similarity"]) for r in self.db.list_review_items(status="pending", limit=10, sort="sim_asc")]
        self.assertEqual(sim_asc, sorted(sim_asc))

    def test_bulk_dismiss_and_rollback(self) -> None:
        unmatched_before = self.db.count_review_items(status="pending", matched="unmatched")
        dismissed = self.db.bulk_dismiss_review_items(status="pending", matched="unmatched", reviewed_by="qa")
        self.assertEqual(dismissed, unmatched_before)
        self.assertEqual(self.db.count_review_items(status="pending", matched="unmatched"), 0)
        remaining = self.db.list_review_items(status="pending", limit=3)
        self.assertEqual(self.db.bulk_dismiss_review_items(item_ids=[remaining[0]["id"], remaining[1]["id"]]), 2)
        self.assertEqual(self.db.bulk_dismiss_review_items(item_ids=[]), 0)
        spy = _RollbackSpyConn(self.db._conn)
        orig_conn = self.db._conn
        self.db._conn = spy
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.db.bulk_dismiss_review_items(status="pending")
            self.assertTrue(spy.rolled_back)
        finally:
            self.db._conn = orig_conn


class TestReviewQueueApi(unittest.TestCase):
    """Verify GET /api/review/queue pagination/totals and POST /api/review/bulk-dismiss."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "review_api.db"))
        self.addCleanup(self.db.close)
        for i in range(65):
            self.db.add_review_item(
                camera_id="cam_lobby", track_id=200 + i, crop_path=f"api_{i}.jpg",
                suggested_entity_id=(2 if i % 4 == 0 else None),
                suggested_name=("Bob" if i % 4 == 0 else ""),
                similarity=round(0.46 + (i % 20) * 0.01, 4), status="pending",
                reason=("reported_wrong" if i < 10 else "borderline"),
            )
        self._orig_deps_db = deps._db
        self._orig_state_db = getattr(app.state, "db", None)
        deps._db = self.db
        app.state.db = self.db
        self.addCleanup(self._restore_db)
        self.client = TestClient(app)

    def _restore_db(self) -> None:
        deps._db = self._orig_deps_db
        app.state.db = self._orig_state_db

    def test_paginated_queue_and_bulk_dismiss_endpoints(self) -> None:
        with patch.object(deps, "get_db", return_value=self.db):
            d1 = self.client.get("/api/review/queue?status=pending&limit=50&offset=0").json()
            self.assertEqual((d1["count"], d1["total"], d1["total_pending"], d1["offset"]), (50, 65, 65, 0))
            d2 = self.client.get("/api/review/queue?status=pending&limit=50&offset=50").json()
            self.assertEqual((d2["count"], d2["total"], d2["total_pending"]), (15, 65, 65))
            df = self.client.get("/api/review/queue?status=pending&reason=reported_wrong&sort=sim_desc").json()
            self.assertEqual((df["total"], df["total_pending"]), (10, 65))
            rb = self.client.post("/api/review/bulk-dismiss", json={"status": "pending", "matched": "unmatched"})
            self.assertEqual(rb.status_code, 200)
            res = rb.json()
            self.assertGreater(res["dismissed"], 0)
            self.assertEqual(res["total_pending"], 65 - res["dismissed"])


class TestReviewQueueFrontendAndToastCss(unittest.TestCase):
    """Verify Node VM review triage/deep-link flows and top-right toast positioning."""

    def test_toast_css_top_right_and_highlight_class(self) -> None:
        css = (ROOT / "dashboard" / "static" / "css" / "toast.css").read_text(encoding="utf-8")
        for token in ("top: 72px;", "right: 24px;", "bottom: auto;", "z-index: 1050;", ".review-card-highlight"):
            self.assertIn(token, css)
        self.assertNotIn("!important", css)

    def test_node_vm_review_totals_deeplink_and_fallback_highlight(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        env = {**os.environ, "IT_ROOT": str(ROOT)}
        proc = subprocess.run(["node", "-e", _NODE_VM_REVIEW_SCRIPT], capture_output=True, text=True, env=env, timeout=20, check=False)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(str(out["badgeAfterLoad"]), "65")
        self.assertEqual(out["counterAfterLoad"], "65 Candidates")
        self.assertEqual(out["pageInfo"], "Showing 1–50 of 65")
        self.assertEqual(out["hash"], "#review?review_id=42")
        self.assertEqual(out["parsedReviewId"], 42)
        self.assertTrue(out["skipReviewAutoLoad"])
        self.assertTrue(out["card42Highlighted"])
        self.assertTrue(out["card99Highlighted"])
        self.assertTrue(out["fetchedFallback99"])


if __name__ == "__main__":
    unittest.main()
