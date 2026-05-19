"""Diagnostic sanity checks for the pipeline outputs.

Runs as the final stage and prints a list of OK / WARN / FAIL findings.
Catches the kinds of issues that usually break a thesis defence quietly:

  - no-data corner artefacts in the DEM
  - unrealistic max slope (> 70 deg on a 30 m DEM)
  - degenerate FS values (NaN, inf)
  - empty runout footprint or sources
  - missing layer textures
"""
from __future__ import annotations

import json
import numpy as np
import rasterio

from .config import Config, PROCESSED, OUTPUTS, banner, update_meta


def _read(name):
    with rasterio.open(PROCESSED / name) as src:
        return src.read(1)


def _check(name, condition, message_ok, message_fail, level="WARN"):
    status = "OK  " if condition else f"{level:<4}"
    msg = message_ok if condition else message_fail
    print(f"  [{status}] {name:<28} {msg}")
    return condition


def run(cfg: Config) -> dict:
    banner("STAGE  -  Diagnostics & sanity checks")

    findings = {}

    # DEM
    dem = _read("dem.tif").astype("float32")
    findings["dem_no_nan"] = _check(
        "DEM: no NaN cells",
        not np.isnan(dem).any(),
        "all cells valid",
        "NaN cells present in DEM",
        level="FAIL")
    findings["dem_no_zero_edge"] = _check(
        "DEM: no zero-elev rim",
        not (dem[0, :].min() == 0 or dem[-1, :].min() == 0
             or dem[:, 0].min() == 0 or dem[:, -1].min() == 0),
        "no zero-elevation rim",
        "rim contains 0 m cells (reprojection artefact?)")

    # Slope
    slope = _read("slope.tif")
    findings["slope_realistic"] = _check(
        "Slope: max < 70 deg",
        float(slope.max()) < 70,
        f"max {slope.max():.1f} deg",
        f"max {slope.max():.1f} deg looks artefactual on a 30 m DEM")
    findings["slope_mean_steep"] = _check(
        "Slope: mean > 10 deg",
        float(slope.mean()) > 10,
        f"mean {slope.mean():.1f} deg (mountainous, expected)",
        f"mean {slope.mean():.1f} deg seems too low for Malico")

    # FS
    fs = _read("fs.tif")
    findings["fs_finite"] = _check(
        "FS: finite and bounded",
        np.isfinite(fs).all() and float(fs.max()) <= 10.0,
        "all finite, capped at 10",
        "FS contains non-finite or unbounded values",
        level="FAIL")

    # Runout
    zone = _read("runout_zone.tif")
    findings["runout_present"] = _check(
        "Runout: footprint > 0",
        int(zone.sum()) > 0,
        f"{int(zone.sum())} cells reached",
        "no runout cells - sources or travel-angle off?",
        level="FAIL")

    sources = _read("runout_sources.tif")
    findings["sources_present"] = _check(
        "Sources: at least 10",
        int(sources.sum()) > 10,
        f"{int(sources.sum())} sources",
        "very few sources - check FS threshold + slope_min")

    # Viewer outputs
    required = ["terrain.bin", "terrain.json", "tex_hillshade.png",
                "tex_slope.png"]
    # Scenario textures (4 each for susceptibility + runout) if scenarios ran.
    for sid in ("dry", "normal", "wet", "extreme"):
        required.append(f"tex_susc_{sid}.png")
        required.append(f"tex_runout_{sid}.png")
    for fn in required:
        findings[f"viewer:{fn}"] = _check(
            f"Viewer asset {fn}",
            (OUTPUTS / fn).exists(),
            "present",
            "MISSING from data/outputs/",
            level="FAIL")

    n_fail = sum(1 for v in findings.values() if not v)
    print(f"\n  -> {len(findings)-n_fail}/{len(findings)} checks passed")
    update_meta({"diagnostics": {k: bool(v) for k, v in findings.items()}})
    return findings


if __name__ == "__main__":
    run(Config.load())
