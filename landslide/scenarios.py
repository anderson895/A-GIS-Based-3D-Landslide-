"""Rainfall-driven scenario simulation.

Runs the susceptibility + runout stages for 4 hydrological scenarios so the
viewer can switch between them and the thesis can discuss "what changes when
it rains".

  Dry         m = 0.10   (groundwater far below the failure plane)
  Normal      m = 0.40   (typical post-rain conditions)
  Wet         m = 0.70   (sustained rainy season)
  Extreme     m = 1.00   (full saturation, e.g. typhoon event)

m = water-table height / soil-depth in the infinite-slope FS equation.
"""
from __future__ import annotations

import copy
import shutil
import numpy as np

from .config import Config, PROCESSED, banner, update_meta
from . import susceptibility, runout

SCENARIOS = [
    {"id": "dry",     "name": "Dry",     "m": 0.10},
    {"id": "normal",  "name": "Normal",  "m": 0.40},
    {"id": "wet",     "name": "Wet",     "m": 0.70},
    {"id": "extreme", "name": "Extreme", "m": 1.00},
]
SCEN_FILES = [
    "fs.tif", "susceptibility.tif",
    "runout_sources.tif", "runout_intensity.tif",
    "runout_deposition.tif", "runout_zone.tif",
]


def run(cfg: Config) -> dict:
    banner("STAGE  -  Rainfall scenarios (Dry / Normal / Wet / Extreme)")
    scen_root = PROCESSED / "scenarios"
    scen_root.mkdir(exist_ok=True)

    summary = {}
    work_cfg = copy.deepcopy(dict(cfg))
    for sc in SCENARIOS:
        print(f"\n  -- Scenario: {sc['name']}  (m = {sc['m']:.2f}) --")
        work_cfg["geotech"]["groundwater_ratio"] = sc["m"]
        wrapper = Config(work_cfg)
        susc_res = susceptibility.run(wrapper)
        ro_res = runout.run(wrapper)
        out_dir = scen_root / sc["id"]
        out_dir.mkdir(exist_ok=True)
        for fn in SCEN_FILES:
            src = PROCESSED / fn
            if src.exists():
                shutil.copy(src, out_dir / fn)
        summary[sc["id"]] = {
            "name": sc["name"], "m": sc["m"],
            "unstable_percent": susc_res["unstable_percent"],
            "class_stats": susc_res["class_stats"],
            "n_sources": ro_res["n_sources"],
            "runout_percent": ro_res["runout_percent"],
            "max_runout_m": ro_res["max_runout_m"],
        }

    # Restore the "normal" scenario as the canonical files in data/processed/
    normal = scen_root / "normal"
    for fn in SCEN_FILES:
        src = normal / fn
        if src.exists():
            shutil.copy(src, PROCESSED / fn)

    update_meta({"scenarios": summary})
    print("\n  Scenario summary")
    print("  " + "-" * 78)
    print(f"  {'Scenario':<10} {'m':>5} {'Unstable':>10} {'Sources':>10} "
          f"{'Runout%':>10} {'MaxRunout':>12}")
    for sc in SCENARIOS:
        s = summary[sc["id"]]
        print(f"  {s['name']:<10} {s['m']:5.2f} {s['unstable_percent']:9.1f}% "
              f"{s['n_sources']:>10d} {s['runout_percent']:9.1f}% "
              f"{s['max_runout_m']:>10.0f} m")
    return summary


if __name__ == "__main__":
    run(Config.load())
