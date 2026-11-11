/**
 * Intelligent Tracker - Video Library & Upload Management Submodule.
 * Handles recording listing, uploads, codec transcoding, and VMS stream mapping.
 */

(function () {
  'use strict';

  const pairedH264ByFilename = new Map();
  let menuListenersBound = false;

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

  function registerVideos(files) {
    pairedH264ByFilename.clear();
    if (!Array.isArray(files)) return;
    files.forEach(file => {
      if (file && !file.web_compatible && file.has_converted_h264 && file.converted_filename) {
        pairedH264ByFilename.set(file.filename, {
          convertedFilename: file.converted_filename,
          videoUrl: `/videos/${encodeURIComponent(file.converted_filename)}`,
        });
      }
    });
  }

  function getPairedH264(filename) {
    return filename ? (pairedH264ByFilename.get(filename) || null) : null;
  }

  function findMenuHost(el) {
    let cur = el;
    while (cur) {
      if (cur.classList?.contains('video-file-card') || cur.classList?.contains('codec-notice-banner')) {
        return cur;
      }
      cur = cur.parentElement || cur.parentNode || null;
    }
    return null;
  }

  function syncMenuCardElevation(menu, isOpen) {
    const host = findMenuHost(menu);
    if (host) host.classList.toggle('menu-open', Boolean(isOpen));
  }

  function closeAllActionMenus(exceptMenu = null) {
    document.querySelectorAll('.video-action-menu').forEach(menu => {
      if (menu !== exceptMenu) {
        menu.hidden = true;
        syncMenuCardElevation(menu, false);
        const toggle = menu.parentElement?.querySelector('.btn-action-menu-toggle');
        if (toggle) toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function ensureMenuListeners() {
    if (menuListenersBound) return;
    menuListenersBound = true;
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.video-action-dropdown')) closeAllActionMenus();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeAllActionMenus();
    });
  }

  function switchToH264(convertedFilename, convertedUrl) {
    if (!convertedFilename) return;
    const url = convertedUrl || `/videos/${encodeURIComponent(convertedFilename)}`;
    if (typeof window.loadVideoIntoPlayer === 'function') {
      window.loadVideoIntoPlayer(url, convertedFilename, true, 'h264');
    } else {
      window.dispatchEvent(new CustomEvent('video-select-request', { detail: { filename: convertedFilename } }));
    }
  }

  function renderReconvertDropdown(filename, extraClass = '') {
    const safeFile = escapeHtml(filename);
    return `
      <div class="video-action-dropdown ${extraClass}">
        <button type="button" class="btn btn-xs btn-outline btn-action-menu-toggle" data-filename="${safeFile}" aria-haspopup="menu" aria-expanded="false" title="More conversion actions">▾</button>
        <div class="video-action-menu glass-panel" role="menu" hidden>
          <button type="button" role="menuitem" class="btn btn-xs btn-outline btn-reconvert-video" data-filename="${safeFile}" title="Force fresh H.264 transcode">↺ Re-convert</button>
        </div>
      </div>
    `;
  }

  function bindPairedActionControls(container, onReconvert) {
    if (!container) return;
    ensureMenuListeners();

    container.querySelectorAll('.btn-switch-h264').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllActionMenus();
        switchToH264(btn.getAttribute('data-converted'), btn.getAttribute('data-converted-url'));
      });
    });

    container.querySelectorAll('.btn-action-menu-toggle').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const menu = btn.parentElement?.querySelector('.video-action-menu');
        if (!menu) return;
        const willOpen = menu.hidden;
        closeAllActionMenus(willOpen ? menu : null);
        menu.hidden = !willOpen;
        syncMenuCardElevation(menu, willOpen);
        btn.setAttribute('aria-expanded', String(willOpen));
      });
    });

    container.querySelectorAll('.btn-reconvert-video').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllActionMenus();
        const fn = btn.getAttribute('data-filename');
        if (onReconvert) {
          onReconvert(fn, { force: true });
        } else {
          transcodeVideo(fn, null, { force: true });
        }
      });
    });
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

  function showCodecNotice(message, filename, onConvert, options = {}) {
    const notice = getCodecNoticeElement();
    if (!notice) return;
    const paired = options.convertedFilename
      ? { convertedFilename: options.convertedFilename, videoUrl: options.convertedUrl || `/videos/${encodeURIComponent(options.convertedFilename)}` }
      : getPairedH264(filename);

    let actionsHtml = '';
    if (filename && paired?.convertedFilename) {
      actionsHtml = `
        <div class="codec-notice-actions">
          <button type="button" class="btn btn-xs btn-primary btn-switch-h264 btn-notice-switch-h264" data-filename="${escapeHtml(filename)}" data-converted="${escapeHtml(paired.convertedFilename)}" data-converted-url="${escapeHtml(paired.videoUrl)}">▶ Switch to H.264</button>
          ${renderReconvertDropdown(filename, 'notice-dropdown')}
        </div>
      `;
    } else if (filename) {
      actionsHtml = `<button type="button" class="btn btn-xs btn-primary btn-notice-convert" data-filename="${escapeHtml(filename)}">⚡ Convert to H.264</button>`;
    }

    notice.style.display = 'flex';
    notice.innerHTML = `
      <div class="codec-notice-message">
        <span style="color:#f59e0b; font-weight:600;">⚠️ Codec Compatibility:</span> ${escapeHtml(message)}
      </div>
      ${actionsHtml}
    `;

    if (filename && paired?.convertedFilename) {
      bindPairedActionControls(notice, onConvert);
    } else if (onConvert) {
      notice.querySelector('.btn-notice-convert')?.addEventListener('click', () => onConvert(filename, { force: false }));
    }
  }

  function hideCodecNotice() {
    const notice = document.getElementById('scrubber-codec-notice');
    if (notice) notice.style.display = 'none';
  }

  function restoreTranscodeButtonLabel(btn) {
    btn.disabled = false;
    if (btn.classList.contains('btn-reconvert-video')) {
      btn.textContent = '↺ Re-convert';
    } else if (btn.classList.contains('btn-notice-convert')) {
      btn.textContent = '⚡ Convert to H.264';
    } else {
      btn.textContent = '⚡ Convert';
    }
  }

  function handleAlreadyExistsTranscode(filename, res, btns, onSuccess) {
    btns.forEach(restoreTranscodeButtonLabel);
    hideCodecNotice();
    showToast(`Using existing H.264 copy '${res.output_filename}'.`, 'info');
    if (res.output_filename) {
      pairedH264ByFilename.set(filename, {
        convertedFilename: res.output_filename,
        videoUrl: res.video_url || `/videos/${encodeURIComponent(res.output_filename)}`,
      });
    }
    if (onSuccess) {
      onSuccess(res);
    } else {
      if (typeof window.loadVideosList === 'function') window.loadVideosList();
      if (window.VideoJobClient?.currentViewedFilename === filename && res.output_filename) {
        switchToH264(res.output_filename, res.video_url);
      }
    }
  }

  function preservePairedSwitchControls(filename) {
    if (!filename) return;
    const safeSel = CSS.escape(filename);
    document.querySelectorAll(
      `.btn-switch-h264[data-filename="${safeSel}"], .btn-action-menu-toggle[data-filename="${safeSel}"]`
    ).forEach(el => { el.disabled = false; });

    const paired = getPairedH264(filename);
    const notice = document.getElementById('scrubber-codec-notice');
    if (paired && notice && notice.style.display !== 'none' && !notice.querySelector('.btn-switch-h264')) {
      showCodecNotice(`Using existing H.264 copy '${paired.convertedFilename}'.`, filename, null, paired);
    }
    if (typeof window.loadVideosList === 'function') {
      window.loadVideosList();
    }
  }

  async function runDirectTranscode(filename, force, btns, onSuccess) {
    showCodecNotice(`Transcoding '${filename}' to web-compatible H.264 MP4... Please wait.`, null);
    const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/transcode?force=${force}`, {
      method: 'POST',
    });
    if (resp.ok) {
      const data = await resp.json();
      hideCodecNotice();
      if (onSuccess) onSuccess(data);
    } else {
      const err = await resp.json();
      showToast(`Transcoding failed: ${err.detail || 'Error'}`, 'error');
      preservePairedSwitchControls(filename);
    }
    btns.forEach(restoreTranscodeButtonLabel);
  }

  async function transcodeVideo(filename, onSuccess, options = {}) {
    if (!filename) return;
    const force = Boolean(options.force);
    const activeJob = window.VideoJobClient?.getActiveJob(filename);
    if (activeJob) {
      window.VideoJobClient.showConflictModal(
        activeJob,
        'Convert to H.264',
        () => window.VideoJobClient.startTranscode(filename, { ...options, force }).catch(
          err => showToast(`Transcode error: ${err.message}`, 'error')
        ),
        () => {}
      );
      return;
    }

    const btns = document.querySelectorAll(
      `.btn-transcode-video[data-filename="${CSS.escape(filename)}"], .btn-notice-convert[data-filename="${CSS.escape(filename)}"], .btn-reconvert-video[data-filename="${CSS.escape(filename)}"]`
    );
    btns.forEach(b => { b.disabled = true; b.textContent = '⏳ Converting...'; });

    try {
      if (window.VideoJobClient) {
        const res = await window.VideoJobClient.startTranscode(filename, { ...options, force });
        if (res && res.already_exists) handleAlreadyExistsTranscode(filename, res, btns, onSuccess);
      } else {
        await runDirectTranscode(filename, force, btns, onSuccess);
      }
    } catch (e) {
      showToast(`Error during transcoding: ${e.message}`, 'error');
      btns.forEach(restoreTranscodeButtonLabel);
    }
  }

  window.addEventListener('video-job-event', (e) => {
    const { type, data } = e.detail || {};
    if (!data) return;
    const job = data;
    if (job.job_type !== 'transcode') return;

    const btns = document.querySelectorAll(
      `.btn-transcode-video[data-filename="${CSS.escape(job.filename)}"], .btn-notice-convert[data-filename="${CSS.escape(job.filename)}"], .btn-reconvert-video[data-filename="${CSS.escape(job.filename)}"]`
    );

    if (type === 'job-started' || type === 'job-update') {
      if (job.status === 'running' || job.status === 'pending') {
        btns.forEach(b => {
          b.disabled = true;
          b.textContent = `⏳ ${(job.progress || 0).toFixed(0)}%`;
        });
      }
    } else if (type === 'job-finished') {
      btns.forEach(restoreTranscodeButtonLabel);
      if (job.status === 'completed') {
        hideCodecNotice();
        showToast(`Transcoding completed for '${job.filename}'!`, 'success');
        if (job.result?.output_filename) {
          const outUrl = job.result.video_url || `/videos/${encodeURIComponent(job.result.output_filename)}`;
          pairedH264ByFilename.set(job.filename, {
            convertedFilename: job.result.output_filename,
            videoUrl: outUrl,
          });
        }
        if (typeof window.loadVideosList === 'function') {
          window.loadVideosList();
        }
        if (window.VideoJobClient?.currentViewedFilename === job.filename && job.result?.output_filename) {
          const outUrl = job.result.video_url || `/videos/${encodeURIComponent(job.result.output_filename)}`;
          if (typeof window.loadVideoIntoPlayer === 'function') {
            window.loadVideoIntoPlayer(outUrl, job.result.output_filename, true, 'h264');
          }
        }
      } else if (job.status === 'cancelled') {
        preservePairedSwitchControls(job.filename);
        showToast(`Transcoding cancelled for '${job.filename}'.`, 'info');
      } else if (job.status === 'failed') {
        preservePairedSwitchControls(job.filename);
        showToast(`Transcode failed: ${job.error || 'Unknown error'}`, 'error');
      }
    }
  });

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

  function openFeedPromotionModal(filename, videoPath) {
    if (window.VideoFeedModal) {
      window.VideoFeedModal.open(filename, videoPath);
    } else {
      addVideoToCameraPool(filename);
    }
  }

  async function addVideoToCameraPool(filename) {
    if (!filename) return;
    if (window.VideoFeedModal) {
      window.VideoFeedModal.open(filename);
      return;
    }
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

  function setActiveVideoCard(filename) {
    const safeName = filename ? String(filename).trim() : null;
    document.querySelectorAll('.video-file-card').forEach(card => {
      const isMatch = safeName !== null && card.getAttribute('data-file') === safeName;
      card.classList.toggle('active-video', isMatch);
      if (isMatch) {
        card.setAttribute('aria-selected', 'true');
      } else {
        card.removeAttribute('aria-selected');
      }
    });
  }

  function renderVideoFileCard(file, currentFilename) {
    const isH264 = file.web_compatible;
    const hasConverted = Boolean(!isH264 && file.has_converted_h264 && file.converted_filename);
    const isCurrent = Boolean(currentFilename && file.filename === currentFilename);
    const codecBadge = isH264
      ? `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.4);">H.264</span>`
      : `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(245,158,11,0.2); color:#f59e0b; border:1px solid rgba(245,158,11,0.4);">${escapeHtml((file.codec || 'HEVC').toUpperCase())}</span>`;

    let convertControls = '';
    if (!isH264 && hasConverted) {
      const convertedUrl = `/videos/${encodeURIComponent(file.converted_filename)}`;
      convertControls = `
        <button type="button" class="btn btn-xs btn-primary btn-switch-h264" data-filename="${escapeHtml(file.filename)}" data-converted="${escapeHtml(file.converted_filename)}" data-converted-url="${escapeHtml(convertedUrl)}" title="Switch immediately to ${escapeHtml(file.converted_filename)}">▶ Switch to H.264</button>
        ${renderReconvertDropdown(file.filename)}
      `;
    } else if (!isH264) {
      convertControls = `<button type="button" class="btn btn-xs btn-outline btn-transcode-video" data-filename="${escapeHtml(file.filename)}" title="Convert to browser-compatible H.264 MP4">⚡ Convert</button>`;
    }

    return `
      <div class="video-file-card glass-panel ${isCurrent ? 'active-video' : ''}" data-file="${escapeHtml(file.filename)}" data-url="${escapeHtml(file.video_url)}" data-web="${file.web_compatible}" data-codec="${escapeHtml(file.codec || '')}" data-has-converted="${hasConverted}" data-converted="${escapeHtml(file.converted_filename || '')}" role="listitem" ${isCurrent ? 'aria-selected="true"' : ''} tabindex="0" title="Click to load ${escapeHtml(file.filename)}">
        <div class="video-file-icon">📼</div>
        <div class="video-file-meta">
          <div class="video-filename truncate-trigger" data-full-text="${escapeHtml(file.filename)}" data-truncate-label="Video File" title="${escapeHtml(file.filename)}">${escapeHtml(window.TextTruncationManager ? window.TextTruncationManager.format(file.filename, { mode: 'middle', maxLength: 30, preserveExt: true }) : file.filename)}</div>
          <div class="video-filesize">${file.size_mb} MB • ${codecBadge} ${file.resolution ? `• ${file.resolution}` : ''}</div>
        </div>
        <div class="video-file-actions">
          ${convertControls}
          <button type="button" class="btn btn-xs btn-primary btn-select-video" data-url="${escapeHtml(file.video_url)}" data-filename="${escapeHtml(file.filename)}" data-web="${file.web_compatible}" data-codec="${escapeHtml(file.codec)}" data-has-converted="${hasConverted}" data-converted="${escapeHtml(file.converted_filename || '')}">▶ Load</button>
          <button type="button" class="btn btn-xs btn-outline btn-del-video" data-filename="${escapeHtml(file.filename)}">🗑️</button>
        </div>
      </div>
    `;
  }

  window.VideoLibrary = {
    registerVideos: registerVideos,
    getPairedH264: getPairedH264,
    switchToH264: switchToH264,
    bindPairedActionControls: bindPairedActionControls,
    renderVideoFileCard: renderVideoFileCard,
    setActiveVideoCard: setActiveVideoCard,
    showCodecNotice: showCodecNotice,
    hideCodecNotice: hideCodecNotice,
    transcodeVideo: transcodeVideo,
    uploadSelectedVideo: uploadSelectedVideo,
    addVideoToCameraPool: addVideoToCameraPool,
    openFeedPromotionModal: openFeedPromotionModal,
  };
})();
