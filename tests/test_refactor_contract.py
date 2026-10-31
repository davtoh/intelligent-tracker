# Generated Contract Smoke Test - Enforces Zero-Regression Refactoring Parity
import pathlib
import re
import unittest

class TestCodebaseContractInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(__file__).resolve().parent.parent / "dashboard"
        ignored = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "_build", "build", "dist", ".refactor", "scratch"}
        cls.html_text = "".join(
            p.read_text(encoding="utf-8", errors="replace") + "\n"
            for p in cls.root.rglob("*.html")
            if not any(part in ignored for part in p.parts)
        )
        cls.js_text = "".join(
            p.read_text(encoding="utf-8", errors="replace") + "\n"
            for p in cls.root.rglob("*.js")
            if not any(part in ignored for part in p.parts)
        )

    def test_dom_interactive_selects_exist(self):
        """Verify all critical <select> dropdown IDs exist in HTML."""
        for sel in ['active-camera-select', 'cam-preset-select', 'cam-stream-select', 'enroll-camera-select', 'enroll-category-select', 'modal-tripwire-bidir-select', 'modal-zone-category-select', 'quick-enroll-category-select', 'reassign-entity-select', 'scrubber-tab-policy', 'studio-camera-select', 'tag-category-select', 'timeline-entity-select', 'timeline-limit-select', 'timeline-zone-select']:
            self.assertIn(f'id="{sel}"', self.html_text, f"Missing select dropdown #{sel} in HTML!")

    def test_dom_element_ids_preserved(self):
        """Verify captured baseline HTML element IDs are preserved."""
        for el_id in ['active-camera-select', 'active-cameras-table-body', 'alerts-table', 'alerts-table-body', 'backup-file-input', 'backup-import-status', 'bev-metric-scale', 'bev-minimap-canvas', 'btn-add-transition-link', 'btn-backup-manager', 'btn-capture-freeze', 'btn-close-drawer', 'btn-download-heatmap', 'btn-enroll-modal', 'btn-filter-sightings', 'btn-fullscreen-toggle', 'btn-import-backup-file', 'btn-journey-export', 'btn-journey-search', 'btn-manage-cameras', 'btn-mobile-menu', 'btn-modal-homography-save', 'btn-modal-quick-enroll-save', 'btn-modal-transition-save', 'btn-modal-tripwire-save', 'btn-modal-zone-save', 'btn-mode-draw-tripwire', 'btn-mode-draw-zone', 'btn-mode-homography', 'btn-open-enrollment', 'btn-quick-tag', 'btn-refresh-heatmap', 'btn-refresh-review-queue', 'btn-save-camera', 'btn-scan-devices', 'btn-snapshot-save', 'btn-stream-pause-play', 'btn-stream-reconnect', 'btn-studio-clear', 'btn-submit-enrollment', 'btn-submit-reassign', 'btn-test-connection', 'btn-upload-enroll-crop', 'btn-upload-video', 'btn-video-add-camera', 'btn-video-analyze', 'cam-channel-input', 'cam-id-input', 'cam-ip-input', 'cam-name-input', 'cam-pass-input', 'cam-port-input', 'cam-preset-select', 'cam-source-input', 'cam-stream-select', 'cam-user-input', 'camera-config-form', 'connection-status-pill', 'connection-status-text', 'discovered-devices-list', 'drawer-alert-badge', 'drawer-btn-backup', 'drawer-btn-cameras', 'drawer-btn-enroll', 'drawer-connection-status-pill', 'drawer-fps-val', 'drawer-review-badge', 'enroll-bbox-canvas', 'enroll-camera-select', 'enroll-canvas-placeholder', 'enroll-category-select', 'enroll-crop-meta', 'enroll-crop-preview-box', 'enroll-crop-preview-img', 'enroll-file-input', 'enroll-locked-anchor-cb', 'enroll-name-input', 'enroll-notes-input', 'enroll-role-input', 'entity-gallery-grid', 'fullscreen-btn', 'gallery-category-filters', 'gallery-search-input', 'header-alert-badge', 'header-fps-val', 'header-review-badge', 'interactive-canvas', 'journey-export-status', 'journey-results-container', 'journey-search-query', 'kpi-active-tracks', 'kpi-total-crossed', 'kpi-tracks-sub', 'live-alerts-feed', 'live-stream-img', 'live-stream-status-badge', 'live-stream-status-text', 'live-video-card', 'mobile-drawer-backdrop', 'mobile-nav-drawer', 'modal-backup-close', 'modal-backup-manager', 'modal-cam-cancel', 'modal-cam-close', 'modal-camera-manager', 'modal-descriptor-versions', 'modal-enroll-cancel', 'modal-enroll-close', 'modal-homography-cancel', 'modal-homography-close', 'modal-homography-height-input', 'modal-homography-width-input', 'modal-quick-enroll-cancel', 'modal-quick-enroll-close', 'modal-quick-enroll-entity', 'modal-reassign-cancel', 'modal-reassign-close', 'modal-review-reassign', 'modal-snapshot-close', 'modal-snapshot-view', 'modal-studio-homography', 'modal-studio-transition', 'modal-studio-tripwire', 'modal-studio-zone', 'modal-tag-cancel', 'modal-tag-close', 'modal-tag-entity', 'modal-tag-submit', 'modal-trans-bidir-cb', 'modal-trans-boost-input', 'modal-trans-src-cam-input', 'modal-trans-src-zone-input', 'modal-trans-tgt-cam-input', 'modal-trans-tgt-zone-input', 'modal-trans-tmax-input', 'modal-trans-tmin-input', 'modal-transition-cancel', 'modal-transition-close', 'modal-tripwire-bidir-select', 'modal-tripwire-cancel', 'modal-tripwire-close', 'modal-tripwire-name-input', 'modal-universal-enrollment', 'modal-versions-close', 'modal-zone-cancel', 'modal-zone-capacity-input', 'modal-zone-category-select', 'modal-zone-close', 'modal-zone-dwell-input', 'modal-zone-name-input', 'multi-grid-container', 'nav-tabs-wrapper', 'overlay-toggle-bboxes', 'overlay-toggle-bev_minimap', 'overlay-toggle-dwell_timers', 'overlay-toggle-heatmap', 'overlay-toggle-hud_bar', 'overlay-toggle-toast_prompts', 'overlay-toggle-track_ids', 'overlay-toggle-tripwires', 'overlay-toggle-velocity', 'overlay-toggle-zones', 'quick-enroll-category-select', 'quick-enroll-form', 'quick-enroll-item-id', 'quick-enroll-name-input', 'reassign-entity-select', 'reassign-item-id', 'reassign-notes-input', 'review-inbox-counter', 'review-queue-container', 'review-reassign-form', 'scrubber-btn-next', 'scrubber-btn-play', 'scrubber-btn-prev', 'scrubber-loaded-title', 'scrubber-tab-policy', 'scrubber-time-display', 'scrubber-timeline-slider', 'scrubber-video-player', 'sightings-timeline-list', 'snapshot-modal-img', 'snapshot-modal-meta', 'snapshot-modal-title', 'speed-btn-1x', 'speed-btn-2x', 'speed-btn-4x', 'speed-btn-8x', 'static-heatmap-img', 'stream-pause-icon', 'stream-pause-text', 'stream-res-badge', 'stream-telemetry-hud', 'studio-camera-select', 'studio-canvas-wrapper', 'studio-drawing-canvas', 'studio-homography-form', 'studio-live-img', 'studio-status-banner', 'studio-transition-form', 'studio-tripwire-form', 'studio-tripwires-list', 'studio-zone-form', 'studio-zones-list', 'tab-alerts', 'tab-analytics', 'tab-btn-alerts', 'tab-btn-analytics', 'tab-btn-gallery', 'tab-btn-journey', 'tab-btn-live', 'tab-btn-review', 'tab-btn-studio', 'tab-btn-timeline', 'tab-btn-videos', 'tab-gallery', 'tab-journey', 'tab-live', 'tab-review', 'tab-studio', 'tab-timeline', 'tab-videos', 'tag-bbox-val', 'tag-category-select', 'tag-entity-form', 'tag-modal-title', 'tag-name-input', 'tag-notes-input', 'tag-track-id', 'test-preview-img', 'test-preview-meta', 'timeline-entity-select', 'timeline-limit-select', 'timeline-zone-select', 'toast-container', 'toggle-heatmap-btn', 'tooltip-body', 'tooltip-tag-btn', 'tooltip-title', 'topology-links-list', 'total-alerts-count', 'track-tooltip', 'trafficChart', 'tripwires-container', 'universal-enrollment-form', 'versions-modal-title', 'versions-timeline-container', 'video-batch-report-container', 'video-file-upload-input', 'video-recordings-list', 'video-stream-title', 'video-upload-status', 'video-wrapper', 'view-all-alerts-link', 'zone-count-badge', 'zones-container']:
            self.assertIn(f'id="{el_id}"', self.html_text, f"Critical DOM element id='{el_id}' was removed from HTML!")

    def test_zero_css_important_creep(self):
        """Verify scoped CSS does not exceed baseline !important threshold."""
        ignored = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "_build", "build", "dist", ".refactor", "scratch"}
        css_text = "".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in self.root.rglob("*.css")
            if not any(part in ignored for part in p.parts)
        )
        count = len(re.findall(r'!important\b', css_text, re.IGNORECASE))
        self.assertLessEqual(count, 0, f"!important count increased to {count}!")

if __name__ == "__main__":
    unittest.main()
