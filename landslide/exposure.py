"""Exposure analysis - OSM features within runout footprint per scenario.

For each rainfall scenario, count how many buildings sit inside the runout
zone and how many metres of road are exposed. These numbers are the bridge
between the physical model and a vulnerability / risk-management discussion.
"""
from __future__ import annotations

import json
import rasterio

from .config import Config, PROCESSED, banner, update_meta


def run(cfg: Config) -> dict:
    banner("STAGE  -  Exposure analysis (features in runout zones)")

    feats_path = PROCESSED / "features.json"
    meta_path = PROCESSED / "meta.json"
    if not feats_path.exists():
        print("  features.json missing - run the 'features' stage first.")
        return {}

    feats = json.loads(feats_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    W = meta["width"]; H = meta["height"]
    cx = meta["cell_x_m"]; cy = meta["cell_y_m"]
    ws = feats["world_scale"]

    def to_grid(wx, wz):
        col = wx / (cx * ws) + (W - 1) / 2
        row = wz / (cy * ws) + (H - 1) / 2
        return col, row

    scen_root = PROCESSED / "scenarios"
    if not scen_root.exists():
        print("  scenarios/ directory missing - run the 'scenarios' stage first.")
        return {}

    summary = {}
    for sc_dir in sorted(p for p in scen_root.iterdir() if p.is_dir()):
        zone_p = sc_dir / "runout_zone.tif"
        if not zone_p.exists():
            continue
        with rasterio.open(zone_p) as src:
            zone = src.read(1)
        sid = sc_dir.name

        # Buildings: centroid in zone.
        b_exp = 0
        for b in feats["buildings"]:
            fp = b["footprint"]
            mx = sum(p[0] for p in fp) / len(fp)
            mz = sum(p[1] for p in fp) / len(fp)
            col, row = to_grid(mx, mz)
            if 0 <= int(row) < H and 0 <= int(col) < W and zone[int(row), int(col)] > 0:
                b_exp += 1

        # Roads: segment-midpoint test, accumulated in metres.
        r_total = r_exp = 0.0
        for road in feats["roads"]:
            line = road["line"]
            for i in range(len(line) - 1):
                p1, p2 = line[i], line[i + 1]
                seg_world = ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2) ** 0.5
                seg_m = seg_world / ws
                r_total += seg_m
                mx = (p1[0] + p2[0]) / 2; mz = (p1[1] + p2[1]) / 2
                col, row = to_grid(mx, mz)
                if 0 <= int(row) < H and 0 <= int(col) < W and zone[int(row), int(col)] > 0:
                    r_exp += seg_m
        summary[sid] = {
            "buildings_total": len(feats["buildings"]),
            "buildings_in_runout": b_exp,
            "roads_total_m": round(r_total, 0),
            "roads_in_runout_m": round(r_exp, 0),
            "roads_in_runout_pct": round(100 * r_exp / r_total, 1) if r_total else 0.0,
        }

    print("  Scenario          Buildings in runout    Road exposed (m)")
    print("  " + "-" * 68)
    for sid, s in summary.items():
        print(f"  {sid:<14}  {s['buildings_in_runout']:>3d} / {s['buildings_total']:<3d}"
              f"  ({100*s['buildings_in_runout']/max(s['buildings_total'],1):5.1f} %)"
              f"   {s['roads_in_runout_m']:>7.0f} / {s['roads_total_m']:.0f} m"
              f"  ({s['roads_in_runout_pct']:.1f} %)")
    update_meta({"exposure": summary})
    return summary


if __name__ == "__main__":
    run(Config.load())
