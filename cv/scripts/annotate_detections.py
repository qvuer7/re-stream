#!/usr/bin/env python3
"""
Draw YOLO detections + confidences on a video so you can pick a threshold by eye.

Runs detection at a LOW confidence (default 0.10) so you see everything — weak
boxes included — then writes an annotated video and prints a confidence
histogram so you can choose the cutoff with numbers, not just vibes.

    uv run scripts/annotate_detections.py clip.mp4
    uv run scripts/annotate_detections.py clip.mp4 --conf 0.05 --out boxed.mp4
    uv run scripts/annotate_detections.py clip.mp4 --model yolov8s.pt   # bigger model, fewer misses

Each box is labelled "class conf" (e.g. "car 0.42"). After you decide a level,
re-run spike_measure.py with --conf <level>.

This is detection-only (no tracking) — pure "what does the model see and how sure
is it" at this resolution.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import cv2

import roi as roilib

# COCO vehicle class ids: car, motorcycle, bus, truck — drawn as one "vehicle"
# label so car<->truck flips don't look like two different detections.
VEHICLE_CLASSES = [2, 3, 5, 7]
VEHICLE_LABEL = "vehicle"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Annotate a video with YOLO detections + confidences.")
    p.add_argument("video", help="path to input video")
    p.add_argument("--out", default="", help="output path (default: annotated_<input>.mp4)")
    p.add_argument("--model", default="yolov8n.pt", help="ultralytics weights (auto-downloads)")
    p.add_argument("--conf", type=float, default=0.50, help="confidence threshold (lower it to explore weak boxes)")
    p.add_argument("--imgsz", type=int, default=640, help="inference image size (upscales the 320x240 frame)")
    p.add_argument("--classes", type=int, nargs="*", default=VEHICLE_CLASSES,
                   help="COCO class ids to keep (default: vehicles); pass nothing-equivalent via --all")
    p.add_argument("--all", action="store_true", help="detect ALL classes, not just vehicles")
    p.add_argument("--track", action=argparse.BooleanOptionalAction, default=True,
                   help="run ByteTrack and draw track IDs + per-ID colors (default on). "
                        "--no-track for pure per-frame detection.")
    p.add_argument("--roi", default="", help="ROI polygon json (define with define_roi.py) to overlay")
    p.add_argument("--line-width", type=int, default=1, help="box line width (1 is good for tiny frames)")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = whole clip)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"video not found: {video}")

    out_path = Path(args.out) if args.out else video.with_name(f"annotated_{video.stem}.mp4")

    # Source geometry/fps for the writer.
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    if not width or not height:
        sys.exit("could not read video dimensions")

    from ultralytics import YOLO

    model = YOLO(args.model)
    # Draw all vehicle classes under one "vehicle" label (even in --all mode,
    # other classes keep their own names).
    for cid in VEHICLE_CLASSES:
        if cid in model.names:
            model.names[cid] = VEHICLE_LABEL
    classes = None if args.all else args.classes

    roi_poly = None
    if args.roi:
        roi_poly, _ = roilib.load_roi(args.roi)

    writer = cv2.VideoWriter(
        str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        sys.exit(f"could not open VideoWriter for {out_path}")

    # Confidence histogram buckets (0.0-0.1, 0.1-0.2, ... 0.9-1.0).
    buckets = Counter()
    n_frames = 0
    n_dets = 0

    track_ids: set[int] = set()
    common = dict(source=str(video), classes=classes, conf=args.conf,
                  imgsz=args.imgsz, stream=True, verbose=False)
    if args.track:
        # persist=True keeps track state across frames; r.plot() then draws the id.
        results = model.track(tracker="bytetrack.yaml", persist=True, **common)
    else:
        results = model.predict(**common)

    for frame_idx, r in enumerate(results):
        if args.max_frames and frame_idx >= args.max_frames:
            break
        n_frames += 1

        if r.boxes is not None:
            for c in r.boxes.conf.tolist():
                n_dets += 1
                buckets[min(int(c * 10), 9)] += 1
            if r.boxes.id is not None:
                track_ids.update(r.boxes.id.int().tolist())

        # r.plot() draws boxes + labels; with tracking the label includes the id.
        # color_mode="instance" colors each track id distinctly, so a car that
        # fragments into several ids visibly changes color frame to frame.
        plot_kwargs = {"line_width": args.line_width}
        if args.track:
            plot_kwargs["color_mode"] = "instance"
        try:
            annotated = r.plot(**plot_kwargs)
        except TypeError:
            annotated = r.plot(line_width=args.line_width)  # older ultralytics: no color_mode
        # plot() may return at imgsz; force back to source size for the writer.
        if annotated.shape[1] != width or annotated.shape[0] != height:
            annotated = cv2.resize(annotated, (width, height))
        if roi_poly is not None:
            annotated = roilib.draw_roi(annotated, roi_poly)
        writer.write(annotated)

    writer.release()

    # ---- report + confidence histogram ----
    print("\n=== detection annotate ===")
    print(f"input        : {video.name}  ({width}x{height} @ {fps:.0f}fps)")
    print(f"model        : {args.model}  (conf>={args.conf}, classes={'all' if args.all else classes})")
    print(f"frames       : {n_frames}")
    print(f"detections   : {n_dets}")
    if args.track:
        print(f"distinct ids : {len(track_ids)}   <-- compare to cars you actually see "
              f"(>> = ByteTrack is fragmenting)")
    print(f"output       : {out_path}\n")

    print("confidence histogram (pick a threshold where junk drops off):")
    maxc = max(buckets.values()) if buckets else 0
    for b in range(9, -1, -1):
        lo, hi = b / 10, (b + 1) / 10
        n = buckets.get(b, 0)
        bar = "#" * int(40 * n / maxc) if maxc else ""
        print(f"  {lo:.1f}-{hi:.1f} | {n:5d} {bar}")
    # cumulative "kept if threshold = X" helps choose the cutoff
    print("\n  detections kept at threshold:")
    total = sum(buckets.values())
    for t in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        kept = sum(n for b, n in buckets.items() if (b / 10) >= t)
        share = f"{100*kept/total:.0f}%" if total else "n/a"
        print(f"    >= {t:.1f} : {kept:5d} ({share})")
    print(f"\nopen {out_path} and scrub it; pick the conf where real cars stay and "
          f"noise disappears, then use it for spike_measure.py --conf <level>.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
