# Root Cause Analysis: Detection Box Synchronization Discrepancy Between Live Monitor and Video Studio

**Date:** 2026-11-18  
**Status:** Completed / Ready for Plan Creation  
**Scope:** Camera Stream Pipeline, Video Studio Scrubber, Live MJPEG Streaming, WebSocket Telemetry  
**Target Entities:** `vid_Video_vecino_mudanza_14` (`Video vecino mudanza 14.mp4`), `StreamWorker`, `AsyncInferenceWorker`, `InteractiveCanvas`, `ScrubberOverlay`

---

## 1. Problem Statement & Observed Symptoms

When viewing a video file registered as a camera stream (specifically `vid_Video_vecino_mudanza_14`, pointing to `Video vecino mudanza 14.mp4`):
1. **Live Monitor Tab:** The visual bounding boxes (analytic detections/tracks) appear unsynchronized from the moving objects in the video, visibly lagging behind or shifting ahead of the visual action.
2. **Video Studio Tab:** When opening and playing or scrubbing the exact same video file, the detection boxes are in **100% frame-perfect synchronization**.
3. **Core Questions Investigated:**
   - Why are the boxes unsynchronized in Live Monitor but in sync in Video Studio?
   - Are the detection boxes shared between Live Monitor and Video Studio?
   - Are the detection boxes cached/saved in a persistent store, or are they recalculated all the time?

---

## 2. Executive Architectural Finding

| Architectural Question | Finding | Details |
| :--- | :--- | :--- |
| **Are detections shared between tabs?** | **NO** | Live Monitor and Video Studio operate on completely separated subsystems with distinct data lifecycles. |
| **Are detections cached or recalculated?** | **Dual Model** | **Video Studio:** 100% cached from SQLite (`tracker.db`).<br>**Live Monitor:** 100% recalculated live on every frame using active YOLOv8 + Centroid tracker. |
| **Video Player Backend** | **Different** | **Live Monitor:** Browser `<img>` tag receiving an HTTP multipart MJPEG stream (`/stream/{id}`).<br>**Video Studio:** Native HTML5 `<video>` tag playing H.264/MP4 (`/api/videos/{name}`). |
| **Overlay Synchronization Clock** | **Different** | **Live Monitor:** Asynchronous WebSocket JSON packets drawn over an uncontrollable browser image decode buffer.<br>**Video Studio:** High-precision `requestAnimationFrame` polling `videoPlayer.currentTime` matched via binary search to pre-indexed frame timestamps. |

---

## 3. Deep-Dive Root Cause Analysis

### Root Cause 1: Asymmetric & Decoupled Transport Channels in Live Monitor
In the Live Monitor tab:
1. **Video Transport (HTTP MJPEG Stream):**
   - The browser renders video using an standard `<img>` tag (`#live-stream-img`).
   - The image source points to `/stream/{camera_id}?annotated=false`.
   - Browsers (Chromium, WebKit) implement internal network buffers, HTTP socket buffers, and asynchronous image decoding pipelines for `multipart/x-mixed-replace` streams.
   - This introduces an uncontrollable, variable display latency of **100ms to 500ms+** between when the backend encodes a frame and when the browser displays it.
2. **Telemetry Transport (WebSocket JSON):**
   - Bounding boxes, track IDs, and RSAC statuses are pushed over a WebSocket connection (`/ws/{camera_id}`).
   - WebSockets have virtually zero transport buffering (<5ms latency on localhost/LAN).
3. **The Synchronization Gap:**
   - An HTML `<img>` tag exposes **no playback clock**, **no frame index**, and **no presentation timestamp** to JavaScript.
   - When a WebSocket message arrives with `active_tracks`, `dashboard/static/app.js` immediately invokes `syncCanvas()` to draw those boxes on `<canvas id="interactive-canvas">`.
   - The canvas renders telemetry calculated for a recent frame on top of an older frame that is still buffered inside the browser's image decoder.

---

### Root Cause 2: Asynchronous Inference Delay (`AsyncInferenceWorker`)
In `dashboard/services/stream_worker.py` and `dashboard/services/async_inference_worker.py`:
1. Live camera pipelines must maintain a stable streaming frame rate (e.g. 20–30 FPS). Because YOLOv8 inference can take 60–150ms per frame on CPU or shared GPU, executing inference synchronously would drop the stream rate to 6–10 FPS.
2. To prevent this, `StreamWorker` passes frames to `AsyncInferenceWorker`, which processes frames asynchronously in a background thread.
3. In `build_live_step_result()`:
   ```python
   if run_vision:
       async_worker.submit(frame, now)
       cached = async_worker.get_latest_result()
       if cached is not None:
           return FrameStepResult(
               frame=frame,
               tracks=cached.tracks,  # Stale: completed from frame N - k
               ...
           )
   ```
4. While frame $N$ is being processed by YOLOv8, the video source continues reading frames $N+1, N+2, N+3$.
5. When `cached` results are retrieved, they represent detections from **several frames in the past**, but they are attached to the *current* frame before being broadcast over WebSocket. This guarantees that fast-moving objects will outrun their bounding boxes.

---

### Root Cause 3: Live Sensor Abstraction vs. Pre-Indexed Media Store
1. **Live Monitor Architecture (`CameraPool`):**
   - `CameraPool` treats all registered sources (RTSP, USB webcam, synthetic, or video file) as **live, real-time camera sensors**.
   - For `video_file` inputs, OpenCV's `VideoCapture` reads frames continuously in real time.
   - Live Monitor **completely ignores** any historical analysis or pre-indexed reports stored in the database. Every frame passes through the active vision pipeline (`FrameProcessor.step()`), executing live object detection, centroid tracking, zone logic, and event generation.
2. **Video Studio Architecture (`TrackerDB` + `ScrubberOverlayRenderer`):**
   - When an analysis or indexing job runs in Video Studio (e.g. run `run_a06e7a52` in `tracker.db`), detections for every single frame are saved in SQLite tables:
     - `video_runs`: Run metadata, resolution, FPS, total detections.
     - `video_detections`: Array of bounding boxes indexed by `frame_idx` and `timestamp_sec`.
   - When Video Studio plays the file:
     - The video is loaded in an HTML5 `<video>` element (`#scrubber-video-player`).
     - On every `requestAnimationFrame`, `dashboard/static/js/scrubber_overlay.js` queries `videoPlayer.currentTime`.
     - `ScrubberOverlayRenderer.findClosestDetections()` performs a binary search to find the exact detection record for that timestamp.
     - Detections and video frames are tied to the exact same temporal clock, resulting in 100% synchronization.

---

## 4. Architectural Comparison Matrix

| Capability / Behavior | Live Monitor (`tab-live`) | Video Studio (`tab-videos`) |
| :--- | :--- | :--- |
| **Primary Media Element** | `<img>` (`#live-stream-img`) | `<video>` (`#scrubber-video-player`) |
| **Media Delivery Protocol** | MJPEG over HTTP (`multipart/x-mixed-replace`) | MP4 / H.264 HTTP range requests |
| **Overlay Technology** | `<canvas id="interactive-canvas">` | `<canvas id="scrubber-overlay-canvas">` |
| **Overlay Data Source** | Real-time WebSocket (`/ws/{camera_id}`) | REST API (`/api/videos/{fn}/detections` or `/jobs/{id}/stream`) |
| **Detection Calculation** | **Live on-the-fly:** Recalculated every frame via YOLOv8 | **Cached:** Read from SQLite `video_detections` table |
| **Frame Rate & Seeking** | Fixed continuous forward flow; cannot seek | Full interactive seeking, scrub bar, variable playback speed |
| **Clock Synchronization** | Uncoupled (HTTP MJPEG buffer vs. WebSocket network) | Coupled (`videoPlayer.currentTime` binary search) |
| **Sync Accuracy** | ~100ms–500ms drift / visual lag | 0ms / frame-perfect |

---

## 5. Potential Solutions & Improvement Proposals

If the goal is to improve or align synchronization for video files in Live Monitor, consider three potential architectural paths:

### Option A: Server-Side Burned Annotation Toggle (`annotated=true`)
- **How It Works:**
  - The live stream endpoint supports `GET /stream/{camera_id}?annotated=true`.
  - In `StreamWorker._encode_annotated_frame()`, OpenCV draws bounding boxes and track labels directly onto the image pixels before JPEG encoding.
- **Advantages:**
  - **Zero transport desync:** The bounding box pixels and video pixels travel in the same JPEG frame; browser buffering cannot desynchronize them.
  - Minimal implementation effort (frontend toggle in Live Monitor HUD).
- **Trade-offs:**
  - Disables client-side canvas interactions (click-to-tag, hover tooltips) unless an invisible hit-test canvas is synchronized.
  - Still subject to `AsyncInferenceWorker` multi-frame latency unless synchronous inference is permitted for video files.

### Option B: Pre-Indexed Detection Replay Provider for File Cameras
- **How It Works:**
  - When `CameraPool` loads a camera with `cam_type == "video_file"`, check if a completed run exists in `TrackerDB` (`active_db.get_video_detection_stream(filename)`).
  - If a cached run exists, `StreamWorker` bypasses YOLOv8 inference entirely.
  - Instead, as `VideoSource` reads frame $N$ (or at time $T$), `StreamWorker` looks up the precomputed detection for frame $N$ from `TrackerDB` and broadcasts it.
- **Advantages:**
  - **Zero CPU/GPU AI load:** Eliminates redundant YOLOv8 inference for files that have already been indexed in Video Studio.
  - Detections match Video Studio exactly.
  - Aligns detection timing directly to the frame reading loop.
- **Trade-offs:**
  - Does not eliminate HTTP image buffering delay in the browser `<img>` tag unless combined with server-side annotation or frame timestamp tagging.

### Option C: Synchronized Media Protocol (WebSocket Binary Video + Metadata or WebCodecs)
- **How It Works:**
  - Replace the decoupled `<img>` MJPEG + WebSocket JSON architecture with a unified transport stream where each payload contains:
    `{ frame_seq, timestamp, image_bytes, detections }`.
  - The client decodes the frame and draws both the image and the boxes on the canvas simultaneously.
- **Advantages:**
  - Complete elimination of transport desynchronization across all camera types (webcams, RTSP, and video files).
  - Enables precise telemetry sync while retaining client-side vector overlays and interactive click-to-tag.
- **Trade-offs:**
  - Requires modest frontend rendering refactor (decoding JPEG blobs onto canvas in JavaScript).

---

## 6. Recommended Next Steps & Roadmap

1. **Phase 1 (Immediate UX Clarity / Workaround):**
   - Add a stream mode toggle on the Live Player HUD (`Burned Annotations` vs. `Interactive Canvas`) so users can switch to `annotated=true` when reviewing fast motion without lag.
2. **Phase 2 (File Camera Optimization):**
   - Implement **Option B** (Pre-Indexed Replay Provider): When a video file is added as a camera, automatically link it to existing `TrackerDB` occurrences/runs to save resources and maximize accuracy.
3. **Phase 3 (Unified Canvas Sync):**
   - Implement frame-sequence synchronization between the live stream and the telemetry layer.
