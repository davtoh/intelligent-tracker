/**
 * Intelligent Tracker - Dashboard UI, Toast & Mobile Drawer Helpers.
 * Extracted from app.js to enforce < 350L modularity budget.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function showToast(titleOrMsg, bodyOrType = 'info', type = 'info', actionText = null, onAction = null) {
    let title = titleOrMsg;
    let body = bodyOrType;
    let toastType = type;
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

  function syncAlertBadges(count) {
    const n = Math.max(0, Number(count ?? 0) || 0);
    const text = String(n);
    ['header-alert-badge', 'drawer-alert-badge', 'drawer-alert-count'].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text;
      el.classList?.toggle?.('has-unread', n > 0);
    });
  }

  function bindDrawerActionButtons(closeDrawer) {
    const openModal = (modalId) => {
      closeDrawer();
      const modal = document.getElementById(modalId);
      if (modal) modal.style.display = 'flex';
    };
    document.getElementById('drawer-btn-enroll')?.addEventListener('click', () => {
      closeDrawer();
      if (window.UniversalEnrollment?.openModal) window.UniversalEnrollment.openModal();
      else openModal('modal-universal-enrollment');
    });
    document.getElementById('drawer-btn-cameras')?.addEventListener('click', () => {
      closeDrawer();
      if (window.CameraManager?.openModal) window.CameraManager.openModal();
      else openModal('modal-camera-manager');
    });
    document.getElementById('drawer-btn-backup')?.addEventListener('click', () => openModal('modal-backup-manager'));
  }

  function bindDrawerAndBackup(drawerTabs, switchTab) {
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

    drawerTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        switchTab(tab.getAttribute('data-tab'));
        closeDrawer();
      });
    });

    bindDrawerActionButtons(closeDrawer);
    window.BackupManager?.bind(showToast);
  }

  window.showToast = showToast;
  window.AppUIHelpers = {
    escapeHtml,
    showToast,
    syncAlertBadges,
    bindDrawerActionButtons,
    bindDrawerAndBackup,
  };
})();
