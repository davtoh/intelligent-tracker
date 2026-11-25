/**
 * Intelligent Tracker - Interactive 2D World Minimap Pointer & Viewport Controls.
 * Supports clicking a camera FOV cone to focus it, dragging camera origin/tip handles,
 * wheel zoom around cursor, empty-canvas drag-to-pan, and #btn-minimap-* controls.
 */
(function () {
  const PAD = 20;
  const HANDLE_RADIUS = 12;
  let dragState = null;
  let panState = null;
  let pendingFocusId = null;

  function getCanvasPoint(canvas, ev) {
    const w = canvas.width || 320;
    const h = canvas.height || 320;
    const rect = typeof canvas.getBoundingClientRect === 'function'
      ? canvas.getBoundingClientRect()
      : { left: 0, top: 0, width: w, height: h };
    const cssW = Math.max(1, rect.width || w);
    const cssH = Math.max(1, rect.height || h);
    return [((ev.clientX ?? 0) - (rect.left ?? 0)) * (w / cssW), ((ev.clientY ?? 0) - (rect.top ?? 0)) * (h / cssH)];
  }

  function angleDiff(a, b) {
    let d = a - b;
    while (d > Math.PI) d -= Math.PI * 2;
    while (d < -Math.PI) d += Math.PI * 2;
    return Math.abs(d);
  }

  function getCameraGeom(cam, bounds, width, height) {
    const view = window.WorldTacticalMinimapView;
    const b = view.normalizeBounds(bounds);
    const zoom = Number(view.getViewport?.().zoom) || 1;
    const spanX = Math.max(1e-3, b[2] - b[0]);
    const pxPerMeter = ((width - PAD * 2) / spanX) * zoom;
    const pose = cam.world_pose || {};
    const yawRad = (Number(pose.yaw_deg ?? 0) * Math.PI) / 180;
    const halfFov = ((Number(pose.fov_deg ?? 75) * Math.PI) / 180) / 2;
    const rangePx = Math.max(12, Number(pose.range_m ?? 12) * pxPerMeter);
    const [cx, cy] = view.toCanvasXY(Number(pose.origin_x ?? 0), Number(pose.origin_y ?? 0), b, width, height, PAD);
    return {
      cam, cx, cy, yawRad, halfFov, rangePx,
      tipX: cx + Math.cos(yawRad) * rangePx,
      tipY: cy + Math.sin(yawRad) * rangePx,
    };
  }

  function hitTestMinimap(cx, cy, worldMap, activeCameraId) {
    const canvas = document.getElementById('bev-minimap-canvas');
    const w = canvas?.width || 320;
    const h = canvas?.height || 320;
    const cams = worldMap?.cameras || [];
    const ordered = [...cams].sort((a, b) => (a.camera_id === activeCameraId ? -1 : b.camera_id === activeCameraId ? 1 : 0));
    const geoms = ordered.map((c) => getCameraGeom(c, worldMap?.bounds, w, h));

    for (const g of geoms) {
      if (Math.hypot(cx - g.tipX, cy - g.tipY) <= HANDLE_RADIUS) return { type: 'tip', cam: g.cam };
    }
    for (const g of geoms) {
      if (Math.hypot(cx - g.cx, cy - g.cy) <= HANDLE_RADIUS) return { type: 'origin', cam: g.cam };
    }
    for (const g of geoms) {
      const dist = Math.hypot(cx - g.cx, cy - g.cy);
      if (dist <= g.rangePx && angleDiff(Math.atan2(cy - g.cy, cx - g.cx), g.yawRad) <= g.halfFov) {
        return { type: 'cone', cam: g.cam };
      }
    }
    return null;
  }

  function focusCamera(cameraId) {
    if (!cameraId) return false;
    const sel = document.getElementById('studio-camera-select');
    if (!sel) return false;
    const opts = [...(sel.options || [])];
    if (opts.length && !opts.some((o) => o.value === cameraId)) return false;
    sel.value = cameraId;
    if (typeof sel.dispatchEvent === 'function') {
      const ev = typeof Event === 'function' ? new Event('change', { bubbles: true }) : { type: 'change', target: sel };
      sel.dispatchEvent(ev);
    }
    return true;
  }

  function applyDragMove(canvas, cx, cy, getActiveCameraId) {
    const view = window.WorldTacticalMinimapView;
    const worldMap = view?.getCachedWorldMap?.();
    if (!dragState || !view || !worldMap) return;
    const [wx, wy] = view.toWorldXY(cx, cy, worldMap.bounds, canvas.width || 320, canvas.height || 320, PAD);
    if (dragState.mode === 'origin') {
      dragState.pose.origin_x = Number(wx.toFixed(2));
      dragState.pose.origin_y = Number(wy.toFixed(2));
    } else if (dragState.mode === 'tip') {
      const dx = wx - Number(dragState.pose.origin_x ?? 0);
      const dy = wy - Number(dragState.pose.origin_y ?? 0);
      dragState.pose.yaw_deg = Number(((Math.atan2(dy, dx) * 180) / Math.PI).toFixed(1));
      dragState.pose.range_m = Number(Math.max(1, Math.hypot(dx, dy)).toFixed(2));
    }
    dragState.moved = true;
    view.setDragPreview(dragState.cameraId, dragState.pose);
    view.syncPoseInputs(dragState.pose);
    view.renderPreview(canvas, getActiveCameraId?.() || dragState.cameraId);
  }

  async function commitDragEnd(canvas, getActiveCameraId) {
    const view = window.WorldTacticalMinimapView;
    if (panState) {
      panState = null;
      if (canvas.style) canvas.style.cursor = 'grab';
      return;
    }
    if (!dragState) {
      if (pendingFocusId) { const cid = pendingFocusId; pendingFocusId = null; focusCamera(cid); }
      return;
    }
    const { cameraId, pose, moved } = dragState;
    dragState = null;
    pendingFocusId = null;
    if (canvas.style) canvas.style.cursor = 'grab';
    if (!moved) {
      view?.setDragPreview?.(null, null);
      if (cameraId !== getActiveCameraId?.()) focusCamera(cameraId);
      return;
    }
    try {
      await view.savePose(cameraId, {
        origin_x: Number(pose.origin_x ?? 0), origin_y: Number(pose.origin_y ?? 0),
        yaw_deg: Number(pose.yaw_deg ?? 0),
        fov_deg: Math.max(10, Math.min(180, Number(pose.fov_deg ?? 75))),
        range_m: Math.max(1, Number(pose.range_m ?? 12)), scale: Number(pose.scale ?? 1.0),
      });
      view.setDragPreview(null, null);
      await view.fetchAndRender(canvas, getActiveCameraId?.() || cameraId, null, []);
    } catch (err) {
      view?.setDragPreview?.(null, null);
      window.showToast?.('Pose Save Failed', err.message || 'Error', 'error');
    }
  }

  function bindMinimapControls(canvas, getActiveCameraId) {
    const view = window.WorldTacticalMinimapView;
    const rerender = () => view?.rerender?.(canvas, getActiveCameraId?.());
    const bindBtn = (id, fn) => {
      const btn = document.getElementById(id);
      if (!btn || btn.dataset?.minimapBound === '1') return;
      if (btn.dataset) btn.dataset.minimapBound = '1';
      btn.addEventListener('click', () => { fn(); rerender(); });
    };
    bindBtn('btn-minimap-zoom-in', () => view?.setZoom?.((view.getViewport?.().zoom || 1) * 1.25));
    bindBtn('btn-minimap-zoom-out', () => view?.setZoom?.((view.getViewport?.().zoom || 1) / 1.25));
    bindBtn('btn-minimap-fit', () => view?.fitToBounds?.());
    bindBtn('btn-minimap-view-toggle', () => view?.toggleViewMode?.());
  }

  function handleWheelZoom(canvas, ev, getActiveCameraId) {
    const view = window.WorldTacticalMinimapView;
    const worldMap = view?.getCachedWorldMap?.();
    if (!view || !worldMap || view.getViewport?.().viewMode === 'camera') return;
    ev.preventDefault?.();
    const [cx, cy] = getCanvasPoint(canvas, ev);
    const factor = Number(ev.deltaY) < 0 ? 1.2 : 1 / 1.2;
    const nextZoom = (view.getViewport?.().zoom || 1) * factor;
    view.setZoom?.(nextZoom, [cx, cy], worldMap.bounds, canvas.width || 320, canvas.height || 320, PAD);
    view.rerender?.(canvas, getActiveCameraId?.());
  }

  function bind(getActiveCameraId) {
    const canvas = document.getElementById('bev-minimap-canvas');
    if (!canvas || canvas.dataset?.interactionsBound === '1') return;
    if (canvas.dataset) canvas.dataset.interactionsBound = '1';
    if (canvas.style) canvas.style.cursor = 'grab';
    bindMinimapControls(canvas, getActiveCameraId);

    canvas.addEventListener('wheel', (ev) => handleWheelZoom(canvas, ev, getActiveCameraId), { passive: false });

    canvas.addEventListener('mousedown', (ev) => {
      const view = window.WorldTacticalMinimapView;
      const worldMap = view?.getCachedWorldMap?.();
      if (!worldMap || view?.getViewport?.().viewMode === 'camera') return;
      const [cx, cy] = getCanvasPoint(canvas, ev);
      const hit = hitTestMinimap(cx, cy, worldMap, getActiveCameraId?.());
      if (!hit) {
        panState = { lastX: cx, lastY: cy };
        if (canvas.style) canvas.style.cursor = 'grabbing';
        return;
      }
      if (hit.type === 'cone') { pendingFocusId = hit.cam.camera_id; return; }
      dragState = { mode: hit.type, cameraId: hit.cam.camera_id, pose: { ...(hit.cam.world_pose || {}) }, moved: false };
      if (canvas.style) canvas.style.cursor = 'grabbing';
    });

    canvas.addEventListener('mousemove', (ev) => {
      const [cx, cy] = getCanvasPoint(canvas, ev);
      if (panState) {
        const view = window.WorldTacticalMinimapView;
        const worldMap = view?.getCachedWorldMap?.();
        if (worldMap) {
          view.panBy?.(cx - panState.lastX, cy - panState.lastY, worldMap.bounds, canvas.width || 320, canvas.height || 320, PAD);
          panState.lastX = cx; panState.lastY = cy;
          view.rerender?.(canvas, getActiveCameraId?.());
        }
        return;
      }
      if (dragState) applyDragMove(canvas, cx, cy, getActiveCameraId);
    });

    canvas.addEventListener('mouseup', () => commitDragEnd(canvas, getActiveCameraId));
    canvas.addEventListener('mouseleave', () => {
      if (dragState || panState) commitDragEnd(canvas, getActiveCameraId);
      pendingFocusId = null;
    });
  }

  window.WorldMinimapInteractions = { bind, hitTestMinimap, getCanvasPoint, focusCamera };
})();
