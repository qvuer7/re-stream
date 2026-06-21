#!/usr/bin/env python3
"""
T0 measure-first spike — size the dedup work BEFORE building it.

Runs stock YOLO + ByteTrack over a recorded clip and reports how badly tracks
fragment on real (blurry, low-fps) traffic footage. Eyeball the dumped crops to
see whether one real car got split into several track IDs, and whether the
best-crop heuristic actually picks clean crops.

    uv run scripts/spike_measure.py path/to/clip.mp4
    uv run scripts/spike_measure.py clip.mp4 --model yolov8s.pt --conf 0.3 --out spike_out

What you're looking for in the output:
  - distinct_track_ids vs the number of cars YOU actually see in the clip
        (many IDs per real car  => fragmentation is real => build the dedup
         machinery + maybe appearance track-merge in T4)
  - short_track_ratio  (tracks shorter than --min-frames)
        a high ratio is the fingerprint of fragmentation / flicker
  - source FPS  (low fps is the root cause; informs the --fps config in T1)
  - the crop dump  (open spike_out/  — are the "best" crops sharp & whole,
         or blurry/truncated at frame edges? this validates the ROI decision)

This is a throwaway measurement tool, not production code. No DB, no embedding
model, no config schema — those are T1+.

Pipeline
--------
    clip.mp4
       │
       ▼
    YOLO(model).track(tracker=bytetrack, persist=True, classes=vehicles)
       │  per frame: boxes {xyxy, conf, cls, id}
       ▼
    accumulate per track_id:  frame indices, best (area×conf) crop
       │
       ▼
    summary stats + per-track best crop dumped to --out  +  summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2

# COCO class ids for vehicles: car, motorcycle, bus, truck — all collapsed to
# one logical "vehicle" class (see merge_vehicle_classes) so a car<->truck label
# flip across frames never reads as two different objects.
VEHICLE_CLASSES = [2, 3, 5, 7]
VEHICLE_LABEL = "vehicle"


def merge_vehicle_classes(model) -> None:
    """Relabel every vehicle COCO class to a single 'vehicle' name in-place.

    ByteTrack associates by motion/IoU (not class), so one physical car already
    gets one track_id even if the per-frame class flips car<->truck. This unifies
    the LABEL too, so crops/counts/plots are per-vehicle, never per-taxonomy.
    """
    for cid in VEHICLE_CLASSES:
        if cid in model.names:
            model.names[cid] = VEHICLE_LABEL


@dataclass
class Track:
    track_id: int
    frames: list[int] = field(default_factory=list)
    best_score: float = -1.0          # max(area × confidence) seen so far
    best_crop = None                  # numpy BGR crop at the best frame
    best_frame: int = -1
    best_conf: float = 0.0
    cls_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def length(self) -> int:
        return len(self.frames)

    @property
    def gap_span(self) -> int:
        # frames between first and last sighting; > length means the track had holes
        return (self.frames[-1] - self.frames[0] + 1) if self.frames else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure YOLO+ByteTrack fragmentation on a clip.")
    p.add_argument("video", help="path to a recorded video clip")
    p.add_argument("--model", default="yolov8n.pt", help="ultralytics model weights (auto-downloads)")
    p.add_argument("--conf", type=float, default=0.50, help="detection confidence threshold")
    p.add_argument("--imgsz", type=int, default=640, help="inference image size")
    p.add_argument("--min-frames", type=int, default=5,
                   help="tracks shorter than this count as 'short' (fragmentation proxy)")
    p.add_argument("--classes", type=int, nargs="*", default=VEHICLE_CLASSES,
                   help="COCO class ids to keep (default: vehicles)")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = whole clip)")
    p.add_argument("--out", default="spike_out", help="directory for per-track best crops + summary")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"video not found: {video}")

    # Source FPS / frame count — low FPS is the root cause of fragmentation.
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    # Imported here so --help works without the heavy torch/ultralytics import.
    from ultralytics import YOLO

    model = YOLO(args.model)
    merge_vehicle_classes(model)  # car/truck/bus/moto -> single "vehicle" label
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tracks: dict[int, Track] = {}
    n_frames = 0
    n_boxes = 0

    # stream=True yields one Results per frame instead of buffering them all.
    results = model.track(
        source=str(video),
        tracker="bytetrack.yaml",
        persist=True,
        classes=args.classes,
        conf=args.conf,
        imgsz=args.imgsz,
        stream=True,
        verbose=False,
    )

    for frame_idx, r in enumerate(results):
        if args.max_frames and frame_idx >= args.max_frames:
            break
        n_frames += 1
        boxes = r.boxes
        if boxes is None or boxes.id is None:
            continue
        frame = r.orig_img  # numpy BGR
        ids = boxes.id.int().tolist()
        xyxy = boxes.xyxy.tolist()
        confs = boxes.conf.tolist()
        clss = boxes.cls.int().tolist()

        for tid, (x1, y1, x2, y2), conf, cls in zip(ids, xyxy, confs, clss):
            n_boxes += 1
            t = tracks.setdefault(tid, Track(track_id=tid))
            t.frames.append(frame_idx)
            t.cls_counts[cls] += 1
            area = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
            score = area * conf  # the v1 best-crop heuristic — we're eyeballing if it's any good
            if score > t.best_score:
                xi1, yi1 = max(0, int(x1)), max(0, int(y1))
                xi2, yi2 = int(x2), int(y2)
                crop = frame[yi1:yi2, xi1:xi2].copy()
                if crop.size:
                    t.best_score = score
                    t.best_crop = crop
                    t.best_frame = frame_idx
                    t.best_conf = conf

    # ---- crunch stats ----
    distinct = len(tracks)
    lengths = sorted(t.length for t in tracks.values())
    short = [t for t in tracks.values() if t.length < args.min_frames]
    fragmented = [t for t in tracks.values() if t.gap_span > t.length]  # had holes

    def pct(n: int) -> str:
        return f"{(100.0 * n / distinct):.0f}%" if distinct else "n/a"

    # ---- dump best crops for eyeballing ----
    dumped = 0
    for t in tracks.values():
        if t.best_crop is not None and t.best_crop.size:
            name = f"track_{t.track_id:04d}_len{t.length:03d}_f{t.best_frame:05d}.jpg"
            cv2.imwrite(str(out_dir / name), t.best_crop)
            dumped += 1

    summary = {
        "video": str(video),
        "model": args.model,
        "source_fps": round(src_fps, 2),
        "source_frames": src_frames,
        "frames_processed": n_frames,
        "total_boxes": n_boxes,
        "distinct_track_ids": distinct,
        "short_tracks": len(short),
        "short_track_ratio": round(len(short) / distinct, 3) if distinct else None,
        "tracks_with_holes": len(fragmented),
        "track_len_min": lengths[0] if lengths else 0,
        "track_len_median": lengths[len(lengths) // 2] if lengths else 0,
        "track_len_max": lengths[-1] if lengths else 0,
        "crops_dumped": dumped,
        "min_frames_threshold": args.min_frames,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # ---- report ----
    print("\n=== T0 fragmentation spike ===")
    print(f"video                : {video.name}")
    print(f"source fps / frames  : {src_fps:.2f} fps / {src_frames} frames "
          f"(low fps is the fragmentation driver)")
    print(f"frames processed     : {n_frames}")
    print(f"vehicle detections   : {n_boxes}")
    print(f"distinct track IDs   : {distinct}   <-- compare to cars YOU count in the clip")
    print(f"short tracks (<{args.min_frames}f)  : {len(short)} ({pct(len(short))})  "
          f"<-- high ratio = fragmentation/flicker")
    print(f"tracks with holes    : {len(fragmented)} ({pct(len(fragmented))})")
    print(f"track length min/med/max : "
          f"{summary['track_len_min']}/{summary['track_len_median']}/{summary['track_len_max']}")
    print(f"\ncrops dumped         : {dumped} -> {out_dir}/  "
          f"(open them: are 'best' crops sharp & whole, or blurry/truncated?)")
    print(f"summary written      : {out_dir / 'summary.json'}")
    print("\nread: if distinct IDs >> real car count, dedup machinery + appearance "
          "track-merge (T4) is warranted. If crops are mostly edge/blurry, the ROI "
          "gating decision (Decision #6) earns its keep.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
