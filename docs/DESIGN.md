# Design: Vehicle Re-ID Processing Module over MediaMTX (v1: single-cam logger)

Status: APPROVED (office-hours + /plan-eng-review, 2026-06-21). Ported into the repo from
`~/.gstack/projects/re-stream/` so it travels with git. Paths updated to the `mediamtx/` + `cv/` layout.

## Problem Statement
re-stream already ensembles public video streams via MediaMTX as a relay. The next thing to build
is the first **processing module**: a vision service that connects to a re-streamed MediaMTX path
and turns raw video into structured data.

**v1:** a **single-camera vehicle logger**. For one MediaMTX path: detect every vehicle, track it so
each unique vehicle is recorded once, pick the best crop, extract an appearance embedding, and store
{embedding, crop file, cam id, timestamp, direction} in a database. Output is a queryable dataset +
a map/timeline view.

**Phase 2 (deferred, designed-for):** cross-camera re-identification — query a neighbor cam's recent
window for the most-similar vehicles to a given one ("this red car"), filtering a vehicle across a
5-6 cam network by appearance. The point is *filtering*, not provable identification — imperfect is
expected and useful.

## Phasing (the working order)
- **Phase A — get the CV right on recorded clips** (file-based, deterministic, cheap; no DB, no GPU
  service). Done when: feed it a clip → get clean one-crop-per-vehicle + embeddings you trust.
- **Phase B — deploy as a per-stream GPU service**: wrap the validated pipeline (live RTSP via the
  `FrameSource` seam), wire storage + APIs + map, run on the GPU box. Same pipeline code, different
  frame source.

## Constraints
- **Mode:** learning / for fun. Workable-first, but easily extendable. Imperfect re-ID is fine.
- **Compute:** cloud GPU, willing to rent (pay-by-hour). Model freedom; cost discipline matters.
- **Consumption:** process the **live** stream in production. Develop on recorded clips. The same
  pipeline takes either — that's the `FrameSource` seam.
- **Data reality:** traffic cams are low-res, low-fps, wide-angle, small/blurry cars. (cam3957 measured:
  H.264, **320×240, 15 fps**.) Re-ID accuracy will be rough — lean on this, don't fight it.
- **Ingest already exists:** MediaMTX (`mediamtx/`) pulls cams on demand. The vision module writes zero
  streaming code; it consumes a stream URL and writes events.
- **Split-compute reachability:** detection runs on a rented GPU; MediaMTX runs elsewhere. The GPU must
  reach the stream — simplest is to co-locate MediaMTX on the GPU box. Pull via **RTSP** for low latency
  (expose 8554 internally — see Cloud Notes). HLS is for dev clips / browsers.
- **Disk growth:** one crop file per vehicle = unbounded disk. Retention out of scope for v1; watch space.

## Primary Risk (v1) — tracking fragmentation
ByteTrack associates frame-to-frame via IoU + Kalman motion only (no appearance). On low-fps/low-res
traffic cams a vehicle jumps far between frames and the box flickers → weak association → ID switches →
one physical car becomes many track IDs → **duplicate crops/rows**. "Imperfect is fine" covers re-ID
*accuracy*, NOT dedup. **CONFIRMED in the spike: ~5 real cars produced ~20 track IDs on cam3957.**

Mitigations, cheapest first:
1. **ROI gating** — restrict to the road region you care about; removes tiny/edge flickery detections
   that spawn junk tracks. (Built — see `cv/scripts/roi.py`, `define_roi.py`, `--roi`.)
2. **Lower conf / higher fps** — steadier detections = steadier tracks.
3. **BoT-SORT with ReID** — appearance-aware tracking (keeps ByteTrack's IoU+Kalman, adds appearance
   re-association). The real fix, and it reuses the same embedding you need for phase-2 re-ID.
4. **Appearance track-merge** — merge fragments by embedding similarity in a time window (= the
   within-camera version of the phase-2 cross-camera query).

Reframe: the endgame is appearance-based *filtering*, so perfect tracking isn't required. Tracking only
has to be good enough to avoid embedding the same car 30×/sec; remaining fragments get merged by
embedding. Don't over-invest in ByteTrack params.

## Premises
1. Single-cam logger + dataset is v1; cross-cam re-ID is a clean phase 2. v1 stores embeddings from
   day one, so phase 2 is a query you add, not a pipeline you rebuild.
2. Imperfect is fine because you're filtering, not identifying.
3. Spatio-temporal gating beats a fancy model (phase 2): candidate set = neighbors ∩ travel-time
   window; appearance kNN only ranks that small set. → v1 does NOT need a world-class re-ID model.
4. MediaMTX stays the ingest layer; the vision module is a separate service (path in → events out).
5. Single-user, no multi-tenant/packaging/distribution concern.

## Chosen approach
**Pure A, simplest:** glue off-the-shelf parts (Ultralytics YOLO + tracker, pgvector, FastAPI+Leaflet),
embed inline, one DB. One hedge carried in: **crops on disk as files** (path in DB), so re-embedding
with a new model later is possible without a rebuild.

## Architecture Direction (intended end-state — NOT v1 scope, do not over-build)
- **Two decoupled subsystems:** (1) *add-camera-stream* owns a camera record/DB (source URL, MediaMTX
  fields, map coords), written by an add-camera API that takes source params directly. (2) *add-processor*
  has its own config passed to the CV processor as a **data contract** (processing params + the stream
  fields it needs), assembled from the stream record at registration time (no drift). The processor never
  reaches into the stream subsystem directly.
- **Per-camera config:** core required fields + OPTIONAL extras (ROI, fps, model, direction params). The
  config model must allow optional/extensible fields.
- **One processing service per stream**, horizontally scalable. v1 = one stream in one process, params
  from config (not hardcoded), so scaling later is "run more workers," not "rewrite."

## Decided for v1
- **Frame ingest:** `cv2.VideoCapture` behind a swappable `FrameSource` interface (GStreamer later).
  Naive read loop accepted for v1; reconnect/staleness hardening deferred (TODOS.md).
- **Vector store:** Postgres + pgvector (one container). Justified by concurrent-writer end-state. hnsw
  index deferred to phase 2.
- **cams.json is TEST-FIXTURE DATA ONLY — never a production catalog.** Add-camera is cams.json-agnostic.
  `mediamtx/add_cam.py` is a dev/test helper, not the production path. Coords are a field on the camera
  record at add-time. Phase-2 topology derives from stored coords, not cams.json.
- **Class merge:** all vehicle classes (car/truck/bus/moto) treated as one `vehicle` — subtype irrelevant,
  re-ID on the crop is the real identity. (In scripts this is a cosmetic label override; dedup is by
  track_id, and the tracker is class-agnostic, so class flips never double-crop.)
- **Best crop:** `max(bbox_area × confidence)` over the track, **gated by per-camera ROI** (ROI excludes
  truncated edge cars, so the simple metric stops feeding blurry/cropped boxes to the embedder).
- **Direction:** raw per-camera start→end vector/angle in v1. World/compass calibration deferred.
- **Track-finalize / dedup rule:** keep per-track state in memory while the ID is live; flush exactly
  one row when an ID has been absent N frames. Also: flush live tracks on shutdown; cap max-track-age so
  parked cars eventually emit. Dedup reframed as **"one row per track segment"**, exactness sized by the
  spike (not a hard "one row per car" invariant).
- **GPU packing:** phase-1 = process-per-stream, model-per-process (own YOLO, shared GPU VRAM) for fault
  isolation. Phase-2 = Triton/litserve inference server (NOT a single shared in-process model — that
  reintroduces a single point of failure).
- **Tests:** full pytest unit coverage + 1 E2E on a recorded clip.
- **Default confidence:** 0.50 (tunable).

## Still open (decide at build start, not blocking)
- **Embedding model:** vehicle re-ID net (torchreid / VeRi-776) vs generic embedder (DINOv2/CLIP). The
  pgvector `vector(N)` column dim is fixed by this choice — pick before creating the table. Generic is
  simpler and "good enough" for v1 filtering; vehicle-specific is better for phase 2. NOTE: BoT-SORT+ReID
  (the tracking fix) needs an appearance model too — picking one model that serves tracking + storage +
  phase-2 is the efficient move.
- **The downstream question the data answers:** counts? specific-vehicle spotting? flow direction?
  Naming it tells you whether ID-switches / embedding quality actually matter.

## Success Criteria (v1)
- Runs on a stream/clip without crashing for a sustained session.
- Each vehicle crossing the ROI produces ~one DB row (embedding, crop file+path, cam id, ts, direction).
- Crops visibly are vehicles; direction correct on an obvious test case.
- Minimal map/timeline shows recent detections at the cam's stored coordinate.
- Crash behavior acceptable: losing in-flight track buffers is fine (MediaMTX recording is the replay net).

## Implementation Tasks
Paths are under `cv/` (the Python service). `T0` is done; the rest are the build.

- [x] **T0 (P1)** — spike — measure-first on a real clip. `cv/scripts/spike_measure.py`,
  `annotate_detections.py`, `define_roi.py`, `roi.py`, `record_clip.sh`. **Finding: fragmentation
  confirmed (~5 cars → ~20 ids).** Next within T0: ROI + BoT-SORT+ReID A/B to drive the number down.
- [ ] **T1 (P1)** — config — pydantic `CamConfig` (optional ROI/extras) + loader. `cv/config/cam_config.py`.
  Verify: pytest valid / missing-required / bad-type / missing-file / ROI-absent default.
- [ ] **T2 (P1)** — mtx — extract idempotent `ensure_path` shared with `mediamtx/add_cam.py`.
  `cv/mtx/client.py`. Verify: path-absent→create, path-exists→noop, API 4xx.
- [ ] **T3 (P1)** — store — Postgres+pgvector schema + cams.json-agnostic add-camera API.
  `cv/store/db.py`, `cv/store/schema.sql`, `cv/api/cameras.py`, pgvector service in compose.
  Verify: add-camera writes record; insert_detection writes row+embedding; `(cam_id, ts)` index.
- [ ] **T4 (P1)** — vision — pipeline: detect→track→finalize(dedup)→crop→embed→direction.
  `cv/ingest/frame_source.py` (cv2 behind interface), `cv/vision/pipeline.py`. Verify: pytest synthetic
  track sequences (ID-absent→1 row, reappear, two-cars, shutdown-flush, max-track-age, ROI gating,
  stationary direction); E2E on a recorded clip. **Dedup is the ★★★ correctness work.**
- [ ] **T5 (P2)** — web — read API + Leaflet map at stored coords. `cv/api/app.py`, `cv/web/map.html`.

## NOT in scope (v1)
Cross-camera re-ID (phase 2) · hnsw index · GStreamer decode · cv2 reconnect hardening (TODOS) · GPU
inference server (phase 2, TODOS) · world/compass direction calibration · camera dashboard UI · multi-worker
GPU scheduling beyond process-per-model · distribution/packaging.

## Cloud Notes (when MediaMTX is hosted on cloud)
- **Co-locate** CV GPU workers in the same VPC/region as MediaMTX → stream pull is internal (fast, cheap).
  Pulling over public internet = metered egress + jitter; avoid for production (fine for dev clip grabs).
- **Pull via RTSP** (low latency) for CV ingest — **expose port 8554** internally (current compose does
  NOT expose it; only RTMP-in/HLS/WHEP/WebRTC/API). HLS (8888) works but is laggy for live CV.
- MediaMTX `sourceOnDemand` pulls each source once and fans out to all consumers — multiple workers +
  browsers share one upstream pull. Internal copies are cheap; GPU decode/inference is the real cost.
- Lock down once cloud-reachable: stream auth (`MTX_AUTHINTERNALUSERS_*` in `.env`), keep the 9997
  control API off the public internet.

## Verdict
ENG CLEARED — ready to implement. Start by finishing T0 (ROI + tracker A/B), then T1→T5.
Outside voice (Claude subagent) raised 13 findings; 3 drove plan changes (measure-first spike, dedup
reframe, ROI-gated cropping). cams.json-as-catalog assumption was killed mid-review.
