/**
 * Intelligent Tracker - Universal Artifact & Face Freeze-Frame Enrollment Submodule.
 * Handles live freeze-frame video acquisition, canvas bounding box selection,
 * and dual-model Re-ID feature extraction.
 */

(function () {
  'use strict';

  const enrollState = {
    freezeFrameImg: null,
    freezeFrameDataUrl: null,
    selectedBbox: null,
    selectedCropBase64: null,
  };

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

  async function loadCategoriesDropdown(selectElem) {
    if (!selectElem) return;
    try {
      const res = await fetch('/api/rsac/categories');
      if (res.ok) {
        const cats = await res.json();
        if (Array.isArray(cats) && cats.length > 0) {
          selectElem.innerHTML = cats.map(c =>
            `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)} (${escapeHtml(c.id)})</option>`
          ).join('');
        }
      }
    } catch (e) {
      console.warn('Failed to load RSAC categories:', e);
    }
  }

  async function populateCameraSelect() {
    const camSelect = document.getElementById('enroll-camera-select');
    if (!camSelect) return;
    let cams = window.CameraManager?.getActiveCameras?.() || [];
    if (!cams.length) {
      try {
        const res = await fetch('/api/cameras');
        if (res.ok) cams = await res.json();
      } catch (e) {
        console.warn('Failed to load cameras for enrollment:', e);
      }
    }
    const activeId = window.App?.getActiveCameraId?.() || '';
    const opts = ['<option value="">Image Upload Only (No Camera)</option>'].concat(
      (Array.isArray(cams) ? cams : []).map(c =>
        `<option value="${escapeHtml(c.id)}" ${c.id === activeId ? 'selected' : ''}>${escapeHtml(c.name || c.id)} (${escapeHtml(c.id)})</option>`
      )
    );
    camSelect.innerHTML = opts.join('');
    if (activeId) camSelect.value = activeId;
  }

  function resetEnrollmentState(form, canvas, placeholder) {
    enrollState.freezeFrameImg = null;
    enrollState.freezeFrameDataUrl = null;
    enrollState.selectedBbox = null;
    enrollState.selectedCropBase64 = null;
    if (form?.reset) form.reset();
    const previewBox = document.getElementById('enroll-crop-preview-box');
    if (previewBox) previewBox.style.display = 'none';
    if (canvas) canvas.style.display = 'none';
    if (placeholder) placeholder.style.display = 'block';
  }

  async function captureFreezeFrame(canvas, placeholder) {
    const camSelect = document.getElementById('enroll-camera-select');
    const camId = camSelect?.value || window.App?.getActiveCameraId?.() || null;
    if (!camId) {
      if (placeholder) placeholder.innerHTML = '<span style="color:#ef4444;">No active camera selected.</span>';
      return;
    }

    if (placeholder) {
      placeholder.style.display = 'block';
      placeholder.innerHTML = 'Capturing live freeze-frame...';
    }
    if (canvas) canvas.style.display = 'none';

    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      loadFreezeImage(data.image_base64, canvas, placeholder);
    } catch (err) {
      if (placeholder) {
        placeholder.innerHTML = `<span style="color:#ef4444;">Failed to capture frame: ${escapeHtml(err.message)}</span>`;
      }
    }
  }

  function loadFreezeImage(dataUrl, canvas, placeholder) {
    enrollState.freezeFrameDataUrl = dataUrl;
    const img = new Image();
    img.onload = () => {
      enrollState.freezeFrameImg = img;
      if (canvas) {
        canvas.width = img.naturalWidth || 640;
        canvas.height = img.naturalHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        canvas.style.display = 'block';
      }
      if (placeholder) placeholder.style.display = 'none';
      enrollState.selectedBbox = null;
      enrollState.selectedCropBase64 = null;
      const previewBox = document.getElementById('enroll-crop-preview-box');
      if (previewBox) previewBox.style.display = 'none';
    };
    img.src = dataUrl;
  }

  function getCanvasPoint(canvas, e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function drawSelectionOverlay(canvas, x, y, w, h) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(enrollState.freezeFrameImg, 0, 0);
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = 'rgba(6, 182, 212, 0.15)';
    ctx.fillRect(x, y, w, h);
  }

  function bindCanvasSelection(canvas) {
    if (!canvas) return;
    let isDrawing = false;
    let startX = 0;
    let startY = 0;
    canvas.addEventListener('mousedown', (e) => {
      if (!enrollState.freezeFrameImg) return;
      isDrawing = true;
      const pt = getCanvasPoint(canvas, e);
      startX = pt.x;
      startY = pt.y;
    });
    canvas.addEventListener('mousemove', (e) => {
      if (!isDrawing || !enrollState.freezeFrameImg) return;
      const pt = getCanvasPoint(canvas, e);
      drawSelectionOverlay(canvas, Math.min(startX, pt.x), Math.min(startY, pt.y), Math.abs(pt.x - startX), Math.abs(pt.y - startY));
    });
    canvas.addEventListener('mouseup', (e) => {
      if (!isDrawing || !enrollState.freezeFrameImg) return;
      isDrawing = false;
      const pt = getCanvasPoint(canvas, e);
      const x = Math.round(Math.min(startX, pt.x));
      const y = Math.round(Math.min(startY, pt.y));
      const w = Math.round(Math.abs(pt.x - startX));
      const h = Math.round(Math.abs(pt.y - startY));
      if (w > 15 && h > 15) {
        enrollState.selectedBbox = [x, y, w, h];
        extractCropThumbnail(x, y, w, h);
      }
    });
  }

  function extractCropThumbnail(x, y, w, h) {
    if (!enrollState.freezeFrameImg) return;
    const cropCanvas = document.createElement('canvas');
    cropCanvas.width = w;
    cropCanvas.height = h;
    const cctx = cropCanvas.getContext('2d');
    cctx.drawImage(enrollState.freezeFrameImg, x, y, w, h, 0, 0, w, h);
    const cropData = cropCanvas.toDataURL('image/jpeg', 0.9);
    enrollState.selectedCropBase64 = cropData;

    const previewBox = document.getElementById('enroll-crop-preview-box');
    const previewImg = document.getElementById('enroll-crop-preview-img');
    const previewMeta = document.getElementById('enroll-crop-meta');

    if (previewBox && previewImg) {
      previewImg.src = cropData;
      previewBox.style.display = 'flex';
      if (previewMeta) previewMeta.textContent = `Region: ${w}x${h} px at (${x}, ${y})`;
    }
  }

  function buildEnrollmentPayload() {
    const name = (document.getElementById('enroll-name-input')?.value || '').trim();
    const category = document.getElementById('enroll-category-select')?.value || 'person';
    const security_role = (document.getElementById('enroll-role-input')?.value || '').trim();
    const camSelect = document.getElementById('enroll-camera-select');
    const camera_id = camSelect?.value || window.App?.getActiveCameraId?.() || null;
    const is_anchor = document.getElementById('enroll-locked-anchor-cb')?.checked ?? true;
    const notes = (document.getElementById('enroll-notes-input')?.value || '').trim();
    if (!camera_id && !enrollState.selectedCropBase64) {
      showToast('Camera Required', 'Please select an active camera source or upload an image.', 'warning');
      return null;
    }
    if (!name) {
      showToast('Validation Required', 'Please enter an entity name.', 'warning');
      return null;
    }
    if (!enrollState.selectedCropBase64 && !enrollState.selectedBbox) {
      showToast('Selection Required', 'Please drag a bounding box on the freeze-frame image.', 'warning');
      return null;
    }
    return {
      name, category, security_role, notes, is_anchor, camera_id,
      crop_base64: enrollState.selectedCropBase64,
      bbox: enrollState.selectedBbox,
    };
  }

  async function submitEnrollment(form, modal, canvas, placeholder) {
    const payload = buildEnrollmentPayload();
    if (!payload) return;
    const submitBtn = document.getElementById('btn-submit-enrollment');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Extracting Biometrics...'; }
    try {
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
      if (modal) modal.style.display = 'none';
      resetEnrollmentState(form, canvas, placeholder);
      showToast('Enrollment Successful', `"${payload.name}" enrolled as ${payload.category.toUpperCase()} (ID #${result.entity_id})!`, 'success');
      if (typeof window.loadGallery === 'function') window.loadGallery();
    } catch (err) {
      showToast('Enrollment Failed', err.message, 'error');
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '✨ Enroll & Lock Anchor'; }
    }
  }

  function bindEnrollmentForm(form, modal, canvas, placeholder) {
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await submitEnrollment(form, modal, canvas, placeholder);
    });
  }

  async function openModal() {
    const modal = document.getElementById('modal-universal-enrollment');
    const canvas = document.getElementById('enroll-bbox-canvas');
    const placeholder = document.getElementById('enroll-canvas-placeholder');
    const form = document.getElementById('universal-enrollment-form');
    const categorySelect = document.getElementById('enroll-category-select');
    if (!modal) return;
    resetEnrollmentState(form, canvas, placeholder);
    modal.style.display = 'flex';
    await Promise.all([loadCategoriesDropdown(categorySelect), populateCameraSelect()]);
    const camId = document.getElementById('enroll-camera-select')?.value || window.App?.getActiveCameraId?.();
    if (camId) await captureFreezeFrame(canvas, placeholder);
  }

  function initUniversalEnrollment() {
    const modal = document.getElementById('modal-universal-enrollment');
    const canvas = document.getElementById('enroll-bbox-canvas');
    const placeholder = document.getElementById('enroll-canvas-placeholder');
    const form = document.getElementById('universal-enrollment-form');
    const fileInput = document.getElementById('enroll-file-input');
    if (!modal) return;

    const closeModal = () => {
      modal.style.display = 'none';
      resetEnrollmentState(form, canvas, placeholder);
    };
    document.getElementById('btn-open-enrollment')?.addEventListener('click', openModal);
    document.getElementById('modal-enroll-close')?.addEventListener('click', closeModal);
    document.getElementById('modal-enroll-cancel')?.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
    document.getElementById('btn-capture-freeze')?.addEventListener('click', () => captureFreezeFrame(canvas, placeholder));
    document.getElementById('btn-upload-enroll-crop')?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (re) => loadFreezeImage(re.target.result, canvas, placeholder);
      reader.readAsDataURL(file);
    });
    bindCanvasSelection(canvas);
    bindEnrollmentForm(form, modal, canvas, placeholder);
  }

  window.UniversalEnrollment = {
    init: initUniversalEnrollment,
    openModal: openModal,
    captureFreezeFrame: captureFreezeFrame,
    loadFreezeImage: loadFreezeImage,
    populateCameraSelect: populateCameraSelect,
    resetEnrollmentState: resetEnrollmentState,
  };
})();

