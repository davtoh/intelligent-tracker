/**
 * Intelligent Tracker - Top-Down Bird's-Eye-View (BEV) Minimap Controller.
 * Projects camera pixel coordinates through ground plane homography into metric space.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  function renderBEVMinimap(bevCanvas, bevCtx, activeCamera, homography, zones, activeTracks) {
    if (!bevCanvas || !bevCtx) return;

    const cw = bevCanvas.width;
    const ch = bevCanvas.height;
    bevCtx.clearRect(0, 0, cw, ch);

    // Dark tactical background
    bevCtx.fillStyle = '#0f172a';
    bevCtx.fillRect(0, 0, cw, ch);

    const margin = 35;
    const innerW = cw - 2 * margin;
    const innerH = ch - 2 * margin;

    const gw = (homography && homography.metric_width) ? homography.metric_width : 10.0;
    const gh = (homography && homography.metric_height) ? homography.metric_height : 10.0;

    const scaleX = innerW / gw;
    const scaleY = innerH / gh;

    function g2c(gx, gy) {
      return {
        x: Math.round(margin + gx * scaleX),
        y: Math.round(margin + gy * scaleY),
      };
    }

    // Grid boundary
    bevCtx.strokeStyle = '#334155';
    bevCtx.lineWidth = 1;
    bevCtx.strokeRect(margin, margin, innerW, innerH);

    // Metric Grid Lines
    bevCtx.fillStyle = '#64748b';
    bevCtx.font = '10px JetBrains Mono, monospace';

    const stepX = Math.max(2, Math.floor(gw / 4));
    for (let gx = stepX; gx < gw; gx += stepX) {
      const p1 = g2c(gx, 0);
      const p2 = g2c(gx, gh);
      bevCtx.beginPath();
      bevCtx.moveTo(p1.x, p1.y);
      bevCtx.lineTo(p2.x, p2.y);
      bevCtx.strokeStyle = '#1e293b';
      bevCtx.stroke();
      bevCtx.fillText(`${gx}m`, p1.x - 8, ch - margin + 14);
    }

    const stepY = Math.max(2, Math.floor(gh / 4));
    for (let gy = stepY; gy < gh; gy += stepY) {
      const p1 = g2c(0, gy);
      const p2 = g2c(gw, gy);
      bevCtx.beginPath();
      bevCtx.moveTo(p1.x, p1.y);
      bevCtx.lineTo(p2.x, p2.y);
      bevCtx.strokeStyle = '#1e293b';
      bevCtx.stroke();
      bevCtx.fillText(`${gy}m`, 6, p1.y + 3);
    }

    // Title Badge
    bevCtx.fillStyle = '#00e5ff';
    bevCtx.font = 'bold 11px Inter, sans-serif';
    bevCtx.fillText(`BEV: ${activeCamera} (${gw}m x ${gh}m)`, margin, 20);

    // Draw Transformed Zones
    if (zones && Array.isArray(zones)) {
      zones.forEach((z) => {
        if (!z.polygon || z.polygon.length < 3) return;
        bevCtx.beginPath();
        const p0 = g2c((z.polygon[0][0] / 640) * gw, (z.polygon[0][1] / 480) * gh);
        bevCtx.moveTo(p0.x, p0.y);
        for (let i = 1; i < z.polygon.length; i++) {
          const pt = g2c((z.polygon[i][0] / 640) * gw, (z.polygon[i][1] / 480) * gh);
          bevCtx.lineTo(pt.x, pt.y);
        }
        bevCtx.closePath();
        bevCtx.fillStyle = 'rgba(0, 200, 100, 0.2)';
        bevCtx.fill();
        bevCtx.strokeStyle = '#00ff88';
        bevCtx.lineWidth = 1.5;
        bevCtx.stroke();

        bevCtx.fillStyle = '#ffffff';
        bevCtx.font = '10px Inter, sans-serif';
        bevCtx.fillText(z.name, p0.x + 4, p0.y + 12);
      });
    }

    // Draw Track Radar Blips
    const tracks = activeTracks || window.latestTelemetry?.active_tracks || [];
    tracks.forEach((trk) => {
      let gx = (trk.bbox[0] + trk.bbox[2] / 2) / 640 * gw;
      let gy = (trk.bbox[1] + trk.bbox[3]) / 480 * gh;
      if (trk.ground_pos) {
        gx = trk.ground_pos[0];
        gy = trk.ground_pos[1];
      }

      const cp = g2c(gx, gy);
      bevCtx.beginPath();
      bevCtx.arc(cp.x, cp.y, 6, 0, Math.PI * 2);
      bevCtx.fillStyle = trk.category === 'restricted' ? '#ef4444' : '#22c55e';
      bevCtx.fill();
      bevCtx.strokeStyle = '#ffffff';
      bevCtx.lineWidth = 1;
      bevCtx.stroke();

      bevCtx.fillStyle = '#f8fafc';
      bevCtx.font = 'bold 9px Inter, sans-serif';
      bevCtx.fillText(trk.entity_name || `#${trk.id}`, cp.x + 8, cp.y + 3);
    });
  }

  window.TrackerApp.BEVMinimap = {
    render: renderBEVMinimap,
  };
})();

