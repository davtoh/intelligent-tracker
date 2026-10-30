/**
 * Intelligent Tracker - Universal Biometric Enrollment Controller.
 * Handles live freeze-frame capture, bounding box crop selection, and anchor locking.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  const showToast = window.showToast || ((m, t) => console.log(m, t));

  const state = {
    freezeFrameDataUrl: null,
    freezeFrameImg: null,
    selectedBbox: null,
    selectedCropBase64: null,
    customCategories: [],
  };

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

    if (canvas) {
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
    }

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
          showToast('Validation Required', 'Please enter an entity name.', 'warning');
          return;
        }

        if (!state.selectedCropBase64 && !state.selectedBbox) {
          showToast('Selection Required', 'Please drag a bounding box on the freeze-frame image to select the entity crop.', 'warning');
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

          if (window.TrackerApp.Gallery?.load) {
            window.TrackerApp.Gallery.load();
          }
        } catch (err) {
          showToast('Enrollment Failed', err.message, 'error');
        } finally {
          submitBtn.disabled = false;
          submitBtn.textContent = '✨ Enroll & Lock Anchor';
        }
      });
    }
  }

  window.TrackerApp.Enrollment = {
    init: initUniversalEnrollment,
  };
})();

