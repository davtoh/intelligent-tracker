/**
 * Intelligent Tracker - Video Studio & Playback Scrubber Controller.
 * 
 * Provides:
 * - Frame-stepping scrubber (< 1 frame, > 1 frame)
 * - Variable playback speed (1x, 2x, 4x, 8x)
 * - HTML5 video player controls & timeline scrubbing
 * - Coordination of VideoLibrary and VideoBatch modules
 */

(function () {
  'use strict';

  let currentVideoUrl = null;
  let currentVideoFilename = null;

  // DOM Elements
  const videoPlayer = document.getElementById('scrubber-video-player');
  const videoFileInput = document.getElementById('video-file-upload-input');
  const btnUploadVideo = document.getElementById('btn-upload-video');
  const videoFilesList = document.getElementById('video-recordings-list');

  // Scrubber Controls & Speed Buttons
  const btnPlayPause = document.getElementById('scrubber-btn-play');
  const btnStepBack = document.getElementById('scrubber-btn-prev');
  const btnStepForward = document.getElementById('scrubber-btn-next');
  const timelineSlider = document.getElementById('scrubber-timeline-slider');
  const timelineTimeDisplay = document.getElementById('scrubber-time-display');
  const btnSpeed1x = document.getElementById('speed-btn-1x');
  const btnSpeed2x = document.getElementById('speed-btn-2x');
  const btnSpeed4x = document.getElementById('speed-btn-4x');
  const btnSpeed8x = document.getElementById('speed-btn-8x');
  const btnAddAsCamera = document.getElementById('btn-video-add-camera');
  const btnAnalyzeVideo = document.getElementById('btn-video-analyze');
  const selectTabPolicy = document.getElementById('scrubber-tab-policy');

  // Tab-Switching Lifecycle & Resource Policy State
  let tabPolicy = localStorage.getItem('intelligent_tracker_tab_policy') || 'auto-resume';
  let wasPlayingBeforeTabSwitch = false;
  let savedTimeBeforeTabSwitch = 0;

  function init() {
    bindEvents();
    loadVideosList();
  }

  function bindPlaybackControls() {
    const updatePlayState = () => {
      if (btnPlayPause) btnPlayPause.textContent = videoPlayer.paused ? '▶ Play' : '⏸ Pause';
    };
    if (videoPlayer) {
      videoPlayer.addEventListener('timeupdate', updateTimeline);
      videoPlayer.addEventListener('loadedmetadata', onVideoLoaded);
      videoPlayer.addEventListener('play', updatePlayState);
      videoPlayer.addEventListener('pause', updatePlayState);
      videoPlayer.addEventListener('ended', updatePlayState);
      videoPlayer.addEventListener('error', handleVideoPlayerError);
    }
    if (btnPlayPause) btnPlayPause.addEventListener('click', togglePlayPause);
    if (btnStepBack) btnStepBack.addEventListener('click', () => stepFrame(-1));
    if (btnStepForward) btnStepForward.addEventListener('click', () => stepFrame(1));
    if (timelineSlider) {
      timelineSlider.addEventListener('input', (e) => {
        if (videoPlayer && videoPlayer.duration) {
          videoPlayer.currentTime = (e.target.value / 100) * videoPlayer.duration;
        }
      });
    }
    bindSpeedButtons();
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
      videoFileInput.addEventListener('change', (e) => {
        window.VideoLibrary?.uploadSelectedVideo(e, (res) => {
          loadVideosList();
          loadVideoIntoPlayer(res.video_url, res.filename, true, 'h264');
        });
      });
    }

    bindPlaybackControls();

    if (btnAddAsCamera) {
      btnAddAsCamera.addEventListener('click', () => {
        if (currentVideoFilename) {
          if (window.VideoLibrary?.openFeedPromotionModal) {
            window.VideoLibrary.openFeedPromotionModal(currentVideoFilename, currentVideoUrl);
          } else {
            window.VideoLibrary?.addVideoToCameraPool(currentVideoFilename);
          }
        }
      });
    }

    if (btnAnalyzeVideo) {
      btnAnalyzeVideo.addEventListener('click', () => {
        if (currentVideoFilename) {
          if (window.VideoBatch?.openBatchModal) {
            window.VideoBatch.openBatchModal(currentVideoFilename);
          } else {
            window.VideoBatch?.runBatchAnalytics(currentVideoFilename);
          }
        }
      });
    }
  }

  function bindSpeedButtons() {
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
  }

  function handleVideoPlayerError() {
    const err = videoPlayer?.error;
    let msg = 'Browser error playing video recording.';
    if (err && err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      msg = 'Codec not supported natively by browser (e.g. HEVC/H.265). Convert to standard H.264 MP4 for instant browser playback.';
    }
    window.VideoLibrary?.showCodecNotice(msg, currentVideoFilename, (fn) => {
      window.VideoLibrary?.transcodeVideo(fn, () => {
        loadVideosList();
      });
    });
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

      videoFilesList.innerHTML = files.map(file => window.VideoLibrary?.renderVideoFileCard(file, currentVideoFilename) || '').join('');
      bindVideoCardActions();

      if (!currentVideoFilename && files.length > 0) {
        const preferred = files.find(f => f.web_compatible) || files[0];
        loadVideoIntoPlayer(preferred.video_url, preferred.filename, preferred.web_compatible, preferred.codec);
      }
    } catch (e) {
      console.warn('Could not load videos list:', e);
    }
  }

  function bindVideoCardActions() {
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
        window.VideoLibrary?.transcodeVideo(fn, (data) => {
          loadVideosList();
          loadVideoIntoPlayer(data.video_url, data.output_filename, true, 'h264');
        });
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
  }

  function updateScrubberLoadedTitle(filename) {
    const titleEl = document.getElementById('scrubber-loaded-title');
    if (!titleEl) return;
    const fullTitle = 'Loaded: ' + filename;
    if (window.TextTruncationManager) {
      window.TextTruncationManager.apply(titleEl, {
        fullText: fullTitle,
        mode: 'middle',
        maxLength: 38,
        preserveExt: true,
        label: 'Loaded Video File'
      });
    } else {
      titleEl.textContent = fullTitle;
      titleEl.title = fullTitle;
    }
  }

  function loadVideoIntoPlayer(url, filename, isWebCompatible, codec) {
    if (!videoPlayer) return;
    currentVideoUrl = url;
    currentVideoFilename = filename;

    try {
      videoPlayer.pause();
    } catch (e) {
      console.debug('[VideoScrubber] Pause error ignored:', e);
    }
    videoPlayer.currentTime = 0;

    if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    if (timelineSlider) timelineSlider.value = 0;
    window.VideoLibrary?.hideCodecNotice();

    videoPlayer.src = url;
    videoPlayer.load();

    updateScrubberLoadedTitle(filename);
    if (btnAddAsCamera) btnAddAsCamera.disabled = false;
    if (btnAnalyzeVideo) btnAnalyzeVideo.disabled = false;

    if (isWebCompatible === false) {
      window.VideoLibrary?.showCodecNotice(
        `This video is encoded with '${(codec || 'HEVC').toUpperCase()}' which may not play in standard browsers without conversion.`,
        filename,
        (fn) => window.VideoLibrary?.transcodeVideo(fn, () => loadVideosList())
      );
    }

    document.querySelectorAll('.video-file-card').forEach(c => {
      c.classList.toggle('active-video', c.getAttribute('data-file') === filename);
    });
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
    if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
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
  window.VideoScrubber.onTabEnter = onTabEnter;
  window.VideoScrubber.onTabLeave = onTabLeave;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
