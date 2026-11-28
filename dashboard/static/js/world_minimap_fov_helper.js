/**
 * Intelligent Tracker - World Tactical Minimap FOV & BEV Quad Helper.
 * Renders calibrated camera `fov_corners_global` polygons (falling back to
 * idealized cone arcs when uncalibrated) and filters by `bevQuadMode`.
 */
(function () {
  'use strict';

  function shouldDrawFov(cam, activeCameraId, bevQuadMode) {
    const mode = bevQuadMode || 'all';
    if (mode === 'off') return false;
    if (mode === 'selected') return Boolean(activeCameraId && cam?.camera_id === activeCameraId);
    return true;
  }

  function drawCameraFovCones(ctx, cameras, bounds, width, height, pad, activeCameraId, toCanvasXY, effectiveBounds, bevQuadMode) {
    const [, , spanX] = effectiveBounds(bounds);
    const pxPerMeter = (width - pad * 2) / Math.max(1e-3, spanX);
    (cameras || []).forEach((cam) => {
      const pose = cam.world_pose || {};
      const yawRad = (Number(pose.yaw_deg ?? 0) * Math.PI) / 180;
      const halfFov = ((Number(pose.fov_deg ?? 75) * Math.PI) / 180) / 2;
      const rangePx = Math.max(12, Number(pose.range_m ?? 12) * pxPerMeter);
      const [cx, cy] = toCanvasXY(Number(pose.origin_x ?? 0), Number(pose.origin_y ?? 0), bounds, width, height, pad);
      const isActive = Boolean(activeCameraId && cam.camera_id === activeCameraId);
      const corners = Array.isArray(cam.fov_corners_global) ? cam.fov_corners_global : [];
      if (shouldDrawFov(cam, activeCameraId, bevQuadMode)) {
        if (cam.calibrated && corners.length >= 3) {
          ctx.beginPath();
          corners.forEach((pt, idx) => {
            const [fx, fy] = toCanvasXY(Number(pt[0]), Number(pt[1]), bounds, width, height, pad);
            if (idx === 0) ctx.moveTo(fx, fy);
            else ctx.lineTo(fx, fy);
          });
          ctx.closePath();
          ctx.fillStyle = isActive ? 'rgba(6, 182, 212, 0.24)' : 'rgba(148, 163, 184, 0.12)';
          ctx.fill();
          ctx.strokeStyle = isActive ? 'rgba(6, 182, 212, 0.85)' : 'rgba(148, 163, 184, 0.45)';
          ctx.lineWidth = isActive ? 1.5 : 1;
          ctx.stroke();
        } else {
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.arc(cx, cy, rangePx, yawRad - halfFov, yawRad + halfFov);
          ctx.closePath();
          ctx.fillStyle = isActive ? 'rgba(6, 182, 212, 0.22)' : 'rgba(148, 163, 184, 0.10)';
          ctx.fill();
        }
      }
      ctx.beginPath();
      ctx.arc(cx, cy, isActive ? 5.5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = isActive ? '#06b6d4' : '#cbd5e1';
      ctx.fill();
      if (isActive) {
        const tx = cx + Math.cos(yawRad) * rangePx;
        const ty = cy + Math.sin(yawRad) * rangePx;
        ctx.beginPath();
        ctx.arc(tx, ty, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = '#f59e0b';
        ctx.fill();
      }
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '10px sans-serif';
      ctx.fillText(cam.camera_id || 'cam', cx + 7, cy + 3);
    });
  }

  window.WorldMinimapFovHelper = { shouldDrawFov, drawCameraFovCones };
})();
