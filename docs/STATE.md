# STATE — resume here

Snapshot for continuing on a new machine. Last updated 2026-06-21.

## Where we are
**Phase A (get the CV right on recorded clips).** Still in **T0: measure-first spike.** The spike is
built and run; it **confirmed the Primary Risk — tracking fragmentation** (≈5 real cars produced ≈20
ByteTrack IDs on cam3957). No production pipeline, DB, or service exists yet — that's T1+.

Full plan + all decisions: [DESIGN.md](DESIGN.md). Deferred work: [../TODOS.md](../TODOS.md).

## Repo layout
```
re-stream/
├── README.md  PLAN.md  TODOS.md  CLAUDE.md  .gitignore
├── docs/        DESIGN.md (the plan) · STATE.md (this file)
├── mediamtx/    docker-compose.yml · .env(.example) · add_cam.py (dev helper) · cams.json (TEST data) · README
└── cv/          pyproject.toml · uv.lock · scripts/ · models/(gitignored) · clips/(gitignored) · rois/ · README
```
`mediamtx/` owns the streams; `cv/` consumes them. They're decoupled.

## What's built (cv/scripts/)
- `record_clip.sh <cam|url> [secs] [out]` — ffmpeg-record a clip from a MediaMTX HLS stream (`-c copy`,
  keeps real fps/res). Writes to `cv/clips/`.
- `annotate_detections.py <video> [--roi r.json] [--no-track] [--model ...]` — draws YOLO boxes +
  confidences + **track IDs** (ByteTrack, per-ID colors via `color_mode="instance"`), prints a confidence
  histogram + distinct-id count. Use it to SEE fragmentation and pick a conf threshold.
- `spike_measure.py <video> [--roi r.json] [--model ...]` — YOLO+ByteTrack, **one best crop
  (area×conf) per track**, dumps crops to `spike_out/` + `summary.json`, reports distinct ids vs
  fragmentation proxies.
- `define_roi.py <video|img> [--out rois/<name>.json] [--scale N]` — click an ROI polygon on a frame
  (needs a display). Saves polygon JSON to `cv/rois/` (kept in git — real per-cam config).
- `roi.py` — shared: `load_roi / save_roi / ref_point (bbox bottom-center) / in_roi (pointPolygonTest) /
  draw_roi`. Imported by the others (`import roi` works because scripts/ is on sys.path under `uv run`).

All default to **conf 0.50** and treat all vehicle classes as one `vehicle`.

## Key findings so far
- **cam3957 = H.264, 320×240, 15 fps.** Low res is the harder problem (small cars, weak embeddings);
  15 fps is workable.
- **ByteTrack fragments badly here** — expected, it's appearance-blind (IoU+Kalman only). ~5 cars → ~20 ids.
- The fix path (in order): **ROI gating** (built) → lower conf / bigger model → **BoT-SORT + ReID**
  (appearance-aware; reuses the phase-2 embedding) → appearance track-merge.

## Immediate next actions
1. **On the new machine, set up** (see "Environment" below): clone, start MediaMTX, `cd cv && uv sync`.
2. **Define the ROI** for cam3957 and re-measure:
   ```bash
   cd cv
   uv run scripts/define_roi.py clips/<some-clip>.mp4 --scale 4 --out rois/cam3957.json
   uv run scripts/annotate_detections.py clips/<clip>.mp4 --roi rois/cam3957.json   # verify overlay
   uv run scripts/spike_measure.py clips/<clip>.mp4 --roi rois/cam3957.json          # distinct ids should drop
   ```
3. **BoT-SORT + ReID A/B** (NOT built yet — the agreed next step): add `cv/trackers/botsort_reid.yaml`
   (`with_reid: True`, `track_buffer: ~75`) and a `--tracker <path>` flag on `spike_measure.py` +
   `annotate_detections.py`, then run the same clip through ByteTrack vs BoT-SORT+ReID and compare
   distinct-id counts. Pick the embedding model here (it also serves storage + phase-2).
4. Once tracking is "good enough" on clips → start the real pipeline: **T1 → T2 → T3 → T4 → T5** (DESIGN.md).

## Environment (new machine)
- **System deps:** `ffmpeg`, `docker` + compose, `uv`, Python ≥3.10. (NVIDIA driver/CUDA if running YOLO
  on GPU; CPU works for short clips, slow.)
- **MediaMTX:** `cd mediamtx && cp .env.example .env && docker compose up -d`, then
  `python add_cam.py 3957` → stream at `http://127.0.0.1:8888/cam3957/`.
- **CV service:** `cd cv && uv sync` (creates `cv/.venv`, pulls torch+ultralytics — big, one-time).
  YOLO weights download to `cv/models/` is gitignored; pass `--model models/yolo26s.pt` to use a
  specific one. Clips/`spike_out/` are gitignored; `rois/` is tracked.
- **NOTE:** an orphaned `.venv/` may exist at the OLD repo root (uv built it before the restructure). On
  the new clone it won't exist — just `uv sync` inside `cv/`.

## Open decisions (carry forward)
- **Embedding model** — vehicle re-ID (torchreid/VeRi-776) vs generic (DINOv2/CLIP). Decide when wiring
  BoT-SORT+ReID, since one model can serve tracking + storage + phase-2. Fixes the pgvector column dim.
- **The downstream question** the data answers (counts / spotting / flow) — name it before phase 2.

## Pointers
- Plan & decisions: `docs/DESIGN.md`
- Deferred work w/ context: `TODOS.md` (cv2 hardening, GPU inference server)
- Media server: `mediamtx/README.md` · CV service: `cv/README.md`
- Old media-server plan: `PLAN.md`
