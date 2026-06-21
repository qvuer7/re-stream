# TODOS — re-stream

Deferred work captured during /plan-eng-review (2026-06-21). Each has enough context to pick up cold.

## cv2.VideoCapture hardening (frame ingest reliability)
- **What:** Replace the naive `cv2.VideoCapture.read()` loop with a threaded grab-latest reader (drains the buffer so you process the newest frame, not a backlog) plus a reconnect watchdog.
- **Why:** On sustained runs cv2+RTSP buffers stale frames (latency grows), silently drops frames under load, and on a network blip returns `ret=False` forever with no exception — the worker stalls invisibly. This is the one v1 failure mode that is both silent and unhandled.
- **Pros:** Reliable long runs; bounded latency; auto-recovery from cam/network blips.
- **Cons:** More code than the naive loop; thread lifecycle to manage.
- **Context:** v1 deliberately uses naive cv2 behind the `FrameSource` interface (ingest/frame_source.py). Do this when sustained-run reliability matters, or fold it into the eventual GStreamer FrameSource swap. The interface already exists, so this is a single-implementation change.
- **Depends on:** FrameSource interface (T4). Pairs with / precedes the GStreamer swap.

## GPU inference server (phase-2 scaling)
- **What:** Move from process-per-stream-with-own-YOLO to a central batching inference server (Triton or litserve), keeping stream processes separate for fault isolation.
- **Why:** Phase-1 loads one YOLO per worker process (VRAM duplication) — fine for 1-2 cams, wasteful at many. A shared in-process model was rejected (single point of failure). An inference server gives GPU efficiency (model loaded once, dynamic batching) WITHOUT losing per-stream process isolation.
- **Pros:** No VRAM duplication at scale; keeps fault isolation; dynamic batching utilizes the GPU.
- **Cons:** Real infra to stand up; another service to operate.
- **Context:** Decided in eng review — phase 1 prioritizes isolation (process-per-model on shared VRAM), phase 2 adopts the server when cam count makes duplication hurt. Logical unit stays per-stream throughout.
- **Depends on:** Phase-1 vision worker (T4) shipped and running multiple cams.
