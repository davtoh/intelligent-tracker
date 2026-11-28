/**
 * Reusable HTML5 Video Timeline Slider & Frame-Step Controller.
 * Shared by Video Studio (video_scrubber.js) and Universal Enrollment (universal_enrollment.js).
 */
(function () {
  'use strict';

  function formatTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) return '00:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function captureFrameToCanvas(videoPlayer, canvas) {
    if (!videoPlayer || !canvas) return null;
    const w = Number(videoPlayer.videoWidth) || 640;
    const h = Number(videoPlayer.videoHeight) || 480;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (ctx) ctx.drawImage(videoPlayer, 0, 0, w, h);
    canvas.style.display = 'block';
    return typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/jpeg', 0.9) : null;
  }

  function create(opts = {}) {
    const {
      videoPlayer, slider, timeDisplay, playBtn, prevBtn, nextBtn, speedButtons = [], fps = 30,
      onTimeUpdate = null, onSeek = null, onStep = null, onPlayStateChange = null, onLoadedMetadata = null, onError = null,
    } = opts;
    let frameDur = 1.0 / (Number(fps) || 30);

    function setFps(nextFps) {
      const parsed = Number(nextFps);
      if (Number.isFinite(parsed) && parsed > 0) frameDur = 1.0 / parsed;
    }

    function syncPlayBtn() {
      if (playBtn && videoPlayer) playBtn.textContent = videoPlayer.paused ? '▶ Play' : '⏸ Pause';
      if (typeof onPlayStateChange === 'function' && videoPlayer) onPlayStateChange(Boolean(videoPlayer.paused));
    }

    function updateTimeline(forceSlider = false, fallbackState = null, useFallbackOnly = false) {
      const store = window.ScrubberPlaybackState;
      if (store && typeof store.updateTimelineUI === 'function' && !opts.standaloneDisplay) {
        store.updateTimelineUI(videoPlayer, slider, timeDisplay, { forceSlider, fallbackState, useFallbackOnly });
        return;
      }
      if (!videoPlayer) return;
      const cur = Number(videoPlayer.currentTime) || 0;
      const dur = Number(videoPlayer.duration) || 0;
      if (slider && (forceSlider || dur > 0)) {
        slider.value = dur > 0 ? Math.min(100, Math.max(0, (cur / dur) * 100)) : 0;
      }
      if (timeDisplay) timeDisplay.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
    }

    async function togglePlayPause() {
      if (!videoPlayer) return;
      if (videoPlayer.paused) {
        try {
          await videoPlayer.play();
          syncPlayBtn();
        } catch (err) {
          console.warn('Playback error or policy prevention:', err);
          if (playBtn) playBtn.textContent = '▶ Play';
        }
      } else {
        videoPlayer.pause();
        syncPlayBtn();
      }
    }

    function stepFrame(delta) {
      if (!videoPlayer) return;
      videoPlayer.pause();
      if (playBtn) playBtn.textContent = '▶ Play';
      const dur = Number(videoPlayer.duration) || 0;
      const cur = Number(videoPlayer.currentTime) || 0;
      videoPlayer.currentTime = Math.max(0, Math.min(dur, cur + (delta * frameDur)));
      updateTimeline();
      if (typeof onStep === 'function') onStep(delta, videoPlayer.currentTime);
    }

    function bind() {
      if (videoPlayer) {
        videoPlayer.addEventListener('timeupdate', () => {
          updateTimeline();
          if (typeof onTimeUpdate === 'function') onTimeUpdate(videoPlayer.currentTime);
        });
        videoPlayer.addEventListener('seeked', () => {
          updateTimeline();
          if (typeof onSeek === 'function') onSeek(videoPlayer.currentTime);
        });
        videoPlayer.addEventListener('loadedmetadata', () => {
          updateTimeline(true);
          if (typeof onLoadedMetadata === 'function') onLoadedMetadata(videoPlayer.duration);
        });
        videoPlayer.addEventListener('play', syncPlayBtn);
        videoPlayer.addEventListener('pause', () => { syncPlayBtn(); window.ScrubberPlaybackState?.flushPendingPersist?.(); });
        videoPlayer.addEventListener('ended', () => { syncPlayBtn(); window.ScrubberPlaybackState?.flushPendingPersist?.(); });
        window.ScrubberPlaybackState?.bindStallRecovery?.(videoPlayer);
        if (typeof onError === 'function') videoPlayer.addEventListener('error', onError);
      }
      if (playBtn) playBtn.addEventListener('click', togglePlayPause);
      if (prevBtn) prevBtn.addEventListener('click', () => stepFrame(-1));
      if (nextBtn) nextBtn.addEventListener('click', () => stepFrame(1));
      if (slider) {
        slider.addEventListener('input', (e) => {
          if (videoPlayer && videoPlayer.duration) {
            videoPlayer.currentTime = (Number(e.target.value) / 100) * videoPlayer.duration;
            updateTimeline();
            if (typeof onSeek === 'function') onSeek(videoPlayer.currentTime, true);
          }
        });
      }
      speedButtons.forEach(({ btn, rate }) => {
        if (!btn) return;
        btn.addEventListener('click', () => {
          if (videoPlayer) videoPlayer.playbackRate = rate;
          speedButtons.forEach(s => s.btn?.classList.remove('active'));
          btn.classList.add('active');
        });
      });
    }

    return { bind, togglePlayPause, stepFrame, updateTimeline, syncPlayBtn, setFps };
  }

  let _enrollSliderCtrl = null;

  function mountEnrollmentScrubber(videoUrl, canvas, placeholder, onFrameCaptured, opts = {}) {
    const box = document.getElementById('enroll-video-scrubber-box');
    const vid = document.getElementById('enroll-scrubber-video');
    if (!box || !vid) return null;
    box.style.display = 'block';
    if (placeholder) placeholder.style.display = 'none';
    window.EnrollmentStageController?.syncVideoStageClasses?.(canvas, true);
    const fps = Number(opts?.fps) || 30;
    const targetTime = Number(opts?.initialTime ?? window.EnrollmentStageController?.getActiveVideoCurrentTime?.() ?? 0);
    const grab = () => {
      const dataUrl = captureFrameToCanvas(vid, canvas);
      if (dataUrl && typeof onFrameCaptured === 'function') onFrameCaptured(dataUrl);
    };
    const seekInitial = () => { if (targetTime > 0 && Number.isFinite(targetTime)) try { vid.currentTime = targetTime; } catch (err) { console.debug('Scrubber initial seek failed:', err); } grab(); };
    if (!vid.dataset?.sliderBound) {
      if (vid.dataset) vid.dataset.sliderBound = '1';
      _enrollSliderCtrl = create({
        videoPlayer: vid, standaloneDisplay: true, fps, slider: document.getElementById('enroll-scrubber-slider'),
        timeDisplay: document.getElementById('enroll-scrubber-time'), playBtn: document.getElementById('enroll-scrubber-play'),
        prevBtn: document.getElementById('enroll-scrubber-prev'), nextBtn: document.getElementById('enroll-scrubber-next'),
        onLoadedMetadata: seekInitial, onSeek: grab, onStep: grab, onTimeUpdate: grab,
      });
      _enrollSliderCtrl.bind();
      vid.addEventListener?.('loadeddata', grab);
      vid.addEventListener?.('seeked', grab);
      document.getElementById('enroll-scrubber-grab')?.addEventListener('click', grab);
    } else if (_enrollSliderCtrl?.setFps) _enrollSliderCtrl.setFps(fps);
    vid.src = videoUrl;
    if (typeof vid.load === 'function') vid.load();
    return vid;
  }

  function hideEnrollmentScrubber(canvas) {
    const box = document.getElementById('enroll-video-scrubber-box');
    const vid = document.getElementById('enroll-scrubber-video');
    if (vid && typeof vid.pause === 'function') {
      try { vid.pause(); } catch (err) { console.debug('[ScrubberTimelineSlider] pause ignored:', err); }
    }
    window.EnrollmentStageController?.syncVideoStageClasses?.(canvas || document.getElementById('enroll-bbox-canvas'), false);
    if (box) box.style.display = 'none';
  }

  window.ScrubberTimelineSlider = {
    create, formatTime, captureFrameToCanvas, mountEnrollmentScrubber, hideEnrollmentScrubber,
  };
})();
