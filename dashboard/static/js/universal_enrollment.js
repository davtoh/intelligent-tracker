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
        selectElem.innerHTML = cats.map(c => 
          `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)} (${escapeHtml(c.id)})</option>`
        ).join('');
      }
    } catch (e) {
      console.warn('Failed to load RSAC categories:', e);
    }
  }

  async function captureFreezeFrame(canvas, placeholder) {
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

  function bindCanvasSelection(canvas) {
    if (!canvas) return;
    let isDrawing = false;
    let startX = 0, startY = 0;

    canvas.addEventListener('mousedown', (e) => {
      if (!enrollState.freezeFrameImg) return;
      isDrawing = true;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      startX = (e.clientX - rect.left) * scaleX;
      startY = (e.clientY - rect.top) * scaleY;
    });

    canvas.addEventListener('mousemove', (e) => {
      if (!isDrawing || !enrollState.freezeFrameImg) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const curX = (e.clientX - rect.left) * scaleX;
      const curY = (e.clientY - rect.top) * scaleY;

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(enrollState.freezeFrameImg, 0, 0);

      const x = Math.min(startX, curX);
      const y = Math.min(startY, curY);
      const w = Math.abs(curX - startX);
      const h = Math.abs(curY - startY);

      ctx.strokeStyle = '#06b6d4';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = 'rgba(6, 182, 212, 0.15)';
      ctx.fillRect(x, y, w, h);
    });

    canvas.addEventListener('mouseup', (e) => {
      if (!isDrawing || !enrollState.freezeFrameImg) return;
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

  function bindEnrollmentForm(form, modal) {
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = (document.getElementById('enroll-name-input')?.value || '').trim();
      const category = document.getElementById('enroll-category-select')?.value || 'person';
      const role = (document.getElementById('enroll-role-input')?.value || '').trim();
      const camSelect = document.getElementById('enroll-camera-select');
      const camId = camSelect ? camSelect.value : 'cam_01';
      const isAnchor = document.getElementById('enroll-locked-anchor-cb')?.checked ?? true;
      const notes = (document.getElementById('enroll-notes-input')?.value || '').trim();

      if (!name) {
        showToast('Validation Required', 'Please enter an entity name.', 'warning');
        return;
      }
      if (!enrollState.selectedCropBase64 && !enrollState.selectedBbox) {
        showToast('Selection Required', 'Please drag a bounding box on the freeze-frame image.', 'warning');
        return;
      }

      const submitBtn = document.getElementById('btn-submit-enrollment');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Extracting Biometrics...';
      }

      try {
        const payload = {
          name, category, security_role: role, notes,
          is_anchor: isAnchor, camera_id: camId,
          crop_base64: enrollState.selectedCropBase64,
          bbox: enrollState.selectedBbox,
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
        if (modal) modal.style.display = 'none';
        form.reset();
        showToast('Enrollment Successful', `"${name}" enrolled as ${category.toUpperCase()} (ID #${result.entity_id})!`, 'success');

        if (typeof window.loadGallery === 'function') window.loadGallery();
      } catch (err) {
        showToast('Enrollment Failed', err.message, 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = '✨ Enroll & Lock Anchor';
        }
      }
    });
  }

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
    const form = document.getElementById('universal-enrollment-form');
    const categorySelect = document.getElementById('enroll-category-select');

    if (!modal) return;

    if (openBtn) {
      openBtn.addEventListener('click', async () => {
        modal.style.display = 'flex';
        await loadCategoriesDropdown(categorySelect);
        captureFreezeFrame(canvas, placeholder);
      });
    }

    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });

    if (captureFreezeBtn) {
      captureFreezeBtn.addEventListener('click', () => captureFreezeFrame(canvas, placeholder));
    }

    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (re) => loadFreezeImage(re.target.result, canvas, placeholder);
        reader.readAsDataURL(file);
      });
    }

    bindCanvasSelection(canvas);
    bindEnrollmentForm(form, modal);
  }

  window.UniversalEnrollment = {
    init: initUniversalEnrollment,
    captureFreezeFrame: captureFreezeFrame,
    loadFreezeImage: loadFreezeImage,
  };
})();

