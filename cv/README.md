# cv — vehicle vision processing service

Detects and tracks vehicles off a MediaMTX stream, picks one best crop per unique
vehicle, and (later) embeds it for re-ID. Python project managed with `uv`.

Right now this is **phase A: get the CV right on recorded clips** (file-based,
deterministic, cheap to iterate — no DB, no GPU service yet). Phase B wraps the
validated pipeline as a deployable per-stream GPU service.

## Setup
```bash
uv sync            # creates cv/.venv, installs ultralytics + opencv (pulls torch — big, one-time)
```

## Workflow (the T0 measure-first spike)
```bash
# 1. record a clip off a live MediaMTX stream (needs mediamtx/ running + a cam added)
scripts/record_clip.sh cam3957 60          # -> clips/clip_cam3957_<ts>.mp4

# 2. eyeball detections + pick a confidence threshold
uv run scripts/annotate_detections.py clips/clip_cam3957_<ts>.mp4   # -> annotated_*.mp4 + conf histogram

# 3. measure tracking: distinct track ids vs cars you actually see (fragmentation),
#    and dump one best crop per vehicle to eyeball crop quality
uv run scripts/spike_measure.py clips/clip_cam3957_<ts>.mp4 --out spike_out
```
Read the spike output: distinct track ids ≫ real car count → fragmentation is real,
the dedup/track-merge work is warranted. Crops blurry/truncated → ROI gating earns its keep.

## Scripts
- `scripts/record_clip.sh` — ffmpeg-record a clip from a MediaMTX HLS stream (keeps the
  source's real fps/resolution; writes to `clips/`).
- `scripts/annotate_detections.py` — draw YOLO boxes + confidences on a video; prints a
  confidence histogram to pick a threshold. Detection-only (no tracking).
- `scripts/spike_measure.py` — YOLO + ByteTrack; one best crop (`area×conf`) per vehicle
  track; reports fragmentation. The dedup-sizing measurement.

All vehicle classes (car/truck/bus/moto) are treated as one `vehicle` — subtype is
irrelevant; re-ID on the crop is the real identity. Default conf 0.50.

## Layout
- `models/` — auto-downloaded YOLO weights (gitignored).
- `clips/` — recorded + annotated video (gitignored).
- `spike_out/` — dumped crops + summary.json (gitignored).
- `pyproject.toml` / `uv.lock` — deps. Heavier deps (pgvector, fastapi, re-id model) land
  with their tasks.
