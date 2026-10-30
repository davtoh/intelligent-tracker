/**
 * Intelligent Tracker - Video Studio & Playback Scrubber Controller.
 * 
 * Provides:
 * - Local video upload & listing (.mp4, .avi, .mkv, .mov)
 * - Frame-stepping scrubber (< 1 frame, > 1 frame)
 * - Variable playback speed (1x, 2x, 4x, 8x)
 * - Dynamic addition of recording as an active Camera Stream
 * - In-browser batch occurrence report generation
 */

(function () {
  'use strict';

  let currentVideoUrl = null;
  let currentVideoFilename = null;

  // DOM Elements
  const videoPlayer = document.getElementById('scrubber-video-player');
  const videoFileInput = document.getElementById('video-file-upload-input');
  const btnUploadVideo = document.getElementById('btn-upload-video');
  const videoUploadStatus = document.getElementById('video-upload-status');
  const videoFilesList = document.getElementById('video-recordings-list');

  // Scrubber Controls
  const btnPlayPause = document.getElementById('scrubber-btn-play');
  const btnStepBack = document.getElementById('scrubber-btn-prev');
  const btnStepForward = document.getElementById('scrubber-btn-next');
  const timelineSlider = document.getElementById('scrubber-timeline-slider');
  const timelineTimeDisplay = document.getElementById('scrubber-time-display');
  const btnSpeed1x = document.getElementById('speed-btn-1x');
  const btnSpeed2x = document.getElementById('speed-btn-2x');
  const btnSpeed4x = document.getElementById('speed-btn-4x');
  const btnSpeed8x = document.getElementById('speed-btn-8x');

  // Video Actions
  const btnAddAsCamera = document.getElementById('btn-video-add-camera');
  const btnAnalyzeVideo = document.getElementById('btn-video-analyze');
  const batchReportContainer = document.getElementById('video-batch-report-container');
  const selectTabPolicy = document.getElementById('scrubber-tab-policy');

  // Tab-Switching Lifecycle & Resource Policy State
  let tabPolicy = localStorage.getItem('intelligent_tracker_tab_policy') || 'auto-resume';
  let wasPlayingBeforeTabSwitch = false;
  let savedTimeBeforeTabSwitch = 0;

  function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      alert(message);
    }
  }

  function init() {
    bindEvents();
    loadVideosList();
  }

  function bindEvents() {
    if (selectTabPolicy) {
      selectTabPolicy.value = tabPolicy;
      selectTabPolicy.addEventListener('change', (e) => {
        tabPolicy = e.target.value;
        localStorage.setItem('intelligent_tracker_tab_policy', tabPolicy);
      });
    }

    if (btnUploadVideo && videoFileInput) {
      btnUploadVideo.addEventListener('click', () => videoFileInput.click());
      videoFileInput.addEventListener('change', uploadSelectedVideo);
    }

    if (videoPlayer) {
      videoPlayer.addEventListener('timeupdate', updateTimeline);
      videoPlayer.addEventListener('loadedmetadata', onVideoLoaded);
      videoPlayer.addEventListener('play', () => {
        if (btnPlayPause && !videoPlayer.paused) btnPlayPause.textContent = '⏸ Pause';
      });
      videoPlayer.addEventListener('pause', () => {
        if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      });
      videoPlayer.addEventListener('ended', () => {
        if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      });
      videoPlayer.addEventListener('error', handleVideoPlayerError);
    }

    if (btnPlayPause) {
      btnPlayPause.addEventListener('click', togglePlayPause);
    }

    if (btnStepBack) {
      btnStepBack.addEventListener('click', () => stepFrame(-1));
    }

    if (btnStepForward) {
      btnStepForward.addEventListener('click', () => stepFrame(1));
    }

    if (timelineSlider) {
      timelineSlider.addEventListener('input', (e) => {
        if (videoPlayer && videoPlayer.duration) {
          videoPlayer.currentTime = (e.target.value / 100) * videoPlayer.duration;
        }
      });
    }

    // Playback Speed buttons
    const speedButtons = [
      { btn: btnSpeed1x, rate: 1.0 },
      { btn: btnSpeed2x, rate: 2.0 },
      { btn: btnSpeed4x, rate: 4.0 },
      { btn: btnSpeed8x, rate: 8.0 }
    ];

    speedButtons.forEach(({ btn, rate }) => {
      if (btn) {
        btn.addEventListener('click', () => {
          if (videoPlayer) videoPlayer.playbackRate = rate;
          speedButtons.forEach(s => s.btn?.classList.remove('active'));
          btn.classList.add('active');
        });
      }
    });

    // Add as camera
    if (btnAddAsCamera) {
      btnAddAsCamera.addEventListener('click', addVideoToCameraPool);
    }

    // Batch analyze
    if (btnAnalyzeVideo) {
      btnAnalyzeVideo.addEventListener('click', runBatchAnalytics);
    }
  }

  function handleVideoPlayerError() {
    const err = videoPlayer?.error;
    let msg = 'Browser error playing video recording.';
    if (err && err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      msg = `Codec not supported natively by browser (e.g. HEVC/H.265). Convert to standard H.264 MP4 for instant browser playback.`;
    }
    showCodecNotice(msg, currentVideoFilename);
  }

  function showCodecNotice(message, filename) {
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

    notice.querySelector('.btn-notice-convert')?.addEventListener('click', () => {
      if (filename) transcodeVideo(filename);
    });
  }

  function hideCodecNotice() {
    const notice = document.getElementById('scrubber-codec-notice');
    if (notice) notice.style.display = 'none';
  }

  async function transcodeVideo(filename) {
    if (!filename) return;
    const btns = document.querySelectorAll(`.btn-transcode-video[data-filename="${CSS.escape(filename)}"], .btn-notice-convert[data-filename="${CSS.escape(filename)}"]`);
    btns.forEach(b => {
      b.disabled = true;
      b.textContent = '⏳ Converting...';
    });
    showCodecNotice(`Transcoding '${filename}' to web-compatible H.264 MP4... Please wait.`);

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(filename)}/transcode`, {
        method: 'POST'
      });
      if (resp.ok) {
        const data = await resp.json();
        hideCodecNotice();
        await loadVideosList();
        loadVideoIntoPlayer(data.video_url, data.output_filename, true, 'h264');
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

  async function loadVideosList() {
    if (!videoFilesList) return;
    try {
      const resp = await fetch('/api/videos');
      const files = await resp.json();

      if (!files || files.length === 0) {
        videoFilesList.innerHTML = '<div class="empty-state">No uploaded recordings found. Upload an MP4 or MKV recording to scrub and analyze.</div>';
        return;
      }

      videoFilesList.innerHTML = files.map(file => {
        const isH264 = file.web_compatible;
        const codecBadge = isH264
          ? `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.4);">H.264</span>`
          : `<span style="font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(245,158,11,0.2); color:#f59e0b; border:1px solid rgba(245,158,11,0.4);">${escapeHtml((file.codec || 'HEVC').toUpperCase())}</span>`;

        const convertBtn = !isH264
          ? `<button class="btn btn-xs btn-outline btn-transcode-video" data-filename="${escapeHtml(file.filename)}" title="Convert to browser-compatible H.264 MP4">⚡ Convert</button>`
          : '';

        return `
        <div class="video-file-card glass-panel ${file.filename === currentVideoFilename ? 'active-video' : ''}" data-file="${escapeHtml(file.filename)}">
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
      `;}).join('');

      videoFilesList.querySelectorAll('.btn-select-video').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const url = btn.getAttribute('data-url');
          const fn = btn.getAttribute('data-filename');
          const web = btn.getAttribute('data-web') === 'true';
          const codec = btn.getAttribute('data-codec');
          loadVideoIntoPlayer(url, fn, web, codec);
        });
      });

      videoFilesList.querySelectorAll('.btn-transcode-video').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const fn = btn.getAttribute('data-filename');
          transcodeVideo(fn);
        });
      });

      videoFilesList.querySelectorAll('.btn-del-video').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const fn = btn.getAttribute('data-filename');
          if (confirm(`Delete recording file '${fn}'?`)) {
            await fetch(`/api/videos/${encodeURIComponent(fn)}`, { method: 'DELETE' });
            await loadVideosList();
          }
        });
      });

      // Auto-load first preferred video if none selected
      if (!currentVideoFilename && files.length > 0) {
        const preferred = files.find(f => f.web_compatible) || files[0];
        loadVideoIntoPlayer(preferred.video_url, preferred.filename, preferred.web_compatible, preferred.codec);
      }

    } catch (e) {
      console.warn('Could not load videos list:', e);
    }
  }

  function loadVideoIntoPlayer(url, filename, isWebCompatible, codec) {
    if (!videoPlayer) return;
    currentVideoUrl = url;
    currentVideoFilename = filename;

    // Explicitly pause and reset playback state to eliminate event race conditions
    try {
      videoPlayer.pause();
    } catch (_) {}
    videoPlayer.currentTime = 0;

    // Reset button state and timeline on new load
    if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    if (timelineSlider) timelineSlider.value = 0;
    hideCodecNotice();

    videoPlayer.src = url;
    videoPlayer.load();

    document.getElementById('scrubber-loaded-title').textContent = `Loaded: ${filename}`;
    if (btnAddAsCamera) btnAddAsCamera.disabled = false;
    if (btnAnalyzeVideo) btnAnalyzeVideo.disabled = false;

    if (isWebCompatible === false) {
      showCodecNotice(`This video is encoded with '${(codec || 'HEVC').toUpperCase()}' which may not play in standard browsers without conversion.`, filename);
    }

    // Highlight card
    document.querySelectorAll('.video-file-card').forEach(c => {
      c.classList.toggle('active-video', c.getAttribute('data-file') === filename);
    });
  }

  async function uploadSelectedVideo(e) {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    videoUploadStatus.textContent = `Uploading ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)...`;

    try {
      const resp = await fetch('/api/videos/upload', {
        method: 'POST',
        body: formData,
      });

      if (resp.ok) {
        const res = await resp.json();
        videoUploadStatus.innerHTML = `<span style="color:#10b981;">✓ Uploaded '${res.filename}'</span>`;
        await loadVideosList();
        loadVideoIntoPlayer(res.video_url, res.filename);
      } else {
        const err = await resp.json();
        videoUploadStatus.innerHTML = `<span style="color:#ef4444;">✗ Upload failed: ${err.detail || 'Error'}</span>`;
      }
    } catch (err) {
      videoUploadStatus.innerHTML = `<span style="color:#ef4444;">✗ Network error: ${err.message}</span>`;
    } finally {
      videoFileInput.value = '';
    }
  }

  async function togglePlayPause() {
    if (!videoPlayer) return;
    if (videoPlayer.paused) {
      try {
        await videoPlayer.play();
        if (btnPlayPause) btnPlayPause.textContent = '⏸ Pause';
      } catch (err) {
        console.warn('Playback error or policy prevention:', err);
        if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      }
    } else {
      videoPlayer.pause();
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    }
  }

  function onTabLeave() {
    if (!videoPlayer) return;
    wasPlayingBeforeTabSwitch = !videoPlayer.paused;
    savedTimeBeforeTabSwitch = videoPlayer.currentTime;
    if (!videoPlayer.paused) {
      videoPlayer.pause();
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    }
  }

  function onTabEnter() {
    if (!videoPlayer) return;
    if (tabPolicy === 'reset') {
      videoPlayer.currentTime = 0;
      if (timelineSlider) timelineSlider.value = 0;
      updateTimeline();
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    } else if (tabPolicy === 'auto-resume') {
      if (wasPlayingBeforeTabSwitch) {
        videoPlayer.currentTime = savedTimeBeforeTabSwitch;
        videoPlayer.play().then(() => {
          if (btnPlayPause) btnPlayPause.textContent = '⏸ Pause';
        }).catch(() => {
          if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
        });
      }
    } else if (tabPolicy === 'keep-paused') {
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    }
    wasPlayingBeforeTabSwitch = false;
  }

  function stepFrame(frameDelta) {
    if (!videoPlayer) return;
    videoPlayer.pause();
    btnPlayPause.textContent = '▶ Play';
    // Assume ~30 FPS frame duration ~0.0333s
    const frameDuration = 1.0 / 30.0;
    videoPlayer.currentTime = Math.max(0, Math.min(videoPlayer.duration || 0, videoPlayer.currentTime + (frameDelta * frameDuration)));
  }

  function onVideoLoaded() {
    if (timelineSlider) timelineSlider.value = 0;
    updateTimeline();
  }

  function updateTimeline() {
    if (!videoPlayer) return;
    const cur = videoPlayer.currentTime;
    const dur = videoPlayer.duration || 1;
    const pct = (cur / dur) * 100;

    if (timelineSlider && !timelineSlider.matches(':active')) {
      timelineSlider.value = pct;
    }

    const frameIdx = Math.floor(cur * 30);
    if (timelineTimeDisplay) {
      timelineTimeDisplay.textContent = `${formatTime(cur)} / ${formatTime(dur)} (Frame #${frameIdx})`;
    }
  }

  function formatTime(seconds) {
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${min}:${sec < 10 ? '0' : ''}${sec}.${ms < 10 ? '0' : ''}${ms}`;
  }

  async function addVideoToCameraPool() {
    if (!currentVideoFilename) return;
    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(currentVideoFilename)}/add_as_camera`, {
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

  async function runBatchAnalytics() {
    if (window.TrackerApp.BatchAnalytics) {
      await window.TrackerApp.BatchAnalytics.run(currentVideoFilename, btnAnalyzeVideo, batchReportContainer);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  window.VideoScrubber = {
    init: init,
    loadVideosList: loadVideosList,
    onTabLeave: onTabLeave,
    onTabEnter: onTabEnter,
    getTabPolicy: () => tabPolicy,
    setTabPolicy: (p) => {
      tabPolicy = p;
      if (selectTabPolicy) selectTabPolicy.value = p;
      localStorage.setItem('intelligent_tracker_tab_policy', p);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
