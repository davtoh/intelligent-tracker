/**
 * Intelligent Tracker - Text Truncation & Accessible Popover Manager
 * Milestone: Layout Stabilization & WCAG 2.1/2.2 AA Accessibility (AX)
 */
(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.TextTruncationManager = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  class TextTruncationManager {
    constructor() {
      this.popoverEl = null;
      this.titleEl = null;
      this.bodyEl = null;
      this.copyBtn = null;
      this.currentTarget = null;
      this.showTimer = null;
      this.hideTimer = null;
      this.isMouseOverPopover = false;
    }

    init() {
      if (document.getElementById('text-truncation-popover')) {
        this.popoverEl = document.getElementById('text-truncation-popover');
        this.titleEl = this.popoverEl.querySelector('.truncate-popover-title');
        this.bodyEl = this.popoverEl.querySelector('.truncate-popover-body');
        this.copyBtn = this.popoverEl.querySelector('.truncate-popover-copy-btn');
        return this;
      }

      this._createPopoverDOM();
      this._bindGlobalEvents();
      this.scan();
      return this;
    }

    _createPopoverDOM() {
      const el = document.createElement('div');
      el.id = 'text-truncation-popover';
      el.className = 'truncate-popover';
      el.setAttribute('role', 'tooltip');
      el.setAttribute('aria-hidden', 'true');

      el.innerHTML = `
        <div class="truncate-popover-arrow"></div>
        <div class="truncate-popover-header">
          <span class="truncate-popover-title">Details</span>
          <button type="button" class="truncate-popover-copy-btn" aria-label="Copy full text to clipboard">
            <span class="copy-icon">📋</span>
            <span class="copy-label">Copy</span>
          </button>
        </div>
        <div class="truncate-popover-body"></div>
      `;

      document.body.appendChild(el);
      this.popoverEl = el;
      this.titleEl = el.querySelector('.truncate-popover-title');
      this.bodyEl = el.querySelector('.truncate-popover-body');
      this.copyBtn = el.querySelector('.truncate-popover-copy-btn');

      this.copyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (this.bodyEl) this.copyText(this.bodyEl.textContent, this.copyBtn);
      });

      el.addEventListener('mouseenter', () => {
        this.isMouseOverPopover = true;
        clearTimeout(this.hideTimer);
      });

      el.addEventListener('mouseleave', () => {
        this.isMouseOverPopover = false;
        this.hideTimer = setTimeout(() => this.hidePopover(), 200);
      });
    }

    _bindGlobalEvents() {
      document.addEventListener('mouseenter', (e) => this._handleTriggerEnter(e), true);
      document.addEventListener('mouseleave', (e) => this._handleTriggerLeave(e), true);
      document.addEventListener('focusin', (e) => this._handleTriggerFocus(e), true);
      document.addEventListener('focusout', (e) => this._handleTriggerBlur(e), true);

      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.popoverEl?.classList.contains('visible')) {
          this.hidePopover();
        }
      });

      document.addEventListener('click', (e) => {
        if (!this.popoverEl?.contains(e.target) && !e.target.closest('.truncate-trigger')) {
          this.hidePopover();
        }
      });
    }

    format(text, options = {}) {
      if (!text || typeof text !== 'string') return '';
      const mode = options.mode || 'middle';
      const maxLen = options.maxLength || 32;
      const preserveExt = options.preserveExt !== false;

      if (text.length <= maxLen) return text;
      if (mode === 'wrap') return text;
      if (mode === 'end') return text.slice(0, maxLen - 3) + '...';

      let ext = '';
      let stem = text;
      if (preserveExt) {
        const lastDot = text.lastIndexOf('.');
        if (lastDot > 0 && text.length - lastDot <= 6) {
          ext = text.slice(lastDot);
          stem = text.slice(0, lastDot);
        }
      }

      const budget = maxLen - 3 - ext.length;
      if (budget <= 4) return text.slice(0, maxLen - 3) + '...';
      const head = Math.ceil(budget / 2);
      const tail = Math.floor(budget / 2);
      return `${stem.slice(0, head)}...${stem.slice(-tail)}${ext}`;
    }

    apply(element, options = {}) {
      if (!element) return;
      const fullText = options.fullText || element.getAttribute('data-full-text') || element.textContent.trim();
      const label = options.label || options.title || 'Details';
      const mode = options.mode || 'middle';
      const maxLen = options.maxLength || 32;

      element.setAttribute('data-full-text', fullText);
      element.setAttribute('data-truncate-label', label);
      element.classList.add('truncate-trigger');

      if (!element.hasAttribute('tabindex') && !['BUTTON', 'A', 'INPUT'].includes(element.tagName)) {
        element.setAttribute('tabindex', '0');
        element.setAttribute('role', 'button');
      }
      element.setAttribute('aria-describedby', 'text-truncation-popover');
      element.setAttribute('title', fullText);

      if (options.format !== false) {
        element.textContent = this.format(fullText, { mode, maxLength: maxLen, preserveExt: options.preserveExt });
      }
      return element;
    }

    showPopover(targetEl, text, label = 'Details') {
      if (!this.popoverEl) this.init();
      clearTimeout(this.showTimer);
      clearTimeout(this.hideTimer);

      this.currentTarget = targetEl;
      this.titleEl.textContent = label;
      this.bodyEl.textContent = text;
      this.popoverEl.setAttribute('aria-hidden', 'false');
      targetEl.setAttribute('aria-expanded', 'true');

      this._reposition(targetEl);
      this.popoverEl.classList.add('visible');
    }

    _reposition(targetEl) {
      const rect = targetEl.getBoundingClientRect();
      const popoverWidth = Math.min(window.innerWidth * 0.92, 440);
      const popoverHeight = 110;

      let top = rect.top - popoverHeight - 8;
      let placement = 'top';
      if (top < 12) {
        top = rect.bottom + 8;
        placement = 'bottom';
      }

      let left = rect.left + (rect.width / 2) - (popoverWidth / 2);
      left = Math.max(12, Math.min(left, window.innerWidth - popoverWidth - 12));

      this.popoverEl.setAttribute('data-placement', placement);
      this.popoverEl.style.top = `${Math.round(top)}px`;
      this.popoverEl.style.left = `${Math.round(left)}px`;
      this.popoverEl.style.width = `${popoverWidth}px`;
    }

    hidePopover() {
      clearTimeout(this.showTimer);
      clearTimeout(this.hideTimer);
      if (this.isMouseOverPopover) return;

      if (this.popoverEl) {
        this.popoverEl.classList.remove('visible');
        this.popoverEl.setAttribute('aria-hidden', 'true');
      }
      if (this.currentTarget) {
        this.currentTarget.setAttribute('aria-expanded', 'false');
        this.currentTarget = null;
      }
    }

    copyText(text, btnEl) {
      if (!text) return;
      const performFeedback = () => {
        if (!btnEl) return;
        btnEl.classList.add('copied');
        const label = btnEl.querySelector('.copy-label');
        if (label) label.textContent = 'Copied!';
        setTimeout(() => {
          btnEl.classList.remove('copied');
          if (label) label.textContent = 'Copy';
        }, 1500);
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(performFeedback).catch((err) => {
          console.debug('[TextTruncation] Clipboard write error:', err);
        });
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
          document.execCommand('copy');
          performFeedback();
        } catch (err) {
          console.debug('[TextTruncation] Fallback execCommand copy failed:', err);
        }
        document.body.removeChild(textarea);
      }
    }

    scan(root = document) {
      const elements = root.querySelectorAll('[data-truncate]');
      elements.forEach(el => {
        const mode = el.getAttribute('data-truncate') || 'middle';
        const maxLen = parseInt(el.getAttribute('data-truncate-max') || '32', 10);
        const label = el.getAttribute('data-truncate-label') || 'Details';
        this.apply(el, { mode, maxLength: maxLen, label });
      });
    }

    _handleTriggerEnter(e) {
      const trigger = e.target.closest?.('.truncate-trigger');
      if (!trigger) return;
      const fullText = trigger.getAttribute('data-full-text') || trigger.getAttribute('title');
      if (!fullText) return;
      const label = trigger.getAttribute('data-truncate-label') || 'Details';
      clearTimeout(this.hideTimer);
      this.showTimer = setTimeout(() => this.showPopover(trigger, fullText, label), 150);
    }

    _handleTriggerLeave(e) {
      const trigger = e.target.closest?.('.truncate-trigger');
      if (!trigger) return;
      clearTimeout(this.showTimer);
      this.hideTimer = setTimeout(() => this.hidePopover(), 250);
    }

    _handleTriggerFocus(e) {
      const trigger = e.target.closest?.('.truncate-trigger');
      if (!trigger) return;
      const fullText = trigger.getAttribute('data-full-text') || trigger.getAttribute('title');
      if (!fullText) return;
      const label = trigger.getAttribute('data-truncate-label') || 'Details';
      this.showPopover(trigger, fullText, label);
    }

    _handleTriggerBlur(e) {
      const trigger = e.target.closest?.('.truncate-trigger');
      if (!trigger) return;
      this.hidePopover();
    }
  }

  const instance = new TextTruncationManager();
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => instance.init());
    } else {
      instance.init();
    }
  }

  return instance;
});

