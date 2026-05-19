"""Hydrology - D8 flow direction and flow accumulation.

Identifies the drainage network of the AOI: where surface water (and, by
proxy, debris flow) concentrates. The drainage network is scenario-
independent because it is purely topographic. The thesis uses it both as a
geomorphic context map and as an explanation of *why* the runout channels
where it does.
"""
from __future__ import annotations

import math
import numpy as np
import rasterio

from .config import Config, PROCESSED, banner, update_meta
from .terrain import _save_tif


def run(cfg: Config) -> dict:
    banner("STAGE  -  Hydrology (D8 flow direction + accumulation)")

    with rasterio.open(PROCESSED / "dem.tif") as src:
        dem = src.read(1).astype("float64")
        transform, crs = src.transform, src.crs
        cell_x = abs(transform.a); cell_y = abs(transform.e)
    H, W = dem.shape
    diag = math.hypot(cell_x, cell_y)
    neigh = [(-1, 0, cell_y), (1, 0, cell_y), (0, -1, cell_x), (0, 1, cell_x),
             (-1, -1, diag), (-1, 1, diag), (1, -1, diag), (1, 1, diag)]

    fdir = np.full((H, W), -1, dtype="int8")
    for r in range(H):
        for c in range(W):
            z = dem[r, c]
            best, best_s = -1, 0.0
            for k, (dr, dc, d) in enumerate(neigh):
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W:
                    s = (z - dem[nr, nc]) / d
                    if s > best_s:
                        best_s = s
                        best = k
            fdir[r, c] = best

    acc = np.ones((H, W), dtype="float64")
    order = np.argsort(dem, axis=None)[::-1]
    for idx in order:
        r, c = divmod(int(idx), W)
        k = fdir[r, c]
        if k < 0:
            continue
        dr, dc, _ = neigh[k]
        acc[r + dr, c + dc] += acc[r, c]

    _save_tif(PROCESSED / "flow_accum.tif", acc.astype("float32"), transform, crs)
    _save_tif(PROCESSED / "flow_dir.tif", (fdir + 1).astype("uint8"),
              transform, crs, dtype="uint8")

    thresh = max(20, (H * W) // 1000)
    n_channel = int((acc > thresh).sum())
    result = {"max_accum": int(acc.max()),
              "channel_cells": n_channel,
              "channel_threshold_cells": int(thresh)}
    print(f"  Max upstream accumulation : {result['max_accum']} cells")
    print(f"  Drainage channels (acc > {thresh}) : {n_channel} cells "
          f"({100*n_channel/(H*W):.1f} % of AOI)")
    update_meta({"hydrology": result})
    return result


if __name__ == "__main__":
    run(Config.load())
