/**
 * Intelligent Tracker - Interactive Canvas & Click-to-Tag Submodule.
 * Handles video aspect-ratio scaling, bounding box hit testing, and AI ROI enrollment.
 */
(function () {
  'use strict';

  let activeCameraGetter = null;
  let lastRoiPointerMs = 0;
  let recognitionSeq = 0;
  let categoryTouched = false;
  let latestState = { ctx: null, canvas: null, videoImg: null, tracks: [], hoveredTrack: null, sceneExtras: {} };
  const el = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

  function getCssDimensions(canvas) {
    return { width: parseFloat(canvas?.style?.width) || canvas?.clientWidth || canvas?.width || 0, height: parseFloat(canvas?.style?.height) || canvas?.clientHeight || canvas?.height || 0 };
  }
  function readLiveOverlayVisibility() {
    const defaults = window.UnifiedCanvasOverlay?.DEFAULT_VISIBILITY || { bboxes: true, track_ids: true, dwell_timers: true, velocity: false, zones: true, tripwires: true, heatmap: false };
    const vis = {};
    Object.keys(defaults).forEach((k) => { const n = el(`overlay-toggle-${k}`); vis[k] = n ? Boolean(n.checked) : defaults[k]; });
    if (window.LivePlayer?.isBurnedAnnotationMode?.()) { vis.bboxes = false; vis.track_ids = false; vis.dwell_timers = false; vis.velocity = false; }
    return vis;
  }
  function syncCanvasSize(videoImg, canvas) {
    if (!videoImg || !canvas || !videoImg.clientWidth || !videoImg.clientHeight) return;
    const overlay = window.UnifiedCanvasOverlay;
    const elemRect = typeof videoImg.getBoundingClientRect === 'function' ? videoImg.getBoundingClientRect() : { left: videoImg.offsetLeft || 0, top: videoImg.offsetTop || 0, width: videoImg.clientWidth, height: videoImg.clientHeight };
    const containerRect = typeof videoImg.parentElement?.getBoundingClientRect === 'function' ? videoImg.parentElement.getBoundingClientRect() : { left: 0, top: 0 };
    const box = overlay.computeContainBox(elemRect, containerRect, videoImg.naturalWidth || 640, videoImg.naturalHeight || 480);
    overlay.syncCanvasDpr(canvas, typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null, box.renderW, box.renderH);
    canvas.style.left = `${box.offsetX}px`; canvas.style.top = `${box.offsetY}px`;
  }
  function drawInteractiveOverlay(ctx, canvas, videoImg, tracks, hoveredTrack, sceneExtras = {}) {
    latestState = { ctx, canvas, videoImg, tracks: tracks || [], hoveredTrack: hoveredTrack || null, sceneExtras: sceneExtras || {} };
    if (!ctx || !canvas) return;
    const { width: cssW, height: cssH } = getCssDimensions(canvas);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!videoImg?.naturalWidth || !cssW || !cssH) return;
    const overlay = window.UnifiedCanvasOverlay;
    const scales = overlay.resolveScaleFactors(cssW, cssH, sceneExtras?.sourceRes, videoImg.naturalWidth, videoImg.naturalHeight);
    overlay.renderScene(ctx, {
      clear: false, clearWidth: cssW, clearHeight: cssH,
      transform: { offsetX: 0, offsetY: 0, scaleX: scales.scaleX, scaleY: scales.scaleY, renderW: cssW, renderH: cssH },
      visibility: readLiveOverlayVisibility(), tracks: latestState.tracks, hoveredTrack: latestState.hoveredTrack,
      zones: sceneExtras?.zones || [], tripwires: sceneExtras?.tripwires || [], heatmap: sceneExtras?.heatmap || null,
    });
  }

  function getActiveScales(cssW, cssH, videoImg, sourceRes) {
    const u = window.UnifiedCanvasOverlay;
    return u?.resolveScaleFactors
      ? u.resolveScaleFactors(cssW, cssH, sourceRes, videoImg.naturalWidth, videoImg.naturalHeight)
      : { scaleX: cssW / videoImg.naturalWidth, scaleY: cssH / videoImg.naturalHeight };
  }

  function findHoveredTrack(mx, my, canvas, videoImg, tracks) {
    if (!videoImg?.naturalWidth) return null;
    const { width: cssW, height: cssH } = getCssDimensions(canvas);
    const { scaleX: sx, scaleY: sy } = getActiveScales(cssW, cssH, videoImg, latestState.sceneExtras?.sourceRes);
    for (const trk of (tracks || [])) {
      const [bx, by, bw, bh] = trk.bbox;
      if (mx >= bx * sx && mx <= (bx + bw) * sx && my >= by * sy && my <= (by + bh) * sy) return trk;
    }
    return null;
  }

  function updateTooltipPosition(track, canvas, videoImg) {
    const tooltip = el('track-tooltip');
    if (!tooltip || !track || !videoImg?.naturalWidth) return;
    const { width: cssW, height: cssH } = getCssDimensions(canvas);
    const { scaleX: sx, scaleY: sy } = getActiveScales(cssW, cssH, videoImg, latestState.sceneExtras?.sourceRes);
    const cLeft = parseFloat(canvas.style.left) || canvas.offsetLeft || 0;
    const cTop = parseFloat(canvas.style.top) || canvas.offsetTop || 0;
    tooltip.style.display = 'block';
    tooltip.style.left = `${Math.min(cLeft + cssW - 180, Math.max(cLeft + 10, cLeft + track.bbox[0] * sx))}px`;
    tooltip.style.top = `${Math.max(cTop + 10, cTop + track.bbox[1] * sy - 70)}px`;
    if (el('tooltip-title')) el('tooltip-title').textContent = track.entity_name || `Track #${track?.id ?? track?.track_id ?? ''}`;
    if (el('tooltip-body')) el('tooltip-body').textContent = `Conf: ${(track.confidence * 100).toFixed(0)}% | Dwell: ${track.dwell_time}s | State: ${track.state}`;
  }
  function mapClassToCategory(label) {
    const norm = String(label || '').trim().toLowerCase();
    if (!norm) return null;
    if (['car', 'truck', 'bus', 'motorcycle', 'vehicle'].includes(norm)) return 'vehicle';
    const opts = Array.from(el('tag-category-select')?.options || []).map((o) => o.value);
    if (opts.includes(norm)) return norm;
    return opts.find((v) => ['object', 'other', 'custom'].includes(v)) || opts[0] || 'object';
  }
  function renderCandidateChips(candidates) {
    const box = el('tag-identity-candidates');
    if (!box) return;
    box.innerHTML = '';
    if (!Array.isArray(candidates) || candidates.length === 0) {
      box.innerHTML = '<span style="font-size:11px;color:#94a3b8;">No gallery match — enter new identity below</span>';
      return;
    }
    candidates.forEach((cand) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-xs btn-outline candidate-chip';
      btn.dataset.entityId = String(cand.entity_id ?? '');
      btn.dataset.name = cand.name || '';
      btn.dataset.category = cand.category || 'person';
      btn.textContent = `${cand.name} (${Math.round((Number(cand.similarity) || 0) * 100)}%)`;
      btn.addEventListener('click', () => {
        if (el('tag-entity-id')) el('tag-entity-id').value = btn.dataset.entityId;
        if (el('tag-name-input')) el('tag-name-input').value = btn.dataset.name;
        if (el('tag-category-select') && btn.dataset.category) el('tag-category-select').value = btn.dataset.category;
        box.querySelectorAll('.candidate-chip').forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
      });
      window.TagFeedbackActions?.attachCandidateDiscourage?.(btn, cand, box, activeCameraGetter);
      box.appendChild(btn);
    });
  }

  async function runRoiRecognition(payload) {
    const panel = el('tag-roi-preview-panel'), badge = el('tag-ai-class-badge'), cropImg = el('tag-roi-crop-img');
    if (panel) panel.style.display = 'flex';
    if (badge) badge.textContent = 'AI: Analyzing...';
    if (cropImg) cropImg.src = payload?.cropBase64 || '';
    if (el('tag-identity-candidates')) el('tag-identity-candidates').innerHTML = '';
    const seq = ++recognitionSeq;
    try {
      const res = await fetch('/api/tag/recognize-roi', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          camera_id: payload?.sourceType === 'video' ? null : (payload?.cameraId || activeCameraGetter?.() || null),
          video_filename: payload?.videoFilename || null, timestamp_sec: payload?.timestampSec ?? null,
          bbox: payload?.bbox || payload?.track?.bbox || null, crop_base64: payload?.cropBase64 || null, top_k: 3,
        }),
      });
      if (!res.ok || seq !== recognitionSeq) { if (badge && seq === recognitionSeq) badge.textContent = 'AI: Ready for manual tag'; return; }
      const { data } = await res.json();
      if (!data || seq !== recognitionSeq) return;
      if (data.crop_base64) {
        if (cropImg) cropImg.src = data.crop_base64;
        if (el('tag-crop-base64')) el('tag-crop-base64').value = data.crop_base64;
      }
      const cls = data.classification || {};
      if (badge) badge.textContent = `AI: ${cls.label || 'object'} (${Math.round((Number(cls.confidence) || 0) * 100)}%)`;
      const mapped = !categoryTouched ? mapClassToCategory(cls.label) : null;
      if (mapped && el('tag-category-select')) el('tag-category-select').value = mapped;
      renderCandidateChips(data.candidates || []);
    } catch { if (badge && seq === recognitionSeq) badge.textContent = 'AI: Offline (manual tag)'; }
  }

  function openTagModal(track, options = {}) {
    if (!options.fromRoi && Date.now() - lastRoiPointerMs < 250) return;
    const modalTag = el('modal-tag-entity');
    if (!modalTag) return;
    window.CategoryBadgeManager?.syncSelect?.(el('tag-category-select'));
    categoryTouched = false;
    modalTag.style.display = 'flex';
    const bbox = options.bbox || track?.bbox || null;
    const trackId = track?.id ?? track?.track_id ?? '';
    const fields = {
      'tag-entity-id': '', 'tag-source-type': options.sourceType || 'live', 'tag-video-filename': options.videoFilename || '',
      'tag-timestamp-sec': options.timestampSec != null ? String(options.timestampSec) : '', 'tag-crop-base64': options.cropBase64 || '',
      'tag-track-id': trackId, 'tag-bbox-val': bbox ? JSON.stringify(bbox) : '',
      'tag-name-input': track?.entity_name || '', 'tag-category-select': track?.category || 'person',
    };
    Object.entries(fields).forEach(([id, val]) => { if (el(id)) el(id).value = val; });
    if (el('tag-modal-title')) el('tag-modal-title').textContent = options.title || (track ? `🏷️ Tag Active Track #${trackId}` : '🏷️ Enroll New Identity');
    if (el('tag-roi-preview-panel')) el('tag-roi-preview-panel').style.display = 'none';
    if (!options.skipRecognition && bbox) runRoiRecognition({ sourceType: 'live', cameraId: activeCameraGetter?.() || null, track, bbox });
    el('tag-name-input')?.focus();
  }

  function handleRoiRecognition(payload = {}) {
    lastRoiPointerMs = Date.now();
    const track = payload.track || null;
    const trackId = track?.id ?? track?.track_id ?? '';
    openTagModal(track, { ...payload, fromRoi: true, skipRecognition: true, title: track ? `🏷️ Tag Track #${trackId}` : '🎯 Tag Selected Region' });
    runRoiRecognition(payload);
  }

  function closeTagModal() {
    recognitionSeq += 1;
    if (el('modal-tag-entity')) el('modal-tag-entity').style.display = 'none';
    if (el('tag-roi-preview-panel')) el('tag-roi-preview-panel').style.display = 'none';
    if (el('tag-identity-candidates')) el('tag-identity-candidates').innerHTML = '';
    el('tag-entity-form')?.reset();
  }
  async function submitTagForm(e) {
    e.preventDefault();
    const name = (el('tag-name-input')?.value || '').trim();
    if (!name) return;
    const category = el('tag-category-select')?.value || 'person', sourceType = el('tag-source-type')?.value || 'live', tsVal = el('tag-timestamp-sec')?.value;
    const cropBase64 = el('tag-crop-base64')?.value || null;
    const payload = {
      entity_name: name, category,
      entity_id: el('tag-entity-id')?.value ? parseInt(el('tag-entity-id').value, 10) : null,
      track_id: el('tag-track-id')?.value ? parseInt(el('tag-track-id').value, 10) : null,
      bbox: cropBase64 ? null : (el('tag-bbox-val')?.value ? JSON.parse(el('tag-bbox-val').value) : null),
      crop_base64: cropBase64, notes: (el('tag-notes-input')?.value || '').trim(),
      camera_id: sourceType === 'video' ? null : (activeCameraGetter?.() || null),
      video_filename: sourceType === 'video' ? ((el('tag-video-filename')?.value || '').trim() || null) : null,
      timestamp_sec: sourceType === 'video' && tsVal !== '' ? parseFloat(tsVal) : null,
    };
    try {
      const res = await fetch('/api/tag/commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Tagging failed');
      const data = await res.json().catch(() => ({}));
      closeTagModal();
      window.showToast?.('Entity Enrolled', `Successfully enrolled "${name}" as ${category.toUpperCase()}!`, 'success');
      if (window.TagFeedbackActions?.onTagCommitted) window.TagFeedbackActions.onTagCommitted(payload, data);
      else window.loadGallery?.() || window.GalleryTimeline?.loadGallery?.();
    } catch (err) { window.showToast?.('Enrollment Failed', err.message, 'error'); }
  }
  function initTagModal(getActiveCameraId) {
    activeCameraGetter = getActiveCameraId;
    window.RoiDrawTagger?.setRecognitionHandler?.(handleRoiRecognition);
    const liveCanvas = el('interactive-canvas');
    const liveVideo = el('live-stream-img') || el('video-stream');
    if (liveCanvas && window.RoiDrawTagger?.attach) {
      window.RoiDrawTagger.attach({
        canvas: liveCanvas, mediaEl: liveVideo, containerEl: liveCanvas.parentElement,
        getTracks: () => latestState.tracks,
        getSourceContext: () => ({ sourceType: 'live', cameraId: activeCameraGetter?.() || null, sourceWidth: liveVideo?.naturalWidth || 0, sourceHeight: liveVideo?.naturalHeight || 0 }),
        onRenderOverlay: () => drawInteractiveOverlay(latestState.ctx, latestState.canvas, latestState.videoImg, latestState.tracks, latestState.hoveredTrack, latestState.sceneExtras),
        onTrackClick: ({ track, sourceContext }) => window.RoiDrawTagger.openWithRecognition({ ...sourceContext, track, bbox: track.bbox }),
        onRoiDrawn: ({ bbox, sourceContext }) => window.RoiDrawTagger.openWithRecognition({ ...sourceContext, track: null, bbox }),
      });
    }
    el('modal-tag-close')?.addEventListener('click', closeTagModal);
    el('modal-tag-cancel')?.addEventListener('click', closeTagModal);
    el('btn-tag-discourage')?.addEventListener('click', () => window.TagFeedbackActions?.discourageFromModal?.(activeCameraGetter));
    el('tag-name-input')?.addEventListener('input', () => { if (el('tag-entity-id')) el('tag-entity-id').value = ''; });
    el('tag-category-select')?.addEventListener('change', () => { categoryTouched = true; });
    el('tag-entity-form')?.addEventListener('submit', submitTagForm);
  }

  window.InteractiveCanvas = {
    syncSize: syncCanvasSize, drawOverlay: drawInteractiveOverlay, findHoveredTrack,
    updateTooltip: updateTooltipPosition, openTagModal, closeTagModal, initTagModal,
    openWithRecognition: handleRoiRecognition,
  };
})();
