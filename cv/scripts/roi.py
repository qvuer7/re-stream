"""Shared ROI (region-of-interest) helpers.

An ROI is a polygon (contour) of [x, y] vertices in image pixels, stored with the
image size it was drawn at (to catch resolution mismatches). A detection counts as
"in ROI" if its ground-contact point — the bbox bottom-center, where the car meets
the road — is inside the polygon.

Polygon, not raster mask: trivial to define (clicks) and store (a few points),
resolution-independent, and the per-box check is a cheap cv2.pointPolygonTest.
Rasterize with cv2.fillPoly only if something downstream needs a pixel mask.

Lives in scripts/ for now so the spike/annotate tools can `import roi`; moves into
the package when the real CV module lands.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def load_roi(path: str | Path):
    """Return (polygon Nx2 int32, (width, height))."""
    data = json.loads(Path(path).read_text())
    poly = np.array(data["polygon"], dtype=np.int32)
    return poly, (data.get("width"), data.get("height"))


def save_roi(path: str | Path, polygon, width: int, height: int, source: str = "") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "source": str(source),
        "width": int(width),
        "height": int(height),
        "polygon": [[int(x), int(y)] for x, y in polygon],
    }, indent=2))


def ref_point(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    """Ground-contact reference point of a box: bottom-center (where car meets road)."""
    return ((x1 + x2) / 2.0, y2)


def in_roi(polygon, x: float, y: float) -> bool:
    """True if point (x, y) is inside (or on) the polygon."""
    return cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0


def draw_roi(frame, polygon, color=(0, 255, 255), alpha: float = 0.25):
    """Overlay the ROI: translucent fill + outline. Returns a new frame."""
    if polygon is None or len(polygon) < 3:
        return frame
    overlay = frame.copy()
    cv2.fillPoly(overlay, [polygon], color)
    out = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
    cv2.polylines(out, [polygon], isClosed=True, color=color, thickness=1)
    return out
