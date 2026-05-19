"""Download and prepare OSM features (buildings + roads) for the AOI.

Uses the Overpass API (free, no API key) to fetch:
  - all way["building"] inside the AOI
  - all way["highway"] inside the AOI

Outputs:
    data/raw/osm.json             raw Overpass response (cached)
    data/processed/features.geojson  open standard GIS file (for QGIS etc.)
    data/processed/features.json  viewer-ready (world-coord polygons + lines
                                  with per-vertex terrain-elevation samples)
"""
from __future__ import annotations

import json
import requests
import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform

from .config import Config, RAW, PROCESSED, banner, update_meta

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
LEVEL_M = 3.0


def _overpass_query(bounds):
    min_lon, min_lat, max_lon, max_lat = bounds
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    return (
        "[out:json][timeout:90];"
        f"(way[\"building\"]({bbox});"
        f" way[\"highway\"]({bbox}););"
        "out body geom;"
    )


def _building_height(tags) -> float:
    if "height" in tags:
        try:
            return float(str(tags["height"]).split()[0])
        except Exception:
            pass
    if "building:levels" in tags:
        try:
            return float(tags["building:levels"]) * LEVEL_M
        except Exception:
            pass
    return LEVEL_M


def run(cfg: Config) -> dict:
    banner("STAGE  -  OSM buildings & roads (Overpass API)")

    bounds = cfg.aoi_bounds
    raw_path = RAW / "osm.json"

    if not raw_path.exists():
        print("  Querying Overpass API...")
        try:
            r = requests.post(OVERPASS_URL,
                              data={"data": _overpass_query(bounds)},
                              timeout=180,
                              headers={"User-Agent": "landslide-thesis/1.0"})
            r.raise_for_status()
            raw_path.write_text(r.text, encoding="utf-8")
            print(f"  Saved Overpass response ({raw_path.stat().st_size/1024:.0f} KB)")
        except Exception as e:
            print(f"  !! Overpass request failed ({e}). "
                  "Skipping features stage - viewer will simply omit OSM data.")
            return {"buildings": 0, "roads": 0, "error": str(e)}
    else:
        print(f"  Using cached Overpass response: {raw_path.name}")

    with open(raw_path, "r", encoding="utf-8") as fh:
        osm = json.load(fh)

    # Match the world coordinate system used by the viewer
    with rasterio.open(PROCESSED / "dem.tif") as src:
        dem = src.read(1)
        transform = src.transform
        crs = src.crs
    H, W = dem.shape
    cell_x = abs(transform.a); cell_y = abs(transform.e)
    world_scale = 200.0 / max((W - 1) * cell_x, (H - 1) * cell_y)
    elev_min = float(np.nanmin(dem))
    inv = ~transform

    def to_world(coords):
        lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
        xs, ys = warp_transform("EPSG:4326", crs, lons, lats)
        out = []
        for x, y in zip(xs, ys):
            col, row = inv * (x, y)
            wx = (col - (W - 1) / 2) * cell_x * world_scale
            wz = (row - (H - 1) / 2) * cell_y * world_scale
            ci = max(0, min(W - 1, int(round(col))))
            ri = max(0, min(H - 1, int(round(row))))
            elev = float(dem[ri, ci])
            out.append([round(wx, 2), round(wz, 2), round(elev, 1)])
        return out

    buildings, roads = [], []
    for el in osm.get("elements", []):
        tags = el.get("tags", {}) or {}
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        coords = [(g["lon"], g["lat"]) for g in geom]
        wc = to_world(coords)
        if "building" in tags and len(wc) >= 4:
            ring = wc[:-1] if wc[0][:2] == wc[-1][:2] else wc
            base_elev = min(p[2] for p in ring)
            buildings.append({
                "footprint": [[p[0], p[1]] for p in ring],
                "base_elev_m": base_elev,
                "height_m": _building_height(tags),
                "tags": {k: tags[k] for k in ("building", "name") if k in tags},
            })
        elif "highway" in tags:
            roads.append({
                "line": wc,
                "highway": tags.get("highway", "road"),
                "name": tags.get("name"),
            })

    features = {
        "world_scale": world_scale,
        "elev_min_m": elev_min,
        "level_m": LEVEL_M,
        "buildings": buildings,
        "roads": roads,
    }
    (PROCESSED / "features.json").write_text(json.dumps(features), encoding="utf-8")

    # Open-standard GeoJSON for QGIS / external GIS.
    gj = {"type": "FeatureCollection", "features": []}
    for el in osm.get("elements", []):
        tags = el.get("tags", {}) or {}
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        ring = [[g["lon"], g["lat"]] for g in geom]
        if "building" in tags:
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            gj["features"].append({"type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": tags})
        elif "highway" in tags:
            gj["features"].append({"type": "Feature",
                "geometry": {"type": "LineString", "coordinates": ring},
                "properties": tags})
    (PROCESSED / "features.geojson").write_text(json.dumps(gj), encoding="utf-8")

    result = {"buildings": len(buildings), "roads": len(roads)}
    print(f"  Buildings: {len(buildings)}    Roads (highway ways): {len(roads)}")
    update_meta({"features": result})
    return result


if __name__ == "__main__":
    run(Config.load())
