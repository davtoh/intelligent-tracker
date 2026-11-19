(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitUntil(fn, timeoutMs = 8000, label = 'condition', diagFn = null) {
    const start = performance.now();
    let lastErr = null;
    while (performance.now() - start < timeoutMs) {
      try {
        const res = fn();
        if (res) return res;
      } catch (err) {
        lastErr = err?.message || String(err);
      }
      await sleep(50);
    }
    const errPart = lastErr ? ` | lastErr=${lastErr}` : '';
    const extra = diagFn ? ' | diag=' + JSON.stringify(diagFn()) : '';
    throw new Error(`Timed out waiting for: ${label}${errPart}${extra}`);
  }
  function assert(cond, msg) {
    if (!cond) throw new Error(`Assertion failed: ${msg}`);
  }
  const liveDiag = () => {
    const el = document.getElementById('live-stream-img');
    return {
      src: el?.src || '',
      complete: el?.complete,
      nw: el?.naturalWidth,
      nh: el?.naturalHeight,
      gridMode: window.CameraGrid?.getGridMode?.(),
      ws: window.MultiviewWsClient?.getState?.(),
    };
  };

  await waitUntil(
    () => window.CameraGrid && window.MultiviewWsClient && document.querySelectorAll('#active-camera-select option').length >= 6,
    8000,
    'initial 6 cameras hydrated',
  );

  // 1. Initial 1x1 state: WS lazy (disconnected), 1x1 MJPEG live
  assert(window.MultiviewWsClient.getState().connected === false, 'WS must stay disconnected in 1x1');
  const liveImg = document.getElementById('live-stream-img');
  await waitUntil(() => liveImg && !liveImg.src.startsWith('data:') && liveImg.naturalWidth > 0, 8000, 'initial 1x1 stream load', liveDiag);
  const initialDims = { w: liveImg.naturalWidth, h: liveImg.naturalHeight, complete: liveImg.complete };

  // 2. 1x1 -> 2x2: WS canvas tiles, Page 1 of 2, live binary frames received, fast fetch()
  const receivedFrames = {};
  document.querySelector('.grid-switch-btn[data-grid="2x2"]').click();
  const origOnFrame = window.MultiviewWsClient.onFrame;
  window.MultiviewWsClient.onFrame = (frame) => {
    receivedFrames[frame.cameraId] = (receivedFrames[frame.cameraId] || 0) + 1;
    return origOnFrame?.(frame);
  };
  await waitUntil(
    () => window.MultiviewWsClient.getState().connected && Object.keys(receivedFrames).length >= 4,
    8000,
    '2x2 WS frames on all 4 page-1 tiles',
  );
  const grid = document.getElementById('multi-grid-container');
  assert(grid.querySelectorAll('canvas.tile-canvas').length === 4, '2x2 should render 4 canvas tiles');
  assert(grid.querySelectorAll('img').length === 0, '2x2 WS mode should render 0 img tiles');
  assert(document.getElementById('grid-page-indicator').textContent === 'Page 1 of 2', '2x2 page 1 indicator');

  const tFetch0 = performance.now();
  const pmResp = await fetch('/api/system/processing-mode');
  const fetchMs = Math.round(performance.now() - tFetch0);
  assert(pmResp.ok && fetchMs < 2000, `fetch(/api/system/processing-mode) failed or slow: ${fetchMs}ms`);

  // 3. Pagination Next -> Page 2 of 2 (cam_05, cam_06)
  document.getElementById('btn-grid-next').click();
  await waitUntil(
    () => document.getElementById('grid-page-indicator').textContent === 'Page 2 of 2'
      && (receivedFrames.cam_05 || 0) > 0 && (receivedFrames.cam_06 || 0) > 0,
    8000,
    '2x2 page 2 frames',
  );
  assert(grid.querySelectorAll('canvas.tile-canvas').length === 2, '2x2 page 2 should render 2 canvas tiles');
  document.getElementById('btn-grid-prev').click();

  // 4. 2x2 -> 3x3 -> 4x4
  document.querySelector('.grid-switch-btn[data-grid="3x3"]').click();
  await waitUntil(() => grid.classList.contains('grid-3x3') && grid.querySelectorAll('canvas.tile-canvas').length === 6, 4000, '3x3 canvas tiles');
  assert(grid.querySelectorAll('img').length === 0, '3x3 WS mode has 0 img');
  assert(document.getElementById('grid-degraded-badge').hidden === true, 'degraded badge hidden in 3x3 WS');

  document.querySelector('.grid-switch-btn[data-grid="4x4"]').click();
  await waitUntil(() => grid.classList.contains('grid-4x4') && grid.querySelectorAll('canvas.tile-canvas').length === 6, 4000, '4x4 canvas tiles');

  // 5. Switch to Video Studio -> back to Live -> 1x1 restore
  document.getElementById('tab-btn-videos').click();
  await waitUntil(() => window.MultiviewWsClient.getState().desired === null, 3000, 'tab switch unsubscribes WS');
  document.getElementById('tab-btn-live').click();
  await waitUntil(() => window.MultiviewWsClient.getState().desired !== null, 3000, 'returning to live re-subscribes WS');

  document.querySelector('.grid-switch-btn[data-grid="1x1"]').click();
  await waitUntil(() => liveImg && !liveImg.src.startsWith('data:') && liveImg.naturalWidth > 0, 8000, '1x1 restored after grid', liveDiag);
  const restoredDims = { w: liveImg.naturalWidth, h: liveImg.naturalHeight, complete: liveImg.complete };
  const tFetch1 = performance.now();
  const pmResp2 = await fetch('/api/system/processing-mode');
  const fetchMsAfter = Math.round(performance.now() - tFetch1);
  assert(pmResp2.ok && fetchMsAfter < 2000, `post-1x1 fetch slow: ${fetchMsAfter}ms`);

  // 6. Forced WS failure -> MJPEG fallback -> auto-restore on 3x3
  document.querySelector('.grid-switch-btn[data-grid="3x3"]').click();
  await waitUntil(() => window.MultiviewWsClient.getState().connected, 6000, 'WS connected on 3x3 before failure');

  const RealWS = window.WebSocket;
  const origBase = window.MultiviewWsClient._backoffBaseMs;
  const origMax = window.MultiviewWsClient._backoffMaxMs;
  window.MultiviewWsClient._backoffBaseMs = 80;
  window.MultiviewWsClient._backoffMaxMs = 200;
  window.WebSocket = function FailingWS(url) {
    this.url = url;
    this.readyState = 0;
    this.close = () => { this.readyState = 3; };
    this.send = () => {};
    setTimeout(() => { this.readyState = 3; this.onclose?.({ code: 1006 }); }, 20);
  };
  window.MultiviewWsClient._ws.close(4000, 'e2e_force_drop');

  await waitUntil(
    () => window.MultiviewWsClient.isDegraded() === true && document.getElementById('grid-degraded-badge').hidden === false,
    6000,
    'degraded MJPEG fallback activated',
  );
  assert(grid.classList.contains('grid-2x2'), 'fallback grid must clamp to 2x2');
  const fallbackImgCount = grid.querySelectorAll('img').length;
  assert(fallbackImgCount === 4, `expected 4 MJPEG fallback tiles, got ${fallbackImgCount}`);

  window.WebSocket = RealWS;
  await waitUntil(
    () => window.MultiviewWsClient.isDegraded() === false && window.MultiviewWsClient.getState().connected === true,
    6000,
    'WS auto-restore',
  );
  window.MultiviewWsClient._backoffBaseMs = origBase;
  window.MultiviewWsClient._backoffMaxMs = origMax;
  assert(document.getElementById('grid-degraded-badge').hidden === true, 'badge hidden after restore');
  assert(grid.classList.contains('grid-3x3'), '3x3 restored after WS recovery');
  assert(grid.querySelectorAll('canvas.tile-canvas').length === 6, '6 canvas tiles restored');

  document.querySelector('.grid-switch-btn[data-grid="1x1"]').click();
  return {
    ok: true,
    initialDims,
    restoredDims,
    fetchMs,
    fetchMsAfter,
    fallbackImgCount,
    frameCounts: receivedFrames,
  };
})()
