# Resource-Aware Analytics Scheduler (Child Plan B — Design Pending)

> Parent: `.TODO/realtime_multiview_master_roadmap.md` (Step 2). **Status: not designed.** Run `/grill-me` + `/frontier-architect` after Step 1 (`multiview_ws_streaming_plan`) is complete.

## Problem Statement

A home/site security deployment must analyze **every armed camera** in near real time to raise alarms, regardless of what the operator is viewing. Today:
- `focus_only` analyzes only the focused camera; other cameras hibernate when unviewed → no alarms.
- `full_realtime` analyzes all pooled cameras at full rate with **no resource budget** (brute force; ~3 threads per camera; CPU/GPU starvation at scale).
- No motion gating, priority, or load shedding exists (`git grep` confirms no scheduler/arbiter/motion-gate classes).

## Candidate Scope (to be confirmed by interview)

- Priority tiers: **P0** focused/viewed + active alarm follow-up, **P1** armed cameras with zone/tripwire/RSAC rules, **P2** unarmed/background.
- Motion-gated cadence: cheap frame-diff / background subtraction decides when a P1 camera gets a YOLO slot; idle armed cameras sampled at a floor rate (e.g. 1 FPS).
- Global inference budget (shared detector pool / batching across cameras, GPU-aware) instead of one `AsyncInferenceWorker` per camera.
- Load shedding + backpressure telemetry; alarm-latency SLA (e.g. motion → alarm ≤ 2 s on P1).
- Guarantee that configuration (zones, tripwires, RSAC rules, whitelist) is always applied to scheduled frames — no "missed configuration" when a camera is time-sliced.
- Integration with `capture_only` deferred indexing for queued backlog when budget is exhausted.

## Hooks Delivered by Step 1

- `armed: bool` per camera in `configs/cameras.json` (prevents hibernation).
- Invariant tests: UI subscriptions never change `should_run_vision_step()` outputs.
