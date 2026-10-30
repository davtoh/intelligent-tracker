/**
 * Intelligent Tracker - Core Web Utilities & Standardized Toast Notifications.
 * Exposes window.escapeHtml and window.showToast across all frontend modules.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  /**
   * Escape HTML to prevent XSS vulnerabilities.
   * @param {string} str
   * @returns {string}
   */
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Modern Toast Notification Dispatcher.
   * @param {string} titleOrMsg
   * @param {string} bodyOrType
   * @param {string} type - 'info' | 'success' | 'warning' | 'error' | 'alert' | 'review'
   * @param {string|null} actionText
   * @param {Function|null} onAction
   */
  function showToast(titleOrMsg, bodyOrType = 'info', type = 'info', actionText = null, onAction = null) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    let title = 'NOTIFICATION';
    let body = '';
    let toastType = 'info';

    const validTypes = ['info', 'success', 'warning', 'error', 'alert', 'review'];
    if (typeof bodyOrType === 'string' && validTypes.includes(bodyOrType.toLowerCase())) {
      toastType = bodyOrType.toLowerCase();
      body = String(titleOrMsg || '');
      title = toastType === 'success' ? 'Success' : (toastType === 'error' ? 'Error' : 'Notification');
    } else if (bodyOrType !== undefined && bodyOrType !== null) {
      title = String(titleOrMsg || 'Notification');
      body = String(bodyOrType || '');
      toastType = (type && validTypes.includes(type.toLowerCase())) ? type.toLowerCase() : 'info';
    } else {
      body = String(titleOrMsg || '');
      toastType = 'info';
    }

    const toast = document.createElement('div');
    toast.className = `toast-message ${toastType}`;

    let actionHtml = '';
    if (actionText && typeof onAction === 'function') {
      actionHtml = `<div class="toast-action">${escapeHtml(actionText)}</div>`;
    }

    toast.innerHTML = `
      <div class="toast-header">
        <span class="toast-title">${escapeHtml(title)}</span>
        <button class="toast-close" aria-label="Close notification">&times;</button>
      </div>
      <div class="toast-body">${escapeHtml(body)}</div>
      ${actionHtml}
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.remove();
    });

    if (actionText && typeof onAction === 'function') {
      toast.querySelector('.toast-action').addEventListener('click', () => {
        onAction();
        toast.remove();
      });
    }

    container.appendChild(toast);

    // Auto-dismiss after 4.5 seconds
    setTimeout(() => {
      if (toast.parentNode) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        setTimeout(() => toast.remove(), 300);
      }
    }, 4500);
  }

  // Export to global scope and namespace
  window.escapeHtml = escapeHtml;
  window.showToast = showToast;
  window.TrackerApp.escapeHtml = escapeHtml;
  window.TrackerApp.showToast = showToast;
})();

