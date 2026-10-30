/**
 * Intelligent Tracker Web Dashboard - Master Application Controller & Router.
 * Coordinates navigation tabs, URL hash routing, mobile drawer, and lifecycle triggers.
 */

window.TrackerApp = window.TrackerApp || {};

document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  let activeTab = 'tab-live';

  // Navigation DOM Elements
  const tabButtons = document.querySelectorAll('.nav-tab');
  const tabPanes = document.querySelectorAll('.tab-pane');
  const navTabsWrapper = document.getElementById('nav-tabs-wrapper');

  // Mobile Drawer DOM Elements
  const btnMobileMenu = document.getElementById('btn-mobile-menu');
  const mobileNavDrawer = document.getElementById('mobile-nav-drawer');
  const drawerBackdrop = document.getElementById('drawer-backdrop');
  const drawerCloseBtn = document.getElementById('drawer-close-btn');
  const drawerTabs = document.querySelectorAll('.drawer-tab');

  function openDrawer() {
    if (!mobileNavDrawer || !drawerBackdrop) return;
    mobileNavDrawer.classList.add('open');
    drawerBackdrop.style.display = 'block';
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    if (!mobileNavDrawer || !drawerBackdrop) return;
    mobileNavDrawer.classList.remove('open');
    drawerBackdrop.style.display = 'none';
    document.body.style.overflow = '';
  }

  function switchTab(targetTabId, updateHash = true) {
    if (!targetTabId) return;
    activeTab = targetTabId;

    // 1. Synchronize Tab Navigation Buttons
    tabButtons.forEach(btn => {
      const match = btn.getAttribute('data-tab') === targetTabId;
      btn.classList.toggle('active', match);
      if (match && navTabsWrapper) {
        btn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      }
    });

    // 2. Synchronize Mobile Drawer Tabs
    drawerTabs.forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === targetTabId);
    });

    // 3. Toggle View Visibility
    tabPanes.forEach(pane => {
      pane.classList.toggle('active', pane.id === targetTabId);
    });

    // 4. Update URL Hash Route
    if (updateHash && window.location.hash !== `#${targetTabId}`) {
      window.history.pushState(null, '', `#${targetTabId}`);
    }

    // 5. Deep Hardware Hibernation & Resource Conservation Lifecycle
    if (targetTabId === 'tab-live') {
      if (window.TrackerApp.LivePlayer?.attach) {
        window.TrackerApp.LivePlayer.attach();
      }
    } else {
      if (window.TrackerApp.LivePlayer?.detach) {
        window.TrackerApp.LivePlayer.detach();
      }
    }

    // 6. Subsystem Lifecycle & Tab Enter Events
    if (targetTabId === 'tab-gallery') {
      if (window.TrackerApp.Gallery?.load) {
        window.TrackerApp.Gallery.load();
      }
    } else if (targetTabId === 'tab-timeline') {
      if (window.TrackerApp.Timeline?.loadFilters) {
        window.TrackerApp.Timeline.loadFilters();
      }
      if (window.TrackerApp.Timeline?.loadSightings) {
        window.TrackerApp.Timeline.loadSightings();
      }
    } else if (targetTabId === 'tab-analytics') {
      if (window.TrackerApp.Analytics?.initChart) {
        window.TrackerApp.Analytics.initChart();
      }
    } else if (targetTabId === 'tab-alerts') {
      if (window.TrackerApp.Analytics?.loadAlerts) {
        window.TrackerApp.Analytics.loadAlerts();
      }
    } else if (targetTabId === 'tab-videos') {
      if (window.VideoScrubber?.onTabEnter) {
        window.VideoScrubber.onTabEnter();
      }
    } else if (targetTabId === 'tab-review') {
      if (window.ReviewAndRSAC?.loadReviewQueue) {
        window.ReviewAndRSAC.loadReviewQueue('pending');
      }
    }
  }

  // Event Listeners for Tab Navigation
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.getAttribute('data-tab');
      switchTab(target);
    });
  });

  drawerTabs.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.getAttribute('data-tab');
      switchTab(target);
      closeDrawer();
    });
  });

  // Mobile Drawer Triggers
  btnMobileMenu?.addEventListener('click', openDrawer);
  drawerCloseBtn?.addEventListener('click', closeDrawer);
  drawerBackdrop?.addEventListener('click', closeDrawer);

  // URL Hash Routing on Load & Popstate
  function handleHashRoute() {
    const hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) {
      switchTab(hash, false);
    } else {
      switchTab('tab-live', false);
    }
  }

  window.addEventListener('popstate', handleHashRoute);
  handleHashRoute();

  // Export to namespace
  window.TrackerApp.switchTab = switchTab;
  window.TrackerApp.openDrawer = openDrawer;
  window.TrackerApp.closeDrawer = closeDrawer;
});

// Backward Compatibility Facade Re-exports for Legacy Callers & Test Harnesses
const STANDBY_POSTER_SVG = window.TrackerApp?.LivePlayer?.STANDBY_POSTER_SVG || '';
const showToast = (msg, type, duration) => (window.TrackerApp?.showToast || window.showToast)(msg, type, duration);
const attachLiveStream = (...args) => window.TrackerApp?.LivePlayer?.attachLiveStream(...args);
const detachLiveStream = (...args) => window.TrackerApp?.LivePlayer?.detachLiveStream(...args);

window.showToast = showToast;
window.STANDBY_POSTER_SVG = STANDBY_POSTER_SVG;
window.attachLiveStream = attachLiveStream;
window.detachLiveStream = detachLiveStream;

