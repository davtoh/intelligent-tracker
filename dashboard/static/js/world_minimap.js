/**
 * Intelligent Tracker - World Tactical Minimap View
 * Renders calibrated multi-camera /api/topology/world-map telemetry
 * (metric grid, FOV cones, zones, transitions, trajectories, velocity vectors)
 * with BEVMinimap fallback and inline camera world-pose editor.
 */
(function () {
  let cachedWorldMap = null;
  let lastFetchMs = 0;
  let fetchInFlight = false;
  let lastEditorCamId = null;

  function toCanvasXY(wx, wy, bounds, width, height, pad) {
    const minX = Number(bounds?.[0] ?? 0);
    const minY = Number(bounds?.[1] ?? 0);
    const maxX = Number(bounds?.[2] ?? 20);
    const maxY = Number(bounds?.[3] ?? 20);
    const spanX = Math.max(1e-3, maxX - minX);
    const spanY = Math.max(1e-3, maxY - minY);
    const drawW = Math.max(1, width - pad * 2);
    const drawH = Math.max(1, height - pad * 2);
    const cx = pad + ((wx - minX) / spanX) * drawW;
    const cy = pad + ((wy - minY) / spanY) * drawH;
    return [cx, cy];
  }

  function drawMetricGrid(ctx, bounds, width, height, pad) {
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.14)';
    ctx.lineWidth = 1;
    const steps = 4;
    const drawW = width - pad * 2;
    const drawH = height - pad * 2;
    for (let i = 0; i <= steps; i += 1) {
      const gx = pad + (drawW * i) / steps;
      const gy = pad + (drawH * i) / steps;
      ctx.beginPath();
      ctx.moveTo(gx, pad);
      ctx.lineTo(gx, height - pad);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(pad, gy);
      ctx.lineTo(width - pad, gy);
      ctx.stroke();
    }
    ctx.fillStyle = '#94a3b8';
    ctx.font = '10px sans-serif';
    const b = bounds || [0, 0, 20, 20];
    ctx.fillText(`World ${(b[2] - b[0]).toFixed(0)}m × ${(b[3] - b[1]).toFixed(0)}m`, pad, 13);
  }

  function drawZonesAndTransitions(ctx, data, bounds, width, height, pad) {
    (data.zones || []).forEach((zone) => {
      const pts = zone.global_polygon || [];
      if (pts.length < 3) return;
      ctx.beginPath();
      pts.forEach((pt, idx) => {
        const [cx, cy] = toCanvasXY(pt[0], pt[1], bounds, width, height, pad);
        if (idx === 0) ctx.moveTo(cx, cy);
        else ctx.lineTo(cx, cy);
      });
      ctx.closePath();
      ctx.fillStyle = zone.restricted ? 'rgba(239, 68, 68, 0.16)' : 'rgba(6, 182, 212, 0.14)';
      ctx.strokeStyle = zone.restricted ? 'rgba(239, 68, 68, 0.7)' : 'rgba(6, 182, 212, 0.65)';
      ctx.lineWidth = 1.25;
      ctx.fill();
      ctx.stroke();
    });

    (data.transitions || []).forEach((tr) => {
      if (!tr.source_xy || !tr.target_xy) return;
      const [sx, sy] = toCanvasXY(tr.source_xy[0], tr.source_xy[1], bounds, width, height, pad);
      const [tx, ty] = toCanvasXY(tr.target_xy[0], tr.target_xy[1], bounds, width, height, pad);
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = tr.active ? 'rgba(129, 140, 248, 0.8)' : 'rgba(148, 163, 184, 0.4)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.restore();
    });
  }

  function drawCameraFovCones(ctx, cameras, bounds, width, height, pad, activeCameraId) {
    const spanX = Math.max(1e-3, (bounds?.[2] ?? 20) - (bounds?.[0] ?? 0));
    const pxPerMeter = (width - pad * 2) / spanX;
    (cameras || []).forEach((cam) => {
      const pose = cam.world_pose || {};
      const ox = Number(pose.origin_x ?? 0);
      const oy = Number(pose.origin_y ?? 0);
      const yawRad = (Number(pose.yaw_deg ?? 0) * Math.PI) / 180;
      const halfFov = ((Number(pose.fov_deg ?? 75) * Math.PI) / 180) / 2;
      const rangePx = Math.max(12, Number(pose.range_m ?? 12) * pxPerMeter);
      const [cx, cy] = toCanvasXY(ox, oy, bounds, width, height, pad);
      const isActive = activeCameraId && cam.camera_id === activeCameraId;

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, rangePx, yawRad - halfFov, yawRad + halfFov);
      ctx.closePath();
      ctx.fillStyle = isActive ? 'rgba(6, 182, 212, 0.18)' : 'rgba(148, 163, 184, 0.10)';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, isActive ? 5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = isActive ? '#06b6d4' : '#cbd5e1';
      ctx.fill();
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '10px sans-serif';
      ctx.fillText(cam.camera_id || 'cam', cx + 7, cy + 3);
    });
  }

  function drawEntitiesAndVelocity(ctx, entities, bounds, width, height, pad) {
    const spanX = Math.max(1e-3, (bounds?.[2] ?? 20) - (bounds?.[0] ?? 0));
    const pxPerMeter = (width - pad * 2) / spanX;
    (entities || []).forEach((ent) => {
      const traj = ent.global_trajectory || [];
      if (traj.length >= 2) {
        ctx.beginPath();
        traj.forEach((pt, idx) => {
          const [tx, ty] = toCanvasXY(pt[0], pt[1], bounds, width, height, pad);
          if (idx === 0) ctx.moveTo(tx, ty);
          else ctx.lineTo(tx, ty);
        });
        ctx.strokeStyle = ent.restricted ? 'rgba(239, 68, 68, 0.55)' : 'rgba(16, 185, 129, 0.55)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      if (!ent.global_xy) return;
      const [ex, ey] = toCanvasXY(ent.global_xy[0], ent.global_xy[1], bounds, width, height, pad);
      const vx = Number(ent.vx ?? 0);
      const vy = Number(ent.vy ?? 0);
      if (Math.hypot(vx, vy) > 0.05) {
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(ex + vx * pxPerMeter * 0.8, ey + vy * pxPerMeter * 0.8);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(ex, ey, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = ent.restricted ? '#ef4444' : '#10b981';
      ctx.fill();
      const label = ent.name || ent.world_entity_id || 'entity';
      ctx.fillStyle = '#f8fafc';
      ctx.font = '10px sans-serif';
      ctx.fillText(label, ex + 6, ey - 4);
    });
  }

  function renderWorldMap(canvas, worldMapData, activeCameraId) {
    if (!canvas || !canvas.getContext) return false;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const w = canvas.width || 320;
    const h = canvas.height || 320;
    const pad = 20;
    const bounds = worldMapData?.bounds || [0, 0, 20, 20];

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#090d16';
    ctx.fillRect(0, 0, w, h);

    drawMetricGrid(ctx, bounds, w, h, pad);
    drawZonesAndTransitions(ctx, worldMapData, bounds, w, h, pad);
    drawCameraFovCones(ctx, worldMapData?.cameras, bounds, w, h, pad, activeCameraId);
    drawEntitiesAndVelocity(ctx, worldMapData?.entities, bounds, w, h, pad);

    const badge = document.getElementById('bev-metric-scale');
    if (badge) {
      const anyCalibrated = (worldMapData?.cameras || []).some((c) => c.calibrated);
      badge.textContent = anyCalibrated ? 'World Calibrated' : 'World Map';
      badge.className = anyCalibrated ? 'badge badge-success' : 'badge';
    }
    return true;
  }

  function populatePoseEditor(worldMapData, cameraId) {
    if (!cameraId || lastEditorCamId === cameraId) return;
    const cam = (worldMapData?.cameras || []).find((c) => c.camera_id === cameraId);
    if (!cam || !cam.world_pose) return;
    lastEditorCamId = cameraId;
    const map = {
      'world-pose-x': cam.world_pose.origin_x ?? 0,
      'world-pose-y': cam.world_pose.origin_y ?? 0,
      'world-pose-yaw': cam.world_pose.yaw_deg ?? 0,
      'world-pose-fov': cam.world_pose.fov_deg ?? 75,
      'world-pose-range': cam.world_pose.range_m ?? 12,
    };
    Object.entries(map).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.value = String(val);
    });
  }

  function hasWorldContent(data) {
    if (!data) return false;
    return (data.cameras?.length || 0) > 0 || (data.zones?.length || 0) > 0 || (data.entities?.length || 0) > 0;
  }

  async function fetchAndRender(canvas, activeCameraId, homography, zones) {
    if (!canvas) return;
    const now = Date.now();
    if (!fetchInFlight && (now - lastFetchMs > 750 || !cachedWorldMap)) {
      fetchInFlight = true;
      lastFetchMs = now;
      try {
        const res = await fetch('/api/topology/world-map');
        if (res.ok) {
          cachedWorldMap = await res.json();
          populatePoseEditor(cachedWorldMap, activeCameraId);
        }
      } catch (_err) {
        // Fallback to BEVMinimap below
      } finally {
        fetchInFlight = false;
      }
    }
    if (hasWorldContent(cachedWorldMap)) {
      populatePoseEditor(cachedWorldMap, activeCameraId);
      renderWorldMap(canvas, cachedWorldMap, activeCameraId);
      return;
    }
    window.BEVMinimap?.render(canvas, homography, zones, activeCameraId);
  }

  async function savePose(cameraId, posePayload) {
    if (!cameraId) return null;
    const res = await fetch(`/api/topology/world-pose/${encodeURIComponent(cameraId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(posePayload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    lastFetchMs = 0;
    lastEditorCamId = null;
    return res.json();
  }

  function bindPoseEditor(getCameraId) {
    const btn = document.getElementById('btn-save-world-pose');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', async () => {
      const cameraId = typeof getCameraId === 'function' ? getCameraId() : '';
      if (!cameraId) return;
      const num = (id, def) => {
        const v = Number(document.getElementById(id)?.value);
        return Number.isFinite(v) ? v : def;
      };
      btn.disabled = true;
      try {
        await savePose(cameraId, {
          origin_x: num('world-pose-x', 0),
          origin_y: num('world-pose-y', 0),
          yaw_deg: num('world-pose-yaw', 0),
          fov_deg: Math.max(10, Math.min(180, num('world-pose-fov', 75))),
          range_m: Math.max(1, num('world-pose-range', 12)),
          scale: 1.0,
        });
        const canvas = document.getElementById('bev-minimap-canvas');
        await fetchAndRender(canvas, cameraId, null, []);
        window.showToast?.('World Pose Saved', `Updated ${cameraId} pose`, 'success');
      } catch (err) {
        window.showToast?.('Pose Save Failed', err.message || 'Error', 'error');
      } finally {
        btn.disabled = false;
      }
    });
  }

  window.WorldTacticalMinimapView = {
    render: renderWorldMap,
    fetchAndRender,
    savePose,
    bindPoseEditor,
    toCanvasXY,
  };
})();
