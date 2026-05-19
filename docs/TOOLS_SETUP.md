# Tools Setup

## Already done in this project

Everything you need to **run the pipeline and the 3-D viewer** is already
installed in the project directory. You do not need to install anything else
to reproduce every output in this repository.

| Tool | Status | Notes |
|------|--------|-------|
| Python 3.10 | already on the system | used to create the venv |
| Project virtual environment (`.venv/`) | created | isolated to this project |
| numpy, scipy, rasterio, pillow, requests, pyyaml, matplotlib | installed inside `.venv` | see `requirements.txt` |
| Three.js + OrbitControls (`viewer/lib/`) | bundled locally | viewer runs offline |
| Copernicus GLO-30 DEM tile | downloaded (32.4 MB) | `data/raw/` |
| OSM buildings + roads (Overpass response) | downloaded (~190 KB) | `data/raw/osm.json` |

To recreate everything from scratch on another machine:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_pipeline.py
.\.venv\Scripts\python.exe -m http.server 8000
# open  http://localhost:8000/viewer/
```

## Online services used (free, no key needed)

| Service | What it gives | Endpoint |
|---------|---------------|----------|
| AWS Open Data – Copernicus DEM | GLO-30 DEM tiles | `copernicus-dem-30m.s3.amazonaws.com` |
| Overpass API | OSM buildings + roads (rate-limited) | `overpass-api.de/api/interpreter` |

Both are anonymous (no account, no key). Overpass is occasionally rate-
limited; if the `features` stage fails the response will be cached after the
first success so subsequent runs are offline.

## Optional tools — install only if your defense requires them

The thesis title and notes mention **OpenLISEM** and **QGIS**. The Python
pipeline in this repository is a self-contained alternative that already
performs DEM preparation, susceptibility, runout, drainage and exposure
analysis, so neither is required for the figures or the 3-D viewer.
However, your adviser/panel may want a QGIS screenshot for the GIS chapter,
or an OpenLISEM comparison for the geodynamic chapter. Both are free.

### QGIS Desktop (recommended for the GIS chapter)
* **Install:** <https://qgis.org/en/site/forusers/download.html> (Windows
  installer, ~1 GB). Use the **Long-Term Release**.
* **Useful for:** opening the GeoTIFFs in `data/processed/` (DEM, slope,
  hillshade, FS, susceptibility, runout, flow accumulation) and the
  `features.geojson` (buildings + roads) and composing publication-quality
  map layouts with scale bar and north arrow.
* QGIS reads the project CRS (UTM 51N / EPSG:32651) from the GeoTIFF
  metadata automatically.

### OpenLISEM Hazard (optional, for the "geodynamic simulation" chapter)
* **Install:** Windows portable build —
  <https://lisemmodel.com/docs/downloads/>
* **Reference paper:** van den Bout et al., *Towards a model for structured
  mass movements: the OpenLISEM hazard model 2.0a*, **GMD 14, 1841–1864
  (2021)** — <https://gmd.copernicus.org/articles/14/1841/2021/>
* **Use it for:** running a physics-based runout / debris-flow simulation
  using the same DEM (`data/processed/dem.tif`) plus a triggering scenario.
  Compare its runout footprint with the energy-line footprint produced by
  this pipeline.

### LiDAR DEM (optional, replaces the global DEM)
If you obtain a higher-resolution LiDAR DEM (Phil-LiDAR / DREAM / UP-TCAGP):

1. Drop the GeoTIFF at `data/raw/lidar_dem.tif`.
2. Run `.\.venv\Scripts\python.exe -m landslide.lidar`
   (re-project + void fill + light smoothing → `data/processed/dem_lidar.tif`).
3. Overwrite `data/processed/dem.tif` with `dem_lidar.tif` and re-run the
   pipeline from the `features` stage:
   `.\.venv\Scripts\python.exe run_pipeline.py --from features`.

## What you do *not* need

* **No GDAL system install** – the rasterio wheel ships its own GDAL.
* **No Conda / Anaconda** – plain `pip` + venv is enough.
* **No API keys** for the DEM or OSM.
* **No Node.js** for the viewer – Three.js is bundled.
