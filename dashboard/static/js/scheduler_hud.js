/**
 * Intelligent Tracker - Resource-Aware Analytics Scheduler HUD.
 * Dynamically renders the live priority tier pill (P0/P1/P2/REPLAY) and
 * load-shedding backpressure badge inside #stream-telemetry-hud's container.
 */

(function () {
  'use strict';

  let lastGlobalSummary = null;

  function formatTierBadge(data = {}) {
    const tier = String(data.priority_tier || 'P2').toUpperCase();
    const fps = typeof data.target_fps === 'number' ? `${data.target_fps.toFixed(1)} FPS` : '';
    if (data.replay_active || tier === 'REPLAY') {
      return { text: 'ZERO-GPU REPLAY', cls: 'tier-replay', title: 'Zero-GPU pre-indexed replay with live rule evaluation' };
    }
    if (tier === 'P0') {
      return { text: 'P0 LIVE', cls: 'tier-p0', title: `High-priority live analytics${fps ? ` (${fps})` : ''}` };
    }
    if (tier === 'P1') {
      if (data.motion_active) {
        return { text: 'P1 MOTION', cls: 'tier-p1-motion', title: `Armed camera motion burst${fps ? ` (${fps})` : ''}` };
      }
      return { text: 'P1 IDLE 1FPS', cls: 'tier-p1-idle', title: `Armed camera heartbeat${fps ? ` (${fps})` : ''}` };
    }
    return { text: 'P2 BG', cls: 'tier-p2', title: `Background camera${fps ? ` (${fps})` : ''}` };
  }

  function ensureHudElements() {
    const anchor = document.getElementById('stream-telemetry-hud');
    const parent = anchor?.parentElement || anchor?.parentNode || null;
    if (!parent) return { tierPill: null, shedBadge: null };

    let tierPill = document.getElementById('scheduler-tier-pill');
    if (!tierPill && typeof document.createElement === 'function') {
      tierPill = document.createElement('span');
      tierPill.id = 'scheduler-tier-pill';
      tierPill.className = 'scheduler-tier-pill tier-p2';
      parent.appendChild(tierPill);
    }

    let shedBadge = document.getElementById('scheduler-shed-badge');
    if (!shedBadge && typeof document.createElement === 'function') {
      shedBadge = document.createElement('span');
      shedBadge.id = 'scheduler-shed-badge';
      shedBadge.className = 'scheduler-shed-badge';
      shedBadge.hidden = true;
      parent.appendChild(shedBadge);
    }
    return { tierPill, shedBadge };
  }

  function renderShedBadge(shedBadge, stageRaw) {
    if (!shedBadge) return;
    const stage = String(stageRaw || 'normal').toLowerCase();
    if (stage === 'elevated' || stage === 'critical') {
      const s = lastGlobalSummary;
      const detail = s
        ? ` (${Number(s.rolling_fps || 0).toFixed(1)}/${Number(s.global_fps_budget || 0)} FPS, ${Math.round(Number(s.ewma_latency_ms || 0))}ms)`
        : '';
      shedBadge.hidden = false;
      shedBadge.className = `scheduler-shed-badge shed-${stage}`;
      shedBadge.textContent = `SHED: ${stage.toUpperCase()}`;
      shedBadge.title = `Scheduler load-shedding ${stage.toUpperCase()}${detail}`;
    } else {
      shedBadge.hidden = true;
      shedBadge.className = 'scheduler-shed-badge';
      shedBadge.textContent = '';
    }
  }

  function updateCamera(telemetryData = {}) {
    const { tierPill, shedBadge } = ensureHudElements();
    if (tierPill) {
      const badge = formatTierBadge(telemetryData);
      tierPill.className = `scheduler-tier-pill ${badge.cls}`;
      tierPill.textContent = badge.text;
      tierPill.title = badge.title;
    }
    const stage = telemetryData.load_shed_stage || lastGlobalSummary?.load_shed_stage || 'normal';
    renderShedBadge(shedBadge, stage);
  }

  function updateGlobal(statusData = {}) {
    if (!statusData || typeof statusData !== 'object') return;
    if (statusData.scheduler && typeof statusData.scheduler === 'object') {
      lastGlobalSummary = statusData.scheduler;
    }
    const { shedBadge } = ensureHudElements();
    if (lastGlobalSummary) renderShedBadge(shedBadge, lastGlobalSummary.load_shed_stage);
  }

  window.SchedulerHUD = { updateCamera, updateGlobal, formatTierBadge };
})();
