#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit & Regression Tests for Reusable Responsive Navigation.
Verifies breakpoint coexistence (Hamburger vs Desktop Nav), scroll arrows,
touch target sizing, zero document horizontal overflow, and zero !important CSS compliance.
"""

import os
import re
import tempfile
import unittest
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.database import TrackerDB
from dashboard.camera_pool import CameraPool


class TestResponsiveNavigation(unittest.TestCase):
    """Test suite for responsive navigation tabs, scroll controls, and breakpoint ergonomics."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp_dir, "test_resp_nav.db")
        cls.cam_cfg = os.path.join(cls.tmp_dir, "cameras.json")
        cls.db = TrackerDB(cls.db_path)

        cls.pool = CameraPool(
            config_file=cls.cam_cfg,
            db_path=cls.db_path,
            autostart=False,
        )
        bind_app_state(
            app,
            camera_pool=cls.pool,
            stream_manager=cls.pool.primary_stream,
            db=cls.db,
        )
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        clear_app_state(app)
        cls.pool.stop_all()
        cls.db.close()
        import shutil
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_nav_tabs_html_structure_and_controls(self):
        """Verify dashboard index.html contains all 9 tabs and responsive navigation controls."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 9 Core VMS Navigation Tabs
        required_tabs = [
            'data-tab="tab-live"',
            'data-tab="tab-videos"',
            'data-tab="tab-gallery"',
            'data-tab="tab-timeline"',
            'data-tab="tab-analytics"',
            'data-tab="tab-alerts"',
            'data-tab="tab-studio"',
            'data-tab="tab-journey"',
            'data-tab="tab-review"',
        ]
        for tab in required_tabs:
            self.assertIn(tab, html, f"Missing required navigation tab {tab}")

        # Header Navigation Container & Scroll Controls
        self.assertIn('class="nav-tabs-container"', html)
        self.assertIn('id="nav-tabs-prev"', html)
        self.assertIn('id="nav-tabs-next"', html)
        self.assertIn('id="nav-tabs-wrapper"', html)
        self.assertIn('id="btn-mobile-menu"', html)

        # Accessibility Attributes
        self.assertIn('aria-label="Scroll tabs left"', html)
        self.assertIn('aria-label="Scroll tabs right"', html)

    def test_header_action_buttons_responsive_spans(self):
        """Verify header action buttons wrap labels in .btn-text for clean responsive icon collapsing."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn('id="btn-open-enrollment"', html)
        self.assertIn('id="btn-manage-cameras"', html)
        self.assertIn('id="btn-backup-manager"', html)
        self.assertIn('class="btn-text"> Enroll</span>', html)
        self.assertIn('class="btn-text"> Cameras</span>', html)
        self.assertIn('class="btn-text"> Backup</span>', html)

    def test_static_assets_responsive_delivery(self):
        """Verify responsive stylesheet and navigation JS module are served with HTTP 200."""
        # Check responsive_patterns.css
        css_res = self.client.get("/static/css/responsive_patterns.css")
        self.assertEqual(css_res.status_code, 200)
        css_text = css_res.text
        self.assertIn(".nav-tabs-container", css_text)
        self.assertIn(".nav-scroll-btn", css_text)
        self.assertIn("overflow-x: clip", css_text)

        # Check master styles.css imports responsive_patterns.css
        master_css_res = self.client.get("/static/styles.css")
        self.assertEqual(master_css_res.status_code, 200)
        self.assertIn('css/responsive_patterns.css', master_css_res.text)

        # Check nav_tabs_manager.js
        js_res = self.client.get("/static/js/nav_tabs_manager.js")
        self.assertEqual(js_res.status_code, 200)
        js_text = js_res.text
        self.assertIn("class NavTabsManager", js_text)
        self.assertIn("scrollNext", js_text)
        self.assertIn("scrollPrev", js_text)

        # Check index.html loads nav_tabs_manager.js and responsive_patterns.css directly
        html_res = self.client.get("/")
        self.assertIn('src="/static/js/nav_tabs_manager.js"', html_res.text)
        self.assertIn('href="/static/css/responsive_patterns.css"', html_res.text)

    def test_css_zero_important_and_modularity_budget(self):
        """Verify responsive_patterns.css contains zero !important declarations and respects modularity budgets."""
        res = self.client.get("/static/css/responsive_patterns.css")
        self.assertEqual(res.status_code, 200)
        css = res.text

        # Verify zero !important declarations in CSS rules (comments excluded)
        code_without_comments = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
        self.assertNotIn("!important", code_without_comments, "Found forbidden !important declaration in responsive_patterns.css")

        # Modularity Budget: healthy target 150-300 lines, soft limit 350 lines
        lines = [line for line in css.splitlines() if line.strip()]
        total_line_count = len(css.splitlines())
        self.assertLessEqual(total_line_count, 350, f"responsive_patterns.css exceeds 350-line soft ceiling ({total_line_count} lines)")

    def test_css_mobile_first_nav_coexistence_contract(self):
        """Verify CSS ensures hamburger button and desktop tab strip never appear simultaneously."""
        res = self.client.get("/static/css/responsive_patterns.css")
        self.assertEqual(res.status_code, 200)
        css = res.text

        # Mobile-First Base: .nav-tabs-container { display: none; }
        self.assertIn(".nav-tabs-container {", css)
        self.assertIn("display: none;", css)

        # Desktop Media Query: @media (min-width: 1025px) { .nav-tabs-container { display: flex; ... } }
        self.assertIn("@media (min-width: 1025px)", css)

        # Touch Target Sizing (WCAG AA >= 24px, Mobile Hamburger >= 44px)
        self.assertIn(".hamburger-btn {", css)
        self.assertIn("min-width: 44px;", css)
        self.assertIn("min-height: 44px;", css)

    def test_tab_navigation_prevents_window_scroll_shift(self):
        """Verify app.js and nav_tabs_manager.js isolate tab scrolling to container, preventing page shifts."""
        app_js_res = self.client.get("/static/app.js")
        self.assertEqual(app_js_res.status_code, 200)
        app_js = app_js_res.text

        # app.js switchTab must not call unconstrained scrollIntoView on tab elements
        self.assertNotIn("tab.scrollIntoView?.({", app_js, "Found unconstrained tab.scrollIntoView which causes horizontal page shift")
        self.assertIn("window.scrollX !== 0", app_js, "app.js must lock window horizontal scroll to 0")

        # nav_tabs_manager.js must use container scrollTo/scrollBy, not scrollIntoView
        nav_js_res = self.client.get("/static/js/nav_tabs_manager.js")
        self.assertEqual(nav_js_res.status_code, 200)
        nav_js = nav_js_res.text
        self.assertNotIn(".scrollIntoView", nav_js, "nav_tabs_manager.js must never use scrollIntoView")
        self.assertIn("scrollBy", nav_js)
        self.assertIn("scrollTo", nav_js)
        self.assertIn("getBoundingClientRect", nav_js)

    def test_tablet_landscape_header_wrapping(self):
        """Verify responsive.css wraps header on tablet landscape (<=1080px) to prevent element crowding."""
        res = self.client.get("/static/css/responsive.css")
        self.assertEqual(res.status_code, 200)
        css = res.text

        self.assertIn("@media (max-width: 1080px)", css)
        self.assertIn("flex-direction: column;", css)

    def test_header_spacing_and_gap_discipline(self):
        """Verify .app-header and .nav-tabs-container enforce defensive gaps and prevent element collision."""
        # layout.css must provide explicit gap on .app-header
        layout_res = self.client.get("/static/css/layout.css")
        self.assertEqual(layout_res.status_code, 200)
        layout_css = layout_res.text
        self.assertIn("gap: 16px;", layout_css, ".app-header must define explicit 16px gap to prevent flush collision")

        # responsive_patterns.css must provide margin and gap on .nav-tabs-container
        resp_res = self.client.get("/static/css/responsive_patterns.css")
        self.assertEqual(resp_res.status_code, 200)
        resp_css = resp_res.text
        self.assertIn("gap: 8px;", resp_css, ".nav-tabs-container must specify internal gap between scroll buttons and wrapper")
        self.assertIn("margin: 0 8px;", resp_css, ".nav-tabs-container must maintain margin to isolate from header-left and header-right")

    def test_nav_tabs_manager_snap_offset_and_disable_contracts(self):
        """Verify nav_tabs_manager.js accurately disables prev/next buttons taking into account scroll-snap offsets."""
        nav_js_res = self.client.get("/static/js/nav_tabs_manager.js")
        self.assertEqual(nav_js_res.status_code, 200)
        nav_js = nav_js_res.text

        # Must include snap-aware isAtStart and isAtEnd methods
        self.assertIn("isAtStart()", nav_js)
        self.assertIn("isAtEnd()", nav_js)
        self.assertIn("firstRect.left >= wrapRect.left", nav_js, "isAtStart must inspect first tab bounding box against wrapper")
        self.assertIn("firstTab.offsetLeft", nav_js, "isAtStart must compensate for first tab offsetLeft snap position")
        self.assertIn("this.isAtStart()", nav_js, "prevBtn.disabled must be driven by isAtStart()")
        self.assertIn("this.isAtEnd()", nav_js, "nextBtn.disabled must be driven by isAtEnd()")

        # scrollPrev must explicitly handle snap return to 0
        self.assertIn("scrollTo({ left: 0", nav_js, "scrollPrev must scroll explicitly to 0 when near start")
        self.assertIn("Math.max(0, targetLeft)", nav_js, "switchTab must clamp targetLeft to 0")


if __name__ == "__main__":
    unittest.main()
