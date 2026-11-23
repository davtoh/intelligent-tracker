/**
 * Intelligent Tracker - Multi-View WebSocket Protocol v1 (Client).
 * Parses 16-byte big-endian binary frames and builds/parses JSON control messages.
 */

(function () {
  'use strict';

  const PROTOCOL_VERSION = 0x01;
  const KIND_JPEG = 0x01;
  const HEADER_SIZE = 16;

  const LAYOUT_DEFAULTS = {
    '2x2': { max_fps: 15, max_width: 640 },
    '3x3': { max_fps: 10, max_width: 480 },
    '4x4': { max_fps: 6, max_width: 320 },
  };

  function decodeUtf8(bytes) {
    if (typeof TextDecoder === 'function') {
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    }
    if (typeof Buffer !== 'undefined') {
      return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('utf8');
    }
    return String.fromCharCode.apply(null, Array.from(bytes));
  }

  function toBufferView(input) {
    if (!input) {
      throw new Error('Binary frame must not be empty');
    }
    if (ArrayBuffer.isView(input)) {
      return { buffer: input.buffer, byteOffset: input.byteOffset, byteLength: input.byteLength };
    }
    if (input instanceof ArrayBuffer || (typeof input.byteLength === 'number' && !input.buffer)) {
      return { buffer: input, byteOffset: 0, byteLength: input.byteLength };
    }
    throw new Error('Binary frame must be an ArrayBuffer or ArrayBufferView');
  }

  function parseBinaryFrame(input) {
    const { buffer, byteOffset, byteLength } = toBufferView(input);
    if (byteLength < HEADER_SIZE) {
      throw new Error(`Frame too short (${byteLength} < ${HEADER_SIZE})`);
    }
    const view = new DataView(buffer, byteOffset, byteLength);
    const version = view.getUint8(0);
    if (version !== PROTOCOL_VERSION) {
      throw new Error(`Unsupported frame version: ${version}`);
    }
    const kind = view.getUint8(1);
    const camIdLen = view.getUint16(2, false);
    if (camIdLen === 0 || HEADER_SIZE + camIdLen > byteLength) {
      throw new Error('Truncated or empty camera_id in frame');
    }
    const seq = view.getUint32(4, false);
    const tsHigh = view.getUint32(8, false);
    const tsLow = view.getUint32(12, false);
    const captureTsMs = (tsHigh * 4294967296) + tsLow;

    const camOffset = byteOffset + HEADER_SIZE;
    const cameraId = decodeUtf8(new Uint8Array(buffer, camOffset, camIdLen));
    const payloadOffset = camOffset + camIdLen;
    const payloadLength = byteLength - HEADER_SIZE - camIdLen;
    const payload = new Uint8Array(buffer, payloadOffset, payloadLength);

    return { version, kind, cameraId, seq, captureTsMs, payload };
  }

  function isNewerSeq(seq, lastSeq) {
    if (lastSeq === null || lastSeq === undefined) return true;
    const diff = (seq - lastSeq) >>> 0;
    return diff > 0 && diff < 0x80000000;
  }

  function buildSubscribeMessage(cameras, layout = '2x2', options = {}) {
    const defaults = LAYOUT_DEFAULTS[layout] || LAYOUT_DEFAULTS['2x2'];
    return {
      v: PROTOCOL_VERSION,
      action: 'subscribe',
      cameras: Array.isArray(cameras) ? cameras.slice() : [],
      layout: layout,
      profile: options.profile || 'thumb',
      max_fps: options.maxFps !== undefined ? options.maxFps : defaults.max_fps,
      max_width: options.maxWidth !== undefined ? options.maxWidth : defaults.max_width,
    };
  }

  function buildControlMessage(action) {
    return { v: PROTOCOL_VERSION, action: String(action || '') };
  }

  function parseControlMessage(raw) {
    if (raw && typeof raw === 'object') return raw;
    if (typeof raw !== 'string') return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  window.MultiviewProtocol = {
    PROTOCOL_VERSION,
    KIND_JPEG,
    HEADER_SIZE,
    LAYOUT_DEFAULTS,
    parseBinaryFrame,
    isNewerSeq,
    buildSubscribeMessage,
    buildControlMessage,
    parseControlMessage,
  };
})();
