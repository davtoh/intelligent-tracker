/**
 * Intelligent Tracker Web Dashboard - Main Coordinator & Hash Router.
 * Coordinates LivePlayer, InteractiveCanvas, TelemetryGateway, GalleryTimeline, and AnalyticsView.
 */

document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  // Application State
  const state = {
    activeTab: 'tab-live',
    tracks: [],
    hoveredTrack: null,
  };

  let activeCameraId = 'cam_01';
  const videoImg = document.getElementById('live-stream-img');
  const canvas = document.getElementById('interactive-canvas');
  const ctx = canvas?.getContext('2d');
  const connStatusPill = document.getElementById('connection-status-pill');
  const connStatusText = document.getElementById('connection-status-text');
  const alertBadge = document.getElementById('header-alert-badge');

  // Standby Poster SVG Constant (Milestone 10 Parity)
  const STANDBY_POSTER_SVG = window.LivePlayer?.STANDBY_POSTER_SVG || 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="100%" height="100%" fill="%230f172a"/></svg>';

  // Modern Toast Notification Dispatcher (Milestone 10)
  function showToast(titleOrMsg, bodyOrType = 'info', type = 'info', actionText = null, onAction = null) {
    let title = titleOrMsg, body = bodyOrType, toastType = type;
    if (['info', 'success', 'warning', 'error', 'alert', 'review'].includes(bodyOrType) && type === 'info') {
      toastType = bodyOrType;
      body = titleOrMsg;
      title = toastType.toUpperCase();
    }

    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-message ${toastType}`;
    const actionHtml = actionText ? `<div class="toast-action">${escapeHtml(actionText)}</div>` : '';
    toast.innerHTML = `
      <div class="toast-header">
        <span class="toast-title">${escapeHtml(title)}</span>
        <button class="toast-close" aria-label="Dismiss">&times;</button>
      </div>
      <div class="toast-body">${escapeHtml(body)}</div>
      ${actionHtml}
    `;

    toast.querySelector('.toast-close')?.addEventListener('click', () => toast.remove());
    if (actionText && onAction) {
      toast.querySelector('.toast-action')?.addEventListener('click', () => { onAction(); toast.remove(); });
    }

    container.appendChild(toast);
    setTimeout(() => { if (toast.parentElement) toast.remove(); }, 6000);
  }

  window.showToast = showToast;

  function detachLiveStream() {
    window.LivePlayer?.detachLiveStream(videoImg);
  }

  function attachLiveStream(forceReconnect = false) {
    window.LivePlayer?.attachLiveStream(videoImg, activeCameraId, forceReconnect);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  // Tab Navigation & Hash Routing
  const navTabs = document.querySelectorAll('.nav-tab');
  const drawerTabs = document.querySelectorAll('.drawer-tab');
  const tabPanes = document.querySelectorAll('.tab-pane');

  function switchTab(targetTabId, updateHash = true) {
    const previousTab = state.activeTab;
    state.activeTab = targetTabId;

    navTabs.forEach(tab => {
      const isTarget = tab.getAttribute('data-tab') === targetTabId;
      tab.classList.toggle('active', isTarget);
      if (isTarget && tab.offsetParent !== null) {
        const wrapper = document.getElementById('nav-tabs-wrapper');
        if (wrapper && wrapper.scrollWidth > wrapper.clientWidth) {
          const wrapRect = wrapper.getBoundingClientRect();
          const tabRect = tab.getBoundingClientRect();
          const targetLeft = (tabRect.left - wrapRect.left) + wrapper.scrollLeft - (wrapper.clientWidth - tabRect.width) / 2;
          wrapper.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
          window.navTabsManager?.updateScrollButtons?.();
          setTimeout(() => window.navTabsManager?.updateScrollButtons?.(), 350);
        }
      }
    });

    if (window.scrollX !== 0) {
      window.scrollTo(0, window.scrollY);
    }

    drawerTabs.forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-tab') === targetTabId);
    });

    tabPanes.forEach(pane => {
      pane.classList.toggle('active', pane.id === targetTabId);
    });

    handleTabLifecycle(previousTab, targetTabId);

    if (updateHash) {
      const cleanHash = '#' + targetTabId.replace('tab-', '');
      if (window.location.hash !== cleanHash) history.pushState(null, '', cleanHash);
    }
  }

  window.switchTab = switchTab;

  function handleTabLifecycle(previousTab, targetTabId) {
    if (previousTab === 'tab-videos' && targetTabId !== 'tab-videos') {
      window.VideoScrubber?.onTabLeave?.();
    } else if (previousTab === 'tab-live' && targetTabId !== 'tab-live') {
      detachLiveStream();
    }

    if (targetTabId === 'tab-live') {
      if (!window.LivePlayer?.isPaused()) attachLiveStream(true);
    } else if (targetTabId === 'tab-videos') {
      window.VideoScrubber?.loadVideosList();
      window.VideoScrubber?.onTabEnter?.();
    } else if (targetTabId === 'tab-gallery') {
      window.GalleryTimeline?.loadGallery();
    } else if (targetTabId === 'tab-timeline') {
      window.GalleryTimeline?.loadTimelineFilters();
      window.GalleryTimeline?.loadSightings();
    } else if (targetTabId === 'tab-analytics') {
      window.AnalyticsView?.initChart();
    } else if (targetTabId === 'tab-alerts') {
      window.AnalyticsView?.loadAlerts();
    } else if (targetTabId === 'tab-studio') {
      window.Studio?.renderBEV?.();
    } else if (targetTabId === 'tab-journey') {
      document.getElementById('journey-search-query')?.focus();
    } else if (targetTabId === 'tab-review') {
      window.ReviewAndRSAC?.loadQueue('pending');
    }
  }

  function handleHashRoute() {
    const raw = (window.location.hash || '').replace('#', '').trim().toLowerCase();
    if (!raw) return;
    const modalMap = {
      cameras: 'modal-camera-manager',
      enroll: 'modal-universal-enrollment',
      backup: 'modal-backup-manager',
      versions: 'modal-descriptor-versions',
    };
    if (modalMap[raw]) {
      const m = document.getElementById(modalMap[raw]);
      if (m) m.style.display = 'flex';
      return;
    }
    const tabId = 'tab-' + raw;
    if (document.getElementById(tabId)) switchTab(tabId, false);
  }

  function switchCamera(camId) {
    if (!camId || camId === activeCameraId) return;
    activeCameraId = camId;
    window.TelemetryGateway?.initWebSocket(camId, onTelemetryReceived, onWsStatusChange);
  }

  function onTelemetryReceived(data) {
    state.tracks = data.active_tracks || [];
    let totalCrossed = 0;
    if (data.tripwires) {
      data.tripwires.forEach(tw => { totalCrossed += (tw.in_count + tw.out_count); });
      window.AnalyticsView?.updateChart(totalCrossed);
    }
    window.TelemetryGateway?.updateKpiDisplays(data, state.tracks.length, totalCrossed);

    if (data.zones) window.TelemetryGateway?.renderZones(data.zones);
    if (data.tripwires) window.TelemetryGateway?.renderTripwires(data.tripwires);
    if (data.recent_alerts) {
      window.TelemetryGateway?.renderMiniAlerts(data.recent_alerts);
      if (alertBadge) alertBadge.textContent = data.recent_alerts.length;
      window.ReviewAndRSAC?.checkAlertEvents(data.recent_alerts);
    }

    syncCanvas();
  }

  function onWsStatusChange(isOnline) {
    if (connStatusPill) connStatusPill.className = `connection-status-pill ${isOnline ? 'online' : 'offline'}`;
    if (connStatusText) {
      const fullText = isOnline ? `Connected (${activeCameraId})` : 'Reconnecting...';
      if (window.TextTruncationManager && isOnline && activeCameraId.length > 14) {
        window.TextTruncationManager.apply(connStatusText, {
          fullText: fullText,
          mode: 'middle',
          maxLength: 24,
          preserveExt: false,
          label: 'Active Stream'
        });
      } else {
        connStatusText.textContent = fullText;
        connStatusText.title = fullText;
      }
    }
  }

  function syncCanvas() {
    window.InteractiveCanvas?.syncSize(videoImg, canvas);
    window.InteractiveCanvas?.drawOverlay(ctx, canvas, videoImg, state.tracks, state.hoveredTrack);
  }

  function bindCanvasEvents() {
    if (!canvas) return;
    canvas.addEventListener('mousemove', (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      state.hoveredTrack = window.InteractiveCanvas?.findHoveredTrack(mx, my, canvas, videoImg, state.tracks);
      syncCanvas();
      if (state.hoveredTrack) {
        window.InteractiveCanvas?.updateTooltip(state.hoveredTrack, canvas, videoImg);
      } else {
        const tooltip = document.getElementById('track-tooltip');
        if (tooltip) tooltip.style.display = 'none';
      }
    });

    canvas.addEventListener('mouseleave', () => {
      state.hoveredTrack = null;
      const tooltip = document.getElementById('track-tooltip');
      if (tooltip) tooltip.style.display = 'none';
      syncCanvas();
    });

    canvas.addEventListener('click', () => {
      if (state.hoveredTrack) window.InteractiveCanvas?.openTagModal(state.hoveredTrack);
    });

    document.getElementById('tooltip-tag-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.hoveredTrack) window.InteractiveCanvas?.openTagModal(state.hoveredTrack);
    });

    document.getElementById('btn-quick-tag')?.addEventListener('click', () => {
      window.InteractiveCanvas?.openTagModal(state.tracks[0] || null);
    });
  }

  function bindDrawerAndBackup() {
    const drawer = document.getElementById('mobile-nav-drawer');
    const drawerBackdrop = document.getElementById('mobile-drawer-backdrop');
    const openDrawer = () => {
      if (drawer) drawer.classList.add('open');
      if (drawerBackdrop) drawerBackdrop.style.display = 'block';
    };
    const closeDrawer = () => {
      if (drawer) drawer.classList.remove('open');
      if (drawerBackdrop) drawerBackdrop.style.display = 'none';
    };

    document.getElementById('btn-mobile-menu')?.addEventListener('click', openDrawer);
    document.getElementById('btn-close-drawer')?.addEventListener('click', closeDrawer);
    drawerBackdrop?.addEventListener('click', closeDrawer);

    drawerTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        switchTab(tab.getAttribute('data-tab'));
        closeDrawer();
      });
    });

    bindDrawerActionButtons(closeDrawer);
    window.BackupManager?.bind(showToast);
  }

  function bindDrawerActionButtons(closeDrawer) {
    document.getElementById('drawer-btn-enroll')?.addEventListener('click', () => {
      closeDrawer();
      const m = document.getElementById('modal-universal-enrollment');
      if (m) m.style.display = 'flex';
    });
    document.getElementById('drawer-btn-cameras')?.addEventListener('click', () => {
      closeDrawer();
      const m = document.getElementById('modal-camera-manager');
      if (m) m.style.display = 'flex';
    });
    document.getElementById('drawer-btn-backup')?.addEventListener('click', () => {
      closeDrawer();
      const m = document.getElementById('modal-backup-manager');
      if (m) m.style.display = 'flex';
    });
  }

  // Setup Lifecycle Listeners
  navTabs.forEach(tab => tab.addEventListener('click', () => switchTab(tab.getAttribute('data-tab'))));
  window.addEventListener('hashchange', handleHashRoute);
  window.addEventListener('popstate', handleHashRoute);
  document.getElementById('view-all-alerts-link')?.addEventListener('click', () => switchTab('tab-alerts'));

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (state.activeTab === 'tab-videos') window.VideoScrubber?.onTabLeave?.();
      else if (state.activeTab === 'tab-live') detachLiveStream();
    } else {
      if (state.activeTab === 'tab-videos') window.VideoScrubber?.onTabEnter?.();
      else if (state.activeTab === 'tab-live' && !window.LivePlayer?.isPaused()) attachLiveStream(true);
    }
  });

  window.addEventListener('resize', syncCanvas);
  videoImg?.addEventListener('load', syncCanvas);
  if (window.ResizeObserver && videoImg) {
    const ro = new ResizeObserver(syncCanvas);
    ro.observe(videoImg);
    const wrapper = document.getElementById('video-wrapper');
    if (wrapper) ro.observe(wrapper);
  }

  const cleanupLiveResources = () => {
    detachLiveStream();
    window.TelemetryGateway?.closeWebSocket();
  };
  window.addEventListener('beforeunload', cleanupLiveResources);
  window.addEventListener('pagehide', cleanupLiveResources);

  // Initialize Modules
  window.LivePlayer?.bindHudButtons(videoImg, () => activeCameraId);
  window.InteractiveCanvas?.initTagModal(() => activeCameraId);
  bindCanvasEvents();
  bindDrawerAndBackup();
  window.GalleryTimeline?.bindGalleryEvents();
  window.GalleryTimeline?.bindTimelineEvents();
  window.GalleryTimeline?.initSnapshotModal();
  window.AnalyticsView?.initHeatmap();

  window.TelemetryGateway?.initWebSocket(activeCameraId, onTelemetryReceived, onWsStatusChange);
  if (window.location.hash) handleHashRoute();

  // Global interfaces
  window.App = {
    switchCamera: switchCamera,
    getActiveCameraId: () => activeCameraId,
  };
  window.App.switchCamera = switchCamera;
  window.showSnapshotModal = (imgUrl, title) => window.GalleryTimeline?.showSnapshotModal(imgUrl, title);
  window.loadGallery = () => window.GalleryTimeline?.loadGallery();
});
