/**
 * Intelligent Tracker - Scenario Studio Interactive Shape Editor.
 * Enables idle-mode polygon/tripwire hit-testing, vertex handle dragging,
 * whole-shape translation, Escape cancel, inline rename, and PUT persistence.
 */

(function () {
  'use strict';

  const HIT_RADIUS = 10;
  let _getState = () => ({});
  let _callbacks = {};
  let _selected = null;
  let _drag = null;
  let _escapeBound = false;

  const clonePts = (pts) => (Array.isArray(pts) ? pts.map((p) => [Math.round(p[0]), Math.round(p[1])]) : []);
  const pointsChanged = (a, b) => a.length !== b.length || a.some((p, i) => p[0] !== b[i][0] || p[1] !== b[i][1]);

  function pointInPolygon(pt, poly) {
    if (!Array.isArray(poly) || poly.length < 3) return false;
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1];
      const xj = poly[j][0], yj = poly[j][1];
      const intersect = ((yi > pt.y) !== (yj > pt.y))
        && (pt.x < ((xj - xi) * (pt.y - yi)) / ((yj - yi) || 1e-9) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function distToSegment(pt, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const lenSq = dx * dx + dy * dy;
    if (lenSq <= 0) return Math.hypot(pt.x - a[0], pt.y - a[1]);
    const t = Math.max(0, Math.min(1, ((pt.x - a[0]) * dx + (pt.y - a[1]) * dy) / lenSq));
    return Math.hypot(pt.x - (a[0] + t * dx), pt.y - (a[1] + t * dy));
  }

  function findShape(type, name) {
    const state = _getState();
    const list = type === 'zone' ? state.zones : state.tripwires;
    return Array.isArray(list) ? list.find((item) => item.name === name) || null : null;
  }

  function applyShapePoints(type, name, pts) {
    const item = findShape(type, name);
    if (!item) return;
    if (type === 'zone') item.polygon = clonePts(pts);
    else item.line_segment = clonePts(pts);
  }

  function getFlipHandle(seg) {
    if (!Array.isArray(seg) || seg.length < 2) return null;
    if (window.UnifiedCanvasOverlay?.computeTripwireFlipHandle) {
      return window.UnifiedCanvasOverlay.computeTripwireFlipHandle(seg[0], seg[1], 26);
    }
    const dx = seg[1][0] - seg[0][0], dy = seg[1][1] - seg[0][1], len = Math.hypot(dx, dy);
    if (len < 1e-3) return null;
    return { x: (seg[0][0] + seg[1][0]) / 2 + (-dy / len) * 26, y: (seg[0][1] + seg[1][1]) / 2 + (dx / len) * 26 };
  }

  function hitTestVertices(pt, items, type, key) {
    for (let i = items.length - 1; i >= 0; i--) {
      const pts = items[i][key] || [];
      for (let v = 0; v < pts.length; v++) {
        if (Math.hypot(pt.x - pts[v][0], pt.y - pts[v][1]) <= HIT_RADIUS) {
          return { type, name: items[i].name, kind: 'vertex', vertexIndex: v, origPoints: clonePts(pts) };
        }
      }
    }
    return null;
  }

  function hitTest(pt) {
    const state = _getState();
    const zones = Array.isArray(state.zones) ? state.zones : [];
    const tripwires = Array.isArray(state.tripwires) ? state.tripwires : [];
    for (let i = tripwires.length - 1; i >= 0; i--) {
      const seg = tripwires[i].line_segment || tripwires[i].line || [];
      const h = getFlipHandle(seg);
      if (h && Math.hypot(pt.x - h.x, pt.y - h.y) <= HIT_RADIUS + 2) {
        return { type: 'tripwire', name: tripwires[i].name, kind: 'flip', origPoints: clonePts(seg) };
      }
    }
    const vHit = hitTestVertices(pt, zones, 'zone', 'polygon') || hitTestVertices(pt, tripwires, 'tripwire', 'line_segment');
    if (vHit) return vHit;
    for (let i = zones.length - 1; i >= 0; i--) {
      if (pointInPolygon(pt, zones[i].polygon)) {
        return { type: 'zone', name: zones[i].name, kind: 'shape', origPoints: clonePts(zones[i].polygon) };
      }
    }
    for (let i = tripwires.length - 1; i >= 0; i--) {
      const seg = tripwires[i].line_segment || tripwires[i].line || [];
      if (seg.length >= 2 && distToSegment(pt, seg[0], seg[1]) <= HIT_RADIUS) {
        return { type: 'tripwire', name: tripwires[i].name, kind: 'shape', origPoints: clonePts(seg) };
      }
    }
    return null;
  }

  function cancelDrag() {
    if (_drag) {
      applyShapePoints(_drag.type, _drag.name, _drag.origPoints);
      _drag = null;
      _callbacks.drawOverlay?.(); _callbacks.updateStatus?.('Shape edit cancelled.');
      return true;
    }
    if (_selected) { _selected = null; _callbacks.drawOverlay?.(); return true; }
    return false;
  }

  function init(getState, callbacks = {}) {
    _getState = getState; _callbacks = callbacks;
    if (!_escapeBound && typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      _escapeBound = true;
      window.addEventListener('keydown', (evt) => {
        if (evt.key === 'Escape' && _getState().mode === 'idle') cancelDrag();
      });
    }
  }

  function onMouseDown(pt) {
    if (_getState().mode !== 'idle' || !pt) return false;
    const hit = hitTest(pt);
    if (!hit) {
      if (_selected) { _selected = null; _callbacks.drawOverlay?.(); }
      _drag = null;
      return false;
    }
    _selected = { type: hit.type, name: hit.name };
    _drag = { ...hit, startPt: { x: pt.x, y: pt.y }, currentPoints: clonePts(hit.origPoints) };
    _callbacks.drawOverlay?.();
    return true;
  }

  function onMouseMove(pt) {
    if (!_drag || !pt) return false;
    if (_drag.kind === 'flip') return true;
    if (_drag.kind === 'vertex') {
      _drag.currentPoints[_drag.vertexIndex] = [Math.round(pt.x), Math.round(pt.y)];
    } else {
      const dx = Math.round(pt.x - _drag.startPt.x), dy = Math.round(pt.y - _drag.startPt.y);
      _drag.currentPoints = _drag.origPoints.map((p) => [p[0] + dx, p[1] + dy]);
    }
    applyShapePoints(_drag.type, _drag.name, _drag.currentPoints);
    _callbacks.drawOverlay?.();
    return true;
  }

  async function persistGeometryEdit(snapshot) {
    const cameraId = _getState().activeCamera;
    if (!cameraId) {
      applyShapePoints(snapshot.type, snapshot.name, snapshot.origPoints);
      _callbacks.drawOverlay?.();
      return false;
    }
    const isZone = snapshot.type === 'zone';
    const endpoint = isZone
      ? `/api/scenarios/zones/${encodeURIComponent(cameraId)}/${encodeURIComponent(snapshot.name)}`
      : `/api/scenarios/tripwires/${encodeURIComponent(cameraId)}/${encodeURIComponent(snapshot.name)}`;
    const body = isZone ? { polygon: snapshot.currentPoints } : { line_segment: snapshot.currentPoints };
    try {
      const res = await fetch(endpoint, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText || `HTTP ${res.status}`);
      }
      window.StudioOverlays?.renderScenarioListUI?.();
      _callbacks.drawOverlay?.();
      _callbacks.updateStatus?.(`Updated ${snapshot.type} '${snapshot.name}'.`);
      _callbacks.showToast?.('Scenario Updated', `Saved geometry for '${snapshot.name}'.`, 'success');
      return true;
    } catch (err) {
      applyShapePoints(snapshot.type, snapshot.name, snapshot.origPoints);
      window.StudioOverlays?.renderScenarioListUI?.();
      _callbacks.drawOverlay?.();
      _callbacks.showToast?.('Update Failed', err.message || 'Could not save geometry.', 'error');
      return false;
    }
  }

  function onMouseUp() {
    if (!_drag) return false;
    const snapshot = _drag;
    _drag = null;
    if (snapshot.kind === 'flip' && snapshot.origPoints.length >= 2) {
      snapshot.currentPoints = [snapshot.origPoints[1], snapshot.origPoints[0]];
      applyShapePoints('tripwire', snapshot.name, snapshot.currentPoints);
      _callbacks.drawOverlay?.();
      return persistGeometryEdit(snapshot);
    }
    if (!pointsChanged(snapshot.origPoints, snapshot.currentPoints)) {
      _callbacks.drawOverlay?.();
      return true;
    }
    return persistGeometryEdit(snapshot);
  }

  function flipTripwire(name) {
    const tw = findShape('tripwire', name);
    const seg = tw?.line_segment || tw?.line;
    if (!Array.isArray(seg) || seg.length < 2) return Promise.resolve(false);
    const origPoints = clonePts(seg);
    const currentPoints = [origPoints[1], origPoints[0]];
    applyShapePoints('tripwire', name, currentPoints);
    _callbacks.drawOverlay?.();
    return persistGeometryEdit({ type: 'tripwire', name, kind: 'flip', origPoints, currentPoints });
  }

  async function updateShapeMetadata(type, cameraId, oldName, payload) {
    if (!cameraId || !oldName || !payload) return false;
    const nextName = payload.name ? String(payload.name).trim() : oldName;
    if (!nextName) return false;
    const body = { ...payload, name: nextName };
    const base = type === 'zone' ? '/api/scenarios/zones' : '/api/scenarios/tripwires';
    const endpoint = `${base}/${encodeURIComponent(cameraId)}/${encodeURIComponent(oldName)}`;
    try {
      const res = await fetch(endpoint, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText || `HTTP ${res.status}`);
      }
      const item = findShape(type, oldName);
      if (item) Object.assign(item, body);
      if (_selected?.type === type && _selected.name === oldName) _selected.name = nextName;
      window.StudioOverlays?.renderScenarioListUI?.();
      _callbacks.drawOverlay?.();
      _callbacks.updateStatus?.(`Updated ${type} '${nextName}'.`);
      _callbacks.showToast?.('Scenario Updated', `Saved '${nextName}'.`, 'success');
      return true;
    } catch (err) {
      _callbacks.showToast?.('Update Failed', err.message || 'Could not update shape.', 'error');
      return false;
    }
  }

  async function renameShape(type, cameraId, oldName, providedName) {
    if (!cameraId || !oldName) return false;
    if (providedName === undefined) {
      const item = findShape(type, oldName);
      const opener = type === 'zone' ? window.ScenarioModals?.openEditZoneModal : window.ScenarioModals?.openEditTripwireModal;
      if (item && typeof opener === 'function') {
        opener(item, cameraId, (cid, orig, payload) => updateShapeMetadata(type, cid, orig, payload));
        return true;
      }
    }
    const raw = providedName !== undefined ? providedName : (typeof prompt === 'function' ? prompt(`Rename ${type} '${oldName}':`, oldName) : null);
    const nextName = raw ? String(raw).trim() : '';
    if (!nextName || nextName === oldName) return false;
    return updateShapeMetadata(type, cameraId, oldName, { name: nextName });
  }

  function drawHandles(ctx, pts, isSelected) {
    if (!Array.isArray(pts)) return;
    for (let i = 0; i < pts.length; i++) {
      ctx.beginPath(); ctx.arc(pts[i][0], pts[i][1], isSelected ? 6 : 4, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? '#38bdf8' : '#ffffff'; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = isSelected ? '#ffffff' : '#0f172a'; ctx.stroke();
    }
  }

  function drawFlipHandle(ctx, seg, isSelected) {
    const h = getFlipHandle(seg);
    if (!h) return;
    ctx.beginPath(); ctx.arc(h.x, h.y, isSelected ? 9 : 8, 0, Math.PI * 2);
    ctx.fillStyle = isSelected ? '#0284c7' : '#0f172a'; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#38bdf8'; ctx.stroke();
    if (typeof ctx.fillText === 'function') {
      ctx.fillStyle = '#ffffff'; ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('⇄', h.x, h.y);
    }
  }

  function drawSelection(ctx, _canvas, saved) {
    if (!ctx || !saved) return;
    ctx.save();
    (saved.zones || []).forEach((z) => drawHandles(ctx, z.polygon, _selected?.type === 'zone' && _selected?.name === z.name));
    (saved.tripwires || []).forEach((tw) => {
      const seg = tw.line_segment || tw.line;
      const isSel = _selected?.type === 'tripwire' && _selected?.name === tw.name;
      drawHandles(ctx, seg, isSel); drawFlipHandle(ctx, seg, isSel);
    });
    ctx.restore();
  }

  function selectShape(type, name) {
    const item = findShape(type, name);
    if (!item) return false;
    _selected = { type, name: item.name }; _callbacks.drawOverlay?.(); return true;
  }

  window.StudioShapeEditor = {
    init, hitTest, onMouseDown, onMouseMove, onMouseUp, cancelDrag, updateShapeMetadata,
    renameShape, flipTripwire, drawSelection, selectShape, getSelected: () => _selected,
  };
})();
