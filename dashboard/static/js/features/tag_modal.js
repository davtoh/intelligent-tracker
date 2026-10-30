/**
 * Intelligent Tracker - Click-to-Tag Modal Dialog Controller.
 * Manages identity tagging from active bounding boxes and Re-ID registration.
 */

window.TrackerApp = window.TrackerApp || {};

(function () {
  'use strict';

  const showToast = window.showToast || ((m, t) => console.log(m, t));

  const modalTag = document.getElementById('modal-tag-entity');
  const tagForm = document.getElementById('tag-entity-form');
  const tagTrackId = document.getElementById('tag-track-id');
  const tagBboxVal = document.getElementById('tag-bbox-val');
  const tagNameInput = document.getElementById('tag-name-input');
  const tagCategorySelect = document.getElementById('tag-category-select');
  const tagNotesInput = document.getElementById('tag-notes-input');
  const modalTagClose = document.getElementById('modal-tag-close');
  const modalTagCancel = document.getElementById('modal-tag-cancel');

  function openTagModal(track, cameraId = 'cam_01') {
    if (!modalTag) return;
    modalTag.style.display = 'flex';
    if (track) {
      if (tagTrackId) tagTrackId.value = track.id;
      if (tagBboxVal) tagBboxVal.value = JSON.stringify(track.bbox);
      if (tagNameInput) tagNameInput.value = track.entity_name || '';
      if (tagCategorySelect) tagCategorySelect.value = track.category || 'person';
      const title = document.getElementById('tag-modal-title');
      if (title) title.textContent = `🏷️ Tag Active Track #${track.id}`;
    } else {
      if (tagTrackId) tagTrackId.value = '';
      if (tagBboxVal) tagBboxVal.value = '';
      if (tagNameInput) tagNameInput.value = '';
      if (tagCategorySelect) tagCategorySelect.value = 'person';
      const title = document.getElementById('tag-modal-title');
      if (title) title.textContent = '🏷️ Enroll New Identity';
    }
    tagNameInput?.focus();
  }

  function closeTagModal() {
    if (modalTag) modalTag.style.display = 'none';
    tagForm?.reset();
  }

  function initTagModal() {
    modalTagClose?.addEventListener('click', closeTagModal);
    modalTagCancel?.addEventListener('click', closeTagModal);

    tagForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = tagNameInput?.value.trim();
      const category = tagCategorySelect?.value || 'person';
      const notes = tagNotesInput?.value.trim() || '';
      const trackId = tagTrackId?.value ? parseInt(tagTrackId.value, 10) : null;
      const bbox = tagBboxVal?.value ? JSON.parse(tagBboxVal.value) : null;
      const camId = window.TrackerApp.LivePlayer?.getActiveCamera?.() || 'cam_01';

      if (!name) return;

      try {
        const res = await fetch('/tag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entity_name: name,
            category: category,
            track_id: trackId,
            bbox: bbox,
            notes: notes,
            camera_id: camId,
          }),
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Tagging failed');
        }

        closeTagModal();
        showToast('Entity Enrolled', `Successfully enrolled "${name}" as ${category.toUpperCase()} into Re-ID Gallery!`, 'success');
        if (window.TrackerApp.Gallery?.load) {
          window.TrackerApp.Gallery.load();
        }
      } catch (err) {
        showToast('Enrollment Failed', err.message, 'error');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTagModal);
  } else {
    initTagModal();
  }

  window.TrackerApp.TagModal = {
    open: openTagModal,
    close: closeTagModal,
  };
})();

