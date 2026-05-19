"""LiDAR DEM preparation utility (optional).

The pipeline runs end-to-end with the Copernicus GLO-30 global DEM, but the
thesis benefits from a higher-resolution LiDAR DEM (Phil-LiDAR / DREAM /
UP-TCAGP, typically 1 m or 5 m for Luzon).

How to use this module
----------------------
1. Obtain the LiDAR DEM for the AOI (GeoTIFF, any CRS, DSM or DTM).
2. Save it as:    data/raw/lidar_dem.tif
3. Run:           .venv/Scripts/python.exe -m landslide.lidar
   which will
     - re-project to EPSG:32651 if needed
     - inverse-distance fill no-data gaps
     - apply a light 3x3 smoothing to suppress LiDAR speckle
     - write              data/processed/dem_lidar.tif
4. Either overwrite data/processed/dem.tif with dem_lidar.tif and re-run
   the pipeline from the susceptibility stage, OR set the dem.tile_url field
   in config.yaml to a local file:// URL pointing at the LiDAR raster and
   re-run from terrain.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import array_bounds

from .config import Config, RAW, PROCESSED, banner

RAW_LIDAR = RAW / "lidar_dem.tif"
OUT_LIDAR = PROCESSED / "dem_lidar.tif"


def _fill_nans(arr: np.ndarray, max_iter: int = 30) -> np.ndarray:
    """Fill NaN cells with the mean of valid 4-neighbours, iteratively."""
    out = arr.copy()
    for _ in range(max_iter):
        mask = np.isnan(out)
        if not mask.any():
            return out
        shift_sum = np.zeros_like(out)
        shift_cnt = np.zeros_like(out)
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            s = np.roll(out, (dr, dc), axis=(0, 1))
            valid = ~np.isnan(s)
            shift_sum[valid] += s[valid]
            shift_cnt[valid] += 1
        fill = np.divide(shift_sum, shift_cnt,
                         out=np.full_like(out, np.nan),
                         where=shift_cnt > 0)
        update = mask & ~np.isnan(fill)
        if not update.any():
            return out
        out[update] = fill[update]
    return out


def run(cfg: Config | None = None) -> str:
    banner("UTIL  -  LiDAR DEM preparation")
    if cfg is None:
        cfg = Config.load()
    if not RAW_LIDAR.exists():
        raise FileNotFoundError(
            f"Place the LiDAR DEM at {RAW_LIDAR} before running this utility.")

    target_epsg = int(cfg["dem"]["target_epsg"])
    dst_crs = rasterio.crs.CRS.from_epsg(target_epsg)

    with rasterio.open(RAW_LIDAR) as src:
        arr = src.read(1, masked=True).astype("float32")
        src_crs = src.crs
        src_transform = src.transform
    arr = np.ma.filled(arr, np.nan)
    arr = _fill_nans(arr)
    print(f"  Input shape : {arr.shape[1]} x {arr.shape[0]} px  ({src_crs.to_string()})")

    if src_crs.to_epsg() != target_epsg:
        bounds = array_bounds(arr.shape[0], arr.shape[1], src_transform)
        dt, dw, dh = calculate_default_transform(
            src_crs, dst_crs, arr.shape[1], arr.shape[0], *bounds)
        out = np.empty((dh, dw), dtype="float32")
        reproject(arr, out, src_transform=src_transform, src_crs=src_crs,
                  dst_transform=dt, dst_crs=dst_crs,
                  resampling=Resampling.bilinear)
        arr = out
        out_transform = dt
        print(f"  Reprojected to EPSG:{target_epsg} : {arr.shape[1]} x {arr.shape[0]} px")
    else:
        out_transform = src_transform

    # Light 5-point mean smoothing to suppress LiDAR speckle.
    sm = arr.copy()
    sm[1:-1, 1:-1] = (
        arr[1:-1, 1:-1] + arr[:-2, 1:-1] + arr[2:, 1:-1] +
        arr[1:-1, :-2] + arr[1:-1, 2:]
    ) / 5.0

    with rasterio.open(
        OUT_LIDAR, "w", driver="GTiff",
        height=sm.shape[0], width=sm.shape[1], count=1,
        dtype="float32", crs=dst_crs, transform=out_transform,
        compress="deflate",
    ) as dst:
        dst.write(sm, 1)
    print(f"  Wrote  {OUT_LIDAR}")
    return str(OUT_LIDAR)


if __name__ == "__main__":
    run()
