/**
 * Intelligent Tracker - Milestone 9: Artifact & Face Intelligence,
 * Active Learning & Adaptive Memory Client Controller.
 *
 * Coordinates:
 * - Human-in-the-Loop Active Learning ("Review & Learn" Inbox)
 * - 1-Click Candidate triage: Confirm (Locked Anchor), Reassign, Enroll New, Dismiss
 * - Universal Freeze-Frame Bounding Box Enrollment with Dual-Model extraction
 * - Descriptor Version Snapshots & Memory Rollback timeline
 * - Real-time WebSocket Toasts for RSAC Violations and Review Items
 */

(function () {
  'use strict';

  // Global Controller State
  const state = {
    currentReviewStatus: 'pending',
    pendingReviewCount: 0,
    enrolledEntities: [],
    customCategories: [],
    freezeFrameImg: null,
    freezeFrameDataUrl: null,
    isDrawingBbox: false,
    bboxStart: null,
    selectedBbox: null, // [x, y, w, h] in image coordinates
    selectedCropBase64: null,
    lastSeenAlertIds: new Set(),
  };

  // Helper escape
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Toast Notification System
  function showToast(title, body, type = 'info', actionText = null, onAction = null) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-message ${type}`;

    let actionHtml = '';
    if (actionText) {
      actionHtml = `<div class="toast-action">${escapeHtml(actionText)}</div>`;
    }

    toast.innerHTML = `
      <div class="toast-header">
        <span class="toast-title">${escapeHtml(title)}</span>
        <button class="toast-close">&times;</button>
      </div>
      <div class="toast-body">${escapeHtml(body)}</div>
      ${actionHtml}
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.remove();
    });

    if (actionText && onAction) {
      toast.querySelector('.toast-action').addEventListener('click', () => {
        onAction();
        toast.remove();
      });
    }

    container.appendChild(toast);

    // Auto-remove after 6 seconds
    setTimeout(() => {
      if (toast.parentElement) toast.remove();
    }, 6000);
  }

  // =========================================================================
  // 1. Active Learning ("Review & Learn") Inbox
  // =========================================================================
  async function loadReviewQueue(status = 'pending') {
    state.currentReviewStatus = status;
    const container = document.getElementById('review-queue-container');
    const counter = document.getElementById('review-inbox-counter');
    const badge = document.getElementById('header-review-badge');

    if (!container) return;

    try {
      const res = await fetch(`/api/active-learning/queue?status=${encodeURIComponent(status)}&limit=50`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items = data.items || [];

      if (status === 'pending') {
        state.pendingReviewCount = items.length;
        if (badge) {
          badge.textContent = items.length;
          badge.style.display = items.length > 0 ? 'inline-block' : 'none';
        }
      }

      if (counter) {
        counter.textContent = `${items.length} Candidate${items.length === 1 ? '' : 's'}`;
      }

      renderReviewGrid(items, container, status);
    } catch (err) {
      container.innerHTML = `<div class="empty-state">Failed to load review queue: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderReviewGrid(items, container, status) {
    if (!items.length) {
      container.innerHTML = `
        <div class="empty-state">
          No ${escapeHtml(status)} candidates in review queue. Borderline matches (0.45 &lt; sim &lt; 0.70) are automatically routed here.
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => {
      const sim = (item.similarity_score || 0) * 100;
      const simColor = sim >= 60 ? '#06b6d4' : '#f59e0b';
      const cropUrl = item.crop_path ? (item.crop_path.startsWith('/') ? item.crop_path : `/${item.crop_path}`) : '/static/avatar-placeholder.png';
      const matchLabel = item.matched_entity_name ? `Matched: <strong>${escapeHtml(item.matched_entity_name)}</strong>` : 'Unidentified Borderline Track';
      const isPending = item.status === 'pending';

      let actionsHtml = '';
      if (isPending) {
        actionsHtml = `
          <div class="review-actions">
            <button class="btn btn-xs btn-confirm" data-id="${item.id}" title="Confirm as Ground Truth Locked Anchor">
              ✓ Confirm (Locked Anchor)
            </button>
            <button class="btn btn-xs btn-reassign" data-id="${item.id}" title="Reassign signature to a different entity">
              🟨 Reassign
            </button>
            <button class="btn btn-xs btn-enroll-new" data-id="${item.id}" data-crop="${escapeHtml(cropUrl)}" title="Enroll as a newly created entity">
              ✨ Enroll New
            </button>
            <button class="btn btn-xs btn-dismiss" data-id="${item.id}" title="Dismiss candidate without changes">
              ✕ Dismiss
            </button>
          </div>
        `;
      } else {
        actionsHtml = `
          <div style="font-size: 11px; color: #94a3b8; font-style: italic;">
            Status: <span style="color: #f8fafc; font-weight: 600;">${escapeHtml(item.status)}</span>
            ${item.notes ? ` &mdash; ${escapeHtml(item.notes)}` : ''}
          </div>
        `;
      }

      return `
        <div class="glass-panel review-card" data-item-id="${item.id}">
          <div class="review-card-top">
            <img class="review-thumb" src="${cropUrl}" alt="Review Crop" onerror="this.src='/static/avatar-placeholder.png';" />
            <div class="review-meta">
              <div class="review-title">Track #${item.track_id} (${escapeHtml(item.camera_id)})</div>
              <div class="review-candidate-match">${matchLabel}</div>
              <div class="confidence-meter">
                <span>Confidence:</span>
                <div class="confidence-bar-track">
                  <div class="confidence-bar-fill" style="width: ${Math.min(100, Math.max(5, sim))}%; background: ${simColor};"></div>
                </div>
                <span style="font-weight: 600; color: ${simColor};">${sim.toFixed(1)}%</span>
              </div>
              <div class="review-timestamp">${escapeHtml(item.created_at)}</div>
            </div>
          </div>
          ${actionsHtml}
        </div>
      `;
    }).join('');

    // Attach Action Handlers
    container.querySelectorAll('.btn-confirm').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await confirmReviewItem(id);
      });
    });

    container.querySelectorAll('.btn-reassign').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        openReassignModal(id);
      });
    });

    container.querySelectorAll('.btn-enroll-new').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await enrollNewFromReview(id);
      });
    });

    container.querySelectorAll('.btn-dismiss').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        await dismissReviewItem(id);
      });
    });
  }

  async function confirmReviewItem(itemId) {
    try {
      const res = await fetch(`/api/active-learning/${itemId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator verified ground-truth locked anchor' }),
      });
      if (!res.ok) throw new Error('Confirm failed');
      const data = await res.json();
      showToast('Candidate Confirmed', `Locked as ground truth anchor for ${data.entity_name || 'entity'}.`, 'success');
      loadReviewQueue(state.currentReviewStatus);
    } catch (err) {
      alert(`Error confirming candidate: ${err.message}`);
    }
  }

  async function dismissReviewItem(itemId) {
    try {
      const res = await fetch(`/api/active-learning/${itemId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Operator dismissed borderline candidate' }),
      });
      if (!res.ok) throw new Error('Dismiss failed');
      showToast('Candidate Dismissed', 'Review item dismissed without modifying gallery.', 'info');
      loadReviewQueue(state.currentReviewStatus);
    } catch (err) {
      alert(`Error dismissing candidate: ${err.message}`);
    }
  }

  async function enrollNewFromReview(itemId) {
    const name = prompt('Enter full name for new entity:');
    if (!name || !name.trim()) return;

    try {
      const res = await fetch(`/api/active-learning/${itemId}/enroll-new`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          category: 'person',
          security_role: 'resident',
          notes: 'Enrolled via Active Learning Review Queue',
        }),
      });
      if (!res.ok) throw new Error('Enroll new failed');
      const data = await res.json();
      showToast('Entity Enrolled', `Registered "${name}" (ID #${data.entity_id}) with initial signature locked!`, 'success');
      loadReviewQueue(state.currentReviewStatus);
    } catch (err) {
      alert(`Error enrolling new entity: ${err.message}`);
    }
  }

  // =========================================================================
  // 2. Reassign Modal
  // =========================================================================
  async function openReassignModal(itemId) {
    const modal = document.getElementById('modal-review-reassign');
    const select = document.getElementById('reassign-entity-select');
    const idInput = document.getElementById('reassign-item-id');

    if (!modal || !select || !idInput) return;

    idInput.value = itemId;
    modal.style.display = 'flex';

    // Populate enrolled entities
    try {
      const res = await fetch('/entities');
      const entities = await res.json();
      select.innerHTML = '<option value="">Select target entity...</option>' +
        entities.map(e => `<option value="${e.id}">${escapeHtml(e.name)} (${escapeHtml(e.category || 'person')})</option>`).join('');
    } catch (err) {
      select.innerHTML = '<option value="">Error loading entities</option>';
    }
  }

  function initReassignModal() {
    const modal = document.getElementById('modal-review-reassign');
    const form = document.getElementById('review-reassign-form');
    const closeBtn = document.getElementById('modal-reassign-close');
    const cancelBtn = document.getElementById('modal-reassign-cancel');

    if (closeBtn && modal) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (cancelBtn && modal) cancelBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.style.display = 'none';
      });
    }

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const itemId = document.getElementById('reassign-item-id').value;
        const targetEntityId = document.getElementById('reassign-entity-select').value;
        const notes = document.getElementById('reassign-notes-input').value;

        if (!targetEntityId) {
          alert('Please select a target entity');
          return;
        }

        try {
          const res = await fetch(`/api/active-learning/${itemId}/reassign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_entity_id: parseInt(targetEntityId, 10),
              notes: notes || 'Operator reassigned candidate crop',
            }),
          });
          if (!res.ok) throw new Error('Reassignment failed');
          modal.style.display = 'none';
          showToast('Reassignment Saved', 'Signature assigned as locked anchor to target entity.', 'success');
          loadReviewQueue(state.currentReviewStatus);
        } catch (err) {
          alert(`Error saving reassignment: ${err.message}`);
        }
      });
    }
  }

  // =========================================================================
  // 3. Universal Artifact & Face Freeze-Frame Enrollment
  // =========================================================================
  function initUniversalEnrollment() {
    const modal = document.getElementById('modal-universal-enrollment');
    const openBtn = document.getElementById('btn-open-enrollment');
    const closeBtn = document.getElementById('modal-enroll-close');
    const cancelBtn = document.getElementById('modal-enroll-cancel');
    const captureFreezeBtn = document.getElementById('btn-capture-freeze');
    const uploadBtn = document.getElementById('btn-upload-enroll-crop');
    const fileInput = document.getElementById('enroll-file-input');
    const canvas = document.getElementById('enroll-bbox-canvas');
    const placeholder = document.getElementById('enroll-canvas-placeholder');
    const previewBox = document.getElementById('enroll-crop-preview-box');
    const previewImg = document.getElementById('enroll-crop-preview-img');
    const previewMeta = document.getElementById('enroll-crop-meta');
    const form = document.getElementById('universal-enrollment-form');
    const categorySelect = document.getElementById('enroll-category-select');

    if (!modal) return;

    if (openBtn) {
      openBtn.addEventListener('click', async () => {
        modal.style.display = 'flex';
        await loadCategoriesDropdown(categorySelect);
        // Automatically grab live frame
        captureFreezeFrame();
      });
    }

    if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    if (cancelBtn) cancelBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.style.display = 'none';
    });

    if (captureFreezeBtn) {
      captureFreezeBtn.addEventListener('click', captureFreezeFrame);
    }

    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (re) => {
          loadFreezeImage(re.target.result);
        };
        reader.readAsDataURL(file);
      });
    }

    async function loadCategoriesDropdown(selectElem) {
      if (!selectElem) return;
      try {
        const res = await fetch('/api/rsac/categories');
        if (res.ok) {
          const cats = await res.json();
          state.customCategories = cats;
          selectElem.innerHTML = cats.map(c => 
            `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)} (${escapeHtml(c.id)})</option>`
          ).join('');
        }
      } catch (e) {
        console.warn('Failed to load RSAC categories:', e);
      }
    }

    async function captureFreezeFrame() {
      const camSelect = document.getElementById('enroll-camera-select');
      const camId = camSelect ? camSelect.value : 'cam_01';

      if (placeholder) {
        placeholder.style.display = 'block';
        placeholder.innerHTML = 'Capturing live freeze-frame...';
      }
      if (canvas) canvas.style.display = 'none';

      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        loadFreezeImage(data.image_base64);
      } catch (err) {
        if (placeholder) {
          placeholder.innerHTML = `<span style="color:#ef4444;">Failed to capture frame: ${escapeHtml(err.message)}</span>`;
        }
      }
    }

    function loadFreezeImage(dataUrl) {
      state.freezeFrameDataUrl = dataUrl;
      const img = new Image();
      img.onload = () => {
        state.freezeFrameImg = img;
        canvas.width = img.naturalWidth || 640;
        canvas.height = img.naturalHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);

        if (placeholder) placeholder.style.display = 'none';
        canvas.style.display = 'block';
        state.selectedBbox = null;
        state.selectedCropBase64 = null;
        if (previewBox) previewBox.style.display = 'none';
      };
      img.src = dataUrl;
    }

    // Canvas Mouse Dragging for Bounding Box
    let isDrawing = false;
    let startX = 0, startY = 0;

    canvas.addEventListener('mousedown', (e) => {
      if (!state.freezeFrameImg) return;
      isDrawing = true;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      startX = (e.clientX - rect.left) * scaleX;
      startY = (e.clientY - rect.top) * scaleY;
    });

    canvas.addEventListener('mousemove', (e) => {
      if (!isDrawing || !state.freezeFrameImg) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const curX = (e.clientX - rect.left) * scaleX;
      const curY = (e.clientY - rect.top) * scaleY;

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(state.freezeFrameImg, 0, 0);

      const x = Math.min(startX, curX);
      const y = Math.min(startY, curY);
      const w = Math.abs(curX - startX);
      const h = Math.abs(curY - startY);

      // Glowing selection box
      ctx.strokeStyle = '#06b6d4';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = 'rgba(6, 182, 212, 0.15)';
      ctx.fillRect(x, y, w, h);
    });

    canvas.addEventListener('mouseup', (e) => {
      if (!isDrawing || !state.freezeFrameImg) return;
      isDrawing = false;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const endX = (e.clientX - rect.left) * scaleX;
      const endY = (e.clientY - rect.top) * scaleY;

      const x = Math.round(Math.min(startX, endX));
      const y = Math.round(Math.min(startY, endY));
      const w = Math.round(Math.abs(endX - startX));
      const h = Math.round(Math.abs(endY - startY));

      if (w > 15 && h > 15) {
        state.selectedBbox = [x, y, w, h];
        extractCropThumbnail(x, y, w, h);
      }
    });

    function extractCropThumbnail(x, y, w, h) {
      const cropCanvas = document.createElement('canvas');
      cropCanvas.width = w;
      cropCanvas.height = h;
      const cctx = cropCanvas.getContext('2d');
      cctx.drawImage(state.freezeFrameImg, x, y, w, h, 0, 0, w, h);
      const cropData = cropCanvas.toDataURL('image/jpeg', 0.9);
      state.selectedCropBase64 = cropData;

      if (previewBox && previewImg) {
        previewImg.src = cropData;
        previewBox.style.display = 'flex';
        if (previewMeta) {
          previewMeta.textContent = `Region: ${w}x${h} px at (${x}, ${y})`;
        }
      }
    }

    // Form Submission
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('enroll-name-input').value.trim();
        const category = document.getElementById('enroll-category-select').value;
        const role = document.getElementById('enroll-role-input').value.trim();
        const camSelect = document.getElementById('enroll-camera-select');
        const camId = camSelect ? camSelect.value : 'cam_01';
        const isAnchor = document.getElementById('enroll-locked-anchor-cb').checked;
        const notes = document.getElementById('enroll-notes-input').value.trim();

        if (!name) {
          alert('Please enter an entity name.');
          return;
        }

        if (!state.selectedCropBase64 && !state.selectedBbox) {
          alert('Please drag a bounding box on the freeze-frame image to select the entity crop.');
          return;
        }

        const submitBtn = document.getElementById('btn-submit-enrollment');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Extracting Biometrics...';

        try {
          const payload = {
            name: name,
            category: category,
            security_role: role,
            notes: notes,
            is_anchor: isAnchor,
            camera_id: camId,
            crop_base64: state.selectedCropBase64,
            bbox: state.selectedBbox,
          };

          const res = await fetch('/api/enroll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });

          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Enrollment failed');
          }

          const result = await res.json();
          modal.style.display = 'none';
          form.reset();
          showToast(
            'Enrollment Successful',
            `"${name}" enrolled as ${category.toUpperCase()} (ID #${result.entity_id}). Initial descriptor v1 locked!`,
            'success'
          );

          // Refresh gallery if active
          if (typeof window.loadGallery === 'function') {
            window.loadGallery();
          }
        } catch (err) {
          alert(`Enrollment failed: ${err.message}`);
        } finally {
          submitBtn.disabled = false;
          submitBtn.textContent = '✨ Enroll & Lock Anchor';
        }
      });
    }
  }

  // =========================================================================
  // 4. Descriptor Version History & Memory Rollback Modal
  // =========================================================================
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
      const versions = data.versions || [];

      if (!versions.length) {
        container.innerHTML = '<div class="empty-state">No version history records found for this entity.</div>';
        return;
      }

      container.innerHTML = versions.map(v => {
        const isAnchor = Boolean(v.is_anchor);
        const anchorBadge = isAnchor ? '<span class="version-anchor-badge">🔒 Locked Anchor (Ground Truth)</span>' : '<span style="font-size:11px;color:#94a3b8;">Adaptive EMA</span>';
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

      // Attach Rollback Click Listeners
      container.querySelectorAll('.btn-rollback').forEach(btn => {
        btn.addEventListener('click', async () => {
          const v = btn.getAttribute('data-version');
          if (confirm(`Roll back entity visual descriptor to version v${v}? This will overwrite active features with this verified snapshot.`)) {
            await rollbackDescriptor(entityId, v, modal);
          }
        });
      });
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
      alert(`Rollback failed: ${err.message}`);
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

  // =========================================================================
  // 5. Real-Time Telemetry Toast Dispatcher
  // =========================================================================
  function checkAlertEvents(alerts) {
    if (!alerts || !Array.isArray(alerts)) return;

    alerts.forEach(ev => {
      const evId = ev.id || `${ev.event_type}_${ev.timestamp}_${ev.track_id || ''}`;
      if (state.lastSeenAlertIds.has(evId)) return;
      state.lastSeenAlertIds.add(evId);

      if (ev.event_type === 'review_item_queued') {
        const sim = (ev.similarity || 0) * 100;
        showToast(
          '🧠 Review Candidate Queued',
          `Borderline match (${sim.toFixed(1)}%) for track #${ev.track_id} (${ev.camera_id}).`,
          'review',
          'Review Candidate',
          () => {
            const btn = document.getElementById('tab-btn-review');
            if (btn) btn.click();
          }
        );
        // Refresh queue
        loadReviewQueue(state.currentReviewStatus);
      } else if (ev.event_type === 'rsac_violation') {
        showToast(
          '🚨 Access Control Violation',
          `${ev.entity_name || 'Entity'} unauthorized in zone '${ev.zone_id}' (${ev.camera_id}).`,
          'alert',
          'View Alerts',
          () => {
            const btn = document.getElementById('tab-btn-alerts');
            if (btn) btn.click();
          }
        );
      }
    });

    // Cap cache size
    if (state.lastSeenAlertIds.size > 200) {
      const arr = Array.from(state.lastSeenAlertIds).slice(-100);
      state.lastSeenAlertIds = new Set(arr);
    }
  }

  // =========================================================================
  // Initialization & Filter Bindings
  // =========================================================================
  document.addEventListener('DOMContentLoaded', () => {
    initUniversalEnrollment();
    initReassignModal();
    initVersionsModal();

    // Review status filters
    document.querySelectorAll('.review-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.review-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const st = btn.getAttribute('data-status');
        loadReviewQueue(st);
      });
    });

    document.getElementById('btn-refresh-review-queue')?.addEventListener('click', () => {
      loadReviewQueue(state.currentReviewStatus);
    });

    // Check initial queue count
    loadReviewQueue('pending');
  });

  // Expose API for app.js
  window.ReviewAndRSAC = {
    loadQueue: loadReviewQueue,
    openVersionsModal: openVersionsModal,
    checkAlertEvents: checkAlertEvents,
    showToast: showToast,
  };
})();
