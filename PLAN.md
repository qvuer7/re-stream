# Plan: `re-stream` — self-hosted RTMP→LL-HLS/WebRTC media server (drop Cloudflare)

Status: locked after /plan-eng-review (2026-06-19). Supersedes the original LiveKit design.
Source design: `~/.gstack/projects/re-stream/andrii-main-design-20260619-162406.md`

## Goal
Kill the Cloudflare bill. Own ingest + fan-out for the V-Penalty stream: hundreds of
passive browser viewers, every browser, with audio, cheap egress. Not a conferencing
product.

## Architecture (locked)
```
V-Penalty (existing Docker service — GStreamer RTMP sink: H.264 + AAC)
      │  rtmp://mediamtx:1935/<stream>          (output_url scheme = rtmp)
      ▼
  ┌──────────────────────────────┐
  │         MediaMTX             │   one off-the-shelf container, no Redis/Node
  │  RTMP in (H.264 + AAC)       │   (all other protocols enabled, not hardened)
  │  LL-HLS out  ────────────────┼──► every browser, with audio, CDN-cacheable   [PRIMARY ~1-2s]
  │  WHEP out    ────────────────┼──► opt-in sub-second, video-only              [OPTIONAL]
  └──────────────────────────────┘
```

Why this shape (the decisions, in order made):
| # | Decision | Rationale |
|---|----------|-----------|
| 1 | MediaMTX, not LiveKit | One container vs 5 services for a one-way broadcast (office-hours). |
| 2 | **RTMP ingest, H.264 + AAC** (not WHIP/Opus) | MediaMTX doesn't transcode; AAC ingest = Safari-correct HLS with audio in *every* browser, zero transcode. Drops `whipclientsink`/`gst-plugins-rs`/Rust build entirely. |
| 3 | **LL-HLS primary**, WHEP opt-in | Passive viewers don't need sub-second; HLS is CDN-cacheable = the actual egress-bill win (outside voice). WHEP kept as opt-in (video-only — WebRTC can't carry AAC). |
| 4 | Explicit docker port publishing | Portable, no host-net surprises; MediaMTX muxes WebRTC on one UDP port (8189), not a 50k range. |
| 5 | Publish-gated AND read-gated | Stops stream hijack + raw-URL hotlinking. **Caveat:** a `READ_KEY` reachable client-side is weak privacy (visible in page source) — it gates the raw stream URL, not per-viewer access. Drop-read-gating is a one-line toggle if it becomes friction (see TODO). |

**The publisher is already built.** `V-Penalty/src/services/gstreamer/gst_concat_filler_rtmps.py`
emits H.264 + AAC over `flvmux → rtmp2sink`; `output_sink.py` selects the RTMP sink from the
`rtmp://` URL scheme. Integration = point V-Penalty's `output_url` at MediaMTX. No publisher
code in this repo.

## Project structure (`~/Projects/re-stream/`)
```
re-stream/
├── README.md                 # run instructions + prod-hardening checklist (rewrite)
├── docker-compose.yml        # mediamtx service, explicit ports, shared net with V-Penalty
├── mediamtx.yml              # LL-HLS lowLatency, publish+read auth, WebRTC single ICE port,
│                             #   Prometheus metrics on; all protocols left enabled
├── .env.example              # PUBLISH_KEY, READ_KEY, stream path, advertised host IP
└── scripts/
    ├── verify.sh             # end-to-end smoke + auth-boundary harness (the test suite)
    └── loadtest.sh           # N concurrent HLS+WHEP readers → per-node ceiling (pre-prod gate)
```
No `web/` viewer in v1 — viewers use MediaMTX's bundled reader pages (custom auto-fallback
player is a P3 TODO). No `publish.sh` — V-Penalty is the publisher.

## MediaMTX config shape (`mediamtx.yml`)
Verify exact keys against the pinned MediaMTX version; shape:
```yaml
# LL-HLS tuned to ~1-2s
hls: yes
hlsVariant: lowLatency
hlsPartDuration: 200ms          # verify: trade latency vs segment overhead
hlsSegmentDuration: 1s
# WebRTC: single ICE mux port, advertise the real host IP in prod
webrtc: yes
webrtcLocalUDPAddress: ":8189"
webrtcAdditionalHosts: ["${ADVERTISE_IP}"]
# auth: publish-gated AND read-gated
authInternalUsers:
  - user: publisher
    pass: ${PUBLISH_KEY}
    permissions: [{action: publish}]
  - user: viewer
    pass: ${READ_KEY}
    permissions: [{action: read}]
metrics: yes                    # Prometheus on :9998 — egress/conn monitoring
```
Ports published by `docker-compose.yml`: `1935/tcp` (RTMP in), `8888/tcp` (HLS),
`8889/tcp` (WHEP), `8189/udp` + `8189/tcp` (WebRTC ICE), `9998/tcp` (metrics, internal).

## What already exists (reuse, don't rebuild)
- **V-Penalty RTMP sink** — H.264 + AAC over RTMP, sink chosen by URL scheme. The entire
  publisher. Reused as-is via config.
- **V-Penalty Docker stack** — already containerized; re-stream shares a docker network so
  `rtmp://mediamtx:1935` resolves.
- **MediaMTX** — off-the-shelf, all protocols (RTMP/RTSP/SRT/WebRTC/HLS) built in. We enable,
  don't build.

## NOT in scope (v1)
- **Transcoding / ABR (multiple bitrates).** Single rendition, source-encoded. Deferred —
  add an ffmpeg `runOnReady` rendition only if viewer bandwidth spread demands it.
- **Custom viewer with auto WHEP→HLS fallback.** v1 uses MediaMTX bundled reader pages;
  auto-fallback is a P3 TODO. Reliability for bad-NAT viewers is manual (hand them HLS) until then.
- **TURN/coturn.** WHEP is opt-in; bad-NAT viewers use the HLS primary path instead. Add coturn
  only if WHEP becomes a required path.
- **Hardening non-RTMP ingest / non-HLS egress.** All protocols stay *enabled* (MediaMTX default)
  but only RTMP-in → HLS/WHEP-out is tested/documented. "Support all sources and sinks" is a free
  capability, not a v1 test matrix.
- **CI/CD + secrets management.** Local-first; `docker compose pull && up -d` is the update path.
- **Real privacy (per-viewer auth/token server).** Read-gating is hotlink protection only.

## Local end-to-end run
1. `cp .env.example .env`; set `PUBLISH_KEY`, `READ_KEY`, `ADVERTISE_IP` (host IP for dev).
2. `docker compose up -d` → MediaMTX (RTMP/HLS/WHEP/metrics up).
3. Point V-Penalty at it: set its `output_url` to `rtmp://<publisher>:${PUBLISH_KEY}@mediamtx:1935/<stream>`
   (or env-equivalent), on the shared docker network. Start a game/stream.
4. Open the MediaMTX HLS reader: `http://localhost:8888/<stream>/` (with read creds) → plays
   in any browser, with audio, ~1-2s. WHEP reader at `:8889` for the sub-second opt-in.
5. `scripts/verify.sh` → asserts the whole path + the auth boundaries. Cloudflare bypassed.

## Tests — `scripts/verify.sh` (full smoke harness, the test suite)
```
verify.sh
  1. docker compose up -d; poll MediaMTX API (:9997) until healthy
  2. publish a test pattern via RTMP WITH PUBLISH_KEY  → expect connected
  3. publish WITHOUT key                                → expect REJECTED (401)   [security]
  4. GET HLS  /<stream>/index.m3u8  WITH READ_KEY       → expect 200 + .m3u8 body
  5. GET HLS  WITHOUT key                               → expect REJECTED          [security]
  6. WHEP offer WITH READ_KEY                           → expect 2xx SDP
  7. WHEP offer WITHOUT key                             → expect REJECTED          [security]
  8. teardown
```
Source for steps 2-3: `ffmpeg -re -f lavfi -i testsrc -f lavfi -i sine -c:v libx264 -c:a aac
-f flv rtmp://...` (matches V-Penalty's H.264+AAC profile; no GStreamer build needed for the test).
Runs in CI later. Security steps (3, 5, 7) are non-negotiable — they prove the auth boundary.

## Performance / load validation — `scripts/loadtest.sh` (pre-prod gate, not v1-blocking)
- Spawn N concurrent HLS readers (primary load: cacheable GETs) + a smaller pool of WHEP
  readers, ramp until CPU/egress saturates, log the viewer count where segments start lagging.
- **Caveat (outside voice):** loopback load won't model real-internet jitter/loss. Treat the
  number as a *CPU/packetize ceiling only*; gate prod on a small real-network canary.
- LL-HLS load is mostly bandwidth + segment serving (cheap, cacheable) — far better fan-out than
  WebRTC, which is why HLS is primary.

## Failure modes (per codepath)
| Path | Realistic failure | Test? | Error handling | Visible? |
|------|-------------------|-------|----------------|----------|
| RTMP ingest | V-Penalty publishes without/with wrong key | verify.sh #3 | MediaMTX 401 | publisher log |
| HLS egress | reader without key | verify.sh #5 | 401 | reader sees error |
| WHEP egress | bad-NAT viewer can't connect (no TURN) | not tested | none | **black player — viewer must switch to HLS** (P3 auto-fallback) |
| Egress cap | sustained ~1Gbps exceeds host NIC/flat-rate cap | loadtest + math | none yet | **silent degradation** → needs metrics alarm (T2) |
| Single node | MediaMTX crashes | — | none (SPOF) | full outage |
**Critical gap:** egress-cap saturation is silent with no alarm → T2 (Prometheus + alert) before prod.

## Implementation Tasks
Synthesized from this review. Run with Claude Code or Codex; checkbox as you ship.

- [x] **T0 (P1)** — egress math (DONE 2026-06-19)
  - Per viewer ≈ **2.6 Mbps** (V-Penalty RTMP sink: 720p30 H.264 2500k + AAC 128k; GOP=1s, ideal for LL-HLS).
  - 10 viewers ≈ 26 Mbps, 100 ≈ 260 Mbps, ~330 ≈ 1 Gbps (single-NIC ceiling).
  - Dev host = own machine: CPU is never the limit (HLS = segment copy); **upload bandwidth is** — fine on LAN, watch residential upload (~10-40 Mbps) for remote viewers.
  - **Scaling lever:** LL-HLS segments are static HTTP → a caching reverse proxy / CDN in front of `:8888` serves each segment once per cache, origin load stays FLAT regardless of viewer count. Scale = add cache tier (deploy-topology change, not code). WHEP does NOT scale this way (linear per-viewer load) → stays opt-in. This is why HLS is primary.
- [x] **T1 (P1)** — MediaMTX stack (DONE 2026-06-19, verified live)
  - Files: docker-compose.yml, mediamtx.tmpl.yml (+ rendered mediamtx.yml, gitignored), .env.example, scripts/up.sh
  - Gotchas solved: MediaMTX v1.11.3 does NOT expand `${VAR}` → `scripts/up.sh` renders via envsubst from `.env`. Locking `authInternalUsers` also locks the API/metrics → added an `any` user with api/metrics/pprof (bounded by the 127.0.0.1 port binding). Image pinned `bluenviron/mediamtx:1.11.3`.
- [~] **T2 (P1)** — metrics endpoint live (`metrics: yes`, :9998 localhost). REMAINING: Prometheus scrape + egress/conn alarm before prod (silent-saturation gap).
- [x] **T3 (P1)** — `scripts/verify.sh` smoke + auth harness (DONE 2026-06-19, 5/5 pass)
  - Verifies: publish w/o key rejected (A), publish w/ key live (B), HLS read w/ key 200 (C), HLS w/o key 401 (D), WHEP w/o key 401 (E). Confirmed muxer serves "H264 + MPEG-4 Audio" LL-HLS.
  - Auth forms (verified): RTMP + WHEP use `?user=&pass=`; **HLS uses HTTP Basic auth**.
- [ ] **T4 (P1, human: ~30min / CC: ~5min)** — point V-Penalty at MediaMTX (config only)
  - Files: V-Penalty `.env` `output_url` → `rtmp://...@mediamtx:1935/<stream>`; shared docker network
  - Verify: a real game streams; HLS reader plays with audio in Firefox + one other browser
- [ ] **T5 (P2, human: ~half day / CC: ~30min)** — `scripts/loadtest.sh` (pre-prod gate)
  - Verify: ramps readers, logs per-node ceiling; documented as CPU-ceiling-only
- [ ] **T6 (P2, human: ~30min / CC: ~10min)** — rewrite `README.md` (run + prod-hardening: TLS via Caddy, advertise IP, firewall ports)
- [ ] **T7 (P3)** — custom viewer page with automatic WHEP→HLS fallback (restores hands-off reliability)
- [ ] **T8 (P3)** — toggle: drop read-gating if it becomes friction (outside voice called it theater)

## Parallelization
- Lane A: T0 (math, independent — do first/in parallel, gates the rest)
- Lane B: T1 → T2 → T3 → T5 (sequential, all touch the MediaMTX stack)
- Lane C: T4 (independent repo: V-Penalty config) — can run once T1 is up
- T6/T7/T8 after B lands.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open→resolved | 6 issues + outside voice; architecture inverted (RTMP/AAC ingest, LL-HLS primary) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CROSS-MODEL:** outside voice (Claude subagent) drove two reversals the user accepted — LL-HLS primary over WebRTC-primary, and the RTMP/AAC ingest that deleted the `gst-plugins-rs` build. Read-gating (called "theater") kept by user as hotlink protection, with caveat documented.
- **VERDICT:** ENG CLEARED — ready to implement. T0 (egress math) is a pre-build gate, not a blocker on writing the plan.

**UNRESOLVED DECISIONS:**
- T8 (drop read-gating) left as an optional toggle — user kept read-gating; revisit only if it adds friction.
