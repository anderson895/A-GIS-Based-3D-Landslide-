"""Download and prepare OSM features for the AOI.

Uses the Overpass API (free, no API key) to fetch a rich set of features
useful for landslide-hazard context + 3D visualization:
  - way["building"]      - buildings
  - way["highway"]       - roads / streets / tracks / paths
  - way["waterway"]      - rivers, streams, creeks (line geometry)
  - way["natural"]       - water bodies, wood, scrub (polygon)
  - way["landuse"]       - residential, farmland, forest, etc. (polygon)
  - node["place"]        - city / town / village / hamlet / sitio
  - node["amenity"]      - schools, churches, hospitals, shops
  - node["natural"]      - mountain peaks, springs
  - node["tourism"]      - viewpoints, attractions
  - node["man_made"]     - towers, water towers, etc.

Outputs:
    data/raw/osm.json                raw Overpass response (cached)
    data/processed/features.geojson  open standard GIS file (for QGIS etc.)
    data/processed/features.json     viewer-ready (world coords + lon/lat)
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
    # Single Overpass query for everything we care about. Generous timeout
    # because remote mountain areas are sparse but the bbox is small.
    return (
        "[out:json][timeout:180];"
        "("
        f"  way[\"building\"]({bbox});"
        f"  way[\"highway\"]({bbox});"
        f"  way[\"waterway\"]({bbox});"
        f"  way[\"natural\"]({bbox});"
        f"  way[\"landuse\"]({bbox});"
        f"  node[\"place\"]({bbox});"
        f"  node[\"amenity\"]({bbox});"
        f"  node[\"natural\"]({bbox});"
        f"  node[\"tourism\"]({bbox});"
        f"  node[\"man_made\"]({bbox});"
        f"  node[\"shop\"]({bbox});"
        ");"
        "out body geom;"
    )


def _boundary_query(bounds, pad_deg=0.15):
    """Admin boundaries - queried from a wider bbox so neighbouring barangays
    / municipalities show their full sakop even when most of their area is
    outside the AOI."""
    min_lon, min_lat, max_lon, max_lat = bounds
    bbox = (f"{min_lat - pad_deg},{min_lon - pad_deg},"
            f"{max_lat + pad_deg},{max_lon + pad_deg}")
    return (
        "[out:json][timeout:180];"
        "(relation[\"boundary\"=\"administrative\"]"
        f"[\"admin_level\"~\"^(6|8|9|10)$\"]({bbox}););"
        "out body geom;"
    )


def _assemble_rings(ways):
    """Chain a set of way-coord-lists into closed polygon rings by matching
    endpoint coordinates. OSM boundary relations split a polygon across many
    outer ways - this stitches them back together."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while pending:
        ring = pending.pop(0)
        guard = 0
        while ring and ring[0] != ring[-1] and guard < 5000:
            guard += 1
            tail = ring[-1]; head = ring[0]
            matched = -1
            for i, w in enumerate(pending):
                if not w:
                    continue
                if w[0] == tail:
                    ring = ring + w[1:]; matched = i; break
                if w[-1] == tail:
                    ring = ring + list(reversed(w))[1:]; matched = i; break
                if w[-1] == head:
                    ring = w + ring[1:]; matched = i; break
                if w[0] == head:
                    ring = list(reversed(w)) + ring[1:]; matched = i; break
            if matched < 0:
                break
            pending.pop(matched)
        if len(ring) >= 4:
            rings.append(ring)
    return rings


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
    banner("STAGE  -  OSM features (Overpass API)")

    bounds = cfg.aoi_bounds
    raw_path = RAW / "osm.json"
    boundary_raw_path = RAW / "osm_boundaries.json"

    if not raw_path.exists():
        print("  Querying Overpass API (enriched query)...")
        try:
            r = requests.post(OVERPASS_URL,
                              data={"data": _overpass_query(bounds)},
                              timeout=240,
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

    if not boundary_raw_path.exists():
        print("  Querying Overpass API for admin boundaries (+0.15 deg pad)...")
        try:
            r = requests.post(OVERPASS_URL,
                              data={"data": _boundary_query(bounds)},
                              timeout=240,
                              headers={"User-Agent": "landslide-thesis/1.0"})
            r.raise_for_status()
            boundary_raw_path.write_text(r.text, encoding="utf-8")
            print(f"  Saved boundary response "
                  f"({boundary_raw_path.stat().st_size/1024:.0f} KB)")
        except Exception as e:
            print(f"  !! Boundary Overpass request failed ({e}). "
                  "Continuing without boundaries.")
            boundary_raw_path.write_text(json.dumps({"elements": []}),
                                         encoding="utf-8")
    else:
        print(f"  Using cached boundary response: {boundary_raw_path.name}")

    with open(raw_path, "r", encoding="utf-8") as fh:
        osm = json.load(fh)
    with open(boundary_raw_path, "r", encoding="utf-8") as fh:
        osm_boundaries = json.load(fh)

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

    def _elev_at_lonlat(lon, lat):
        xs, ys = warp_transform("EPSG:4326", crs, [lon], [lat])
        col, row = inv * (xs[0], ys[0])
        ci = max(0, min(W - 1, int(round(col))))
        ri = max(0, min(H - 1, int(round(row))))
        return float(dem[ri, ci])

    def _world_xz(lon, lat):
        xs, ys = warp_transform("EPSG:4326", crs, [lon], [lat])
        col, row = inv * (xs[0], ys[0])
        wx = (col - (W - 1) / 2) * cell_x * world_scale
        wz = (row - (H - 1) / 2) * cell_y * world_scale
        return wx, wz

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

    buildings, roads, waterways = [], [], []
    water_bodies, landuse = [], []
    places, pois, peaks = [], [], []

    # POI categories we keep (everything else with amenity/tourism/etc. is ignored).
    POI_TYPES = {
        "school", "kindergarten", "college", "university",
        "place_of_worship", "hospital", "clinic", "doctors", "pharmacy",
        "townhall", "police", "fire_station", "post_office",
        "marketplace", "shop", "restaurant", "cafe", "fast_food",
        "fuel", "bank", "atm",
    }
    TOURISM_TYPES = {"viewpoint", "attraction", "guest_house", "hotel"}
    MANMADE_TYPES = {"tower", "water_tower", "communications_tower", "mast"}
    PLACE_TYPES = {
        "city", "town", "village", "hamlet", "isolated_dwelling",
        "locality", "neighbourhood", "suburb",
    }

    for el in osm.get("elements", []):
        tags = el.get("tags", {}) or {}
        el_type = el.get("type")

        # ---- WAY features (line / polygon) ----
        if el_type == "way":
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
                    "tags": {k: tags[k] for k in ("building", "name", "amenity") if k in tags},
                })
            elif "highway" in tags:
                roads.append({
                    "line": wc,
                    "highway": tags.get("highway", "road"),
                    "name": tags.get("name"),
                    "ref":  tags.get("ref"),
                })
            elif "waterway" in tags:
                waterways.append({
                    "line": wc,
                    "waterway": tags.get("waterway", "stream"),
                    "name": tags.get("name"),
                })
            elif tags.get("natural") == "water":
                ring = wc[:-1] if len(wc) > 1 and wc[0][:2] == wc[-1][:2] else wc
                water_bodies.append({
                    "footprint": [[p[0], p[1]] for p in ring],
                    "name": tags.get("name"),
                })
            elif "landuse" in tags and len(wc) >= 3:
                ring = wc[:-1] if wc[0][:2] == wc[-1][:2] else wc
                landuse.append({
                    "footprint": [[p[0], p[1]] for p in ring],
                    "type": tags.get("landuse"),
                    "name": tags.get("name"),
                })
            elif tags.get("natural") in {"wood", "scrub", "grassland", "wetland"} and len(wc) >= 3:
                ring = wc[:-1] if wc[0][:2] == wc[-1][:2] else wc
                landuse.append({
                    "footprint": [[p[0], p[1]] for p in ring],
                    "type": f"natural_{tags['natural']}",
                    "name": tags.get("name"),
                })

        # ---- NODE features (point) ----
        elif el_type == "node":
            lon = el.get("lon"); lat = el.get("lat")
            if lon is None or lat is None:
                continue
            try:
                wx, wz = _world_xz(lon, lat)
                elev = _elev_at_lonlat(lon, lat)
            except Exception:
                continue
            base = {"x": round(wx, 2), "z": round(wz, 2),
                    "elev_m": round(elev, 1),
                    "lon": round(lon, 6), "lat": round(lat, 6),
                    "name": tags.get("name")}

            if tags.get("place") in PLACE_TYPES:
                places.append({**base, "type": tags["place"]})
            elif tags.get("natural") == "peak":
                peaks.append({**base,
                              "ele": tags.get("ele"),
                              "type": "peak"})
            elif tags.get("amenity") in POI_TYPES:
                pois.append({**base, "category": "amenity",
                             "subtype": tags["amenity"]})
            elif tags.get("tourism") in TOURISM_TYPES:
                pois.append({**base, "category": "tourism",
                             "subtype": tags["tourism"]})
            elif tags.get("man_made") in MANMADE_TYPES:
                pois.append({**base, "category": "man_made",
                             "subtype": tags["man_made"]})
            elif "shop" in tags:
                pois.append({**base, "category": "shop",
                             "subtype": tags["shop"]})

    # ---- Admin boundaries (separate Overpass response) ----------------
    boundaries = []
    for el in osm_boundaries.get("elements", []):
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {}) or {}
        if tags.get("boundary") != "administrative":
            continue
        al = tags.get("admin_level")
        if al not in ("6", "8", "9", "10"):
            continue
        outer_ways = []
        for m in el.get("members", []):
            if m.get("type") != "way":
                continue
            role = m.get("role") or ""
            if role not in ("outer", ""):
                continue
            geom = m.get("geometry") or []
            if len(geom) < 2:
                continue
            outer_ways.append([(g["lon"], g["lat"]) for g in geom])
        rings = _assemble_rings(outer_ways)
        for ring in rings:
            if len(ring) < 4:
                continue
            wc = to_world([(lon, lat) for lon, lat in ring])
            # [wx, wz, elev_m]. Elev is clamped to nearest edge cell for
            # vertices outside the AOI (best-effort for visualization).
            world_xz = [[p[0], p[1], p[2]] for p in wc]
            latlon = [[round(lat, 6), round(lon, 6)] for lon, lat in ring]
            # Centroid (lat/lon mean) for labels.
            clat = sum(p[0] for p in latlon) / len(latlon)
            clon = sum(p[1] for p in latlon) / len(latlon)
            try:
                celev = _elev_at_lonlat(clon, clat)
                cwx, cwz = _world_xz(clon, clat)
            except Exception:
                celev = elev_min; cwx = cwz = 0.0
            boundaries.append({
                "name": tags.get("name") or f"admin_{al}_{el.get('id')}",
                "admin_level": int(al),
                "world": world_xz,                  # for 3D outline
                "latlon": latlon,                   # for Leaflet
                "centroid": {
                    "lon": round(clon, 6), "lat": round(clat, 6),
                    "x": round(cwx, 2), "z": round(cwz, 2),
                    "elev_m": round(celev, 1),
                },
            })

    features = {
        "world_scale": world_scale,
        "elev_min_m": elev_min,
        "level_m": LEVEL_M,
        "aoi_wgs84": {
            "min_lon": bounds[0], "min_lat": bounds[1],
            "max_lon": bounds[2], "max_lat": bounds[3],
        },
        "buildings": buildings,
        "roads": roads,
        "waterways": waterways,
        "water_bodies": water_bodies,
        "landuse": landuse,
        "places": places,
        "pois": pois,
        "peaks": peaks,
        "boundaries": boundaries,
    }
    (PROCESSED / "features.json").write_text(json.dumps(features), encoding="utf-8")

    # Open-standard GeoJSON for QGIS / external GIS - preserves ALL features.
    gj = {"type": "FeatureCollection", "features": []}
    for el in osm.get("elements", []):
        tags = el.get("tags", {}) or {}
        el_type = el.get("type")
        if el_type == "way":
            geom = el.get("geometry") or []
            if len(geom) < 2:
                continue
            ring = [[g["lon"], g["lat"]] for g in geom]
            is_area = (
                "building" in tags
                or "landuse" in tags
                or tags.get("natural") in {"water", "wood", "scrub", "grassland", "wetland"}
            )
            if is_area:
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                gj["features"].append({"type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": tags})
            else:
                gj["features"].append({"type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": ring},
                    "properties": tags})
        elif el_type == "node":
            lon = el.get("lon"); lat = el.get("lat")
            if lon is None or lat is None:
                continue
            gj["features"].append({"type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": tags})
    (PROCESSED / "features.geojson").write_text(json.dumps(gj), encoding="utf-8")

    result = {
        "buildings": len(buildings),
        "roads": len(roads),
        "waterways": len(waterways),
        "water_bodies": len(water_bodies),
        "landuse": len(landuse),
        "places": len(places),
        "pois": len(pois),
        "peaks": len(peaks),
        "boundaries": len(boundaries),
    }
    print(
        f"  Buildings:{len(buildings)}  Roads:{len(roads)}  "
        f"Waterways:{len(waterways)}  Water bodies:{len(water_bodies)}  "
        f"Landuse:{len(landuse)}  Places:{len(places)}  "
        f"POIs:{len(pois)}  Peaks:{len(peaks)}  "
        f"Boundaries:{len(boundaries)}"
    )
    update_meta({"features": result})
    return result


if __name__ == "__main__":
    run(Config.load())
