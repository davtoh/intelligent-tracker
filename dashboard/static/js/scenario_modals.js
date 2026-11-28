/**
 * Intelligent Tracker - Scenario Studio In-Page Modals Submodule.
 * Handles zone, tripwire, homography calibration, and spatial transition dialogs.
 */

(function () {
  'use strict';

  let pendingZonePolygon = null;
  let pendingTripwirePoints = null;
  let pendingHomographyPoints = null;
  let editingZone = null;
  let editingTripwire = null;
  let studioModalsInitialized = false;

  function setModalHeading(modalId, titleText, submitId, submitText) {
    const h = document.getElementById(modalId)?.querySelector?.('h3');
    if (h) h.textContent = titleText;
    const btn = document.getElementById(submitId);
    if (btn) btn.textContent = submitText;
  }

  function initZoneModal(onSaveZone, onCancel) {
    const modalZone = document.getElementById('modal-studio-zone');
    const formZone = document.getElementById('studio-zone-form');

    const closeZone = (notifyCancel = true) => {
      if (modalZone) modalZone.style.display = 'none';
      pendingZonePolygon = null;
      editingZone = null;
      if (notifyCancel && onCancel) onCancel();
    };

    document.getElementById('modal-zone-close')?.addEventListener('click', () => closeZone(true));
    document.getElementById('modal-zone-cancel')?.addEventListener('click', () => closeZone(true));

    if (formZone) {
      formZone.addEventListener('submit', (e) => {
        e.preventDefault();
        const name = (document.getElementById('modal-zone-name-input')?.value || '').trim();
        const cat = (document.getElementById('modal-zone-category-select')?.value || '').trim();
        const dwell = parseFloat(document.getElementById('modal-zone-dwell-input')?.value || '5.0') || 5.0;
        const capVal = parseInt(document.getElementById('modal-zone-capacity-input')?.value || '0', 10);
        const cap = capVal > 0 ? capVal : null;
        if (editingZone) {
          const editCtx = editingZone;
          closeZone(false);
          if (editCtx.onUpdate) {
            editCtx.onUpdate(editCtx.cameraId, editCtx.originalName, {
              name, category_filter: cat, dwell_threshold: dwell, capacity_limit: cap,
            });
          }
          return;
        }
        if (!pendingZonePolygon) return closeZone(true);
        if (onSaveZone) {
          onSaveZone({
            name, polygon: pendingZonePolygon, category_filter: cat,
            dwell_threshold: dwell, capacity_limit: cap, color: [0, 200, 100],
          });
        }
        closeZone(true);
      });
    }
  }

  function initTripwireModal(onSaveTripwire, onCancel) {
    const modalTripwire = document.getElementById('modal-studio-tripwire');
    const formTripwire = document.getElementById('studio-tripwire-form');

    const closeTripwire = (notifyCancel = true) => {
      if (modalTripwire) modalTripwire.style.display = 'none';
      pendingTripwirePoints = null;
      editingTripwire = null;
      if (notifyCancel && onCancel) onCancel();
    };

    document.getElementById('modal-tripwire-close')?.addEventListener('click', () => closeTripwire(true));
    document.getElementById('modal-tripwire-cancel')?.addEventListener('click', () => closeTripwire(true));

    if (formTripwire) {
      formTripwire.addEventListener('submit', (e) => {
        e.preventDefault();
        const name = (document.getElementById('modal-tripwire-name-input')?.value || '').trim();
        const bidir = document.getElementById('modal-tripwire-bidir-select')?.value === '1';
        if (editingTripwire) {
          const editCtx = editingTripwire;
          closeTripwire(false);
          if (editCtx.onUpdate) editCtx.onUpdate(editCtx.cameraId, editCtx.originalName, { name, bidirectional: bidir });
          return;
        }
        if (!pendingTripwirePoints) return closeTripwire(true);
        if (onSaveTripwire) {
          onSaveTripwire({ name, line_segment: pendingTripwirePoints, bidirectional: bidir, color: [0, 255, 255] });
        }
        closeTripwire(true);
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
    editingZone = null;
    setModalHeading('modal-studio-zone', 'Configure Spatial Zone', 'btn-modal-zone-save', 'Save Zone');
    const nameInput = document.getElementById('modal-zone-name-input');
    if (nameInput) nameInput.value = `zone_${Date.now() % 1000}`;
    const catSel = document.getElementById('modal-zone-category-select');
    if (catSel) catSel.value = '';
    const dwellIn = document.getElementById('modal-zone-dwell-input');
    if (dwellIn) dwellIn.value = '5.0';
    const capIn = document.getElementById('modal-zone-capacity-input');
    if (capIn) capIn.value = '0';
    const modal = document.getElementById('modal-studio-zone');
    if (modal) modal.style.display = 'flex';
  }

  function openEditZoneModal(zone, cameraId, onUpdate) {
    if (!zone) return;
    pendingZonePolygon = null;
    editingZone = { cameraId, originalName: zone.name, onUpdate };
    setModalHeading('modal-studio-zone', 'Edit Spatial Zone', 'btn-modal-zone-save', 'Update Zone');
    const nameInput = document.getElementById('modal-zone-name-input');
    if (nameInput) nameInput.value = zone.name || '';
    const catSel = document.getElementById('modal-zone-category-select');
    if (catSel) catSel.value = zone.category_filter || '';
    const dwellIn = document.getElementById('modal-zone-dwell-input');
    if (dwellIn) dwellIn.value = String(zone.dwell_threshold ?? 5.0);
    const capIn = document.getElementById('modal-zone-capacity-input');
    if (capIn) capIn.value = String(zone.capacity_limit ?? 0);
    const modal = document.getElementById('modal-studio-zone');
    if (modal) modal.style.display = 'flex';
  }

  function openTripwireModal(points) {
    pendingTripwirePoints = points;
    editingTripwire = null;
    setModalHeading('modal-studio-tripwire', 'Configure Tripwire Line', 'btn-modal-tripwire-save', 'Save Tripwire');
    const nameInput = document.getElementById('modal-tripwire-name-input');
    if (nameInput) nameInput.value = `tw_${Date.now() % 1000}`;
    const bidirSel = document.getElementById('modal-tripwire-bidir-select');
    if (bidirSel) bidirSel.value = '1';
    const modal = document.getElementById('modal-studio-tripwire');
    if (modal) modal.style.display = 'flex';
  }

  function openEditTripwireModal(tripwire, cameraId, onUpdate) {
    if (!tripwire) return;
    pendingTripwirePoints = null;
    editingTripwire = { cameraId, originalName: tripwire.name, onUpdate };
    setModalHeading('modal-studio-tripwire', 'Edit Tripwire Line', 'btn-modal-tripwire-save', 'Update Tripwire');
    const nameInput = document.getElementById('modal-tripwire-name-input');
    if (nameInput) nameInput.value = tripwire.name || '';
    const bidirSel = document.getElementById('modal-tripwire-bidir-select');
    if (bidirSel) bidirSel.value = tripwire.bidirectional ? '1' : '0';
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
    if (srcCamInput) srcCamInput.value = activeCamera || window.App?.getActiveCameraId?.() || '';
    const modal = document.getElementById('modal-studio-transition');
    if (modal) modal.style.display = 'flex';
  }

  window.ScenarioModals = {
    init: initStudioModals,
    openZoneModal: openZoneModal,
    openEditZoneModal: openEditZoneModal,
    openTripwireModal: openTripwireModal,
    openEditTripwireModal: openEditTripwireModal,
    openHomographyModal: openHomographyModal,
    openTransitionLinkModal: openTransitionLinkModal,
  };
})();

