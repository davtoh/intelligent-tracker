/**
 * Intelligent Tracker - Scrubber Per-Recording Playback State Persistence.
 *
 * Stores playback position and play/pause intent keyed by canonical recording
 * stem (sharing position across original and _h264 variants) in memory and
 * bounded localStorage, and manages policy-governed timeline restoration.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'intelligent_tracker_scrubber_playback_v1';
  const MAX_STORED_RECORDINGS = 50;
  const savedPlaybackByStem = new Map();
  let storageHydrated = false;

  function getBaseStem(filename) {
    if (!filename) return '';
    return String(filename).trim().replace(/_h264(\.[^.]+)$/i, '$1').replace(/\.[^.]+$/, '');
  }

  function readStorageMap() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_err) {
      return {};
    }
  }

  function writeStorageMap(mapObj) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(mapObj));
    } catch (_err) {
      // Ignore storage quota or private-mode restrictions
    }
  }

  function hydrateIfNeeded() {
    if (storageHydrated) return;
    storageHydrated = true;
    const stored = readStorageMap();
    for (const [stem, entry] of Object.entries(stored)) {
      if (!stem || !entry || typeof entry !== 'object') continue;
      const time = Number(entry.time);
      const duration = Number(entry.duration) || 0;
      const pct = Number(entry.pct) || (duration > 0 && time > 0 ? (time / duration) * 100 : 0);
      if (Number.isFinite(time) && time >= 0) {
        savedPlaybackByStem.set(stem, {
          time,
          duration,
          pct: Math.max(0, Math.min(100, pct)),
          wasPlaying: false,
        });
      }
    }
  }

  function persistMapToStorage() {
    const out = {};
    const entries = Array.from(savedPlaybackByStem.entries());
    const startIdx = Math.max(0, entries.length - MAX_STORED_RECORDINGS);
    for (let i = startIdx; i < entries.length; i++) {
      const [stem, state] = entries[i];
      out[stem] = { time: state.time, duration: state.duration, pct: state.pct };
    }
    writeStorageMap(out);
  }

  function saveState(filename, state, options = {}) {
    hydrateIfNeeded();
    const stem = getBaseStem(filename);
    if (!stem || !state) return null;
    const rawTime = Number(state.time);
    const time = Number.isFinite(rawTime) && rawTime >= 0 ? rawTime : 0;
    const rawDur = Number(state.duration);
    const duration = Number.isFinite(rawDur) && rawDur > 0 ? rawDur : 0;
    const rawPct = Number(state.pct);
    const computedPct = duration > 0 ? (time / duration) * 100 : (Number.isFinite(rawPct) ? rawPct : 0);
    const normalized = {
      time,
      duration,
      pct: Math.max(0, Math.min(100, computedPct)),
      wasPlaying: Boolean(state.wasPlaying),
    };
    savedPlaybackByStem.delete(stem);
    savedPlaybackByStem.set(stem, normalized);
    while (savedPlaybackByStem.size > MAX_STORED_RECORDINGS) {
      savedPlaybackByStem.delete(savedPlaybackByStem.keys().next().value);
    }
    if (options.persist !== false) persistMapToStorage();
    return { ...normalized };
  }

  function saveFromPlayer(videoPlayer, filename, metadataLoaded, wasPlayingOverride = null) {
    if (!videoPlayer || !filename) return null;
    const curTime = Number(videoPlayer.currentTime) || 0;
    const dur = Number(videoPlayer.duration) || 0;
    const hasPlayableState = !videoPlayer.error && (metadataLoaded || dur > 0 || curTime > 0);
    if (!hasPlayableState) return null;
    const wasPlaying = wasPlayingOverride !== null ? Boolean(wasPlayingOverride) : Boolean(!videoPlayer.paused);
    return saveState(filename, {
      time: curTime,
      duration: dur,
      pct: dur > 0 ? (curTime / dur) * 100 : 0,
      wasPlaying,
    });
  }

  function getState(filename) {
    hydrateIfNeeded();
    const stem = getBaseStem(filename);
    if (!stem || !savedPlaybackByStem.has(stem)) return null;
    return { ...savedPlaybackByStem.get(stem) };
  }

  function clearState(filename) {
    hydrateIfNeeded();
    const stem = getBaseStem(filename);
    if (!stem) return;
    savedPlaybackByStem.delete(stem);
    persistMapToStorage();
  }

  function formatTime(seconds) {
    const safe = Math.max(0, Number(seconds) || 0);
    const min = Math.floor(safe / 60);
    const sec = Math.floor(safe % 60);
    const ms = Math.floor((safe % 1) * 100);
    return `${min}:${sec < 10 ? '0' : ''}${sec}.${ms < 10 ? '0' : ''}${ms}`;
  }

  function updateTimelineUI(videoPlayer, timelineSlider, timelineTimeDisplay, options = {}) {
    if (!videoPlayer) return;
    const rawDur = options.useFallbackOnly ? NaN : Number(videoPlayer.duration);
    const hasDuration = Number.isFinite(rawDur) && rawDur > 0;
    const fallback = options.fallbackState || null;
    const cur = hasDuration
      ? (Number(videoPlayer.currentTime) || 0)
      : (Number(fallback?.time) || Number(videoPlayer.currentTime) || 0);
    const dur = hasDuration ? rawDur : (Number(fallback?.duration) || 0);
    const pct = dur > 0
      ? Math.max(0, Math.min(100, (cur / dur) * 100))
      : Math.max(0, Math.min(100, Number(fallback?.pct) || 0));

    const isSliderActive = typeof timelineSlider?.matches === 'function' && timelineSlider.matches(':active');
    if (timelineSlider && (options.forceSlider || !isSliderActive)) {
      timelineSlider.value = pct;
    }
    if (timelineTimeDisplay) {
      const frameIdx = Math.floor(cur * 30);
      timelineTimeDisplay.textContent = `${formatTime(cur)} / ${formatTime(dur || 0)} (Frame #${frameIdx})`;
    }
  }

  function resolveLoadRestore(filename, policy) {
    const stem = getBaseStem(filename);
    if (policy === 'reset') {
      clearState(filename);
      return { stem, time: 0, duration: 0, pct: 0, shouldResume: false };
    }
    const saved = getState(filename);
    return {
      stem,
      time: saved ? saved.time : 0,
      duration: saved ? saved.duration : 0,
      pct: saved ? saved.pct : 0,
      shouldResume: policy === 'auto-resume' && Boolean(saved?.wasPlaying),
    };
  }

  function resumeVideoPlayback(videoPlayer, btnPlayPause) {
    if (!videoPlayer || typeof videoPlayer.play !== 'function') return;
    const playPromise = videoPlayer.play();
    if (playPromise && typeof playPromise.then === 'function') {
      playPromise.then(() => {
        if (btnPlayPause) btnPlayPause.textContent = '⏸ Pause';
      }).catch(() => {
        if (btnPlayPause) btnPlayPause.textContent = '▶ Play';
      });
    } else if (btnPlayPause) {
      btnPlayPause.textContent = '⏸ Pause';
    }
  }

  function applyMetadataRestore(videoPlayer, timelineSlider, timelineTimeDisplay, btnPlayPause, filename, policy, pendingRestore) {
    const stem = getBaseStem(filename);
    const restore = pendingRestore && pendingRestore.stem === stem
      ? pendingRestore
      : (policy === 'reset' ? null : getState(filename));
    const dur = Number(videoPlayer?.duration) || 0;
    if (policy === 'reset' || !restore) {
      if (videoPlayer) videoPlayer.currentTime = 0;
      if (timelineSlider) timelineSlider.value = 0;
      if (policy === 'reset' && filename) clearState(filename);
      updateTimelineUI(videoPlayer, timelineSlider, timelineTimeDisplay, { forceSlider: true });
      return;
    }
    const rawTime = Number(restore.time) || 0;
    const clampedTime = dur > 0 ? Math.max(0, Math.min(dur, rawTime)) : rawTime;
    if (videoPlayer) videoPlayer.currentTime = clampedTime;
    updateTimelineUI(videoPlayer, timelineSlider, timelineTimeDisplay, {
      forceSlider: true,
      fallbackState: dur > 0 ? null : restore,
      useFallbackOnly: !(dur > 0),
    });
    if (restore.shouldResume && policy === 'auto-resume') {
      resumeVideoPlayback(videoPlayer, btnPlayPause);
    }
  }

  window.ScrubberPlaybackState = {
    STORAGE_KEY,
    getBaseStem,
    saveState,
    saveFromPlayer,
    getState,
    clearState,
    formatTime,
    updateTimelineUI,
    resolveLoadRestore,
    resumeVideoPlayback,
    applyMetadataRestore,
    getSavedMap: () => savedPlaybackByStem,
  };
})();
