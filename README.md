# re-stream

Self-hosted video ingest + processing. Two independent parts:

```
re-stream/
├── mediamtx/   # the media server: ingests/re-streams cameras (MediaMTX in Docker)
│               #   docker-compose.yml, .env, add_cam.py (dev helper), cams.json (test fixtures)
└── cv/         # the CV processing service: detects/tracks vehicles off a stream (Python)
                #   pyproject.toml (uv), scripts/ (record_clip, spike_measure, annotate_detections)
```

The two are decoupled: **`mediamtx/` owns the streams**, **`cv/` consumes them**. The CV
service connects to a MediaMTX stream URL; it never reaches into the media server's config.

## Quickstart

1. **Media server** — see [`mediamtx/README.md`](mediamtx/README.md)
   ```bash
   cd mediamtx && cp .env.example .env && docker compose up -d
   python add_cam.py 3957              # pull a test cam -> http://127.0.0.1:8888/cam3957/
   ```
2. **CV service** — see [`cv/README.md`](cv/README.md)
   ```bash
   cd cv
   scripts/record_clip.sh cam3957 60                 # grab a clip off the stream
   uv run scripts/spike_measure.py clips/clip_*.mp4  # measure detection/tracking
   ```

## Status & plans
- [PLAN.md](PLAN.md) — media-server design (locked).
- [TODOS.md](TODOS.md) — deferred work captured during eng review.
- Full vision-module design doc lives in `~/.gstack/projects/re-stream/` (office-hours + eng-review output).

The plan: get the CV right on recorded clips first (`cv/`, file-based), then deploy the
processor as a GPU service consuming live streams from `mediamtx/`.
