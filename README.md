# re-stream

Self-hosted WHIP → WebRTC media server to replace Cloudflare for live streaming.

GStreamer (`whipclientsink`) pushes a file/RTSP source via WHIP into a self-hosted
**LiveKit** stack (ingress + SFU), which fans it out to browser viewers over WebRTC
at sub-second latency.

See [PLAN.md](./PLAN.md) for the full design and implementation plan.

## Status
Planning. Implementation not started.
