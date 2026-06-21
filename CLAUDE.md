# CLAUDE.md

Guidance for AI coding agents working in this repo. Read `docs/STATE.md` first to resume.

## What this is
Self-hosted video ingest + CV processing. Two decoupled parts:
- **`mediamtx/`** — MediaMTX in Docker: ingests/re-streams cameras. Owns the streams.
- **`cv/`** — Python (uv) vehicle-vision service: detects/tracks vehicles off a stream, picks one best
  crop per vehicle, embeds it for re-ID. Consumes streams; never reaches into the media server's config.

The build: **Phase A** = get the CV right on recorded clips (file-based, cheap). **Phase B** = deploy as
a per-stream GPU service on live RTSP. Same pipeline code, swapped frame source (`FrameSource` seam).

## Read these to get oriented
1. `docs/STATE.md` — current state, findings, exact next commands. **Start here.**
2. `docs/DESIGN.md` — the locked plan: all decisions, tasks T0–T5, primary risk, cloud notes.
3. `TODOS.md` — deferred work with context.
4. `cv/README.md`, `mediamtx/README.md` — per-subsystem usage.

## Current focus
T0 (measure-first spike) confirmed the **Primary Risk: ByteTrack fragments** (~5 cars → ~20 ids on a
320×240/15fps cam). Next: ROI gating (built) → BoT-SORT+ReID A/B (not built) → then build pipeline T1–T5.

## Conventions / decisions that bind the code (see DESIGN.md for rationale)
- **cams.json is TEST FIXTURE DATA, never a production catalog.** Production add-camera is cams.json-agnostic.
- **All vehicle classes = one `vehicle`** (subtype irrelevant; re-ID on the crop is identity).
- **Dedup = "one row per track segment"**, keyed by track_id, flushed N frames after the id disappears
  (+ flush on shutdown, + max-track-age). This is the ★★★ correctness work.
- **Best crop = max(area×conf) gated by per-camera ROI** (ROI excludes truncated edge cars).
- **Postgres + pgvector** for storage; crops on disk as files (path in DB).
- **Frame ingest = cv2.VideoCapture behind a `FrameSource` interface** (GStreamer later).
- **Per-camera config = core fields + optional extras** (ROI is optional). Decoupled stream vs processor
  subsystems; processor gets a data contract, never reaches into the stream store.
- Tests non-negotiable: full pytest unit coverage + 1 E2E. Default detection conf 0.50.

## Working norms
- Python in `cv/` is a `uv` project: `cd cv && uv run scripts/<x>.py`. Don't use system Python.
- Keep `mediamtx/` (infra) and `cv/` (service) separate. Don't make `cv/` depend on `mediamtx/` internals.
- Gitignored: `.venv/`, `*.pt` / `cv/models/`, `*.mp4` / `cv/clips/`, `spike_out/`, `.env`. Tracked: `cv/rois/`.
- Build order: finish T0 (ROI + tracker A/B) → T1 config → T2 mtx client → T3 store+add-camera API →
  T4 vision pipeline (the hard one) → T5 read API + map.

## Skill routing (gstack)
When a request matches a skill, invoke it: product/brainstorm → /office-hours · architecture → /plan-eng-review ·
bugs → /investigate · diff review → /code-review · ship → /ship.
