# Real-Time Multiview & Always-On Analytics — Master Roadmap

> Parent of two child plans. Goal: unlimited camera count in the dashboard (e.g. 100 cameras) without browser socket starvation, plus a security-grade path for analyzing every camera feed in the background under a resource budget.

## Core Architectural Invariants (apply to every child plan)

1. **Viewing ≠ Analytics.** UI subscriptions (1x1, grid tiles, Hub viewers) may wake *capture* but never decide *AI inference*. Inference is decided only by `ProcessingModeService` mode + per-camera `armed` policy (and later by the Analytics Scheduler).
2. **Bounded browser sockets.** The SPA uses at most: 1 × `/ws/multiview` + 1 × MJPEG `/stream/{id}` (1x1) + transient `fetch()`/MP4 Range requests. Socket use never grows with camera count.
3. **Encode once, fan out many.** Every JPEG (full or thumbnail) is encoded once per camera per tick on the worker thread and shared by all viewers. No per-viewer encode.
4. **Latest-frame-wins everywhere.** No unbounded frame queues on server or client; slow consumers drop stale frames instead of stalling workers.
5. **Additive public contracts.** `GET /stream/{camera_id}`, `/ws/{camera_id}`, `GET /videos/{filename}` and `GET /api/cameras/{camera_id}/telemetry` (Enterprise Hub contract) remain backward compatible.

## Steps

### Milestone 1: Multiview WebSocket Streaming & Grid Scalability
- [x] **.TODO/multiview_ws_streaming_plan.md**: Grid stabilization + pagination, WebSocket security, `/ws/multiview` binary multiplexer with shared thumbnail cache, `armed` flag, client `FrameSurface`, automatic MJPEG fallback, diagnostics log bridge, Hub/HTTP2 docs.

### Milestone 2: Step 1.5 — Cross-Platform Pipeline Hardening & Live/Studio Sync
- [ ] **.TODO/step_1_5_cross_platform_pipeline_hardening.md**: Cross-platform video path normalization, fast-fail missing files & unavailable USB probes, `StreamWorker` loop fault isolation, open trace catalog fixes (`TRC-001/004/007`), and Live Monitor vs Video Studio overlay synchronization (`frame_seq` provenance, pre-indexed file replay, `#live-stream-img` tagger fix, and opt-in `annotated=true` toggle).

### Milestone 3: Step 2 — Resource-Aware Analytics Scheduler *(Deferred — design via /grill-me after Step 1.5)*
- [ ] **.TODO/resource_aware_analytics_scheduler.md**: P0/P1/P2 inference priorities, motion-gated cadence, CPU/GPU budget, load shedding, alarm-latency SLA.

## Decision Log (from `/grill-me`, 2026-11-16)

| # | Decision | Choice |
|---|---|---|
| Q1 | Multiview transport | Single `/ws/multiview` binary WebSocket (JPEG → canvas); HTTP/2/TLS optional deployment upgrade, no app dependency |
| Q2 | Grid model for N cameras | Pagination: 2x2=4, 3x3=9, new 4x4=16 per page; subscribe only current page |
| Q3 | Thumbnail frames | Shared, throttled, downscaled per-camera thumbnail cache, encoded only while subscribed |
| Q4 | FPS/size policy | Server-side adaptive per layout (2x2 15 FPS/640px, 3x3 10/480, 4x4 6/320), env-configurable, client may request lower only |
| Q5 | Grid vs processing modes | Grid tiles wake capture but never enable inference; off-page cameras re-hibernate after lease TTL; recording overrides |
| Q5b | Always-on security analytics | Separate child plan (Step 2); Step 1 adds `armed` flag (never hibernates) + "viewing never drives inference" invariant |
| Q6 | Security | `Origin` allowlist on all WebSockets (`ALLOWED_ORIGINS`), optional HMAC short-lived token, CORS tightened to allowlist, uvicorn proxy headers via `FORWARDED_ALLOW_IPS` |
| Q7 | WS failure fallback | After 3 failed upgrades → capped MJPEG grid (≤4 live sockets) + "Degraded transport" badge, background WS retry (exp. backoff ≤60s), auto-restore |
| Q8 | 1x1 + lifecycle | 1x1 stays MJPEG; protocol carries `profile: thumb|full` from v1 + generic `FrameSurface` for later migration; one lazy client per tab, `unsubscribe_all` outside grid, idle close 30s / `pagehide`, pause on `document.hidden` |
| Q9 | Diagnostics + HTTP/2 | Rate-limited `DiagnosticLogHandler` → `.diagnostics/traces/`; `source_status` control frames; HTTP/2 = docs-only reverse-proxy recipe |
