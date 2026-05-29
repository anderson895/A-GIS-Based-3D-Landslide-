# GIS-Based 3D Landslide Hazard Visualization Model

**Study area:** Barangay Malico, San Nicolas, Pangasinan, Philippines
(16.1573 °N, 120.8267 °E — along the Villa Verde / Pangasinan–Nueva Vizcaya
road, an area with documented landslide events).

A complete, reproducible GIS workflow that turns free public datasets into a
3-D, browser-based landslide-hazard visualization with quantitative
susceptibility, runout, drainage, and exposure layers — across four rainfall
scenarios.

## What the project produces

**Eight pipeline stages**, all driven by `config.yaml`:

| Stage | What it does |
|-------|--------------|
| 1 · download   | Pulls the Copernicus GLO-30 DEM tile (N16 E120) from the AWS Open Data public bucket — no API key. |
| 2 · terrain    | Clips a buffered AOI, reprojects to UTM 51N, derives slope, aspect, hillshade. |
| 3 · features   | Downloads OSM **buildings + roads** for the AOI via Overpass API. |
| 4 · hydrology  | D8 **flow direction + drainage accumulation** (channel network). |
| 5 · scenarios  | Runs **susceptibility + runout for 4 rainfall scenarios** (Dry / Normal / Wet / Extreme). |
| 6 · exposure   | Counts buildings & road metres inside each scenario’s runout footprint. |
| 7 · export     | Builds the **3-D viewer assets** + 8 publication-ready thesis figures. |
| 8 · diagnostics| Sanity-checks every output and writes a green/red report. |

A `data/outputs/run_manifest.json` is written at the end of every run with
timestamps, library versions, full config snapshot, and SHA256 hashes of all
output files — full reproducibility.

**The 3-D viewer** (Three.js / WebGL, fully offline once built):

- 5 hazard layers: Shaded Relief, Slope, Drainage Network, Susceptibility, Runout & Deposition
- 4 rainfall scenarios switchable in real time
- 3-D extruded **OSM buildings** + textured **road ribbons** draped on the terrain
- Vertical-exaggeration slider, sun direction slider
- Camera presets (Oblique / Top / Side), screenshot export
- Live scenario statistics + exposure read-out

---
## Quick start
```powershell
# 1. (one-time) create the virtual environment + install dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. run the full pipeline (DEM download + OSM + 4 scenarios + figures)
.\.venv\Scripts\python.exe run_pipeline.py

# 3. serve the 3D viewer
.\.venv\Scripts\python.exe -m http.server 8000
# open  http://localhost:8000/viewer/
```

CLI flags:

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --list             # show stages
.\.venv\Scripts\python.exe run_pipeline.py --only scenarios
.\.venv\Scripts\python.exe run_pipeline.py --from features
```

---

## Last run – key numbers (default config, ~8.5 × 8.5 km AOI around Malico)

| Metric | Dry (m=0.10) | Normal (m=0.40) | Wet (m=0.70) | Extreme (m=1.00) |
|---|---:|---:|---:|---:|
| Theoretically unstable (FS<1) | 6.5 % | **19.0 %** | 38.2 % | 60.7 % |
| Failure source cells | 5 463 | 16 084 | 25 816 | 25 816 |
| Runout footprint | 23.0 % | **41.0 %** | 51.5 % | 51.5 % |
| Max runout distance | 989 m | 1 275 m | 1 245 m | 1 245 m |
| Buildings exposed | 0 / 6 | 0 / 6 | 0 / 6 | 0 / 6 |
| **Road length exposed (of 40.4 km)** | **4.5 km** | **9.3 km** | **11.6 km** | **11.6 km** |

Static descriptors (scenario-independent):

| Metric | Value |
|---|---|
| Elevation range | 147 – 1579 m |
| Mean slope · max slope | 25.1° · 56.1° |
| Drainage channel cells | 3 832 (4.5 % of AOI) |
| OSM buildings · roads (ways) | 6 · 15 |

---

## Project layout

```
GIS-Based 3D/
├── config.yaml              # AOI, geotech, runout, viz parameters
├── requirements.txt
├── run_pipeline.py          # CLI orchestrator + manifest writer
├── landslide/               # the analysis package
│   ├── config.py            # config loader, project paths, meta merge helper
│   ├── download.py          # 1  fetch Copernicus DEM
│   ├── terrain.py           # 2  clip / reproject / slope / hillshade
│   ├── features.py          # 3  OSM buildings + roads (Overpass API)
│   ├── hydrology.py         # 4  D8 flow direction + accumulation
│   ├── susceptibility.py    # → infinite-slope FS (used by scenarios)
│   ├── runout.py            # → energy-line runout (used by scenarios)
│   ├── scenarios.py         # 5  multi-scenario rainfall runs
│   ├── exposure.py          # 6  features in runout zones
│   ├── export_web.py        # 7  viewer assets + thesis figures
│   ├── diagnostics.py       # 8  sanity checks
│   └── lidar.py             # optional LiDAR DEM preparation utility
├── viewer/                  # Three.js 3D viewer (offline-capable)
│   ├── index.html, main.js, style.css
│   ├── lib/three.module.js + OrbitControls.js
│   └── data/                # copied pipeline outputs
├── data/
│   ├── raw/                 # Copernicus tile + Overpass response (cached)
│   ├── processed/           # all GeoTIFFs + meta.json + features.* + scenarios/
│   └── outputs/             # terrain.bin, terrain.json, tex_*.png, manifest
├── docs/
│   ├── METHODOLOGY.md       # equations, model assumptions, references
│   ├── DATA_SOURCES.md      # dataset provenance
│   ├── TOOLS_SETUP.md       # required vs optional tools
│   └── figures/             # 8 thesis-ready PNG maps + scenario panels
└── .venv/                   # project virtual environment
```

See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the science, references,
and parameter meanings; [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for
dataset provenance; [`docs/TOOLS_SETUP.md`](docs/TOOLS_SETUP.md) for the
(short) list of tools.
