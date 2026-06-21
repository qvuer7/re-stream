# mediamtx — the media server

One MediaMTX container that ingests/re-streams cameras. All config is in `.env`
(host ports + `MTX_*` native MediaMTX settings). The CV service connects to the
streams this serves; it does not depend on anything in here.

## Run
```bash
cp .env.example .env        # edit if needed
docker compose up -d        # run from THIS directory (.env is auto-loaded here)
```
Ports (defaults): `1935` RTMP in · `8888` HLS · `8889` WHEP · `8189/udp+tcp` WebRTC ·
`9997` control API (localhost only).

## Add a camera (dev/test helper)
`add_cam.py` registers a camera's RTSP source with MediaMTX via the control API,
pulling on demand. It looks the camera up in `cams.json` by id.

```bash
python add_cam.py 3957            # -> watch at http://127.0.0.1:8888/cam3957/
python add_cam.py 3957 3379       # several at once
```

## Files
- `docker-compose.yml` — the MediaMTX service (pinned image, explicit ports).
- `.env` / `.env.example` — host ports + `MTX_*` config (`.env` is gitignored).
- `add_cam.py` — **dev/test helper only.** Registers test cams from `cams.json`.
  The production "add camera" flow (cams.json-agnostic) is a separate concern; this
  script is just for feeding test streams in.
- `cams.json` — **test-fixture data**: the cameras we have on hand for testing. NOT a
  production catalog, NOT a source of truth. Nothing in production should read it.
- `vdot_hls_urls.txt` — scratch list of VDOT URLs.
