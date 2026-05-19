"""Satellite-imagery basemap (Esri World Imagery -> UTM raster).

Downloads ESRI World Imagery XYZ tiles covering the AOI at a chosen zoom,
stitches them into one Web-Mercator mosaic, and reprojects to the project
UTM grid so it aligns pixel-for-pixel with the DEM. Output:

    data/processed/satellite.png       RGB raster, same grid as dem.tif

Attribution (must be displayed in the viewer): Esri, Maxar, Earthstar
Geographics, and the GIS User Community.
"""
from __future__ import annotations

import math
import time
import numpy as np
import requests
from PIL import Image
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds as transform_from_bounds

from .config import Config, RAW, PROCESSED, banner, update_meta

TILE_URL = ("https://services.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
ATTRIBUTION = ("Imagery: Esri, Maxar, Earthstar Geographics, "
               "and the GIS User Community")
TILE_SIZE = 256
DEFAULT_ZOOM = 15      # ~4.8 m/pixel at lat 16N
WEB_MERC_R = 6378137.0


def lonlat_to_tile_float(lon: float, lat: float, z: int):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x: int, y: int, z: int):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return lon, math.degrees(lat_rad)


def merc(lon: float, lat: float):
    """Lon/lat -> Web Mercator metres."""
    x = math.radians(lon) * WEB_MERC_R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * WEB_MERC_R
    return x, y


def _fetch_tile(url, dest, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": "landslide-thesis/1.0"})
            r.raise_for_status()
            dest.write_bytes(r.content)
            return
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"Tile fetch failed after {retries} retries: {last}")


def run(cfg: Config) -> dict:
    banner("STAGE  -  Satellite imagery (Esri World Imagery)")
    bounds = cfg.aoi_bounds            # min_lon, min_lat, max_lon, max_lat
    z = DEFAULT_ZOOM
    cache = RAW / "esri_tiles"
    cache.mkdir(exist_ok=True)

    x0, y0 = lonlat_to_tile_float(bounds[0], bounds[3], z)   # NW
    x1, y1 = lonlat_to_tile_float(bounds[2], bounds[1], z)   # SE
    tx0, ty0 = int(math.floor(x0)), int(math.floor(y0))
    tx1, ty1 = int(math.floor(x1)), int(math.floor(y1))
    nx = tx1 - tx0 + 1; ny = ty1 - ty0 + 1
    print(f"  Zoom {z}: {nx} x {ny} = {nx*ny} tiles to fetch / cache")

    mosaic = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
    fetched = cached = 0
    for j, ty in enumerate(range(ty0, ty1 + 1)):
        for i, tx in enumerate(range(tx0, tx1 + 1)):
            f = cache / f"z{z}_x{tx}_y{ty}.jpg"
            if f.exists() and f.stat().st_size > 0:
                cached += 1
            else:
                _fetch_tile(TILE_URL.format(z=z, x=tx, y=ty), f)
                fetched += 1
            mosaic.paste(Image.open(f).convert("RGB"),
                         (i * TILE_SIZE, j * TILE_SIZE))
    print(f"  Tiles : {fetched} downloaded, {cached} from cache")

    # Web Mercator bounds of the full mosaic (NW corner of tile tx0,ty0
    # and SE corner of tile tx1,ty1 which equals NW of tx1+1, ty1+1).
    lon_nw, lat_nw = tile_to_lonlat(tx0, ty0, z)
    lon_se, lat_se = tile_to_lonlat(tx1 + 1, ty1 + 1, z)
    mw, mn = merc(lon_nw, lat_nw)
    me, ms = merc(lon_se, lat_se)
    src_w, src_h = mosaic.size
    src_transform = transform_from_bounds(mw, ms, me, mn, src_w, src_h)
    src_arr = np.array(mosaic).transpose(2, 0, 1)            # bands first

    # Reproject to UTM 51N matching the DEM grid exactly.
    with rasterio.open(PROCESSED / "dem.tif") as dem:
        dst_transform = dem.transform
        dst_w, dst_h = dem.width, dem.height
        dst_crs = dem.crs

    out = np.zeros((3, dst_h, dst_w), dtype="uint8")
    for b in range(3):
        reproject(
            src_arr[b], out[b],
            src_transform=src_transform, src_crs="EPSG:3857",
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
    sat = out.transpose(1, 2, 0)
    out_path = PROCESSED / "satellite.png"
    Image.fromarray(sat, "RGB").save(out_path)
    print(f"  Aligned satellite raster: {dst_w} x {dst_h} px -> {out_path.name}")

    update_meta({"imagery": {"zoom": z, "tiles": nx * ny,
                             "attribution": ATTRIBUTION}})
    return {"tiles": nx * ny, "zoom": z}


if __name__ == "__main__":
    run(Config.load())
