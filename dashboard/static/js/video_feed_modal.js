/**
 * Intelligent Tracker - Video Feed Promotion Modal Submodule.
 * Handles promoting recorded video files to live active camera streams with custom AI detector models.
 */

(function () {
  'use strict';

  let currentPromotionFilename = null;
  let currentPromotionPath = null;

  function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      alert(message);
    }
  }

  function syncFeedConfidence(val) {
    const num = Math.min(Math.max(parseFloat(val) || 0.40, 0.05), 1.00);
    const formatted = num.toFixed(2);

    const range = document.getElementById('feed-conf-range');
    const input = document.getElementById('feed-conf-input');
    const display = document.getElementById('feed-conf-display');

    if (range && range.value !== formatted) range.value = formatted;
    if (input && input.value !== formatted) input.value = formatted;
    if (display) display.textContent = formatted;
  }

  function openModal(filename, videoPath) {
    if (!filename) return;
    currentPromotionFilename = filename;
    currentPromotionPath = videoPath || (`data/videos/${filename}`);

    const modal = document.getElementById('modal-feed-promotion');
    if (!modal) return;

    const sub = document.getElementById('feed-modal-filename-sub');
    if (sub) {
      const fullText = `Recording: ${filename}`;
      if (window.TextTruncationManager) {
        window.TextTruncationManager.apply(sub, {
          fullText: fullText,
          mode: 'middle',
          maxLength: 38,
          preserveExt: true,
          label: 'Recording File'
        });
      } else {
        sub.textContent = fullText;
        sub.title = fullText;
      }
    }

    const baseId = filename.replace(/\.[^/.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_').toLowerCase();
    const defaultId = `vid_${baseId}`;
    const defaultName = `Video (${filename})`;

    const camIdInput = document.getElementById('feed-cam-id-input');
    if (camIdInput) camIdInput.value = defaultId;

    const camNameInput = document.getElementById('feed-cam-name-input');
    if (camNameInput) camNameInput.value = defaultName;

    const sourceInput = document.getElementById('feed-cam-source-input');
    if (sourceInput) sourceInput.value = currentPromotionPath;

    const detSelect = document.getElementById('feed-detector-select');
    if (detSelect) detSelect.value = 'yolov8';

    const trkSelect = document.getElementById('feed-tracker-select');
    if (trkSelect) trkSelect.value = 'centroid';

    syncFeedConfidence(0.40);

    const classesInput = document.getElementById('feed-classes-input');
    if (classesInput) classesInput.value = '';

    document.querySelectorAll('.btn-tag-preset[data-target="feed"]').forEach(b => {
      b.classList.remove('active');
    });

    modal.style.display = 'flex';
  }

  function closeModal() {
    const modal = document.getElementById('modal-feed-promotion');
    if (modal) modal.style.display = 'none';
  }

  async function promoteVideoToCamera(filename, config) {
    if (!filename || !config) return;
    const submitBtn = document.getElementById('btn-feed-modal-submit');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '⏳ Adding Stream...';
    }

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/add_as_camera`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });

      if (resp.ok) {
        const data = await resp.json();
        showToast(`Video successfully added as active stream '${data.camera_id}'!`, 'success');
        closeModal();
        if (window.CameraManager) {
          await window.CameraManager.refreshCameras();
          window.CameraManager.focusCamera(data.camera_id);
        }
      } else {
        const err = await resp.json();
        showToast(`Failed to add video as camera: ${err.detail || 'Error'}`, 'error');
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '➕ Register as Active Camera';
      }
    }
  }

  function bindEvents() {
    const modal = document.getElementById('modal-feed-promotion');
    const closeBtn = document.getElementById('modal-feed-close');
    const cancelBtn = document.getElementById('modal-feed-cancel');
    const form = document.getElementById('feed-promotion-form');
    const confRange = document.getElementById('feed-conf-range');
    const confInput = document.getElementById('feed-conf-input');

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
    }

    if (confRange) {
      confRange.addEventListener('input', (e) => syncFeedConfidence(e.target.value));
    }
    if (confInput) {
      confInput.addEventListener('input', (e) => syncFeedConfidence(e.target.value));
      confInput.addEventListener('change', (e) => syncFeedConfidence(e.target.value));
    }

    // Preset tag buttons
    document.querySelectorAll('.btn-tag-preset[data-target="feed"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const classes = e.currentTarget.getAttribute('data-classes') || '';
        const classesInput = document.getElementById('feed-classes-input');
        if (classesInput) classesInput.value = classes;

        document.querySelectorAll('.btn-tag-preset[data-target="feed"]').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const camId = (document.getElementById('feed-cam-id-input')?.value || '').trim();
        const camName = (document.getElementById('feed-cam-name-input')?.value || '').trim();
        const detector = document.getElementById('feed-detector-select')?.value || 'yolov8';
        const tracker = document.getElementById('feed-tracker-select')?.value || 'centroid';
        const confVal = parseFloat(document.getElementById('feed-conf-input')?.value || '0.40');
        const confidence = isNaN(confVal) ? 0.40 : Math.min(Math.max(confVal, 0.05), 1.00);

        const classesRaw = (document.getElementById('feed-classes-input')?.value || '').trim();
        const classes = classesRaw
          ? classesRaw.split(',').map(s => s.trim()).filter(Boolean)
          : null;

        promoteVideoToCamera(currentPromotionFilename, {
          camera_id: camId,
          name: camName,
          detector: detector,
          tracker: tracker,
          confidence: confidence,
          classes: classes,
        });
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal && modal.style.display === 'flex') {
        closeModal();
      }
    });
  }

  function init() {
    bindEvents();
  }

  window.VideoFeedModal = {
    init: init,
    open: openModal,
    close: closeModal,
    promoteVideoToCamera: promoteVideoToCamera,
    syncConfidence: syncFeedConfidence,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

