/**
 * Intelligent Tracker - Video Studio & Playback Scrubber Controller.
 *
 * Provides:
 * - Frame-stepping scrubber (< 1 frame, > 1 frame)
 * - Variable playback speed (1x, 2x, 4x, 8x)
 * - HTML5 video player controls & policy-governed timeline persistence
 * - Coordination of VideoLibrary, VideoBatch, ScrubberOverlay, and ScrubberPlaybackState
 */

(function () {
  'use strict';

  let currentVideoUrl = null;
  let currentVideoFilename = null;
  let currentVideoMetadataLoaded = false;
  let pendingPlaybackRestore = null;
  let isTransitioningVideo = false;

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

  function getPlaybackStore() {
    return window.ScrubberPlaybackState || null;
  }

  function getActiveTabPolicy() {
    return (selectTabPolicy && selectTabPolicy.value) || tabPolicy || 'auto-resume';
  }

  function persistCurrentPlayback(wasPlayingOverride = null) {
    return getPlaybackStore()?.saveFromPlayer(
      videoPlayer,
      currentVideoFilename,
      currentVideoMetadataLoaded,
      wasPlayingOverride
    );
  }

  function updatePlayButtonAndLoop() {
    if (btnPlayPause) btnPlayPause.textContent = videoPlayer.paused ? '▶ Play' : '⏸ Pause';
    if (videoPlayer.paused) {
      window.ScrubberOverlay?.stopLoop();
    } else {
      window.ScrubberOverlay?.startLoop();
    }
  }

  function bindPlayerMediaEvents() {
    if (!videoPlayer) return;
    videoPlayer.addEventListener('timeupdate', () => {
      if (pendingPlaybackRestore && (Number(videoPlayer.currentTime) || 0) === 0) return;
      if (currentVideoMetadataLoaded || (Number(videoPlayer.currentTime) || 0) > 0) {
        persistCurrentPlayback();
      }
      updateTimeline();
      if (videoPlayer.paused) window.ScrubberOverlay?.render();
    });
    videoPlayer.addEventListener('seeked', () => {
      if (!isTransitioningVideo && currentVideoMetadataLoaded) {
        persistCurrentPlayback();
      }
      updateTimeline();
      window.ScrubberOverlay?.render();
    });
    videoPlayer.addEventListener('loadedmetadata', onVideoLoaded);
    videoPlayer.addEventListener('play', updatePlayButtonAndLoop);
    videoPlayer.addEventListener('pause', () => {
      updatePlayButtonAndLoop();
      if (!isTransitioningVideo) persistCurrentPlayback(false);
    });
    videoPlayer.addEventListener('ended', updatePlayButtonAndLoop);
    videoPlayer.addEventListener('error', handleVideoPlayerError);
  }

  function bindPlaybackControls() {
    bindPlayerMediaEvents();
    if (btnPlayPause) btnPlayPause.addEventListener('click', togglePlayPause);
    if (btnStepBack) btnStepBack.addEventListener('click', () => {
      stepFrame(-1);
      window.ScrubberOverlay?.render();
    });
    if (btnStepForward) btnStepForward.addEventListener('click', () => {
      stepFrame(1);
      window.ScrubberOverlay?.render();
    });
    if (timelineSlider) {
      timelineSlider.addEventListener('input', (e) => {
        if (videoPlayer && videoPlayer.duration) {
          videoPlayer.currentTime = (e.target.value / 100) * videoPlayer.duration;
          persistCurrentPlayback(!videoPlayer.paused);
          updateTimeline();
          window.ScrubberOverlay?.render();
        }
      });
    }
    bindSpeedButtons();
  }

  function handleAnalyzeVideoClick() {
    if (!currentVideoFilename) return;
    const triggerBatch = () => {
      if (window.VideoBatch?.openBatchModal) {
        window.VideoBatch.openBatchModal(currentVideoFilename);
      } else {
        window.VideoBatch?.runBatchAnalytics(currentVideoFilename);
      }
    };
    const activeJob = window.VideoJobClient?.getActiveJob(currentVideoFilename);
    if (activeJob) {
      window.VideoJobClient.showConflictModal(activeJob, 'Batch Video Analytics', triggerBatch, () => {});
      return;
    }
    triggerBatch();
  }

  function bindEvents() {
    if (selectTabPolicy) {
      selectTabPolicy.value = tabPolicy;
      selectTabPolicy.addEventListener('change', (e) => {
        tabPolicy = e.target.value;
        localStorage.setItem('intelligent_tracker_tab_policy', tabPolicy);
      });
    }

    window.addEventListener('video-select-request', (e) => {
      const fn = e.detail?.filename;
      if (!fn) return;
      const card = document.querySelector(`.video-file-card[data-file="${CSS.escape(fn)}"]`);
      card?.querySelector('.btn-select-video')?.click();
    });

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
        if (!currentVideoFilename) return;
        if (window.VideoLibrary?.openFeedPromotionModal) {
          window.VideoLibrary.openFeedPromotionModal(currentVideoFilename, currentVideoUrl);
        } else {
          window.VideoLibrary?.addVideoToCameraPool(currentVideoFilename);
        }
      });
    }
    if (btnAnalyzeVideo) btnAnalyzeVideo.addEventListener('click', handleAnalyzeVideoClick);
  }

  function bindSpeedButtons() {
    const speedButtons = [
      { btn: btnSpeed1x, rate: 1.0 },
      { btn: btnSpeed2x, rate: 2.0 },
      { btn: btnSpeed4x, rate: 4.0 },
      { btn: btnSpeed8x, rate: 8.0 },
    ];
    speedButtons.forEach(({ btn, rate }) => {
      if (!btn) return;
      btn.addEventListener('click', () => {
        if (videoPlayer) videoPlayer.playbackRate = rate;
        speedButtons.forEach(s => s.btn?.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  }

  function handleVideoPlayerError() {
    window.ScrubberLibraryBridge?.handlePlayerError(videoPlayer, currentVideoFilename, loadVideosList);
  }

  async function loadVideosList() {
    await window.ScrubberLibraryBridge?.loadVideosList({
      videoFilesList,
      getCurrentFilename: () => currentVideoFilename,
      loadVideoIntoPlayer,
      reloadList: loadVideosList,
    });
  }

  function loadVideoIntoPlayer(url, filename, isWebCompatible, codec, options = {}) {
    if (!videoPlayer) return;
    const policy = getActiveTabPolicy();
    const store = getPlaybackStore();
    const wasPlayingOutgoing = Boolean(!videoPlayer.paused);

    isTransitioningVideo = true;
    try {
      if (policy === 'reset') {
        if (currentVideoFilename) store?.clearState(currentVideoFilename);
      } else {
        persistCurrentPlayback(wasPlayingOutgoing);
      }
      try {
        videoPlayer.pause();
      } catch (e) {
        console.debug('[VideoScrubber] Pause error ignored:', e);
      }

      currentVideoUrl = url;
      currentVideoFilename = filename;
      currentVideoMetadataLoaded = false;
      pendingPlaybackRestore = store?.resolveLoadRestore(filename, policy) || {
        stem: '', time: 0, duration: 0, pct: 0, shouldResume: false,
      };

      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      window.VideoLibrary?.hideCodecNotice();

      videoPlayer.src = url;
      if (typeof videoPlayer.load === 'function') videoPlayer.load();
      videoPlayer.currentTime = pendingPlaybackRestore.time;
      if (timelineSlider) timelineSlider.value = pendingPlaybackRestore.pct;
      updateTimeline(true, pendingPlaybackRestore, true);
    } finally {
      isTransitioningVideo = false;
    }

    window.ScrubberLibraryBridge?.syncLoadedVideoUI(filename, isWebCompatible, codec, options, {
      btnAddAsCamera,
      reloadList: loadVideosList,
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
    window.ScrubberOverlay?.stopLoop();
    wasPlayingBeforeTabSwitch = !videoPlayer.paused;
    savedTimeBeforeTabSwitch = Number(videoPlayer.currentTime) || 0;
    isTransitioningVideo = true;
    try {
      persistCurrentPlayback(wasPlayingBeforeTabSwitch);
      if (!videoPlayer.paused) {
        videoPlayer.pause();
        if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      }
    } finally {
      isTransitioningVideo = false;
    }
  }

  function onTabEnter() {
    if (!videoPlayer) return;
    const policy = getActiveTabPolicy();
    if (currentVideoFilename) {
      window.VideoJobClient?.setCurrentViewedFilename(currentVideoFilename);
      window.VideoBatch?.restoreReportForFile(currentVideoFilename);
      window.ScrubberOverlay?.loadDetections(currentVideoFilename);
    }
    if (policy === 'reset') {
      videoPlayer.currentTime = 0;
      if (timelineSlider) timelineSlider.value = 0;
      if (currentVideoFilename) getPlaybackStore()?.clearState(currentVideoFilename);
      updateTimeline(true);
      window.ScrubberOverlay?.render();
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    } else if (policy === 'auto-resume') {
      if (wasPlayingBeforeTabSwitch) {
        videoPlayer.currentTime = savedTimeBeforeTabSwitch;
        updateTimeline(true);
        getPlaybackStore()?.resumeVideoPlayback(videoPlayer, btnPlayPause);
      } else {
        window.ScrubberOverlay?.render();
      }
    } else if (policy === 'keep-paused') {
      window.ScrubberOverlay?.render();
      if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    }
    wasPlayingBeforeTabSwitch = false;
  }

  function stepFrame(frameDelta) {
    if (!videoPlayer) return;
    videoPlayer.pause();
    if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
    const frameDuration = 1.0 / 30.0;
    videoPlayer.currentTime = Math.max(
      0,
      Math.min(videoPlayer.duration || 0, videoPlayer.currentTime + (frameDelta * frameDuration))
    );
    persistCurrentPlayback(false);
    updateTimeline();
  }

  function onVideoLoaded() {
    currentVideoMetadataLoaded = true;
    const policy = getActiveTabPolicy();
    const restore = pendingPlaybackRestore;
    pendingPlaybackRestore = null;
    getPlaybackStore()?.applyMetadataRestore(
      videoPlayer,
      timelineSlider,
      timelineTimeDisplay,
      btnPlayPause,
      currentVideoFilename,
      policy,
      restore
    );
    window.ScrubberOverlay?.render();
  }

  function updateTimeline(forceSlider = false, fallbackState = null, useFallbackOnly = false) {
    getPlaybackStore()?.updateTimelineUI(videoPlayer, timelineSlider, timelineTimeDisplay, {
      forceSlider,
      fallbackState,
      useFallbackOnly,
    });
  }

  window.loadVideosList = loadVideosList;
  window.loadVideoIntoPlayer = loadVideoIntoPlayer;
  window.VideoScrubber = {
    init,
    loadVideosList,
    loadVideoIntoPlayer,
    onTabLeave,
    onTabEnter,
    getTabPolicy: () => getActiveTabPolicy(),
    setTabPolicy: (p) => {
      tabPolicy = p;
      if (selectTabPolicy) selectTabPolicy.value = p;
      localStorage.setItem('intelligent_tracker_tab_policy', p);
    },
    getSavedPlaybackState: (fn) => getPlaybackStore()?.getState(fn) || null,
    getBaseStem: (fn) => getPlaybackStore()?.getBaseStem(fn) || '',
    loadDetections: (fn, runId) => window.ScrubberOverlay?.loadDetections(fn, runId),
    renderOverlay: () => window.ScrubberOverlay?.render(),
    clearOverlay: () => window.ScrubberOverlay?.clear(),
  };
  window.VideoScrubber.onTabEnter = onTabEnter;
  window.VideoScrubber.onTabLeave = onTabLeave;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
