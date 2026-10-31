/**
 * Intelligent Tracker - Video Library & Upload Management Submodule.
 * Handles recording listing, uploads, codec transcoding, and VMS stream mapping.
 */

(function () {
  'use strict';

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      alert(message);
    }
  }

  function getCodecNoticeElement() {
    let notice = document.getElementById('scrubber-codec-notice');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'scrubber-codec-notice';
      notice.className = 'codec-notice-banner glass-panel';
      const viewport = document.querySelector('.scrubber-viewport');
      if (viewport && viewport.parentNode) {
        viewport.parentNode.insertBefore(notice, viewport);
      }
    }
    return notice;
  }

  function showCodecNotice(message, filename, onConvert) {
    const notice = getCodecNoticeElement();
    if (!notice) return;
    notice.style.display = 'flex';
    notice.style.alignItems = 'center';
    notice.style.justifyContent = 'space-between';
    notice.style.padding = '10px 14px';
    notice.style.marginBottom = '12px';
    notice.style.borderRadius = '8px';
    notice.style.background = 'rgba(245, 158, 11, 0.12)';
    notice.style.border = '1px solid rgba(245, 158, 11, 0.4)';
    notice.style.fontSize = '0.85rem';
    notice.innerHTML = `
      <div style="flex:1; padding-right: 10px;">
        <span style="color:#f59e0b; font-weight:600;">⚠️ Codec Compatibility:</span> ${escapeHtml(message)}
      </div>
      ${filename ? `<button class="btn btn-xs btn-primary btn-notice-convert" data-filename="${escapeHtml(filename)}">⚡ Convert to H.264</button>` : ''}
    `;

    if (onConvert) {
      notice.querySelector('.btn-notice-convert')?.addEventListener('click', () => onConvert(filename));
    }
  }

  function hideCodecNotice() {
    const notice = document.getElementById('scrubber-codec-notice');
    if (notice) notice.style.display = 'none';
  }

  async function transcodeVideo(filename, onSuccess) {
    if (!filename) return;
    const btns = document.querySelectorAll(
      `.btn-transcode-video[data-filename="${CSS.escape(filename)}"], .btn-notice-convert[data-filename="${CSS.escape(filename)}"]`
    );
    btns.forEach(b => {
      b.disabled = true;
      b.textContent = '⏳ Converting...';
    });
    showCodecNotice(`Transcoding '${filename}' to web-compatible H.264 MP4... Please wait.`, null);

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/transcode`, {
        method: 'POST'
      });
      if (resp.ok) {
        const data = await resp.json();
        hideCodecNotice();
        if (onSuccess) onSuccess(data);
      } else {
        const err = await resp.json();
        showToast(`Transcoding failed: ${err.detail || 'Error'}`, 'error');
      }
    } catch (e) {
      showToast(`Error during transcoding: ${e.message}`, 'error');
    } finally {
      btns.forEach(b => {
        b.disabled = false;
        b.textContent = '⚡ Convert';
      });
    }
  }

  async function uploadSelectedVideo(e, onUploaded) {
    const file = e.target.files[0];
    const statusEl = document.getElementById('video-upload-status');
    const inputEl = document.getElementById('video-file-upload-input');
    if (!file || !statusEl) return;

    const formData = new FormData();
    formData.append('file', file);
    statusEl.textContent = `Uploading ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)...`;

    try {
      const resp = await fetch('/api/videos/upload', {
        method: 'POST',
        body: formData,
      });

      if (resp.ok) {
        const res = await resp.json();
        statusEl.innerHTML = `<span style="color:#10b981;">✓ Uploaded '${escapeHtml(res.filename)}'</span>`;
        if (onUploaded) onUploaded(res);
      } else {
        const err = await resp.json();
        statusEl.innerHTML = `<span style="color:#ef4444;">✗ Upload failed: ${escapeHtml(err.detail || 'Error')}</span>`;
      }
    } catch (err) {
      statusEl.innerHTML = `<span style="color:#ef4444;">✗ Network error: ${escapeHtml(err.message)}</span>`;
    } finally {
      if (inputEl) inputEl.value = '';
    }
  }

  async function addVideoToCameraPool(filename) {
    if (!filename) return;
    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/add_as_camera`, {
        method: 'POST'
      });
      if (resp.ok) {
        const data = await resp.json();
        showToast(`Video successfully added as active stream '${data.camera_id}'!`, 'success');
        if (window.CameraManager) {
          await window.CameraManager.refreshCameras();
          window.CameraManager.focusCamera(data.camera_id);
        }
      } else {
        showToast('Failed to add video as camera.', 'error');
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, 'error');
    }
  }

  function renderVideoFileCard(file, currentFilename) {
    const isH264 = file.web_compatible;
    const codecBadge = isH264
      ? `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.4);">H.264</span>`
      : `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(245,158,11,0.2); color:#f59e0b; border:1px solid rgba(245,158,11,0.4);">${escapeHtml((file.codec || 'HEVC').toUpperCase())}</span>`;

    const convertBtn = !isH264
      ? `<button class="btn btn-xs btn-outline btn-transcode-video" data-filename="${escapeHtml(file.filename)}" title="Convert to browser-compatible H.264 MP4">⚡ Convert</button>`
      : '';

    return `
      <div class="video-file-card glass-panel ${file.filename === currentFilename ? 'active-video' : ''}" data-file="${escapeHtml(file.filename)}">
        <div class="video-file-icon">📼</div>
        <div class="video-file-meta">
          <div class="video-filename" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</div>
          <div class="video-filesize">${file.size_mb} MB • ${codecBadge} ${file.resolution ? `• ${file.resolution}` : ''}</div>
        </div>
        <div class="video-file-actions">
          ${convertBtn}
          <button class="btn btn-xs btn-primary btn-select-video" data-url="${escapeHtml(file.video_url)}" data-filename="${escapeHtml(file.filename)}" data-web="${file.web_compatible}" data-codec="${escapeHtml(file.codec)}">▶ Load</button>
          <button class="btn btn-xs btn-outline btn-del-video" data-filename="${escapeHtml(file.filename)}">🗑️</button>
        </div>
      </div>
    `;
  }

  window.VideoLibrary = {
    renderVideoFileCard: renderVideoFileCard,
    showCodecNotice: showCodecNotice,
    hideCodecNotice: hideCodecNotice,
    transcodeVideo: transcodeVideo,
    uploadSelectedVideo: uploadSelectedVideo,
    addVideoToCameraPool: addVideoToCameraPool,
  };
})();

