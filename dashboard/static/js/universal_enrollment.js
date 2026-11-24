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
    mergeEntityId: null,
    forceCreateNew: false,
  };

  function escapeHtml(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : ''; }
  function showToast(title, body, type = 'info') { if (typeof window.showToast === 'function') window.showToast(title, body, type); else alert(`${title}: ${body}`); }

  async function loadCategoriesDropdown(selectElem) {
    if (!selectElem) return;
    if (window.CategoryBadgeManager?.fetchCategories) {
      await window.CategoryBadgeManager.fetchCategories();
      window.CategoryBadgeManager.syncSelect(selectElem);
      return;
    }
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

  async function populateCameraSelect(options = {}) {
    const camSelect = document.getElementById('enroll-camera-select');
    if (!camSelect) return;
    let cams = window.CameraManager?.getActiveCameras?.() || [];
    let videos = [];
    try {
      const fetches = [!cams.length ? fetch('/api/cameras') : Promise.resolve(null), fetch('/api/videos')];
      const [camRes, vidRes] = await Promise.all(fetches);
      if (camRes?.ok) cams = await camRes.json();
      if (vidRes?.ok) {
        const vData = await vidRes.json();
        videos = Array.isArray(vData) ? vData : (Array.isArray(vData?.videos) ? vData.videos : []);
      }
    } catch (e) { console.warn('Failed to load enrollment sources:', e); }
    const activeId = window.App?.getActiveCameraId?.() || '';
    const preferred = window.EnrollmentStageController?.resolvePreferredSource?.(cams, videos, activeId, options) || activeId;
    const camOpts = (Array.isArray(cams) ? cams : []).map(c =>
      `<option value="${escapeHtml(c.id)}" ${c.id === preferred ? 'selected' : ''}>${escapeHtml(c.name || c.id)} (${escapeHtml(c.id)})</option>`
    ).join('');
    const vidOpts = videos.map(v => {
      const fn = v.filename || v.name || '';
      const url = v.video_url || `/videos/${encodeURIComponent(fn)}`;
      const fps = Number(v.fps) || 30;
      return `<option value="video:${escapeHtml(fn)}" data-video-url="${escapeHtml(url)}" data-fps="${fps}" ${preferred === `video:${fn}` ? 'selected' : ''}>${escapeHtml(fn)}</option>`;
    }).join('');
    camSelect.innerHTML = '<option value="">Image Upload Only (No Camera)</option>'
      + (camOpts ? `<optgroup label="Camera Profiles">${camOpts}</optgroup>` : '')
      + (vidOpts ? `<optgroup label="Recorded Videos">${vidOpts}</optgroup>` : '');
    if (preferred) camSelect.value = preferred;
    window.EnrollmentStageController?.updateSourceBadge?.(camSelect.value);
  }

  function resetEnrollmentState(form, canvas, placeholder) {
    enrollState.freezeFrameImg = null;
    enrollState.freezeFrameDataUrl = null;
    enrollState.selectedBbox = null;
    enrollState.selectedCropBase64 = null;
    enrollState.mergeEntityId = null;
    enrollState.forceCreateNew = false;
    window.ScrubberTimelineSlider?.hideEnrollmentScrubber?.(canvas);
    if (form?.reset) form.reset();
    const banner = document.getElementById('enroll-collision-banner');
    if (banner) { banner.style.display = 'none'; banner.innerHTML = ''; }
    const previewBox = document.getElementById('enroll-crop-preview-box');
    if (previewBox) previewBox.style.display = 'none';
    if (canvas) canvas.style.display = 'none';
    if (placeholder) placeholder.style.display = 'block';
  }

  async function captureFreezeFrame(canvas, placeholder) {
    const camSelect = document.getElementById('enroll-camera-select');
    const camId = camSelect ? (camSelect.value || null) : (window.App?.getActiveCameraId?.() || null);
    window.EnrollmentStageController?.updateSourceBadge?.(camId);
    if (camId && camId.startsWith('video:')) {
      const opt = camSelect?.options?.[camSelect.selectedIndex];
      const url = opt?.getAttribute?.('data-video-url') || `/videos/${encodeURIComponent(camId.slice(6))}`;
      const fps = Number(opt?.getAttribute?.('data-fps')) || 30;
      window.ScrubberTimelineSlider?.mountEnrollmentScrubber?.(url, canvas, placeholder, (dataUrl) => loadFreezeImage(dataUrl, canvas, placeholder), { fps });
      return;
    }
    window.ScrubberTimelineSlider?.hideEnrollmentScrubber?.(canvas);
    if (!camId) {
      if (placeholder) placeholder.innerHTML = '<span style="color:#ef4444;">No active camera selected.</span>';
      return;
    }
    if (placeholder) { placeholder.style.display = 'block'; placeholder.innerHTML = 'Capturing live freeze-frame...'; }
    if (canvas) canvas.style.display = 'none';
    try {
      const res = await fetch(`/api/cameras/${encodeURIComponent(camId)}/freeze_frame`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      loadFreezeImage(data.image_base64, canvas, placeholder);
    } catch (err) {
      if (placeholder) placeholder.innerHTML = `<span style="color:#ef4444;">Failed to capture frame: ${escapeHtml(err.message)}</span>`;
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
      const x = Math.round(Math.min(startX, pt.x)), y = Math.round(Math.min(startY, pt.y));
      const w = Math.round(Math.abs(pt.x - startX)), h = Math.round(Math.abs(pt.y - startY));
      if (w > 15 && h > 15) { enrollState.selectedBbox = [x, y, w, h]; extractCropThumbnail(x, y, w, h); }
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
    const rawCamId = camSelect ? (camSelect.value || null) : (window.App?.getActiveCameraId?.() || null);
    const meta = window.EnrollmentStageController?.getSelectedSourceMeta?.(camSelect) || { camera_id: rawCamId && rawCamId.startsWith('video:') ? null : rawCamId, video_filename: rawCamId?.startsWith('video:') ? rawCamId.slice(6) : null, media_offset_sec: null };
    const camera_id = meta.camera_id;
    const is_anchor = document.getElementById('enroll-locked-anchor-cb')?.checked ?? true;
    const notes = (document.getElementById('enroll-notes-input')?.value || '').trim();
    if (!camera_id && !meta.video_filename && !enrollState.selectedCropBase64) {
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
      video_filename: meta.video_filename, media_offset_sec: meta.media_offset_sec,
      crop_base64: enrollState.selectedCropBase64, bbox: enrollState.selectedBbox,
      merge_entity_id: enrollState.mergeEntityId, force_create_new: enrollState.forceCreateNew,
    };
  }

  async function runCollisionGuard(payload, form, modal, canvas, placeholder) {
    if (enrollState.mergeEntityId || enrollState.forceCreateNew) return false;
    try {
      const cRes = await fetch('/api/enroll/check-collision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ camera_id: payload.camera_id, bbox: payload.bbox, crop_base64: payload.crop_base64 }) });
      const col = cRes.ok ? await cRes.json() : null;
      const top = col?.has_collision ? col.matches?.[0] : null;
      const banner = top ? document.getElementById('enroll-collision-banner') : null;
      if (!banner) return false;
      banner.style.display = 'block';
      banner.innerHTML = `<strong>Possible duplicate:</strong> ${escapeHtml(top.name)} (${Math.round(top.similarity * 100)}%) <button type="button" class="btn btn-xs btn-primary" id="btn-enroll-merge-existing">Merge into ${escapeHtml(top.name)}</button> <button type="button" class="btn btn-xs btn-outline" id="btn-enroll-create-new">Create New</button>`;
      document.getElementById('btn-enroll-merge-existing')?.addEventListener('click', () => { enrollState.mergeEntityId = top.entity_id; banner.style.display = 'none'; submitEnrollment(form, modal, canvas, placeholder); });
      document.getElementById('btn-enroll-create-new')?.addEventListener('click', () => { enrollState.forceCreateNew = true; banner.style.display = 'none'; submitEnrollment(form, modal, canvas, placeholder); });
      return true;
    } catch (e) { console.warn('Collision check skipped:', e); return false; }
  }

  async function submitEnrollment(form, modal, canvas, placeholder) {
    const payload = buildEnrollmentPayload();
    if (!payload || await runCollisionGuard(payload, form, modal, canvas, placeholder)) return;
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

  async function openModal(options = {}) {
    const modal = document.getElementById('modal-universal-enrollment');
    const canvas = document.getElementById('enroll-bbox-canvas');
    const placeholder = document.getElementById('enroll-canvas-placeholder');
    const form = document.getElementById('universal-enrollment-form');
    const categorySelect = document.getElementById('enroll-category-select');
    if (!modal) return;
    resetEnrollmentState(form, canvas, placeholder);
    modal.style.display = 'flex';
    await Promise.all([loadCategoriesDropdown(categorySelect), populateCameraSelect(options)]);
    const camSelect = document.getElementById('enroll-camera-select');
    const camId = camSelect ? (camSelect.value || null) : (window.App?.getActiveCameraId?.() || null);
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
    document.getElementById('enroll-camera-select')?.addEventListener('change', (e) => {
      if (e.target.value) captureFreezeFrame(canvas, placeholder);
      else resetEnrollmentState(null, canvas, placeholder);
    });
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

