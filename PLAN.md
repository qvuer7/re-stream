# Plan: `re-stream` — self-hosted WHIP→WebRTC media server (drop Cloudflare)

## Context

Today the stream path is **GStreamer (`whipsink`) → Cloudflare (WHIP ingest + SFU fan-out) → viewers**.
Cloudflare is doing two jobs: terminating the WHIP ingest and fanning the stream out to
many low-latency viewers. The goal is to **own both jobs ourselves** so Cloudflare can be
removed entirely.

Decisions locked in (from clarifying questions):
- **Stack:** LiveKit (self-hosted, open source) — purpose-built SFU, scales horizontally,
  native WHIP ingress. Confirmed as the production target.
- **Hosting:** decide later → build **local-first** (Docker on this Linux box), keep deploy
  abstracted so it ports to Hetzner/cloud/on-prem later.
- **Source:** GStreamer encoding from a **file / RTSP / other upstream input**.
- **Latency:** lowest possible → **WebRTC only**, no HLS tier.
- **Scale target:** hundreds of concurrent viewers of a single stream.

### Key reality that shapes the design
LiveKit ingests via **WHIP** but **does not serve WHEP** for playback (open feature
request, not implemented). Browser viewers therefore subscribe with the **`livekit-client`
JS SDK** over WebRTC — still sub-second, just not the literal WHEP protocol. Two
consequences baked into this plan:
1. A small **token server** is required to mint short-lived subscriber JWTs (API secret
   must stay server-side, never in the browser).
2. The viewer page uses `Room.connect()` + `TrackSubscribed`, not a `<video>` pointed at a
   WHEP URL.

Architecture:
```
GStreamer (whipclientsink)
      │  WHIP POST (bearer = ingress stream key)
      ▼
  livekit-ingress ──(Redis RPC)── livekit-server (SFU)  ──► hundreds of browser viewers
                                        ▲                      (livekit-client SDK, WebRTC)
                                        │ JWT
                                  token-server (mints subscriber tokens)
```

## Project structure (`~/Projects/re-stream/`)

```
re-stream/
├── README.md                 # run instructions, prod-hardening checklist
├── docker-compose.yml        # livekit-server + ingress + redis (host networking, Linux)
├── .env.example              # LIVEKIT_API_KEY / SECRET, room name, source URI
├── config/
│   ├── livekit.yaml          # server config: api keys, redis, rtc ports, ingress base url
│   └── ingress.yaml          # ingress config: ws_url, redis, whip_port
├── scripts/
│   ├── create-ingress.sh     # `lk ingress create` → prints WHIP URL + stream key
│   └── publish.sh            # gst-launch pipeline → whipclientsink at LiveKit WHIP URL
├── token-server/
│   ├── package.json          # livekit-server-sdk + express
│   └── server.js             # GET /token?room=&identity= → subscriber JWT
└── web/
    ├── index.html            # video element + "join" button
    └── viewer.js             # livekit-client: fetch token, Room.connect, render tracks
```

## Components

### 1. `docker-compose.yml` + `config/` — the media server
Three services, Linux **host networking** (required for LiveKit WebRTC port ranges):
- **redis** — mandatory RPC/state bus between server and ingress.
- **livekit-server** (`livekit/livekit-server`) — ports 7880 (API/WS), 7881 (WebRTC/TCP),
  UDP 50000–60000 (WebRTC media). Config `config/livekit.yaml`:
  - `api.api_key` / `api.api_secret` (generate a 32+ char secret)
  - `redis.address: localhost:6379`
  - `rtc.port_range_start/end: 50000–60000`, `rtc.use_external_ip: true`
  - `ingress.whip_base_url: http://<host>:8080/w` (localhost for dev)
- **livekit-ingress** (`livekit/ingress`) — WHIP on port 8080. Config `config/ingress.yaml`:
  `ws_url: ws://localhost:7880`, `redis.address: localhost:6379`, `api_key/secret` matching
  the server, `whip_port: 8080`. Disable transcoding for WHIP where possible (lower CPU).

For **local dev**: plain HTTP on `localhost` — browsers permit WebRTC on localhost without
TLS, so no Caddy/certs needed yet. TLS + Caddy + coturn are deferred to the prod-hardening
section.

### 2. `scripts/create-ingress.sh` — provision the WHIP endpoint
LiveKit has no static WHIP listener; each endpoint is created via API/CLI. Uses the `lk`
CLI (livekit-cli) with `LIVEKIT_URL/API_KEY/API_SECRET` env to `lk ingress create` an
`input_type: WHIP_INPUT` ingress bound to our room (e.g. `restream`). Prints the resulting
**WHIP URL + stream key** that `publish.sh` consumes. Re-runnable; the ingress is reusable
across reconnects.

### 3. `scripts/publish.sh` — the GStreamer side (replaces the Cloudflare URL)
Uses **`whipclientsink`** (the modern element in the local `~/Projects/gst-plugins-rs`,
replacing deprecated `whipsink`). `whipclientsink` is a `BaseWebRTCSink` — feed it **raw**
A/V and it negotiates/encodes internally. File/RTSP source via `uridecodebin`:
```bash
gst-launch-1.0 -e \
  uridecodebin uri="$SOURCE_URI" name=d \
  d. ! queue ! videoconvert ! video/x-raw ! queue ! ws.video_0 \
  d. ! queue ! audioconvert ! audioresample ! audio/x-raw ! queue ! ws.audio_0 \
  whipclientsink name=ws \
    signaller::whip-endpoint="$WHIP_URL" \
    signaller::auth-token="$STREAM_KEY"
```
(Exact pad names verified against the local plugin; the bearer token is the LiveKit ingress
stream key. Audio branch dropped automatically for video-only sources.)

### 4. `token-server/` — subscriber JWT minting
Minimal Express service using **`livekit-server-sdk`**: `GET /token?room=restream&identity=<rand>`
builds an `AccessToken` with grant `{ roomJoin: true, room, canSubscribe: true,
canPublish: false }` and returns `at.toJwt()`. Runs on e.g. :8081. This is the only
backend the browser talks to for auth.

### 5. `web/` — the browser viewer
`viewer.js` with **`livekit-client`**: fetch a token from the token-server, then
```js
const room = new Room({ adaptiveStream: true });
await room.connect('ws://localhost:7880', token);
room.on(RoomEvent.TrackSubscribed, (track) => {
  if (track.kind === 'video' || track.kind === 'audio')
    track.attach(document.getElementById('media')); // or attach() → element
});
```
`Room.startAudio()` wired to the join click to satisfy autoplay policies. Served as static
files (any static server / `python -m http.server`).

## Local end-to-end run (the prototype)
1. `cp .env.example .env`, set `API_KEY/SECRET` and `SOURCE_URI`.
2. `docker compose up -d` → redis + livekit-server + ingress.
3. `scripts/create-ingress.sh` → copy the printed WHIP URL + stream key into `.env`.
4. `cd token-server && npm i && node server.js` (:8081).
5. Serve `web/` and open it; click **Join** → empty room waiting.
6. `scripts/publish.sh` → GStreamer pushes the file/RTSP source via WHIP.
7. Video/audio appears in the browser with sub-second latency. **Cloudflare fully bypassed.**

## Verification
- **Plugin present:** `gst-inspect-1.0 whipclientsink` resolves (else build/install from the
  local `~/Projects/gst-plugins-rs`).
- **Ingress healthy:** ingress `/health` + `/availability` endpoints OK; `lk ingress list`
  shows the created WHIP ingress.
- **Publish connects:** `publish.sh` reaches PLAYING with no WHIP HTTP errors; LiveKit logs
  show a participant publishing in room `restream`.
- **Playback:** browser `TrackSubscribed` fires; frames render. Eyeball latency < ~1s.
- **Fan-out sanity:** open several browser tabs (each its own identity) — all receive the
  single publisher. (Real hundreds-scale load via `lk load-test` later.)

## Production hardening (deferred until hosting is chosen)
Not built now, but the layout leaves room for:
- **TLS** via Caddy (LetsEncrypt) — required once off-localhost; WS becomes `wss://`.
- **coturn / external TURN** + `rtc.use_external_ip` for viewers behind strict NATs.
- **Public IP + open UDP 50000–60000 / TCP 7881 / 3478** on the host.
- **Bandwidth:** hundreds × ~3 Mbps = ~1 Gbps egress — pick a host with real network
  capacity (Hetzner dedicated is the cost-effective pick; cloud egress is pricey at scale).
- **Scaling:** one node handles a single stream to thousands of subscribers; multi-node +
  shared Redis only needed for many concurrent rooms.

## Open considerations / non-goals
- **WHEP gap:** if a downstream *service* (not a browser) specifically needs to pull WHEP,
  LiveKit can't serve it — that would argue for MediaMTX instead. This plan assumes
  browser-SDK viewers, which matches the stated "rendering is a webpage."
- No HLS tier (explicitly out of scope for latency reasons).
- Production secrets management and CI/deploy are out of scope for this first cut.
