/**
 * Intelligent Tracker - Scenario Modals & Scenario List UI Controller.
 * Manages Zone, Tripwire, Homography, and Spatial Transition modal forms.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const escapeHtml = window.escapeHtml || (s => s);
  let modalsInitialized = false;

  let pendingZonePoly = null;
  let pendingTripwirePts = null;
  let pendingHomographyPts = null;

  function initScenarioModals(callbacks) {
    if (modalsInitialized) return;
    modalsInitialized = true;

    const { saveZone, saveTripwire, saveHomography, setMode } = callbacks;

    // 1. Zone Builder Modal
    const modalZone = document.getElementById('modal-studio-zone');
    const formZone = document.getElementById('studio-zone-form');
    const closeZone = () => {
      if (modalZone) modalZone.style.display = 'none';
      pendingZonePoly = null;
      setMode?.('idle');
    };
    document.getElementById('modal-zone-close')?.addEventListener('click', closeZone);
    document.getElementById('modal-zone-cancel')?.addEventListener('click', closeZone);
    formZone?.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!pendingZonePoly) return closeZone();
      const name = (document.getElementById('modal-zone-name-input')?.value || '').trim();
      const cat = (document.getElementById('modal-zone-category-select')?.value || '').trim();
      const dwell = parseFloat(document.getElementById('modal-zone-dwell-input')?.value || '5.0') || 5.0;
      const capVal = parseInt(document.getElementById('modal-zone-capacity-input')?.value || '0', 10);
      const camId = window.Studio?.getActiveCamera?.() || 'cam_01';

      saveZone?.({
        camera_id: camId,
        name: name,
        polygon: pendingZonePoly,
        category_filter: cat,
        dwell_threshold: dwell,
        capacity_limit: capVal > 0 ? capVal : null,
        color: [0, 200, 100],
      });
      closeZone();
    });

    // 2. Tripwire Builder Modal
    const modalTripwire = document.getElementById('modal-studio-tripwire');
    const formTripwire = document.getElementById('studio-tripwire-form');
    const closeTripwire = () => {
      if (modalTripwire) modalTripwire.style.display = 'none';
      pendingTripwirePts = null;
      setMode?.('idle');
    };
    document.getElementById('modal-tripwire-close')?.addEventListener('click', closeTripwire);
    document.getElementById('modal-tripwire-cancel')?.addEventListener('click', closeTripwire);
    formTripwire?.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!pendingTripwirePts) return closeTripwire();
      const name = (document.getElementById('modal-tripwire-name-input')?.value || '').trim();
      const bidir = document.getElementById('modal-tripwire-bidir-select')?.value === '1';
      const camId = window.Studio?.getActiveCamera?.() || 'cam_01';

      saveTripwire?.({
        camera_id: camId,
        name: name,
        line_segment: pendingTripwirePts,
        bidirectional: bidir,
        color: [0, 255, 255],
      });
      closeTripwire();
    });

    // 3. Homography Calibration Modal
    const modalHomography = document.getElementById('modal-studio-homography');
    const formHomography = document.getElementById('studio-homography-form');
    const closeHomography = () => {
      if (modalHomography) modalHomography.style.display = 'none';
      pendingHomographyPts = null;
      setMode?.('idle');
    };
    document.getElementById('modal-homography-close')?.addEventListener('click', closeHomography);
    document.getElementById('modal-homography-cancel')?.addEventListener('click', closeHomography);
    formHomography?.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!pendingHomographyPts) return closeHomography();
      const w = parseFloat(document.getElementById('modal-homography-width-input')?.value || '10.0') || 10.0;
      const h = parseFloat(document.getElementById('modal-homography-height-input')?.value || '10.0') || 10.0;
      const camId = window.Studio?.getActiveCamera?.() || 'cam_01';

      saveHomography?.({
        camera_id: camId,
        src_points: pendingHomographyPts,
        metric_width: w,
        metric_height: h,
      });
      closeHomography();
    });

    // 4. Spatial Transition Modal
    const modalTransition = document.getElementById('modal-studio-transition');
    const formTransition = document.getElementById('studio-transition-form');
    const closeTransition = () => {
      if (modalTransition) modalTransition.style.display = 'none';
    };
    document.getElementById('modal-transition-close')?.addEventListener('click', closeTransition);
    document.getElementById('modal-transition-cancel')?.addEventListener('click', closeTransition);
    formTransition?.addEventListener('submit', (e) => {
      e.preventDefault();
      const srcCam = (document.getElementById('modal-trans-src-cam-input')?.value || '').trim();
      const srcZone = (document.getElementById('modal-trans-src-zone-input')?.value || '').trim();
      const tgtCam = (document.getElementById('modal-trans-tgt-cam-input')?.value || '').trim();
      const tgtZone = (document.getElementById('modal-trans-tgt-zone-input')?.value || '').trim();
      const tMin = parseFloat(document.getElementById('modal-trans-tmin-input')?.value || '2.0') || 2.0;
      const tMax = parseFloat(document.getElementById('modal-trans-tmax-input')?.value || '15.0') || 15.0;
      const boost = parseFloat(document.getElementById('modal-trans-boost-input')?.value || '0.35') || 0.35;
      const bidir = !!document.getElementById('modal-trans-bidir-cb')?.checked;

      if (window.TrackerApp.Topology?.saveLink) {
        window.TrackerApp.Topology.saveLink({
          source_camera: srcCam,
          source_zone: srcZone,
          target_camera: tgtCam,
          target_zone: tgtZone,
          min_transit_seconds: tMin,
          max_transit_seconds: tMax,
          prior_probability: boost,
          bidirectional: bidir,
        });
      }
      closeTransition();
    });
  }

  function openZoneModal(polygon) {
    pendingZonePoly = polygon;
    const nameInput = document.getElementById('modal-zone-name-input');
    if (nameInput) nameInput.value = `zone_${Date.now() % 1000}`;
    const modal = document.getElementById('modal-studio-zone');
    if (modal) modal.style.display = 'flex';
  }

  function openTripwireModal(points) {
    pendingTripwirePts = points;
    const nameInput = document.getElementById('modal-tripwire-name-input');
    if (nameInput) nameInput.value = `tw_${Date.now() % 1000}`;
    const modal = document.getElementById('modal-studio-tripwire');
    if (modal) modal.style.display = 'flex';
  }

  function openHomographyModal(points) {
    pendingHomographyPts = points;
    const modal = document.getElementById('modal-studio-homography');
    if (modal) modal.style.display = 'flex';
  }

  function openTransitionLinkModal(activeCamera) {
    const srcCamInput = document.getElementById('modal-trans-src-cam-input');
    if (srcCamInput) srcCamInput.value = activeCamera || 'cam_01';
    const modal = document.getElementById('modal-studio-transition');
    if (modal) modal.style.display = 'flex';
  }

  function renderScenarioListUI(zones, tripwires, activeCamera, onDeleteZone, onDeleteTripwire) {
    const zoneListEl = document.getElementById('studio-zones-list');
    if (zoneListEl) {
      if (!zones || zones.length === 0) {
        zoneListEl.innerHTML = '<div class="empty-state">No zones defined. Click Draw Zone to create one.</div>';
      } else {
        zoneListEl.innerHTML = zones.map((z) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${z.color[2]}, ${z.color[1]}, ${z.color[0]});"></span>
              <strong>${escapeHtml(z.name)}</strong>
              ${z.capacity_limit ? `<span class="badge">Cap: ${z.capacity_limit}</span>` : ''}
            </div>
            <div class="item-sub">${z.polygon.length} vertices | Dwell: ${z.dwell_threshold}s</div>
            <button class="btn btn-xs btn-outline-danger btn-del-zone" data-name="${escapeHtml(z.name)}">🗑️</button>
          </div>
        `).join('');
        zoneListEl.querySelectorAll('.btn-del-zone').forEach((btn) => {
          btn.addEventListener('click', () => onDeleteZone?.(activeCamera, btn.getAttribute('data-name')));
        });
      }
    }

    const twListEl = document.getElementById('studio-tripwires-list');
    if (twListEl) {
      if (!tripwires || tripwires.length === 0) {
        twListEl.innerHTML = '<div class="empty-state">No tripwires defined. Click Draw Tripwire.</div>';
      } else {
        twListEl.innerHTML = tripwires.map((tw) => `
          <div class="studio-item-card">
            <div class="item-title">
              <span class="color-dot" style="background: rgb(${tw.color[2]}, ${tw.color[1]}, ${tw.color[0]});"></span>
              <strong>${escapeHtml(tw.name)}</strong>
              <span class="badge">${tw.bidirectional ? 'IN/OUT' : 'One-Way'}</span>
            </div>
            <div class="item-sub">(${tw.line_segment[0][0]}, ${tw.line_segment[0][1]}) -> (${tw.line_segment[1][0]}, ${tw.line_segment[1][1]})</div>
            <button class="btn btn-xs btn-outline-danger btn-del-tw" data-name="${escapeHtml(tw.name)}">🗑️</button>
          </div>
        `).join('');
        twListEl.querySelectorAll('.btn-del-tw').forEach((btn) => {
          btn.addEventListener('click', () => onDeleteTripwire?.(activeCamera, btn.getAttribute('data-name')));
        });
      }
    }
  }

  window.TrackerApp.ScenarioModals = {
    init: initScenarioModals,
    openZoneModal: openZoneModal,
    openTripwireModal: openTripwireModal,
    openHomographyModal: openHomographyModal,
    openTransitionLinkModal: openTransitionLinkModal,
    renderScenarioListUI: renderScenarioListUI,
  };
})();

