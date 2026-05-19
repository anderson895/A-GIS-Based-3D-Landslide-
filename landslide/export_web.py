"""Final stage - bundle the viewer assets and render thesis figures.

The viewer in viewer/ reads:
    data/terrain.bin            float32 elevation grid (north-up)
    data/terrain.json           grid metadata + layer/scenario manifests + stats
    data/tex_hillshade.png      base relief
    data/tex_slope.png          slope gradient
    data/tex_channels.png       drainage / flow-accumulation overlay
    data/tex_susc_<scenario>.png      hazard class per scenario  (4 files)
    data/tex_runout_<scenario>.png    runout & deposition per scenario (4 files)
    data/features.json          OSM buildings + roads (world coords)

Thesis figures (docs/figures/):
    fig_hillshade.png      shaded relief
    fig_slope.png          slope gradient
    fig_susceptibility.png Normal-scenario hazard
    fig_runout.png         Normal-scenario runout
    fig_channels.png       drainage network
    fig_scenarios.png      2x2 susceptibility across 4 scenarios
    fig_runout_scenarios.png 2x2 runout across 4 scenarios
    fig_exposure.png       exposed buildings / roads bar chart
"""
from __future__ import annotations

import json
import math
import shutil
import numpy as np
import rasterio
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from .config import Config, PROCESSED, OUTPUTS, FIGURES, VIEWER, banner
from .susceptibility import CLASS_NAMES
from .scenarios import SCENARIOS

SUSC_COLORS = [
    (26, 152, 80), (145, 207, 96), (254, 224, 139),
    (252, 141, 89), (215, 48, 39),
]
SUSC_FS_RANGE = [">= 2.0", "1.5 - 2.0", "1.25 - 1.5", "1.0 - 1.25", "< 1.0"]


# ---------------------------------------------------------------------------
def _read(name, root=PROCESSED):
    with rasterio.open(root / name) as src:
        return src.read(1)


def _relief(hs):
    return 0.45 + 0.55 * (hs.astype("float32") / 255.0)


def _rgba(rgb, alpha=255):
    h, w = rgb.shape[:2]
    out = np.empty((h, w, 4), dtype="uint8")
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def _shade(rgb_f, relief):
    return (np.clip(rgb_f * relief[..., None], 0, 1) * 255.0).astype("uint8")


def _save_png(rgba, path):
    Image.fromarray(rgba, "RGBA").save(path)


# ---------------------------------------------------------------------------
# Texture builders
# ---------------------------------------------------------------------------
def _tex_hillshade(hs):
    g = hs.astype("uint8")
    return _rgba(np.dstack([g, g, g]))


def _tex_slope(slope, relief):
    rgb = plt.get_cmap("RdYlGn_r")(np.clip(slope / 50.0, 0, 1))[..., :3]
    return _rgba(_shade(rgb, relief))


def _tex_susceptibility(susc, relief):
    rgb = np.zeros((*susc.shape, 3), dtype="float32")
    for i, color in enumerate(SUSC_COLORS, start=1):
        rgb[susc == i] = np.array(color) / 255.0
    return _rgba(_shade(rgb, relief))


def _tex_runout(hs, intensity, deposition, sources):
    relief = _relief(hs)
    base = np.dstack([relief, relief, relief])

    def lognorm(a):
        a = np.asarray(a, dtype="float64"); mx = a.max()
        return np.zeros_like(a) if mx <= 0 else np.log1p(a) / math.log1p(mx)

    t = lognorm(intensity)
    ramp = plt.get_cmap("YlOrRd")(np.clip(t * 0.85 + 0.15, 0, 1))[..., :3]
    a = np.clip(t * 1.4, 0, 0.92)[..., None]
    img = base * (1 - a) + ramp * a

    d = lognorm(deposition)
    dep_color = np.array([106, 61, 154]) / 255.0
    ad = np.clip((d - 0.25) * 1.6, 0, 0.85)[..., None]
    img = img * (1 - ad) + dep_color * ad

    sm = (sources > 0)[..., None]
    img = np.where(sm, np.array([120, 0, 0]) / 255.0, img)
    return _rgba((np.clip(img, 0, 1) * 255).astype("uint8"))


def _tex_channels(hs, accum):
    """Drainage network overlay: log-scaled flow accumulation on hillshade."""
    relief = _relief(hs)
    base = np.dstack([relief, relief, relief])
    a = np.log1p(accum) / math.log1p(accum.max() + 1e-9)
    rgb = plt.get_cmap("PuBu")(np.clip(a * 0.9 + 0.05, 0, 1))[..., :3]
    alpha = np.clip((a - 0.35) * 2.0, 0, 0.85)[..., None]
    img = base * (1 - alpha) + rgb * alpha
    return _rgba((np.clip(img, 0, 1) * 255).astype("uint8"))


# ---------------------------------------------------------------------------
# Thesis figures
# ---------------------------------------------------------------------------
def _fig(rgba, title, path, legend=None, cbar=None):
    fig, ax = plt.subplots(figsize=(7.2, 7.0), dpi=130)
    ax.imshow(rgba)
    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_xlabel("Easting (pixels, ~30 m cells)")
    ax.set_ylabel("Northing (pixels)")
    if legend:
        ax.legend(handles=legend, loc="lower right", fontsize=7,
                  framealpha=0.9, title="Hazard class")
    if cbar is not None:
        sm, lab = cbar
        fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04, label=lab)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def _fig_panel(panels, suptitle, path, cols=2):
    rows = (len(panels) + cols - 1) // cols
    fig, axs = plt.subplots(rows, cols, figsize=(7.2 * cols, 6.6 * rows), dpi=120)
    axs = np.atleast_2d(axs)
    for i, (img, title) in enumerate(panels):
        ax = axs[i // cols, i % cols]
        ax.imshow(img); ax.set_title(title, fontsize=10)
        ax.set_xticks([]); ax.set_yticks([])
    for j in range(len(panels), rows * cols):
        axs[j // cols, j % cols].axis("off")
    fig.suptitle(suptitle, fontsize=12, weight="bold")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def _fig_exposure(exposure, path):
    ids = [s["id"] for s in SCENARIOS]
    names = [s["name"] for s in SCENARIOS]
    b_exp = [exposure.get(i, {}).get("buildings_in_runout", 0) for i in ids]
    r_exp = [exposure.get(i, {}).get("roads_in_runout_m", 0) for i in ids]
    b_tot = max([exposure.get(i, {}).get("buildings_total", 0) for i in ids] + [1])
    r_tot = max([exposure.get(i, {}).get("roads_total_m", 0) for i in ids] + [1])

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.5), dpi=130)
    x = np.arange(len(names))
    a1.bar(x, b_exp, color="#fc8d59")
    a1.axhline(b_tot, color="#444", linestyle="--", linewidth=0.7,
               label=f"Total ({b_tot})")
    a1.set_xticks(x); a1.set_xticklabels(names)
    a1.set_ylabel("Buildings inside runout")
    a1.set_title("Building exposure by scenario"); a1.legend(loc="upper left")
    a2.bar(x, np.asarray(r_exp) / 1000.0, color="#6a3d9a")
    a2.axhline(r_tot / 1000.0, color="#444", linestyle="--", linewidth=0.7,
               label=f"Total ({r_tot/1000:.1f} km)")
    a2.set_xticks(x); a2.set_xticklabels(names)
    a2.set_ylabel("Road exposed (km)"); a2.set_title("Road exposure by scenario")
    a2.legend(loc="upper left")
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------------
def run(cfg: Config) -> dict:
    banner("STAGE  -  Export viewer assets + thesis figures")
    meta = json.loads((PROCESSED / "meta.json").read_text(encoding="utf-8"))

    dem = _read("dem.tif").astype("float32")
    hs = _read("hillshade.tif")
    slope = _read("slope.tif")
    H, W = dem.shape

    # --- Optional downsample ------------------------------------------------
    max_grid = int(cfg["viz"]["max_grid"])
    f = max(1, math.ceil(max(H, W) / max_grid))
    sl = (slice(None, None, f), slice(None, None, f))
    if f > 1:
        dem = dem[sl]; hs = hs[sl]; slope = slope[sl]
        H, W = dem.shape
        print(f"  Downsampled grid by {f}x -> {W} x {H}")

    relief = _relief(hs)

    # --- terrain.bin --------------------------------------------------------
    dem_clean = np.nan_to_num(dem, nan=float(np.nanmin(dem)))
    (OUTPUTS / "terrain.bin").write_bytes(dem_clean.astype("<f4").tobytes())

    # --- Shared textures ----------------------------------------------------
    _save_png(_tex_hillshade(hs),       OUTPUTS / "tex_hillshade.png")
    _save_png(_tex_slope(slope, relief), OUTPUTS / "tex_slope.png")

    if (PROCESSED / "flow_accum.tif").exists():
        accum = _read("flow_accum.tif")[sl]
        _save_png(_tex_channels(hs, accum), OUTPUTS / "tex_channels.png")

    # Satellite imagery layer (if the imagery stage produced satellite.png).
    sat_path = PROCESSED / "satellite.png"
    if sat_path.exists():
        sat_img = Image.open(sat_path).convert("RGB")
        if f > 1:
            sat_img = sat_img.resize((W, H), Image.BILINEAR)
        sat_arr = np.array(sat_img)
        sat_rgba = _rgba(sat_arr)
        _save_png(sat_rgba, OUTPUTS / "tex_satellite.png")

    # --- Per-scenario textures ---------------------------------------------
    scen_root = PROCESSED / "scenarios"
    scenarios_meta = meta.get("scenarios", {})
    exposure_meta = meta.get("exposure", {})
    scen_layers = {}
    if scen_root.exists():
        for sc in SCENARIOS:
            d = scen_root / sc["id"]
            if not d.exists():
                continue
            susc = _read("susceptibility.tif", root=d)[sl]
            inten = _read("runout_intensity.tif", root=d)[sl]
            dep = _read("runout_deposition.tif", root=d)[sl]
            srcs = _read("runout_sources.tif", root=d)[sl]
            susc_tex = f"tex_susc_{sc['id']}.png"
            runout_tex = f"tex_runout_{sc['id']}.png"
            _save_png(_tex_susceptibility(susc, relief), OUTPUTS / susc_tex)
            _save_png(_tex_runout(hs, inten, dep, srcs), OUTPUTS / runout_tex)
            scen_layers[sc["id"]] = {"susc": susc_tex, "runout": runout_tex}

    print(f"  Wrote {len(scen_layers)} scenario texture pair(s)")

    # --- terrain.json -------------------------------------------------------
    site = meta["site"]
    layers = [
        {"id": "hillshade", "name": "Shaded Relief",
         "texture": "tex_hillshade.png",
         "description": "Base terrain illumination from the DEM."},
    ]
    if (OUTPUTS / "tex_satellite.png").exists():
        layers.append({
            "id": "satellite", "name": "Satellite Imagery",
            "texture": "tex_satellite.png",
            "description": "Esri World Imagery at zoom 15 (~4.8 m/pixel) "
                           "reprojected to the project UTM grid.",
            "attribution": "Esri, Maxar, Earthstar Geographics, "
                           "GIS User Community",
        })
    layers.append({
        "id": "slope", "name": "Slope Gradient",
        "texture": "tex_slope.png",
        "description": "Slope steepness - a primary landslide pre-condition.",
        "legend": [{"label": "0 deg", "color": "#1a9850"},
                   {"label": "25 deg", "color": "#fee08b"},
                   {"label": "50 deg+", "color": "#d73027"}]})
    if (OUTPUTS / "tex_channels.png").exists():
        layers.append({
            "id": "channels", "name": "Drainage Network",
            "texture": "tex_channels.png",
            "description": "D8 flow-accumulation: where surface water (and "
                           "debris flow) concentrates.",
            "legend": [{"label": "Low accumulation", "color": "#f1eef6"},
                       {"label": "Channel", "color": "#74a9cf"},
                       {"label": "Main valley", "color": "#0570b0"}]})
    if scen_layers:
        layers.append({
            "id": "susceptibility", "name": "Landslide Susceptibility",
            "scenarioTextures": {k: v["susc"] for k, v in scen_layers.items()},
            "description": "Infinite-slope Factor of Safety binned into "
                           "5 classes (changes with rainfall scenario).",
            "legend": [{"label": f"{n} (FS {r})",
                        "color": "#%02x%02x%02x" % c}
                       for c, n, r in zip(SUSC_COLORS, CLASS_NAMES, SUSC_FS_RANGE)]})
        layers.append({
            "id": "runout", "name": "Runout & Deposition",
            "scenarioTextures": {k: v["runout"] for k, v in scen_layers.items()},
            "description": "Energy-line runout: sources, transport paths and "
                           "deposition zones (changes with rainfall scenario).",
            "legend": [{"label": "Source (slope failure)", "color": "#780000"},
                       {"label": "Transport path", "color": "#fc8d3b"},
                       {"label": "Deposition zone", "color": "#6a3d9a"}]})

    scenarios_out = []
    for sc in SCENARIOS:
        s = scenarios_meta.get(sc["id"])
        if not s:
            continue
        scenarios_out.append({
            "id": sc["id"], "name": sc["name"], "m": sc["m"],
            "stats": {
                "unstable_percent": s["unstable_percent"],
                "n_sources": s["n_sources"],
                "runout_percent": s["runout_percent"],
                "max_runout_m": s["max_runout_m"],
            },
            "exposure": exposure_meta.get(sc["id"], {}),
        })

    terrain_json = {
        "project": cfg["project"]["name"],
        "area": cfg["project"]["area"],
        "generated_grid": {"width": W, "height": H, "downsample": f},
        "cell_x_m": meta["cell_x_m"] * f,
        "cell_y_m": meta["cell_y_m"] * f,
        "elev_min": float(np.nanmin(dem)),
        "elev_max": float(np.nanmax(dem)),
        "aoi_wgs84": meta["aoi_wgs84"],
        "vertical_exaggeration": cfg["viz"]["vertical_exaggeration"],
        "site": {
            "label": site["label"], "lon": site["lon"], "lat": site["lat"],
            "row": site["row"] / f, "col": site["col"] / f,
            "u": (site["col"] / f) / max(W - 1, 1),
            "v": (site["row"] / f) / max(H - 1, 1),
        },
        "layers": layers,
        "scenarios": scenarios_out,
        "default_scenario": "normal",
        "shared_stats": {
            "elev_min_m": round(float(np.nanmin(dem)), 1),
            "elev_max_m": round(float(np.nanmax(dem)), 1),
            "mean_slope_deg": round(float(np.nanmean(slope)), 1),
            "max_slope_deg": round(float(np.nanmax(slope)), 1),
            "travel_angle_deg": float(cfg["runout"]["travel_angle_deg"]),
            "n_buildings": meta.get("features", {}).get("buildings", 0),
            "n_roads": meta.get("features", {}).get("roads", 0),
            "channel_cells": meta.get("hydrology", {}).get("channel_cells", 0),
        },
        "features_url": "features.json" if (PROCESSED / "features.json").exists()
                          else None,
    }
    (OUTPUTS / "terrain.json").write_text(json.dumps(terrain_json, indent=2),
                                          encoding="utf-8")

    if (PROCESSED / "features.json").exists():
        shutil.copy(PROCESSED / "features.json", OUTPUTS / "features.json")

    print(f"  Wrote terrain.json  ({len(layers)} layers, "
          f"{len(scenarios_out)} scenarios)")

    # --- Thesis figures -----------------------------------------------------
    _fig(_tex_hillshade(hs), "Shaded Relief - Malico, San Nicolas, Pangasinan",
         FIGURES / "fig_hillshade.png")
    sm = plt.cm.ScalarMappable(cmap="RdYlGn_r", norm=plt.Normalize(0, 50))
    _fig(_tex_slope(slope, relief), "Slope Gradient Map",
         FIGURES / "fig_slope.png", cbar=(sm, "Slope (degrees)"))

    if (OUTPUTS / "tex_channels.png").exists():
        _fig(np.asarray(Image.open(OUTPUTS / "tex_channels.png")),
             "Drainage Network (D8 Flow Accumulation)",
             FIGURES / "fig_channels.png")

    susc_legend = [Patch(facecolor=np.array(c) / 255.0,
                         label=f"{n}  (FS {r})")
                   for c, n, r in zip(SUSC_COLORS, CLASS_NAMES, SUSC_FS_RANGE)]
    runout_legend = [
        Patch(facecolor=(120/255, 0, 0), label="Source (slope failure)"),
        Patch(facecolor=(0.99, 0.55, 0.23), label="Transport path"),
        Patch(facecolor=(106/255, 61/255, 154/255), label="Deposition zone"),
    ]
    if scen_layers:
        # Normal-scenario thesis maps.
        normal = scen_root / "normal"
        susc_n = _read("susceptibility.tif", root=normal)[sl]
        _fig(_tex_susceptibility(susc_n, relief),
             "Landslide Susceptibility - Normal scenario (m=0.40)",
             FIGURES / "fig_susceptibility.png", legend=susc_legend)
        inten_n = _read("runout_intensity.tif", root=normal)[sl]
        dep_n = _read("runout_deposition.tif", root=normal)[sl]
        srcs_n = _read("runout_sources.tif", root=normal)[sl]
        _fig(_tex_runout(hs, inten_n, dep_n, srcs_n),
             "Landslide Runout - Normal scenario (m=0.40)",
             FIGURES / "fig_runout.png", legend=runout_legend)

        # 2x2 scenario comparison panels.
        susc_panels, runout_panels = [], []
        for sc in SCENARIOS:
            d = scen_root / sc["id"]
            susc_panels.append(
                (_tex_susceptibility(_read("susceptibility.tif", root=d)[sl], relief),
                 f"{sc['name']}  (m = {sc['m']:.2f})"))
            runout_panels.append(
                (_tex_runout(hs,
                             _read("runout_intensity.tif", root=d)[sl],
                             _read("runout_deposition.tif", root=d)[sl],
                             _read("runout_sources.tif", root=d)[sl]),
                 f"{sc['name']}  (m = {sc['m']:.2f})"))
        _fig_panel(susc_panels, "Susceptibility under 4 rainfall scenarios",
                   FIGURES / "fig_scenarios.png")
        _fig_panel(runout_panels, "Runout under 4 rainfall scenarios",
                   FIGURES / "fig_runout_scenarios.png")

    if exposure_meta:
        _fig_exposure(exposure_meta, FIGURES / "fig_exposure.png")

    print(f"  Rendered thesis figures to {FIGURES}")

    # --- Copy assets to viewer/data ----------------------------------------
    viewer_data = VIEWER / "data"
    viewer_data.mkdir(exist_ok=True)
    # Clear stale per-scenario files first
    for old in viewer_data.glob("tex_susc_*.png"): old.unlink()
    for old in viewer_data.glob("tex_runout_*.png"): old.unlink()
    for src in OUTPUTS.iterdir():
        if src.is_file():
            shutil.copy(src, viewer_data / src.name)
    print(f"  Copied viewer assets to {viewer_data}")
    return terrain_json
