/**
 * Intelligent Tracker - Interactive Canvas & Click-to-Tag Submodule.
 * Handles video aspect-ratio scaling, bounding box hit testing, and operator identity enrollment.
 */

(function () {
  'use strict';

  function syncCanvasSize(videoImg, canvas) {
    if (!videoImg || !canvas) return;
    const imgW = videoImg.clientWidth;
    const imgH = videoImg.clientHeight;
    if (!imgW || !imgH) return;

    const natW = videoImg.naturalWidth || 640;
    const natH = videoImg.naturalHeight || 480;
    const imgRatio = natW / natH;
    const elemRatio = imgW / imgH;

    let renderW, renderH, offsetX, offsetY;
    if (elemRatio > imgRatio) {
      renderH = imgH;
      renderW = renderH * imgRatio;
      offsetX = (imgW - renderW) / 2;
      offsetY = 0;
    } else {
      renderW = imgW;
      renderH = renderW / imgRatio;
      offsetX = 0;
      offsetY = (imgH - renderH) / 2;
    }

    const left = (videoImg.offsetLeft || 0) + offsetX;
    const top = (videoImg.offsetTop || 0) + offsetY;
    const pixelW = Math.round(renderW);
    const pixelH = Math.round(renderH);

    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }

    canvas.style.left = `${left}px`;
    canvas.style.top = `${top}px`;
    canvas.style.width = `${renderW}px`;
    canvas.style.height = `${renderH}px`;
  }

  function drawInteractiveOverlay(ctx, canvas, videoImg, tracks, hoveredTrack) {
    if (!ctx || !canvas) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!videoImg?.naturalWidth || !canvas.width) return;

    const scaleX = canvas.width / videoImg.naturalWidth;
    const scaleY = canvas.height / videoImg.naturalHeight;

    (tracks || []).forEach(trk => {
      const [bx, by, bw, bh] = trk.bbox;
      const x = bx * scaleX;
      const y = by * scaleY;
      const w = bw * scaleX;
      const h = bh * scaleY;

      if (hoveredTrack && hoveredTrack.id === trk.id) {
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 3;
        ctx.shadowColor = '#06b6d4';
        ctx.shadowBlur = 12;
        ctx.strokeRect(x, y, w, h);
        ctx.shadowBlur = 0;

        ctx.fillStyle = 'rgba(6, 182, 212, 0.12)';
        ctx.fillRect(x, y, w, h);
      }
    });
  }

  function findHoveredTrack(mx, my, canvas, videoImg, tracks) {
    if (!videoImg?.naturalWidth) return null;
    const scaleX = canvas.width / videoImg.naturalWidth;
    const scaleY = canvas.height / videoImg.naturalHeight;

    for (const trk of (tracks || [])) {
      const [bx, by, bw, bh] = trk.bbox;
      const x = bx * scaleX;
      const y = by * scaleY;
      const w = bw * scaleX;
      const h = bh * scaleY;
      if (mx >= x && mx <= x + w && my >= y && my <= y + h) {
        return trk;
      }
    }
    return null;
  }

  function updateTooltipPosition(track, canvas, videoImg) {
    const tooltip = document.getElementById('track-tooltip');
    const title = document.getElementById('tooltip-title');
    const body = document.getElementById('tooltip-body');
    if (!tooltip || !track || !videoImg?.naturalWidth) return;

    const scaleX = canvas.width / videoImg.naturalWidth;
    const scaleY = canvas.height / videoImg.naturalHeight;
    const [bx, by] = track.bbox;
    const x = bx * scaleX;
    const y = by * scaleY;

    tooltip.style.display = 'block';
    const cLeft = parseFloat(canvas.style.left) || canvas.offsetLeft || 0;
    const cTop = parseFloat(canvas.style.top) || canvas.offsetTop || 0;
    tooltip.style.left = `${Math.min(cLeft + canvas.width - 180, Math.max(cLeft + 10, cLeft + x))}px`;
    tooltip.style.top = `${Math.max(cTop + 10, cTop + y - 70)}px`;

    if (title) title.textContent = track.entity_name || `Track #${track.id}`;
    if (body) {
      body.textContent = `Conf: ${(track.confidence * 100).toFixed(0)}% | Dwell: ${track.dwell_time}s | State: ${track.state}`;
    }
  }

  function openTagModal(track) {
    const modalTag = document.getElementById('modal-tag-entity');
    const tagTrackId = document.getElementById('tag-track-id');
    const tagBboxVal = document.getElementById('tag-bbox-val');
    const tagNameInput = document.getElementById('tag-name-input');
    const tagCategorySelect = document.getElementById('tag-category-select');
    const title = document.getElementById('tag-modal-title');
    if (!modalTag) return;

    modalTag.style.display = 'flex';
    if (track) {
      if (tagTrackId) tagTrackId.value = track.id;
      if (tagBboxVal) tagBboxVal.value = JSON.stringify(track.bbox);
      if (tagNameInput) tagNameInput.value = track.entity_name || '';
      if (tagCategorySelect) tagCategorySelect.value = track.category || 'person';
      if (title) title.textContent = `🏷️ Tag Active Track #${track.id}`;
    } else {
      if (tagTrackId) tagTrackId.value = '';
      if (tagBboxVal) tagBboxVal.value = '';
      if (tagNameInput) tagNameInput.value = '';
      if (tagCategorySelect) tagCategorySelect.value = 'person';
      if (title) title.textContent = '🏷️ Enroll New Identity';
    }
    tagNameInput?.focus();
  }

  function closeTagModal() {
    const modalTag = document.getElementById('modal-tag-entity');
    const tagForm = document.getElementById('tag-entity-form');
    if (modalTag) modalTag.style.display = 'none';
    if (tagForm) tagForm.reset();
  }

  function initTagModal(getActiveCameraId) {
    const tagForm = document.getElementById('tag-entity-form');
    document.getElementById('modal-tag-close')?.addEventListener('click', closeTagModal);
    document.getElementById('modal-tag-cancel')?.addEventListener('click', closeTagModal);

    if (tagForm) {
      tagForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = (document.getElementById('tag-name-input')?.value || '').trim();
        const category = document.getElementById('tag-category-select')?.value || 'person';
        const notes = (document.getElementById('tag-notes-input')?.value || '').trim();
        const trackIdVal = document.getElementById('tag-track-id')?.value;
        const bboxVal = document.getElementById('tag-bbox-val')?.value;

        if (!name) return;

        try {
          const res = await fetch('/tag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              entity_name: name,
              category: category,
              track_id: trackIdVal ? parseInt(trackIdVal, 10) : null,
              bbox: bboxVal ? JSON.parse(bboxVal) : null,
              notes: notes,
              camera_id: getActiveCameraId?.() || 'cam_01',
            }),
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Tagging failed');
          }
          closeTagModal();
          window.showToast?.('Entity Enrolled', `Successfully enrolled "${name}" as ${category.toUpperCase()}!`, 'success');
        } catch (err) {
          window.showToast?.('Enrollment Failed', err.message, 'error');
        }
      });
    }
  }

  window.InteractiveCanvas = {
    syncSize: syncCanvasSize,
    drawOverlay: drawInteractiveOverlay,
    findHoveredTrack: findHoveredTrack,
    updateTooltip: updateTooltipPosition,
    openTagModal: openTagModal,
    closeTagModal: closeTagModal,
    initTagModal: initTagModal,
  };
})();

