(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, ms = 1500) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { const v = fn(); if (v) return v; await sleep(50); }
    return fn();
  };
  const isContained = (child, parent) => {
    if (!child || !parent) return false;
    const cr = child.getBoundingClientRect(), pr = parent.getBoundingClientRect();
    return cr.right <= pr.right + 2 && cr.left >= pr.left - 2;
  };
  const tabs = ['tab-live', 'tab-videos', 'tab-gallery', 'tab-timeline', 'tab-analytics', 'tab-alerts', 'tab-studio', 'tab-journey', 'tab-review'];
  const tabResults = {};
  for (const id of tabs) {
    const btn = document.querySelector(`.nav-tab[data-tab="${id}"]`);
    if (!btn) { tabResults[id] = { missing: true }; continue; }
    btn.click();
    await sleep(180);
    const pane = document.getElementById(id);
    const overflowX = document.documentElement.scrollWidth > window.innerWidth + 1;
    tabResults[id] = { active: pane?.classList.contains('active') || false, overflowX };
  }
  document.querySelector('.nav-tab[data-tab="tab-live"]')?.click();
  await sleep(150);
  const gridEl = document.getElementById('multi-grid-container');
  const gridParity = {};
  for (const mode of ['2x2', '3x3', '4x4', '1x1']) {
    document.querySelector(`.grid-switch-btn[data-grid="${mode}"]`)?.click();
    await sleep(180);
    if (mode !== '1x1') {
      const tiles = Array.from(document.querySelectorAll('#multi-grid-container .camera-grid-tile'));
      const mismatch = tiles.some((tile) => {
        const cont = tile.querySelector('.tile-video-container');
        const cvs = tile.querySelector('canvas.tile-overlay-canvas');
        if (!cont || !cvs) return true;
        const cr = cont.getBoundingClientRect(), vr = cvs.getBoundingClientRect();
        return Math.abs(cr.width - vr.width) > 2 || Math.abs(cr.height - vr.height) > 2;
      });
      gridParity[mode] = { active: gridEl?.classList.contains(`grid-${mode}`) || false, tiles: tiles.length, overlayMatch: !mismatch };
    }
  }
  const sel = document.getElementById('active-camera-select');
  const titleEl = document.getElementById('video-stream-title');
  const titleRects = [];
  if (sel && sel.options.length >= 2) {
    for (const opt of [sel.options[1], sel.options[0]]) {
      sel.value = opt.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(100);
      titleRects.push(titleEl ? titleEl.getBoundingClientRect().height : 0);
    }
  }
  document.querySelector('.nav-tab[data-tab="tab-videos"]')?.click();
  await sleep(150);
  const vPanel = document.querySelector('#tab-videos .video-upload-panel');
  const vStatus = document.getElementById('video-upload-status');
  if (vStatus) vStatus.innerHTML = '<span style="color:#10b981;">\u2713 Uploaded \'warehouse_north_entrance_security_recording_2026_11_27_long_clip_01.mp4\'</span>';
  const vSpan = vStatus?.querySelector('span');
  const uploadHintContained = Boolean(isContained(vStatus, vPanel) && (!vSpan || isContained(vSpan, vPanel)));
  document.querySelector('.nav-tab[data-tab="tab-analytics"]')?.click();
  const hm = document.getElementById('static-heatmap-img');
  const heatmapLoaded = Boolean(await waitFor(() => hm && hm.complete && hm.naturalWidth > 0));
  const aSel = document.getElementById('analytics-source-select');
  await waitFor(() => aSel && aSel.options.length > 1, 2000);
  const aCard = document.querySelector('#tab-analytics .chart-card');
  const analyticsSelectContained = Boolean(isContained(aSel, aCard));
  document.querySelector('.nav-tab[data-tab="tab-alerts"]')?.click();
  const alertsReady = Boolean(await waitFor(() => document.getElementById('tab-alerts')?.classList.contains('active')));
  document.querySelector('.nav-tab[data-tab="tab-journey"]')?.click();
  const journeyReady = Boolean(await waitFor(() => document.getElementById('tab-journey')?.classList.contains('active')));
  document.querySelector('.nav-tab[data-tab="tab-review"]')?.click();
  const reviewCardReady = Boolean(await waitFor(() => {
    const card = document.querySelector('#review-queue-container .review-card');
    return card && card.querySelector('.review-bbox-badge') && card.querySelector('.review-source-pill');
  }));
  const reviewCards = Array.from(document.querySelectorAll('#review-queue-container .review-card'));
  const reviewCardContained = Boolean(reviewCards.length) && reviewCards.every((c) => {
    const targets = [c.querySelector('.review-card-top'), c.querySelector('.review-meta'), c.querySelector('.review-title'), c.querySelector('.review-source-pill')].filter(Boolean);
    return targets.every((el) => isContained(el, c));
  });
  let connStatusPopoverCleared = false;
  const connPill = document.getElementById('connection-status-pill');
  const connTxt = document.getElementById('connection-status-text');
  if (connTxt && window.AppUIHelpers?.updateWsStatus) {
    window.AppUIHelpers.updateWsStatus(true, 'warehouse_north_entrance_camera_long_id_01', connPill, connTxt);
    const hadTrigger = connTxt.classList.contains('truncate-trigger') && connTxt.hasAttribute('data-full-text');
    window.AppUIHelpers.updateWsStatus(true, 'cam_short', connPill, connTxt);
    window.TelemetryGateway?.updateConnectionStatus?.({ status: 'simulation', camera_id: 'cam_short' }, 'cam_short');
    connStatusPopoverCleared = hadTrigger && !connTxt.classList.contains('truncate-trigger') && !connTxt.hasAttribute('data-full-text');
  }
  document.querySelector('.nav-tab[data-tab="tab-studio"]')?.click();
  const stImg = document.getElementById('studio-live-img'), stSel = document.getElementById('studio-camera-select');
  if (await waitFor(() => stSel && Array.from(stSel.options).some((o) => o.value === 'cam_short'))) {
    stSel.value = 'cam_short'; stSel.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const studioLiveLoaded = Boolean(await waitFor(() => stImg && stImg.naturalWidth > 0, 2800));
  let studioOfflineEmptyOk = false;
  if (stSel && Array.from(stSel.options).some((o) => o.value === 'cam_long')) {
    stSel.value = 'cam_long'; stSel.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(150);
    const emptyEl = document.getElementById('studio-empty-state') || document.querySelector('#tab-studio .media-empty-state');
    const imgHidden = !stImg || getComputedStyle(stImg).display === 'none';
    studioOfflineEmptyOk = Boolean(emptyEl && getComputedStyle(emptyEl).display !== 'none' && imgHidden);
  }
  const recGroup = await waitFor(() => stSel && Array.from(stSel.querySelectorAll('optgroup')).find((g) => g.label === 'Recorded Videos'));
  let recordedSelected = false;
  if (recGroup && recGroup.querySelector('option')) {
    stSel.value = recGroup.querySelector('option').value;
    stSel.dispatchEvent(new Event('change', { bubbles: true }));
    recordedSelected = Boolean(await waitFor(() => document.querySelector('#studio-video-player, #tab-studio video')));
  }
  const modalOk = {};
  let enrollChanged = false;
  let camTableErgonomic = false;
  let candidateXNonClosing = false;
  for (const [openId, modalId, closeId] of [['#btn-manage-cameras', '#modal-camera-manager', '#modal-cam-close'], ['#btn-open-enrollment', '#modal-universal-enrollment', '#modal-enroll-close']]) {
    document.querySelector(openId)?.click(); await sleep(150);
    const el = document.querySelector(modalId);
    const open = el?.classList.contains('active') || getComputedStyle(el || document.body).display !== 'none';
    if (modalId === '#modal-camera-manager') {
      const tbl = el?.querySelector('.data-table');
      camTableErgonomic = Boolean(!tbl || tbl.scrollWidth <= tbl.clientWidth + 2);
    }
    if (modalId === '#modal-universal-enrollment') {
      const esel = document.getElementById('enroll-camera-select');
      const liveToggleBtn = document.getElementById('btn-enroll-live-toggle');
      if (await waitFor(() => esel && Array.from(esel.options).some((o) => o.value === 'cam_short'))) {
        esel.value = 'cam_short'; esel.dispatchEvent(new Event('change', { bubbles: true }));
        const cvs = document.getElementById('enroll-bbox-canvas');
        enrollChanged = Boolean(liveToggleBtn) && Boolean(await waitFor(() => cvs && cvs.width > 0 && getComputedStyle(cvs).display !== 'none'));
      }
    }
    document.querySelector(closeId)?.click(); await sleep(100);
    modalOk[modalId] = open;
  }
  const sourceRefRoundTripOk = Boolean(
    window.AppNavigation?.buildHash && window.AppNavigation?.parseHash && (() => {
      const h1 = window.AppNavigation.buildHash('tab-analytics', { cameraId: 'cam_short', runId: 'r1' });
      const h2 = window.AppNavigation.buildHash('tab-videos', { videoFilename: 'clip.mp4', mediaOffsetSec: 3.5, runId: 'r1' });
      const p1 = window.AppNavigation.parseHash(h1), p2 = window.AppNavigation.parseHash(h2);
      return p1.route === 'analytics' && p1.params.camera === 'cam_short' && p2.route === 'videos' && p2.params.video === 'clip.mp4';
    })()
  );
  const jumpButtonsHtml = window.VideoTimelineLinks?.buildSourceJumpButtonsHtml?.({ cameraId: 'cam_short', videoFilename: 'clip.mp4', mediaOffsetSec: 2 }) || '';
  const sourceJumpButtonsOk = jumpButtonsHtml.includes('btn-jump-live') && jumpButtonsHtml.includes('btn-jump-studio');
  const freezeButtonsOk = Boolean(document.getElementById('btn-studio-freeze-toggle') && document.getElementById('btn-enroll-live-toggle') && document.getElementById('analytics-source-select'));
  const tagModal = document.getElementById('modal-tag-entity');
  const candBox = document.getElementById('tag-identity-candidates');
  if (tagModal && candBox && window.TagFeedbackActions?.attachCandidateDiscourage) {
    tagModal.style.display = 'flex';
    candBox.innerHTML = '<button type="button" class="btn btn-xs btn-outline candidate-chip" data-entity-id="1"><span>Alice</span></button>';
    const chipBtn = candBox.querySelector('.candidate-chip');
    window.TagFeedbackActions.attachCandidateDiscourage(chipBtn, { entity_id: 1, name: 'Alice', similarity: 0.72 }, candBox, () => 'cam_short');
    candBox.querySelector('.candidate-discourage-btn')?.click();
    await sleep(100);
    candidateXNonClosing = getComputedStyle(tagModal).display !== 'none';
    tagModal.style.display = 'none';
  }
  return { tabs: tabResults, grid2x2Active: Boolean(gridParity['2x2']?.active), gridParity, heatmapLoaded, alertsReady, journeyReady, reviewCardReady, studioLiveLoaded, studioOfflineEmptyOk, recordedSelected, enrollChanged, camTableErgonomic, candidateXNonClosing, uploadHintContained, analyticsSelectContained, reviewCardContained, connStatusPopoverCleared, sourceRefRoundTripOk, sourceJumpButtonsOk, freezeButtonsOk, titleHeights: titleRects, modals: modalOk };
})()
