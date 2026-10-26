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

  function init() {
    bindEvents();
    loadVideosList();
  }

  function bindEvents() {
    if (btnUploadVideo && videoFileInput) {
      btnUploadVideo.addEventListener('click', () => videoFileInput.click());
      videoFileInput.addEventListener('change', uploadSelectedVideo);
    }

    if (videoPlayer) {
      videoPlayer.addEventListener('timeupdate', updateTimeline);
      videoPlayer.addEventListener('loadedmetadata', onVideoLoaded);
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

  async function loadVideosList() {
    if (!videoFilesList) return;
    try {
      const resp = await fetch('/api/videos');
      const files = await resp.json();

      if (!files || files.length === 0) {
        videoFilesList.innerHTML = '<div class="empty-state">No uploaded recordings found. Upload an MP4 or MKV recording to scrub and analyze.</div>';
        return;
      }

      videoFilesList.innerHTML = files.map(file => `
        <div class="video-file-card glass-panel ${file.filename === currentVideoFilename ? 'active-video' : ''}" data-file="${escapeHtml(file.filename)}">
          <div class="video-file-icon">📼</div>
          <div class="video-file-meta">
            <div class="video-filename">${escapeHtml(file.filename)}</div>
            <div class="video-filesize">${file.size_mb} MB</div>
          </div>
          <div class="video-file-actions">
            <button class="btn btn-xs btn-primary btn-select-video" data-url="${escapeHtml(file.video_url)}" data-filename="${escapeHtml(file.filename)}">▶ Load</button>
            <button class="btn btn-xs btn-outline btn-del-video" data-filename="${escapeHtml(file.filename)}">🗑️</button>
          </div>
        </div>
      `).join('');

      videoFilesList.querySelectorAll('.btn-select-video').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const url = btn.getAttribute('data-url');
          const fn = btn.getAttribute('data-filename');
          loadVideoIntoPlayer(url, fn);
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

      // Auto-load first video if none selected
      if (!currentVideoFilename && files.length > 0) {
        loadVideoIntoPlayer(files[0].video_url, files[0].filename);
      }

    } catch (e) {
      console.warn('Could not load videos list:', e);
    }
  }

  function loadVideoIntoPlayer(url, filename) {
    if (!videoPlayer) return;
    currentVideoUrl = url;
    currentVideoFilename = filename;

    videoPlayer.src = url;
    videoPlayer.load();

    document.getElementById('scrubber-loaded-title').textContent = `Loaded: ${filename}`;
    if (btnAddAsCamera) btnAddAsCamera.disabled = false;
    if (btnAnalyzeVideo) btnAnalyzeVideo.disabled = false;

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

  function togglePlayPause() {
    if (!videoPlayer) return;
    if (videoPlayer.paused) {
      videoPlayer.play();
      btnPlayPause.textContent = '⏸ Pause';
    } else {
      videoPlayer.pause();
      btnPlayPause.textContent = '▶ Play';
    }
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
        alert(`Video successfully added as active stream '${data.camera_id}'!`);
        if (window.CameraManager) {
          await window.CameraManager.refreshCameras();
          window.CameraManager.focusCamera(data.camera_id);
        }
      } else {
        alert('Failed to add video as camera.');
      }
    } catch (e) {
      alert(`Error: ${e.message}`);
    }
  }

  async function runBatchAnalytics() {
    if (!currentVideoFilename) return;
    btnAnalyzeVideo.disabled = true;
    btnAnalyzeVideo.textContent = '⏳ Processing Analytics...';
    batchReportContainer.innerHTML = '<div class="empty-state">Running Edge AI detector and Re-ID indexer on recording...</div>';

    try {
      const resp = await fetch(`/api/videos/${encodeURIComponent(currentVideoFilename)}/analyze?sample_rate=1`, {
        method: 'POST'
      });
      const data = await resp.json();

      if (data.status === 'success') {
        const rep = data.report || {};
        batchReportContainer.innerHTML = `
          <div class="batch-report-card glass-panel">
            <h4>📊 Occurrence Indexing Report (${escapeHtml(currentVideoFilename)})</h4>
            <div class="kpi-row" style="margin-top: 10px;">
              <div class="kpi-card glass-panel">
                <div class="kpi-label">Frames Processed</div>
                <div class="kpi-value cyan">${rep.frames_processed || 0}</div>
              </div>
              <div class="kpi-card glass-panel">
                <div class="kpi-label">Detections</div>
                <div class="kpi-value green">${rep.total_detections || 0}</div>
              </div>
              <div class="kpi-card glass-panel">
                <div class="kpi-label">Sightings Recorded</div>
                <div class="kpi-value cyan">${rep.total_sightings || 0}</div>
              </div>
              <div class="kpi-card glass-panel">
                <div class="kpi-label">Unique Entities</div>
                <div class="kpi-value green">${rep.unique_entities_identified || 0}</div>
              </div>
            </div>
            <div style="margin-top: 12px; font-size: 13px; color: #94a3b8;">
              Audit records cataloged in <code>TrackerDB</code>. View complete results in <strong>Sighting Timeline</strong> tab.
            </div>
          </div>
        `;
      } else {
        batchReportContainer.innerHTML = `<div class="empty-state" style="color:#ef4444;">Analysis failed: ${data.detail || 'Error'}</div>`;
      }
    } catch (e) {
      batchReportContainer.innerHTML = `<div class="empty-state" style="color:#ef4444;">Request error: ${e.message}</div>`;
    } finally {
      btnAnalyzeVideo.disabled = false;
      btnAnalyzeVideo.textContent = '⚡ Run Batch Occurrence Report';
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
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
