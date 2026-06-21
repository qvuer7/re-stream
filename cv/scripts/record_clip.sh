#!/usr/bin/env bash
# Record a short clip from a MediaMTX HLS stream — feed it to scripts/spike_measure.py.
#
#   scripts/record_clip.sh cam3957                 # 60s of cam3957 -> clip_cam3957_<ts>.mp4
#   scripts/record_clip.sh cam3957 30              # 30s
#   scripts/record_clip.sh cam3957 30 myclip.mp4   # custom output path
#   scripts/record_clip.sh http://host:8888/cam9/index.m3u8 30   # full URL also works
#
# Uses -c copy (no re-encode): keeps the source's real fps/resolution so the
# spike measures the actual stream characteristics, not ffmpeg's re-encode.
set -euo pipefail

ARG="${1:?usage: record_clip.sh <cam-name|hls-url> [seconds] [out.mp4]}"
DURATION="${2:-60}"
HOST="${MTX_HLS_HOST:-127.0.0.1:8888}"

# Build the HLS URL: pass a full http(s) URL through, otherwise treat as a cam name.
case "$ARG" in
  http://*|https://*) URL="$ARG"; NAME="$(basename "$(dirname "$URL")")" ;;
  *)                  NAME="$ARG"; URL="http://${HOST}/${NAME}/index.m3u8" ;;
esac

OUT="${3:-clip_${NAME}_$(date +%Y%m%d-%H%M%S).mp4}"

echo "recording ${DURATION}s from ${URL}"
echo "  -> ${OUT}"

# -t limits duration; -c copy avoids re-encode; +genpts repairs HLS timestamps
# so the muxed mp4 is seekable. ffmpeg stops itself at DURATION.
ffmpeg -hide_banner -loglevel warning -stats \
  -fflags +genpts \
  -i "$URL" \
  -t "$DURATION" \
  -c copy \
  -movflags +faststart \
  -y "$OUT"

echo
if [ -s "$OUT" ]; then
  SIZE=$(du -h "$OUT" | cut -f1)
  echo "done: ${OUT} (${SIZE})"
  echo "next: uv run scripts/spike_measure.py ${OUT}"
else
  echo "FAILED: ${OUT} is empty. Is the cam live? Check: curl -sI ${URL}" >&2
  echo "If -c copy choked on the stream, retry with re-encode:" >&2
  echo "  ffmpeg -i '${URL}' -t ${DURATION} -c:v libx264 -an -y '${OUT}'" >&2
  exit 1
fi
