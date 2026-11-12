/**
 * Intelligent Tracker - Scrubber Library Sidebar & Codec UI Bridge.
 *
 * Manages video recordings sidebar fetching, card selection/deletion bindings,
 * loaded title truncation, and codec notice synchronization for VideoScrubber.
 */

(function () {
  'use strict';

  function updateLoadedTitle(filename) {
    const titleEl = document.getElementById('scrubber-loaded-title');
    if (!titleEl) return;
    const fullTitle = 'Loaded: ' + filename;
    if (window.TextTruncationManager) {
      window.TextTruncationManager.apply(titleEl, {
        fullText: fullTitle,
        mode: 'middle',
        maxLength: 38,
        preserveExt: true,
        label: 'Loaded Video File',
      });
    } else {
      titleEl.textContent = fullTitle;
      titleEl.title = fullTitle;
    }
  }

  function handlePlayerError(videoPlayer, currentVideoFilename, reloadList) {
    const err = videoPlayer?.error;
    let msg = 'Browser error playing video recording.';
    if (err && typeof MediaError !== 'undefined' && err.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      msg = 'Codec not supported natively by browser (e.g. HEVC/H.265). Convert to standard H.264 MP4 for instant browser playback.';
    }
    window.VideoLibrary?.showCodecNotice(msg, currentVideoFilename, (fn, opts) => {
      window.VideoLibrary?.transcodeVideo(fn, () => reloadList(), opts);
    });
  }

  function syncLoadedVideoUI(filename, isWebCompatible, codec, options = {}, context = {}) {
    updateLoadedTitle(filename);
    if (context.btnAddAsCamera) context.btnAddAsCamera.disabled = false;
    window.VideoJobClient?.setCurrentViewedFilename(filename);
    window.VideoBatch?.setCurrentBatchFilename(filename);
    window.VideoBatch?.restoreReportForFile(filename);
    window.ScrubberOverlay?.loadDetections(filename);

    if (isWebCompatible === false) {
      window.VideoLibrary?.showCodecNotice(
        `This video is encoded with '${(codec || 'HEVC').toUpperCase()}' which may not play in standard browsers without conversion.`,
        filename,
        (fn, opts) => window.VideoLibrary?.transcodeVideo(fn, () => context.reloadList?.(), opts),
        options
      );
      const activeJob = window.VideoJobClient?.getActiveJob(filename);
      if (activeJob && activeJob.job_type === 'transcode') {
        const noticeBtn = document.querySelector(`.btn-notice-convert[data-filename="${CSS.escape(filename)}"]`);
        if (noticeBtn) {
          noticeBtn.disabled = true;
          noticeBtn.textContent = `⏳ ${(activeJob.progress || 0).toFixed(0)}%`;
        }
      }
    }
    window.VideoLibrary?.setActiveVideoCard?.(filename);
  }

  function bindCardSelectionEvents(videoFilesList, loadVideoIntoPlayer) {
    videoFilesList.querySelectorAll('.video-file-card').forEach(card => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('button, a, input, .video-action-dropdown')) return;
        card.querySelector('.btn-select-video')?.click();
      });
      card.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === card) {
          e.preventDefault();
          card.querySelector('.btn-select-video')?.click();
        }
      });
    });

    videoFilesList.querySelectorAll('.btn-select-video').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        loadVideoIntoPlayer(
          btn.getAttribute('data-url'),
          btn.getAttribute('data-filename'),
          btn.getAttribute('data-web') === 'true',
          btn.getAttribute('data-codec'),
          { convertedFilename: btn.getAttribute('data-converted') || null }
        );
      });
    });
  }

  function bindVideoCardActions(videoFilesList, { loadVideoIntoPlayer, reloadList }) {
    bindCardSelectionEvents(videoFilesList, loadVideoIntoPlayer);

    const onTranscodeDone = (data) => {
      reloadList();
      if (data?.output_filename) {
        loadVideoIntoPlayer(data.video_url, data.output_filename, true, 'h264');
      }
    };

    window.VideoLibrary?.bindPairedActionControls?.(videoFilesList, (fn, opts) => {
      window.VideoLibrary?.transcodeVideo(fn, onTranscodeDone, opts);
    });

    videoFilesList.querySelectorAll('.btn-transcode-video').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fn = btn.getAttribute('data-filename');
        window.VideoLibrary?.transcodeVideo(fn, onTranscodeDone, { force: false });
      });
    });

    videoFilesList.querySelectorAll('.btn-del-video').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const fn = btn.getAttribute('data-filename');
        if (confirm(`Delete recording file '${fn}'?`)) {
          await fetch(`/api/videos/${encodeURIComponent(fn)}`, { method: 'DELETE' });
          await reloadList();
        }
      });
    });
  }

  async function loadVideosList({ videoFilesList, getCurrentFilename, loadVideoIntoPlayer, reloadList }) {
    if (!videoFilesList) return;
    try {
      const resp = await fetch('/api/videos');
      const files = await resp.json();

      if (!files || files.length === 0) {
        window.VideoLibrary?.registerVideos?.([]);
        videoFilesList.innerHTML = '<div class="empty-state">No uploaded recordings found. Upload an MP4 or MKV recording to scrub and analyze.</div>';
        return;
      }

      const activeFilename = getCurrentFilename();
      window.VideoLibrary?.registerVideos?.(files);
      videoFilesList.innerHTML = files.map(file => window.VideoLibrary?.renderVideoFileCard(file, activeFilename) || '').join('');
      bindVideoCardActions(videoFilesList, { loadVideoIntoPlayer, reloadList });
      window.VideoLibrary?.setActiveVideoCard?.(activeFilename);
      window.VideoJobClient?.updateSidebarCards();

      if (!activeFilename && files.length > 0) {
        const preferred = files.find(f => f.web_compatible) || files[0];
        loadVideoIntoPlayer(preferred.video_url, preferred.filename, preferred.web_compatible, preferred.codec, {
          convertedFilename: preferred.converted_filename,
        });
      }
    } catch (e) {
      console.warn('Could not load videos list:', e);
    }
  }

  window.ScrubberLibraryBridge = {
    updateLoadedTitle,
    handlePlayerError,
    syncLoadedVideoUI,
    bindVideoCardActions,
    loadVideosList,
  };
})();

