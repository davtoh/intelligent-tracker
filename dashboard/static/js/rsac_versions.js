/**
 * Intelligent Tracker - Descriptor Version Snapshots & Memory Rollback Submodule.
 * Handles chronological version history retrieval, diffing, and 1-click memory rollback.
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
      .replace(/'/g, '&#39;');
  }

  function showToast(title, body, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(title, body, type);
    } else {
      alert(`${title}: ${body}`);
    }
  }

  function renderVersionEntries(versions, entityId, modal) {
    const container = document.getElementById('versions-timeline-container');
    if (!container) return;

    if (!versions.length) {
      container.innerHTML = '<div class="empty-state">No version history records found for this entity.</div>';
      return;
    }

    container.innerHTML = versions.map(v => {
      const isAnchor = Boolean(v.is_anchor);
      const anchorBadge = isAnchor
        ? '<span class="version-anchor-badge">🔒 Locked Anchor (Ground Truth)</span>'
        : '<span style="font-size:11px;color:#94a3b8;">Adaptive EMA</span>';
      const simText = v.similarity_to_anchor !== null && v.similarity_to_anchor !== undefined
        ? `<span style="font-size: 11px; color: #06b6d4;">Sim: ${(v.similarity_to_anchor * 100).toFixed(1)}%</span>`
        : '';

      return `
        <div class="version-entry" data-version="${v.version}">
          <div class="version-entry-left">
            <span class="version-num-pill">v${v.version}</span>
            <div class="version-meta">
              <div class="version-reason">
                ${escapeHtml(v.update_reason || 'Visual Descriptor Snapshot')}
                ${anchorBadge}
                ${simText}
              </div>
              <div class="version-timestamp">Created: ${escapeHtml(v.created_at)}</div>
            </div>
          </div>
          <div>
            <button class="btn btn-xs btn-outline btn-rollback" data-id="${entityId}" data-version="${v.version}">
              ↩ Rollback to v${v.version}
            </button>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.btn-rollback').forEach(btn => {
      btn.addEventListener('click', async () => {
        const v = btn.getAttribute('data-version');
        if (confirm(`Roll back entity visual descriptor to version v${v}? This will overwrite active features with this verified snapshot.`)) {
          await rollbackDescriptor(entityId, v, modal);
        }
      });
    });
  }

  async function openVersionsModal(entityId, entityName) {
    const modal = document.getElementById('modal-descriptor-versions');
    const title = document.getElementById('versions-modal-title');
    const container = document.getElementById('versions-timeline-container');

    if (!modal || !container) return;

    modal.style.display = 'flex';
    if (title) title.textContent = `⏳ Descriptor Versions: ${entityName || `#${entityId}`}`;
    container.innerHTML = '<div class="empty-state">Loading descriptor version history...</div>';

    try {
      const res = await fetch(`/api/entities/${entityId}/versions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderVersionEntries(data.versions || [], entityId, modal);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">Failed to load versions: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function rollbackDescriptor(entityId, version, modal) {
    try {
      const res = await fetch(`/api/entities/${entityId}/rollback/${version}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: `Manual operator rollback to v${version}` }),
      });
      if (!res.ok) throw new Error('Rollback failed');
      if (modal) modal.style.display = 'none';
      showToast('Descriptor Rolled Back', `Entity descriptor restored to verified snapshot v${version}!`, 'success');
      if (typeof window.loadGallery === 'function') window.loadGallery();
    } catch (err) {
      showToast('Rollback Failed', err.message, 'error');
    }
  }

  function initVersionsModal() {
    const modal = document.getElementById('modal-descriptor-versions');
    const closeBtn = document.getElementById('modal-versions-close');
    if (closeBtn && modal) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
      });
    }
  }

  window.RSACVersions = {
    init: initVersionsModal,
    openVersionsModal: openVersionsModal,
    rollbackDescriptor: rollbackDescriptor,
  };
})();

