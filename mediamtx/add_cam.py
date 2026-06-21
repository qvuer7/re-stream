#!/usr/bin/env python3
"""
Add a camera to MediaMTX.

Looks up the camera's RTSP URL in cams.json by id, then tells MediaMTX to pull
it. MediaMTX does all the streaming — this just calls its API. Stdlib only, so
no pip install needed.

    python add_cam.py 3958
    python add_cam.py 3958 3379      # several at once

Watch afterwards at:  http://127.0.0.1:8888/cam<id>/
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MTX_API = "http://127.0.0.1:9997/v3"   # MediaMTX control API
# cams.json is test-fixture data (the cams we have on hand), not a prod catalog.
# Resolve it next to this script so add_cam works from any CWD.
CAMS_FILE = Path(__file__).with_name("cams.json")


def rtsp_for(cam_id: str):
    catalog = json.load(open(CAMS_FILE))
    for feature in catalog["features"]:
        p = feature["properties"]
        if str(p.get("id")) == cam_id:
            return p.get("rtsp_url"), p.get("description", "")
    return None, None


def add(cam_id: str) -> None:
    rtsp, desc = rtsp_for(cam_id)
    if not rtsp:
        print(f"  cam {cam_id}: not found (or no rtsp_url) in {CAMS_FILE}")
        return

    name = f"cam{cam_id}"
    payload = json.dumps({
        "source": rtsp,
        "sourceOnDemand": True,   # only pull from the camera while someone watches
        "rtspTransport": "tcp",   # VDOT cams need TCP
    }).encode()
    req = urllib.request.Request(
        f"{MTX_API}/config/paths/add/{name}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        print(f"  {name}: added  ({desc})")
        print(f"          watch: http://127.0.0.1:8888/{name}/")
    except urllib.error.HTTPError as e:
        print(f"  {name}: FAILED {e.code} {e.read().decode()}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python add_cam.py <cam_id> [<cam_id> ...]")
    for cid in sys.argv[1:]:
        add(cid)
