/**
 * ============================================================================
 * Intelligent Tracker - Reusable Responsive Nav Tabs Scroll Manager
 * Encapsulates direct horizontal scroll navigation, cut-off detection,
 * ARIA keyboard navigation, and drawer synchronization across all 9 tabs.
 * Modularity Budget: <= 200 lines (SRP & KISS compliant)
 * ============================================================================
 */

(function () {
  'use strict';

  class NavTabsManager {
    constructor() {
      this.container = document.querySelector('.nav-tabs-container');
      this.wrapper = document.getElementById('nav-tabs-wrapper');
      this.nav = this.wrapper ? this.wrapper.querySelector('.nav-tabs') : null;
      this.prevBtn = document.getElementById('nav-tabs-prev');
      this.nextBtn = document.getElementById('nav-tabs-next');
      this.tabs = [];
      this.activeTabId = 'tab-live';

      this.init();
    }

    init() {
      if (!this.wrapper || !this.nav) return;
      this.collectTabs();
      this.setupScrollControls();
      this.setupKeyboardNav();
      this.observeResizeAndScroll();
      this.updateScrollButtons();
    }

    collectTabs() {
      const tabElements = this.nav.querySelectorAll('.nav-tab');
      this.tabs = Array.from(tabElements).map(el => {
        const id = el.getAttribute('data-tab');
        const icon = el.querySelector('.tab-icon')?.textContent.trim() || '📄';
        const labelEl = Array.from(el.childNodes).find(n => n.nodeType === 3 && n.textContent.trim().length > 0) || el.querySelector('span:not(.tab-icon):not(.badge)');
        const label = labelEl ? labelEl.textContent.trim() : id;
        return { id, icon, label, element: el };
      });
    }

    setupScrollControls() {
      if (this.prevBtn) {
        this.prevBtn.addEventListener('click', (e) => {
          e.preventDefault();
          this.scrollPrev();
        });
      }
      if (this.nextBtn) {
        this.nextBtn.addEventListener('click', (e) => {
          e.preventDefault();
          this.scrollNext();
        });
      }

      this.wrapper.addEventListener('scroll', () => this.updateScrollButtons(), { passive: true });
    }

    scrollNext() {
      if (!this.wrapper) return;
      const step = Math.max(160, Math.floor(this.wrapper.clientWidth * 0.75));
      this.wrapper.scrollBy({ left: step, behavior: 'smooth' });
      setTimeout(() => this.updateScrollButtons(), 350);
    }

    scrollPrev() {
      if (!this.wrapper) return;
      const step = Math.max(160, Math.floor(this.wrapper.clientWidth * 0.75));
      if (this.wrapper.scrollLeft <= step + 30) {
        this.wrapper.scrollTo({ left: 0, behavior: 'smooth' });
      } else {
        this.wrapper.scrollBy({ left: -step, behavior: 'smooth' });
      }
      setTimeout(() => this.updateScrollButtons(), 350);
    }

    isAtStart() {
      if (!this.wrapper) return true;
      const { scrollLeft } = this.wrapper;
      if (scrollLeft <= 4) return true;
      const firstTab = this.tabs[0]?.element;
      if (!firstTab) return scrollLeft <= 16;
      const wrapRect = this.wrapper.getBoundingClientRect();
      const firstRect = firstTab.getBoundingClientRect();
      // Tab left edge is within/at wrapper left edge, or scrollLeft aligns with first tab offset
      return firstRect.left >= wrapRect.left - 4 || scrollLeft <= (firstTab.offsetLeft + 2);
    }

    isAtEnd() {
      if (!this.wrapper) return true;
      const { scrollLeft, scrollWidth, clientWidth } = this.wrapper;
      if ((scrollLeft + clientWidth) >= (scrollWidth - 6)) return true;
      const lastTab = this.tabs[this.tabs.length - 1]?.element;
      if (!lastTab) return false;
      const wrapRect = this.wrapper.getBoundingClientRect();
      const lastRect = lastTab.getBoundingClientRect();
      // Tab right edge is within/at wrapper right edge
      return lastRect.right <= wrapRect.right + 4;
    }

    updateScrollButtons() {
      if (!this.wrapper || !this.prevBtn || !this.nextBtn) return;
      const { scrollWidth, clientWidth } = this.wrapper;
      const isOverflowing = scrollWidth > clientWidth + 6;

      if (this.container) {
        this.container.classList.toggle('no-overflow', !isOverflowing);
      }

      if (!isOverflowing) {
        this.prevBtn.disabled = true;
        this.nextBtn.disabled = true;
        return;
      }

      this.prevBtn.disabled = this.isAtStart();
      this.nextBtn.disabled = this.isAtEnd();
    }

    setupKeyboardNav() {
      if (!this.nav) return;
      this.nav.addEventListener('keydown', (e) => {
        const activeIdx = this.tabs.findIndex(t => t.id === this.activeTabId);
        if (activeIdx === -1) return;

        let nextIdx = null;
        if (e.key === 'ArrowRight') nextIdx = (activeIdx + 1) % this.tabs.length;
        if (e.key === 'ArrowLeft') nextIdx = (activeIdx - 1 + this.tabs.length) % this.tabs.length;
        if (e.key === 'Home') nextIdx = 0;
        if (e.key === 'End') nextIdx = this.tabs.length - 1;

        if (nextIdx !== null) {
          e.preventDefault();
          const target = this.tabs[nextIdx];
          this.switchTab(target.id);
          target.element.focus();
        }
      });
    }

    observeResizeAndScroll() {
      if (typeof ResizeObserver !== 'undefined' && this.wrapper) {
        const ro = new ResizeObserver(() => this.updateScrollButtons());
        ro.observe(this.wrapper);
      }
      window.addEventListener('resize', () => this.updateScrollButtons(), { passive: true });
    }

    switchTab(tabId) {
      this.activeTabId = tabId;

      // Update Header nav tabs
      this.tabs.forEach(t => {
        const isActive = t.id === tabId;
        t.element.classList.toggle('active', isActive);
        t.element.setAttribute('aria-selected', String(isActive));
        t.element.setAttribute('tabindex', isActive ? '0' : '-1');
        // Direct container scrolling only - NEVER scrollIntoView (prevents whole page shifts)
        if (isActive && t.element.offsetParent !== null && this.wrapper) {
          if (this.wrapper.scrollWidth > this.wrapper.clientWidth) {
            const wrapRect = this.wrapper.getBoundingClientRect();
            const tabRect = t.element.getBoundingClientRect();
            const targetLeft = (tabRect.left - wrapRect.left) + this.wrapper.scrollLeft - (this.wrapper.clientWidth - tabRect.width) / 2;
            this.wrapper.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
          }
        }
      });

      // Delegate to global switchTab in app.js
      if (typeof window.switchTab === 'function') {
        window.switchTab(tabId);
      } else {
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === tabId));
      }

      // Lock window horizontal scroll to 0
      if (window.scrollX !== 0) {
        window.scrollTo(0, window.scrollY);
      }

      this.updateScrollButtons();
      setTimeout(() => this.updateScrollButtons(), 350);
    }
  }

  // Auto-instantiate when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      window.navTabsManager = new NavTabsManager();
    });
  } else {
    window.navTabsManager = new NavTabsManager();
  }

  window.NavTabsManager = NavTabsManager;
})();
