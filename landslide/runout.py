"""Stage 4 - Landslide runout, sediment transport and deposition model.

A geometric / energy-line ("Fahrboeschung") runout model, the approach used by
tools such as Flow-R for regional debris-flow and landslide runout assessment.

Concept
-------
1. SOURCE      cells that are both unstable (FS below threshold) and steep
               enough are treated as potential failure initiation points.
2. TRANSPORT   from each source, material is routed downslope. It can reach a
               downhill cell only while that cell stays below the energy line
                   z_line = z_source - tan(travel_angle) * path_distance
               Flow is split between downslope neighbours (multiple-flow
               direction), giving a relative sediment-transport intensity.
3. DEPOSITION  where the energy line is reached (or the terrain flattens) the
               flow stops; the remaining material is recorded as deposition.

Outputs (data/processed/):
    runout_sources.tif    failure initiation cells (0/1)
    runout_intensity.tif  relative sediment-transport intensity
    runout_deposition.tif relative deposited material
    runout_zone.tif       full runout footprint (0/1)
"""
from __future__ import annotations

import math
import numpy as np
import rasterio

from .config import Config, PROCESSED, banner, update_meta
from .terrain import _save_tif


def run(cfg: Config) -> dict:
    banner("STAGE 4/5  -  Runout, sediment transport and deposition")
    r = cfg["runout"]
    travel_angle = math.radians(float(r["travel_angle_deg"]))
    fs_thr = float(r["source_fs_threshold"])
    slope_min = float(r["source_slope_min_deg"])
    tan_ta = math.tan(travel_angle)

    with rasterio.open(PROCESSED / "dem.tif") as src:
        dem = src.read(1).astype("float64")
        transform, crs = src.transform, src.crs
        cell_x, cell_y = abs(src.transform.a), abs(src.transform.e)
    with rasterio.open(PROCESSED / "slope.tif") as src:
        slope_deg = src.read(1)
    with rasterio.open(PROCESSED / "fs.tif") as src:
        fs = src.read(1)

    H, W = dem.shape
    # 8-connected neighbours with horizontal step lengths.
    diag = math.hypot(cell_x, cell_y)
    neigh = [(-1, 0, cell_y), (1, 0, cell_y), (0, -1, cell_x), (0, 1, cell_x),
             (-1, -1, diag), (-1, 1, diag), (1, -1, diag), (1, 1, diag)]

    # --- Source cells --------------------------------------------------------
    src_mask = (fs < fs_thr) & (slope_deg > slope_min)
    n_sources = int(np.count_nonzero(src_mask))
    print(f"  Source cells (FS<{fs_thr} & slope>{slope_min} deg): {n_sources}")

    intensity = np.zeros((H, W), dtype="float64")
    deposition = np.zeros((H, W), dtype="float64")
    reached = np.zeros((H, W), dtype=bool)
    ref_z = np.full((H, W), -np.inf)        # source elevation of best path
    path_d = np.full((H, W), np.inf)        # path distance of best path
    best_e = np.full((H, W), -np.inf)       # best remaining energy at the cell

    src_rows, src_cols = np.where(src_mask)
    for rr, cc in zip(src_rows, src_cols):
        reached[rr, cc] = True
        ref_z[rr, cc] = dem[rr, cc]
        path_d[rr, cc] = 0.0
        best_e[rr, cc] = 0.0
        intensity[rr, cc] += 1.0           # one unit of material per source

    # --- Propagate, processing cells from high to low elevation -------------
    order = np.argsort(dem, axis=None)[::-1]
    for idx in order:
        rc = divmod(int(idx), W)
        rr, cc = rc
        if not reached[rr, cc]:
            continue
        I = intensity[rr, cc]
        z = dem[rr, cc]
        src_ref = ref_z[rr, cc]
        dist0 = path_d[rr, cc]

        cands = []
        for dr, dc, step in neigh:
            nr, nc = rr + dr, cc + dc
            if nr < 0 or nr >= H or nc < 0 or nc >= W:
                continue
            zn = dem[nr, nc]
            if zn >= z:                      # only route downhill
                continue
            nd = dist0 + step
            energy = (src_ref - tan_ta * nd) - zn   # height above energy line
            if energy <= 0.0:                # runout reach exhausted
                continue
            cands.append((nr, nc, zn, nd, energy, z - zn))

        if not cands or I <= 0.0:
            deposition[rr, cc] += I          # flow terminates -> deposition
            continue

        total_drop = sum(c[5] for c in cands)
        for nr, nc, zn, nd, energy, drop in cands:
            frac = drop / total_drop         # multiple-flow-direction split
            intensity[nr, nc] += I * frac
            reached[nr, nc] = True
            if energy > best_e[nr, nc]:      # keep the best-reaching path
                best_e[nr, nc] = energy
                ref_z[nr, nc] = src_ref
                path_d[nr, nc] = nd

    zone = (intensity > 1e-6).astype("uint8")
    runout_cells = int(zone.sum())
    max_runout = float(np.nanmax(np.where(reached & (~src_mask), path_d, 0.0)))

    _save_tif(PROCESSED / "runout_sources.tif", src_mask.astype("uint8"),
              transform, crs, dtype="uint8")
    _save_tif(PROCESSED / "runout_intensity.tif", intensity.astype("float32"),
              transform, crs)
    _save_tif(PROCESSED / "runout_deposition.tif", deposition.astype("float32"),
              transform, crs)
    _save_tif(PROCESSED / "runout_zone.tif", zone, transform, crs, dtype="uint8")

    aoi_cells = H * W
    print(f"  Runout footprint : {runout_cells} cells "
          f"({100.0*runout_cells/aoi_cells:.1f} % of AOI)")
    print(f"  Max runout distance from a source: {max_runout:.0f} m")
    print(f"  Saved 4 runout rasters to {PROCESSED}")
    result = {
        "n_sources": n_sources,
        "runout_cells": runout_cells,
        "runout_percent": round(100.0 * runout_cells / aoi_cells, 1),
        "max_runout_m": round(max_runout, 0),
        "travel_angle_deg": float(r["travel_angle_deg"]),
    }
    update_meta({"runout": result})
    return result


if __name__ == "__main__":
    run(Config.load())
