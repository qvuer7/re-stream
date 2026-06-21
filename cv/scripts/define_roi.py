#!/usr/bin/env python3
"""
Define an ROI polygon for a camera by clicking on a frame. Manual, no automation.

    uv run scripts/define_roi.py clips/clip_cam3957_*.mp4              # -> rois/clip_cam3957_*.json
    uv run scripts/define_roi.py clips/clip_cam3957.mp4 --out rois/cam3957.json --frame 30

Controls (in the window):
    left click    add a point
    u             undo last point
    c             clear all points
    s  or  Enter  save and quit
    q  or  Esc    quit without saving

Saves a polygon (contour) of [x, y] vertices + the image size. Detections are
filtered later with roi.in_roi() on each box's bottom-center point — see
spike_measure.py --roi and annotate_detections.py --roi.

Needs a display (run locally, not on a headless GPU box). The JSON it writes is
small and portable — copy it to wherever the processor runs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

import roi as roilib

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def grab_frame(source: str, frame_idx: int):
    p = Path(source)
    if p.suffix.lower() in IMAGE_SUFFIXES:
        img = cv2.imread(str(p))
        if img is None:
            sys.exit(f"could not read image: {p}")
        return img
    cap = cv2.VideoCapture(str(p))
    if frame_idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, img = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read frame {frame_idx} from {p}")
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description="Click an ROI polygon on a frame.")
    ap.add_argument("source", help="video or image to draw the ROI on")
    ap.add_argument("--out", default="", help="output json (default: rois/<stem>.json)")
    ap.add_argument("--frame", type=int, default=0, help="frame index to grab (video only)")
    ap.add_argument("--scale", type=float, default=3.0,
                    help="zoom the window — tiny cams (320x240) are hard to click precisely")
    args = ap.parse_args()

    frame = grab_frame(args.source, args.frame)
    h, w = frame.shape[:2]
    out = Path(args.out) if args.out else Path("rois") / f"{Path(args.source).stem}.json"

    pts: list[tuple[int, int]] = []  # vertices in ORIGINAL image coords
    win = "define ROI  |  click=add  u=undo  c=clear  s/Enter=save  q/Esc=quit"
    scale = args.scale

    def redraw() -> None:
        disp = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
        if pts:
            sp = (np.array(pts) * scale).astype(int)
            if len(sp) >= 3:
                ov = disp.copy()
                cv2.fillPoly(ov, [sp], (0, 255, 255))
                disp = cv2.addWeighted(ov, 0.25, disp, 0.75, 0)
            if len(sp) >= 2:
                cv2.polylines(disp, [sp], len(sp) >= 3, (0, 255, 255), 1)
            for p in sp:
                cv2.circle(disp, tuple(p), 4, (0, 0, 255), -1)
        cv2.imshow(win, disp)

    def on_mouse(event, x, y, flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            pts.append((int(round(x / scale)), int(round(y / scale))))
            redraw()

    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    redraw()

    while True:
        k = cv2.waitKey(20) & 0xFF
        if k in (ord("s"), 13):  # s or Enter
            if len(pts) < 3:
                print("need at least 3 points to make a polygon")
                continue
            roilib.save_roi(out, pts, w, h, source=args.source)
            print(f"saved ROI ({len(pts)} points, {w}x{h}) -> {out}")
            break
        if k == ord("u"):
            if pts:
                pts.pop()
                redraw()
        elif k == ord("c"):
            pts.clear()
            redraw()
        elif k in (ord("q"), 27):  # q or Esc
            print("quit without saving")
            break

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
