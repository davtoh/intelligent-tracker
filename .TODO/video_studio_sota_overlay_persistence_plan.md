# Video Studio SOTA Analytics, Overlay & Persistence Architecture Plan

## 1. Executive Summary & Problem Breakdown

This architectural upgrade resolves the 6 specific defects and UX limitations identified in the Video Studio workflow:

1. **Active Banner vs. Report Container Mutual Exclusion**:
   - While an analytics job is running for the loaded video, `#video-batch-report-container` is completely hidden (`display: none`). Only `#scrubber-active-job-banner` displays progress.
2. **Persistent, Video-Scoped Report History**:
   - Analytics reports are persisted to disk (`data/reports/{video_filename}_reports.json`) so they survive server restarts and browser reloads.
   - Reports are strictly scoped to the active video: switching videos immediately swaps the report view to that video's historical reports (or the clean empty state if never analyzed).
3. **Card Selection & `.active-video` Highlighting Hardening**:
   - In accordance with AX / Accessibility best practices, individual buttons remain the sole actionable interactive targets (`.btn-select-video`, `.btn-transcode-video`, `.btn-del-video`).
   - Hardens `.active-video` synchronization across card re-renders, uploads, transcodes, and tab transitions so the currently loaded video card is always accurately highlighted without DOM desynchronization.
4. **Stackable Historical Reports**:
   - When a video is analyzed multiple times with different parameters (e.g. YOLOv8 conf=0.40 vs conf=0.25 vs stride=5), each run is archived in that video's report stack.
   - The report view displays the latest run by default with a History Run Switcher dropdown allowing the user to inspect any previous run configuration and metrics.
5. **Accurate Object Detection Counts**:
   - In `intelligent_tracker/batch.py` and `dashboard/routers/video_jobs.py`, separates raw detected objects (`total_detections`) from enrolled gallery matches (`identifications_count`), eliminating the bug where `total_detections` falsely reported `0` when no gallery entities were matched.
6. **Real-Time Video Playback Canvas Overlay**:
   - Adds a synchronized `<canvas id="scrubber-overlay-canvas">` over `<video id="scrubber-video-player">`.
   - Stores time-indexed track and detection records (`data/reports/{video_filename}_{run_id}_detections.json`) using the platform's standard `Track.to_dict()` schema.
   - As the video plays or scrubs, bounding boxes, confidence tags, class labels, and track IDs are rendered in real time.

---

## 2. Architectural Design & Invariant Contracts

```mermaid
flowchart TD
    subgraph Ingestion["Batch Analytics Pipeline (Backend)"]
        Vid["Video File"] --> Det["Detector (YOLOv8 / Mock)"]
        Det -->|Raw Detections| Counter["Count Raw Objects (total_detections)"]
        Det --> Track["Centroid / Kalman Tracker"]
        Track --> Match["GalleryMatcher (Enrolled Sightings)"]
        
        Counter --> Agg["Report Aggregator"]
        Track -->|Per-frame Track.to_dict()| Stream["Time-Indexed Detections File\ndata/reports/{video}_{run_id}_detections.json"]
        Match --> Agg
        Agg --> Store["Stacked Report Store\ndata/reports/{video}_reports.json"]
    end

    subgraph Presentation["Video Studio UI (Frontend)"]
        Store --> API["GET /api/videos/{file}/reports"]
        Stream --> DetAPI["GET /api/videos/{file}/reports/{run_id}/detections"]
        
        API --> Dropdown["History Run Switcher\n(Run #2 [yolov8 conf=0.40] - Latest)"]
        Dropdown --> Card["#video-batch-report-container\n(Render KPI Cards)"]
        
        DetAPI --> Overlay["#scrubber-overlay-canvas\n(Over scrubber-video-player)"]
        Player["videoPlayer.currentTime (timeupdate / play)"] -->|Draw BBoxes & Labels| Overlay
    end
```

### Invariant Contracts
1. **Container Isolation Invariant**:
   - While `VideoJobClient.getActiveJob(filename)` is running an analytics job, `#video-batch-report-container` has `style.display = 'none'`.
   - When no job is running, `#video-batch-report-container` has `style.display = 'block'`.
2. **Platform Reusable Track Invariant**:
   - Per-frame detection objects adhere to the platform's canonical `Track.to_dict()` schema:
     `{ "track_id": int, "bbox": [x, y, w, h], "label": str, "confidence": float, "identity_label": Optional[str] }`.
3. **Card Selection Invariant**:
   - Clicking anywhere on `.video-file-card` (except explicit action buttons like 🗑️ or ⚡ Convert) selects and loads that video, immediately updating `.active-video`.

---

## 3. Quantitative Modularity & SRP Budgets

| Target File | Current Lines | Planned Net Lines | Hard Ceiling | Status |
| :--- | :--- | :--- | :--- | :--- |
| `intelligent_tracker/batch.py` | 397 lines | ~420 lines | 500 lines | Within ceiling |
| `dashboard/routers/video_jobs.py` | 254 lines | ~310 lines | 350 lines | Healthy |
| `dashboard/static/js/video_batch.js` | 380 lines | ~440 lines | 500 lines | Within ceiling |
| `dashboard/static/video_scrubber.js` | 391 lines | ~430 lines | 500 lines | Within ceiling |
| `dashboard/static/js/video_library.js` | 261 lines | ~275 lines | 350 lines | Healthy |
| `dashboard/static/index.html` | 1,677 lines | +6 lines | Freeze | Adding overlay canvas |
| `tests/test_video_jobs.py` | 382 lines | ~450 lines | 500 lines | Within ceiling |

---

## 4. Atomic Implementation Roadmap

### Phase 1: Backend Data Model, Persistence & Detection Serialization
- [x] **intelligent_tracker/batch.py**:
  - [x] Record `total_detections_count` across all frames (sum of `len(detections)`).
  - [x] Collect time-indexed frame track snapshots `[{ "time": float, "frame": int, "tracks": [...] }]` using `Track.to_dict()`.
  - [x] Save stacked report summaries to `data/reports/{video_filename}_reports.json` and frame detections to `data/reports/{video_filename}_{run_id}_detections.json`.
- [x] **dashboard/routers/video_jobs.py**:
  - [x] In `_runner`, return `total_detections` as `raw_detections_count` and `total_sightings` as `matched_identifications`.
  - [x] Add REST endpoints:
    - [x] `GET /api/videos/{filename}/reports`: Returns array of stacked report runs for that video.
    - [x] `GET /api/videos/{filename}/reports/{run_id}/detections`: Returns time-indexed detection stream for scrubber canvas overlay.

### Phase 2: Frontend Overlay Canvas & Video Playback Synchronization
- [x] **dashboard/static/index.html**:
  - [x] Wrap `#scrubber-video-player` inside `.scrubber-viewport` with a transparent `<canvas id="scrubber-overlay-canvas"></canvas>`.
- [x] **dashboard/static/css/scrubber.css**:
  - [x] Add responsive absolute positioning rules for `#scrubber-overlay-canvas` matching `#scrubber-video-player` (`position: absolute; inset: 0; pointer-events: none; width: 100%; height: 100%; object-fit: contain;`).
- [x] **dashboard/static/video_scrubber.js**:
  - [x] Implement canvas overlay renderer that resizes with the video and on `timeupdate` / `play` draws detected bounding boxes and labels for the current timestamp.
  - [x] Hardened `.video-file-card` click handling so clicking anywhere on the card loads the video and updates `.active-video`.

### Phase 3: Stackable Report History & Scoped Container Visibility
- [x] **dashboard/static/js/video_batch.js**:
  - [x] Implement History Run Switcher dropdown in the report card header.
  - [x] Hide `#video-batch-report-container` while a job is running for the active video.
  - [x] Strictly filter reports by `currentBatchFilename` and restore historical runs from `/api/videos/{filename}/reports`.
- [x] **dashboard/static/js/video_library.js**:
  - [x] Update `renderVideoFileCard` to support card-level selection and robust active state tagging.

### Phase 4: Automated Testing & Verification
- [x] **tests/test_video_jobs.py**:
  - [x] Unit test verifying `total_detections` > 0 even with zero enrolled gallery entities.
  - [x] Unit test verifying stacked report storage and retrieval via `GET /api/videos/{filename}/reports`.
  - [x] Unit test verifying detection stream endpoint `GET /api/videos/{filename}/reports/{run_id}/detections`.

---

## 5. Scenario Combinations Matrix

| Scenario ID | Test Condition | Expected Behavior | Verification Check |
| :--- | :--- | :--- | :--- |
| **SC-01** | Run analytics on video without enrolled gallery entities | Report card displays real `Detections > 0` and `Sightings: 0`. | `python -m unittest tests/test_video_jobs.py` |
| **SC-02** | Active job running on current video | `#video-batch-report-container` is hidden (`display: none`); only `#scrubber-active-job-banner` is visible. | `diagnose.py ui --live --selectors "#scrubber-active-job-banner,#video-batch-report-container"` |
| **SC-03** | Switch from Video A to Video B | Video B only shows Video B's reports (or empty state); Video A's report is never shown on Video B. | `diagnose.py ui --live --audit-layout` |
| **SC-04** | Reload page or restart server | Navigating to Video A restores Video A's reports from `data/reports/{video}_reports.json`. | `Invoke-RestMethod -Uri "http://localhost:8050/api/videos/{video}/reports"` |
| **SC-05** | Multiple runs with different configs on same video | Report displays dropdown switcher ("Run #2 [yolov8 conf=0.40] (Latest) ▼"); selecting Run #1 loads Run #1's report. | Manual & live CDP verification |
| **SC-06** | Video playback in Scrubber player | Bounding boxes and labels render on `#scrubber-overlay-canvas` in real time as video plays. | `diagnose.py ui --live --selectors "#scrubber-overlay-canvas"` |
