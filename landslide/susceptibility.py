"""Stage 3 - Landslide susceptibility (infinite-slope stability model).

Computes a Factor of Safety (FS) for every cell with the classic infinite-slope
equation - the standard physically-based model for shallow translational
landslides on long uniform slopes:

        c' + (gamma - m * gamma_w) * z * cos^2(b) * tan(phi')
   FS = -----------------------------------------------------
                  gamma * z * sin(b) * cos(b)

   b      = slope angle                c'      = effective cohesion
   z      = soil depth to failure      phi'    = effective friction angle
   gamma  = soil unit weight           gamma_w = water unit weight
   m      = groundwater ratio (water-table height / soil depth)

FS < 1  -> theoretically unstable.  FS is then binned into 5 hazard classes.

Outputs (data/processed/):
    fs.tif             Factor of Safety (clipped to 0-10)
    susceptibility.tif hazard class 1 (Very Low) .. 5 (Very High)
"""
from __future__ import annotations

import numpy as np
import rasterio

from .config import Config, PROCESSED, banner, update_meta
from .terrain import _save_tif

# FS thresholds -> hazard class.  Index 0..4 maps to class 1..5.
FS_BREAKS = [2.0, 1.5, 1.25, 1.0]          # >=2 VeryLow ... <1 VeryHigh
CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]


def classify_fs(fs: np.ndarray) -> np.ndarray:
    """Bin a Factor-of-Safety array into hazard classes 1..5."""
    cls = np.full(fs.shape, 5, dtype="uint8")          # default Very High
    cls[fs >= FS_BREAKS[3]] = 4                        # 1.00 - 1.25  High
    cls[fs >= FS_BREAKS[2]] = 3                        # 1.25 - 1.50  Moderate
    cls[fs >= FS_BREAKS[1]] = 2                        # 1.50 - 2.00  Low
    cls[fs >= FS_BREAKS[0]] = 1                        # >= 2.00      Very Low
    return cls


def run(cfg: Config) -> dict:
    banner("STAGE 3/5  -  Landslide susceptibility (Factor of Safety)")
    g = cfg["geotech"]
    c = float(g["cohesion_kpa"])
    phi = np.radians(float(g["friction_angle_deg"]))
    gamma = float(g["unit_weight_kn_m3"])
    gamma_w = float(g["water_unit_weight_kn_m3"])
    z = float(g["soil_depth_m"])
    m = float(g["groundwater_ratio"])

    with rasterio.open(PROCESSED / "slope.tif") as src:
        slope_deg = src.read(1)
        transform, crs = src.transform, src.crs

    beta = np.radians(np.clip(slope_deg, 0.05, 89.0))  # avoid 0/90 singularities
    sin_b, cos_b = np.sin(beta), np.cos(beta)

    numerator = c + (gamma - m * gamma_w) * z * cos_b**2 * np.tan(phi)
    denominator = gamma * z * sin_b * cos_b
    fs = np.clip(numerator / denominator, 0.0, 10.0).astype("float32")

    susceptibility = classify_fs(fs)

    _save_tif(PROCESSED / "fs.tif", fs, transform, crs)
    _save_tif(PROCESSED / "susceptibility.tif", susceptibility, transform, crs,
              dtype="uint8")

    # Per-class statistics
    total = susceptibility.size
    stats = {}
    print(f"  Geotech: c'={c} kPa, phi'={g['friction_angle_deg']} deg, "
          f"z={z} m, m={m}")
    for i, name in enumerate(CLASS_NAMES, start=1):
        n = int(np.count_nonzero(susceptibility == i))
        pct = 100.0 * n / total
        stats[name] = {"cells": n, "percent": round(pct, 1)}
        print(f"  Class {i} {name:<10}: {pct:5.1f} %  ({n} cells)")

    unstable = 100.0 * np.count_nonzero(fs < 1.0) / total
    print(f"  Theoretically unstable (FS < 1.0): {unstable:.1f} % of the AOI")
    result = {"class_stats": stats, "unstable_percent": round(unstable, 1)}
    update_meta({"susceptibility": result})
    return result


if __name__ == "__main__":
    run(Config.load())
