"""Node VM unit tests for dashboard/static/js/grid_pagination.js."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

GRID_PAGINATION_JS = (
    Path(__file__).resolve().parents[1]
    / "dashboard"
    / "static"
    / "js"
    / "grid_pagination.js"
)


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _vm_bootstrap(initial_storage: dict | None = None) -> str:
    store = json.dumps(initial_storage or {})
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const code = fs.readFileSync({json.dumps(str(GRID_PAGINATION_JS))}, 'utf8');\n"
        f"const store = {store};\n"
        "const localStorage = {\n"
        "  getItem: (k) => (k in store ? store[k] : null),\n"
        "  setItem: (k, v) => { store[k] = String(v); },\n"
        "};\n"
        "const win = { localStorage };\n"
        "vm.runInNewContext(code, { window: win, Math, Number, String, Array, Object, console });\n"
    )


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
class TestGridPagination(unittest.TestCase):
    """Verify page sizes, clamping, slicing, and localStorage persistence."""

    def test_layout_page_sizes_and_total_pages(self) -> None:
        script = _vm_bootstrap() + (
            "const GP = win.GridPagination;\n"
            "process.stdout.write(JSON.stringify({\n"
            "  s1: GP.getPageSize('1x1'), s2: GP.getPageSize('2x2'),\n"
            "  s3: GP.getPageSize('3x3'), s4: GP.getPageSize('4x4'),\n"
            "  t0: GP.getTotalPages(0, '2x2'), t6: GP.getTotalPages(6, '2x2'),\n"
            "  t17: GP.getTotalPages(17, '4x4'),\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertEqual(
            out,
            {"s1": 1, "s2": 4, "s3": 9, "s4": 16, "t0": 1, "t6": 2, "t17": 2},
        )

    def test_clamp_and_slice_on_camera_list_shrink(self) -> None:
        script = _vm_bootstrap({"it_grid_layout": "2x2", "it_grid_page": "3"}) + (
            "const GP = win.GridPagination;\n"
            "const cams = Array.from({ length: 6 }, (_, i) => ({ id: 'cam_' + i }));\n"
            "const res = GP.paginate(cams, '2x2');\n"
            "process.stdout.write(JSON.stringify({\n"
            "  page: res.page, totalPages: res.totalPages,\n"
            "  ids: res.items.map(c => c.id), storedPage: store.it_grid_page,\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["page"], 2)
        self.assertEqual(out["totalPages"], 2)
        self.assertEqual(out["ids"], ["cam_4", "cam_5"])
        self.assertEqual(out["storedPage"], "2")

    def test_prev_next_and_layout_persistence(self) -> None:
        script = _vm_bootstrap() + (
            "const GP = win.GridPagination;\n"
            "GP.setLayout('3x3', 20);\n"
            "const p1 = GP.getState().page;\n"
            "const p2 = GP.nextPage(20, '3x3').page;\n"
            "const p3 = GP.nextPage(20, '3x3').page;\n"
            "const p4 = GP.nextPage(20, '3x3').page;\n"
            "const pBack = GP.prevPage(20, '3x3').page;\n"
            "process.stdout.write(JSON.stringify({\n"
            "  p1, p2, p3, p4, pBack, layout: store.it_grid_layout, page: store.it_grid_page,\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["p1"], 1)
        self.assertEqual(out["p2"], 2)
        self.assertEqual(out["p3"], 3)
        self.assertEqual(out["p4"], 3)
        self.assertEqual(out["pBack"], 2)
        self.assertEqual(out["layout"], "3x3")
        self.assertEqual(out["page"], "2")
