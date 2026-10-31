/**
 * Intelligent Tracker - Scenario Studio In-Page Modals Submodule.
 * Handles zone, tripwire, homography calibration, and spatial transition dialogs.
 */

(function () {
  'use strict';

  let pendingZonePolygon = null;
  let pendingTripwirePoints = null;
  let pendingHomographyPoints = null;
  let studioModalsInitialized = false;

  function initZoneModal(onSaveZone, onCancel) {
    const modalZone = document.getElementById('modal-studio-zone');
    const formZone = document.getElementById('studio-zone-form');

    const closeZone = () => {
      if (modalZone) modalZone.style.display = 'none';
      pendingZonePolygon = null;
      if (onCancel) onCancel();
    };

    document.getElementById('modal-zone-close')?.addEventListener('click', closeZone);
    document.getElementById('modal-zone-cancel')?.addEventListener('click', closeZone);

    if (formZone) {
      formZone.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!pendingZonePolygon) return closeZone();
        const name = (document.getElementById('modal-zone-name-input')?.value || '').trim();
        const cat = (document.getElementById('modal-zone-category-select')?.value || '').trim();
        const dwell = parseFloat(document.getElementById('modal-zone-dwell-input')?.value || '5.0') || 5.0;
        const capVal = parseInt(document.getElementById('modal-zone-capacity-input')?.value || '0', 10);

        if (onSaveZone) {
          onSaveZone({
            name: name,
            polygon: pendingZonePolygon,
            category_filter: cat,
            dwell_threshold: dwell,
            capacity_limit: capVal > 0 ? capVal : null,
            color: [0, 200, 100],
          });
        }
        closeZone();
      });
    }
  }

  function initTripwireModal(onSaveTripwire, onCancel) {
    const modalTripwire = document.getElementById('modal-studio-tripwire');
    const formTripwire = document.getElementById('studio-tripwire-form');

    const closeTripwire = () => {
      if (modalTripwire) modalTripwire.style.display = 'none';
      pendingTripwirePoints = null;
      if (onCancel) onCancel();
    };

    document.getElementById('modal-tripwire-close')?.addEventListener('click', closeTripwire);
    document.getElementById('modal-tripwire-cancel')?.addEventListener('click', closeTripwire);

    if (formTripwire) {
      formTripwire.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!pendingTripwirePoints) return closeTripwire();
        const name = (document.getElementById('modal-tripwire-name-input')?.value || '').trim();
        const bidir = document.getElementById('modal-tripwire-bidir-select')?.value === '1';

        if (onSaveTripwire) {
          onSaveTripwire({
            name: name,
            line_segment: pendingTripwirePoints,
            bidirectional: bidir,
            color: [0, 255, 255],
          });
        }
        closeTripwire();
      });
    }
  }

  function initHomographyModal(onSaveHomography, onCancel) {
    const modalHomography = document.getElementById('modal-studio-homography');
    const formHomography = document.getElementById('studio-homography-form');

    const closeHomography = () => {
      if (modalHomography) modalHomography.style.display = 'none';
      pendingHomographyPoints = null;
      if (onCancel) onCancel();
    };

    document.getElementById('modal-homography-close')?.addEventListener('click', closeHomography);
    document.getElementById('modal-homography-cancel')?.addEventListener('click', closeHomography);

    if (formHomography) {
      formHomography.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!pendingHomographyPoints) return closeHomography();
        const w = parseFloat(document.getElementById('modal-homography-width-input')?.value || '10.0') || 10.0;
        const h = parseFloat(document.getElementById('modal-homography-height-input')?.value || '10.0') || 10.0;

        if (onSaveHomography) {
          onSaveHomography({
            src_points: pendingHomographyPoints,
            metric_width: w,
            metric_height: h,
          });
        }
        closeHomography();
      });
    }
  }

  function initTransitionModal(onSaveTransition) {
    const modalTransition = document.getElementById('modal-studio-transition');
    const formTransition = document.getElementById('studio-transition-form');

    const closeTransition = () => {
      if (modalTransition) modalTransition.style.display = 'none';
    };

    document.getElementById('modal-transition-close')?.addEventListener('click', closeTransition);
    document.getElementById('modal-transition-cancel')?.addEventListener('click', closeTransition);

    if (formTransition) {
      formTransition.addEventListener('submit', (e) => {
        e.preventDefault();
        const srcCam = (document.getElementById('modal-trans-src-cam-input')?.value || '').trim();
        const srcZone = (document.getElementById('modal-trans-src-zone-input')?.value || '').trim();
        const tgtCam = (document.getElementById('modal-trans-tgt-cam-input')?.value || '').trim();
        const tgtZone = (document.getElementById('modal-trans-tgt-zone-input')?.value || '').trim();
        const tMin = parseFloat(document.getElementById('modal-trans-tmin-input')?.value || '2.0') || 2.0;
        const tMax = parseFloat(document.getElementById('modal-trans-tmax-input')?.value || '15.0') || 15.0;
        const boost = parseFloat(document.getElementById('modal-trans-boost-input')?.value || '0.35') || 0.35;
        const bidir = !!document.getElementById('modal-trans-bidir-cb')?.checked;

        if (onSaveTransition) {
          onSaveTransition({
            source_camera: srcCam,
            source_zone: srcZone,
            target_camera: tgtCam,
            target_zone: tgtZone,
            t_min: tMin,
            t_max: tMax,
            prior_boost: boost,
            bidirectional: bidir,
          });
        }
        closeTransition();
      });
    }
  }

  function initStudioModals(handlers) {
    if (studioModalsInitialized) return;
    studioModalsInitialized = true;

    initZoneModal(handlers.onSaveZone, handlers.onCancel);
    initTripwireModal(handlers.onSaveTripwire, handlers.onCancel);
    initHomographyModal(handlers.onSaveHomography, handlers.onCancel);
    initTransitionModal(handlers.onSaveTransition);
  }

  function openZoneModal(polygon) {
    pendingZonePolygon = polygon;
    const nameInput = document.getElementById('modal-zone-name-input');
    if (nameInput) nameInput.value = `zone_${Date.now() % 1000}`;
    const modal = document.getElementById('modal-studio-zone');
    if (modal) modal.style.display = 'flex';
  }

  function openTripwireModal(points) {
    pendingTripwirePoints = points;
    const nameInput = document.getElementById('modal-tripwire-name-input');
    if (nameInput) nameInput.value = `tw_${Date.now() % 1000}`;
    const modal = document.getElementById('modal-studio-tripwire');
    if (modal) modal.style.display = 'flex';
  }

  function openHomographyModal(points) {
    pendingHomographyPoints = points;
    const modal = document.getElementById('modal-studio-homography');
    if (modal) modal.style.display = 'flex';
  }

  function openTransitionLinkModal(activeCamera) {
    const srcCamInput = document.getElementById('modal-trans-src-cam-input');
    if (srcCamInput) srcCamInput.value = activeCamera || 'cam_01';
    const modal = document.getElementById('modal-studio-transition');
    if (modal) modal.style.display = 'flex';
  }

  window.ScenarioModals = {
    init: initStudioModals,
    openZoneModal: openZoneModal,
    openTripwireModal: openTripwireModal,
    openHomographyModal: openHomographyModal,
    openTransitionLinkModal: openTransitionLinkModal,
  };
})();

