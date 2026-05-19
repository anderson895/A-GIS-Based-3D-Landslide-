"""Stage 2 - Terrain preparation and derivatives.

Clips the raw DEM to the AOI, reprojects it to a metric UTM grid (so slope is
measured correctly in metres), and derives slope, aspect and hillshade.

Outputs (data/processed/):
    dem.tif        elevation, metres, UTM 51N
    slope.tif      slope, degrees
    aspect.tif     aspect, degrees from north
    hillshade.tif  shaded relief, 0-255
    meta.json      grid metadata (size, cell size, CRS, AOI, site location)
"""
from __future__ import annotations

import json
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform as warp_transform

from .config import Config, PROCESSED, banner
from .download import raw_dem_path


def _save_tif(path, array, transform, crs, dtype="float32", nodata=None):
    array = array.astype(dtype)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=array.shape[0], width=array.shape[1],
        count=1, dtype=dtype, crs=crs, transform=transform,
        nodata=nodata, compress="deflate",
    ) as dst:
        dst.write(array, 1)


def _hillshade(slope_rad, aspect_rad, azimuth_deg, altitude_deg):
    az = np.radians(360.0 - azimuth_deg + 90.0)
    alt = np.radians(altitude_deg)
    hs = (np.sin(alt) * np.cos(slope_rad) +
          np.cos(alt) * np.sin(slope_rad) * np.cos(az - aspect_rad))
    return np.clip(hs, 0.0, 1.0) * 255.0


def run(cfg: Config) -> dict:
    banner("STAGE 2/5  -  Terrain preparation (clip / reproject / derivatives)")
    src_path = raw_dem_path(cfg)
    dst_epsg = int(cfg["dem"]["target_epsg"])
    bounds = cfg.aoi_bounds  # min_lon, min_lat, max_lon, max_lat
    dst_crs = rasterio.crs.CRS.from_epsg(dst_epsg)

    # --- Clip a *buffered* window from the COG ------------------------------
    # A lat/lon AOI box becomes a skewed quadrilateral once reprojected to UTM.
    # Reading ~1.5 km of extra margin guarantees the final AOI grid is fully
    # covered by real data, with no no-data corner artifacts.
    buf = 0.015
    bbuf = (bounds[0] - buf, bounds[1] - buf, bounds[2] + buf, bounds[3] + buf)
    with rasterio.open(src_path) as src:
        window = from_bounds(*bbuf, transform=src.transform)
        dem_wgs = src.read(1, window=window, masked=True).astype("float32")
        win_transform = src.window_transform(window)
        src_crs = src.crs
    print(f"  Clipped buffered window: "
          f"{dem_wgs.shape[1]} x {dem_wgs.shape[0]} px (WGS84)")

    # Fill any missing pixels so derivatives stay well-defined.
    dem_wgs = np.ma.filled(dem_wgs, np.nan)
    if np.isnan(dem_wgs).any():
        dem_wgs = np.where(np.isnan(dem_wgs), np.nanmin(dem_wgs), dem_wgs)

    # --- Reproject the buffered area to a metric UTM grid -------------------
    bt, bw, bh = calculate_default_transform(
        src_crs, dst_crs, dem_wgs.shape[1], dem_wgs.shape[0], *bbuf)
    dem_buf = np.empty((bh, bw), dtype="float32")
    reproject(
        source=dem_wgs, destination=dem_buf,
        src_transform=win_transform, src_crs=src_crs,
        dst_transform=bt, dst_crs=dst_crs,
        resampling=Resampling.bilinear,
    )

    # --- Crop to the exact AOI (its bounding box in UTM) --------------------
    cx, cy = warp_transform(
        "EPSG:4326", dst_crs,
        [bounds[0], bounds[0], bounds[2], bounds[2]],
        [bounds[1], bounds[3], bounds[1], bounds[3]])
    aoi_utm = (min(cx), min(cy), max(cx), max(cy))
    cw = from_bounds(*aoi_utm, transform=bt).round_offsets().round_lengths()
    r0, c0 = max(int(cw.row_off), 0), max(int(cw.col_off), 0)
    r1 = min(r0 + int(cw.height), bh)
    c1 = min(c0 + int(cw.width), bw)
    dem = dem_buf[r0:r1, c0:c1].copy()
    dst_transform = bt * rasterio.Affine.translation(c0, r0)
    dst_h, dst_w = dem.shape
    cell_x = abs(dst_transform.a)
    cell_y = abs(dst_transform.e)
    print(f"  Reprojected to EPSG:{dst_epsg}: {dst_w} x {dst_h} px, "
          f"cell {cell_x:.1f} x {cell_y:.1f} m")

    # --- Derivatives: slope, aspect, hillshade ------------------------------
    # np.gradient returns d/d(row) and d/d(col); rows increase southward.
    g_row, g_col = np.gradient(dem, cell_y, cell_x)
    dz_dx = g_col
    dz_dy = -g_row  # flip so +y points north
    slope_rad = np.arctan(np.hypot(dz_dx, dz_dy))
    slope_deg = np.degrees(slope_rad)
    aspect_rad = np.arctan2(dz_dy, -dz_dx)
    aspect_deg = (np.degrees(aspect_rad) + 360.0) % 360.0
    hs = _hillshade(slope_rad, aspect_rad,
                    cfg["viz"]["hillshade_azimuth"], cfg["viz"]["hillshade_altitude"])

    # --- Save rasters --------------------------------------------------------
    _save_tif(PROCESSED / "dem.tif", dem, dst_transform, dst_crs)
    _save_tif(PROCESSED / "slope.tif", slope_deg, dst_transform, dst_crs)
    _save_tif(PROCESSED / "aspect.tif", aspect_deg, dst_transform, dst_crs)
    _save_tif(PROCESSED / "hillshade.tif", hs, dst_transform, dst_crs,
              dtype="uint8")

    # --- Locate Brgy. Malico on the grid ------------------------------------
    sx, sy = warp_transform(
        "EPSG:4326", dst_crs,
        [cfg["site"]["center_lon"]], [cfg["site"]["center_lat"]])
    inv = ~dst_transform
    site_col, site_row = inv * (sx[0], sy[0])

    meta = {
        "width": int(dst_w),
        "height": int(dst_h),
        "cell_x_m": float(cell_x),
        "cell_y_m": float(cell_y),
        "epsg": dst_epsg,
        "transform": list(dst_transform)[:6],
        "aoi_wgs84": {"min_lon": bounds[0], "min_lat": bounds[1],
                      "max_lon": bounds[2], "max_lat": bounds[3]},
        "elev_min": float(np.nanmin(dem)),
        "elev_max": float(np.nanmax(dem)),
        "slope_mean_deg": float(np.nanmean(slope_deg)),
        "slope_max_deg": float(np.nanmax(slope_deg)),
        "site": {
            "label": cfg["site"]["label"],
            "lon": cfg["site"]["center_lon"], "lat": cfg["site"]["center_lat"],
            "row": float(site_row), "col": float(site_col),
        },
    }
    with open(PROCESSED / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print(f"  Elevation range: {meta['elev_min']:.0f} - {meta['elev_max']:.0f} m")
    print(f"  Mean slope: {meta['slope_mean_deg']:.1f} deg  "
          f"(max {meta['slope_max_deg']:.1f} deg)")
    print(f"  Saved 4 rasters + meta.json to {PROCESSED}")
    return meta


if __name__ == "__main__":
    run(Config.load())
