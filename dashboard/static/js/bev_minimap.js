/**
 * Intelligent Tracker - 2D Bird's-Eye-View (BEV) Minimap Submodule.
 * Renders tactical top-down metric grid, calibrated ground zones, and active telemetry entities.
 */

(function () {
  'use strict';

  function drawMetricGrid(ctx, margin, innerW, innerH, gw, gh, cw, ch, g2c) {
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1;
    ctx.strokeRect(margin, margin, innerW, innerH);

    ctx.fillStyle = '#64748b';
    ctx.font = '10px JetBrains Mono, monospace';

    const stepX = Math.max(2, Math.floor(gw / 4));
    for (let gx = stepX; gx < gw; gx += stepX) {
      const p1 = g2c(gx, 0);
      const p2 = g2c(gx, gh);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = '#1e293b';
      ctx.stroke();
      ctx.fillText(`${gx}m`, p1.x - 8, ch - margin + 14);
    }

    const stepY = Math.max(2, Math.floor(gh / 4));
    for (let gy = stepY; gy < gh; gy += stepY) {
      const p1 = g2c(0, gy);
      const p2 = g2c(gw, gy);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = '#1e293b';
      ctx.stroke();
      ctx.fillText(`${gy}m`, 6, p1.y + 3);
    }
  }

  function isHomographyCalibrated(homography) {
    return Boolean(
      homography
      && homography.is_calibrated
      && Array.isArray(homography.homography_matrix)
      && homography.homography_matrix.length === 3
    );
  }

  function projectWithHomography(px, py, homography, gw, gh, srcW, srcH) {
    if (isHomographyCalibrated(homography)) {
      const H = homography.homography_matrix;
      const denom = H[2][0] * px + H[2][1] * py + H[2][2];
      if (Math.abs(denom) > 1e-6) {
        return {
          x: (H[0][0] * px + H[0][1] * py + H[0][2]) / denom,
          y: (H[1][0] * px + H[1][1] * py + H[1][2]) / denom,
        };
      }
    }
    return { x: (px / srcW) * gw, y: (py / srcH) * gh };
  }

  function updateScaleBadge(calibrated) {
    const badge = document.getElementById('bev-metric-scale');
    if (!badge) return;
    badge.textContent = calibrated ? 'Calibrated' : 'Pixel Est.';
    badge.classList?.toggle?.('badge-calibrated', calibrated);
    badge.classList?.toggle?.('badge-uncalibrated', !calibrated);
  }

  function drawProjectedZones(ctx, zones, homography, gw, gh, g2c) {
    if (!zones) return;
    const srcW = Number(homography?.frame_width) || 640;
    const srcH = Number(homography?.frame_height) || 480;
    zones.forEach((z) => {
      if (!z.polygon || z.polygon.length < 3) return;
      ctx.beginPath();
      const gp0 = projectWithHomography(z.polygon[0][0], z.polygon[0][1], homography, gw, gh, srcW, srcH);
      const p0 = g2c(gp0.x, gp0.y);
      ctx.moveTo(p0.x, p0.y);
      for (let i = 1; i < z.polygon.length; i++) {
        const gp = projectWithHomography(z.polygon[i][0], z.polygon[i][1], homography, gw, gh, srcW, srcH);
        const pt = g2c(gp.x, gp.y);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(0, 200, 100, 0.2)';
      ctx.fill();
      ctx.strokeStyle = '#00ff88';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.font = '10px Inter, sans-serif';
      ctx.fillText(z.name, p0.x + 4, p0.y + 12);
    });
  }

  function drawActiveEntities(ctx, homography, gw, gh, g2c) {
    const activeTracks = window.latestTelemetry?.active_tracks;
    if (!activeTracks) return;
    const calibrated = isHomographyCalibrated(homography);
    const srcW = Number(homography?.frame_width) || 640;
    const srcH = Number(homography?.frame_height) || 480;

    activeTracks.forEach((trk) => {
      let gp;
      if (calibrated && Array.isArray(trk.ground_pos) && trk.ground_pos.length >= 2) {
        gp = { x: trk.ground_pos[0], y: trk.ground_pos[1] };
      } else if (Array.isArray(trk.bbox) && trk.bbox.length >= 4) {
        gp = projectWithHomography(trk.bbox[0] + trk.bbox[2] / 2, trk.bbox[1] + trk.bbox[3], homography, gw, gh, srcW, srcH);
      } else {
        return;
      }

      const cp = g2c(gp.x, gp.y);
      ctx.beginPath();
      ctx.arc(cp.x, cp.y, 6, 0, Math.PI * 2);
      ctx.fillStyle = trk.category === 'restricted' ? '#ef4444' : '#22c55e';
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = '#f8fafc';
      ctx.font = 'bold 9px Inter, sans-serif';
      ctx.fillText(trk.entity_name || `#${trk.id}`, cp.x + 8, cp.y + 3);
    });
  }

  function renderBEVMinimap(canvas, homography, zones, activeCameraId) {
    const calibrated = isHomographyCalibrated(homography);
    updateScaleBadge(calibrated);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const cw = canvas.width;
    const ch = canvas.height;
    ctx.clearRect(0, 0, cw, ch);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, cw, ch);

    const margin = 35;
    const innerW = cw - 2 * margin;
    const innerH = ch - 2 * margin;

    const gw = (homography && homography.metric_width) ? homography.metric_width : 10.0;
    const gh = (homography && homography.metric_height) ? homography.metric_height : 10.0;

    const scaleX = innerW / gw;
    const scaleY = innerH / gh;

    const g2c = (gx, gy) => ({
      x: Math.round(margin + gx * scaleX),
      y: Math.round(margin + gy * scaleY),
    });

    drawMetricGrid(ctx, margin, innerW, innerH, gw, gh, cw, ch, g2c);

    ctx.fillStyle = '#00e5ff';
    ctx.font = 'bold 11px Inter, sans-serif';
    const modeTag = calibrated ? `${gw}m x ${gh}m` : 'Pixel Est.';
    ctx.fillText(`BEV: ${activeCameraId || 'N/A'} (${modeTag})`, margin, 20);

    drawProjectedZones(ctx, zones, homography, gw, gh, g2c);
    drawActiveEntities(ctx, homography, gw, gh, g2c);
  }

  window.BEVMinimap = {
    render: renderBEVMinimap,
    isCalibrated: isHomographyCalibrated,
    projectPoint: projectWithHomography,
  };
})();

