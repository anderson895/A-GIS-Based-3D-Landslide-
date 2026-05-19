# Methodology

The pipeline implements a multi-stage workflow that mirrors standard practice
for physically-based landslide hazard mapping with an added vulnerability /
exposure component. Each stage is a single module under `landslide/` so the
math is auditable from the code.

## 1. Digital Elevation Model

Base terrain: **Copernicus GLO-30 Digital Surface Model** (30-metre
horizontal resolution, mean absolute vertical accuracy < 4 m for the
Philippines region). The 1° × 1° tile `N16 E120` is pulled from the AWS Open
Data public bucket — no API key required. A higher-resolution **LiDAR DEM**
can be substituted via `landslide/lidar.py` (Phil-LiDAR / DREAM / UP-TCAGP).

## 2. Terrain preparation

* Clip a buffered AOI from the COG, reproject to **UTM Zone 51 N (EPSG:32651)**
  with bilinear resampling, then crop to the exact AOI — buffered read
  prevents the no-data corner artefacts that appear when a lat/lon AOI box is
  reprojected to a planar grid.
* **Slope** β = `arctan(sqrt((dz/dx)² + (dz/dy)²))` from a finite-difference
  gradient on the metric grid.
* **Hillshade** uses the standard ESRI/USGS formula (azimuth 315°, alt 45°).

## 3. OSM features

The **Overpass API** is queried for all `way["building"]` and `way["highway"]`
inside the AOI bounding box. Each feature’s lon/lat geometry is converted to
the project’s UTM grid; buildings get a sampled base elevation, roads get a
per-vertex elevation profile so they drape correctly on the terrain in the
viewer. Output: `features.json` (viewer-ready) and `features.geojson`
(open standard for QGIS).

## 4. Hydrology — D8 flow accumulation

Standard D8 flow direction (steepest descent over 8 neighbours) processed
from highest to lowest elevation. Each cell contributes one unit upstream
into its single downstream neighbour. The result is a per-cell **upstream
contributing area**; cells exceeding a threshold trace out the drainage
**channel network**, which is also where debris flow tends to concentrate.

## 5. Susceptibility — infinite-slope Factor of Safety

The canonical physically-based model for shallow, translational landslides
on long uniform slopes:

```
       c' + (γ − m · γ_w) · z · cos²β · tan φ'
FS = ─────────────────────────────────────────
              γ · z · sin β · cos β
```

| Symbol | Meaning | Default value | Units |
|-------:|---------|---------------|-------|
| c'     | Effective cohesion | 5.0 | kPa (kN/m²) |
| φ'     | Effective friction angle | 30.0 | ° |
| γ      | Soil unit weight | 18.0 | kN/m³ |
| γ_w    | Water unit weight | 9.81 | kN/m³ |
| z      | Depth to failure plane | 2.0 | m |
| m      | Groundwater ratio | varies per scenario | — |
| β      | Slope angle (per-cell) | from DEM | ° |

`FS < 1` ⇒ theoretically unstable. The continuous FS raster is binned into
5 hazard classes at break-points `2.0 / 1.5 / 1.25 / 1.0`.

## 6. Rainfall scenarios

The pipeline runs the FS + runout model for **four hydrological scenarios**
that capture the seasonal envelope of slope-stability conditions in Malico:

| Scenario  | m (water-table / soil-depth) | Physical meaning |
|-----------|------------------------------|------------------|
| Dry       | 0.10 | Long dry season; water table far below the failure plane |
| Normal    | 0.40 | Typical post-rain conditions |
| Wet       | 0.70 | Sustained rainy season, soils near saturated |
| Extreme   | 1.00 | Typhoon / convective downpour, full saturation |

Each scenario yields its own FS raster, susceptibility classes, runout
footprint, and exposure statistics.

## 7. Runout — energy-line model with MFD routing

Implements an **energy-line (Fahrböschung)** runout model, the same
conceptual framework used by Flow-R for regional debris-flow runout (Horton
et al., 2013).

1. **Source cells** are unstable (`FS < threshold`) *and* steep
   (`slope > minimum`). Each source contributes one unit of relative
   material.
2. **Transport.** Cells are processed top-down; flow is split between
   downhill neighbours by drop (**multiple-flow direction**). A neighbour
   receives flow only while it lies below the energy line
   `z_line = z_source − tan(α_travel) · d_path` (default α = 26°).
3. **Deposition** is recorded where the energy line catches the terrain or
   where no downhill neighbour remains.

Outputs per scenario:

* `runout_sources.tif`     – failure initiation cells
* `runout_intensity.tif`   – relative sediment-transport intensity
* `runout_deposition.tif`  – deposited material
* `runout_zone.tif`        – binary runout footprint

## 8. Exposure analysis

For each scenario, the runout zone is intersected against the OSM features:

* **Buildings** – a building is "exposed" if its centroid sits inside the
  runout zone.
* **Roads** – segment-midpoints are tested; each exposed segment’s length
  is accumulated in metres (and reported as a percentage of the AOI road
  network length).

These numbers bridge the physical model and the vulnerability discussion in
the thesis.

## 9. Visualization

* The 3-D viewer is a self-contained Three.js / WebGL app. It reads a
  Float32 elevation grid (`terrain.bin`), per-layer textures, a metadata
  JSON (`terrain.json`) carrying layer legends + scenario stats + exposure,
  and the OSM `features.json`.
* Buildings are rendered as **extruded prisms** (height ×8 visual
  exaggeration so a 3 m building reads at the kilometre-scale terrain),
  roads as **textured ribbons** draped on the terrain at a small Y offset.
* Layer textures are scenario-aware: when the user toggles a rainfall
  scenario, the Susceptibility and Runout maps refresh while the Drainage
  / Slope / Shaded-Relief layers stay constant.
* Thesis figures (`docs/figures/`) are publication-ready Matplotlib maps
  including a 2×2 scenario-comparison panel for both susceptibility and
  runout, plus an exposure bar chart.

## 10. Reproducibility

Every pipeline run writes `data/outputs/run_manifest.json` recording:

* timestamp + total duration
* Python version + library versions (numpy, scipy, rasterio, pillow,
  requests, pyyaml, matplotlib)
* the full `config.yaml` snapshot
* per-stage result summaries
* SHA-256 hash and byte size of every output file

Any later re-run can be byte-compared against this manifest.

## References

* Horton, P., Jaboyedoff, M., Rudaz, B., and Zimmermann, M. (2013).
  *Flow-R, a model for susceptibility mapping of debris flows and other
  gravitational hazards at a regional scale.*
  **Natural Hazards and Earth System Sciences 13, 869–885.**
* van Westen, C. J., Castellanos, E., and Kuriakose, S. L. (2008).
  *Spatial data for landslide susceptibility, hazard, and vulnerability
  assessment.* **Engineering Geology 102, 112–131.**
* Bessette-Kirton, E. K. and Coe, J. A. (2020). *Landslide runout: a review
  of analytical and empirical models.* USGS.
* Mines and Geosciences Bureau (MGB-DENR). *Landslide and Flood
  Susceptibility Maps of the Philippines (1:10,000).*
* ESA / Airbus. *Copernicus DEM – Global and European DEM (COP-DEM).*
* OpenStreetMap contributors. *Map data licensed under the Open Database
  License (ODbL).*  https://www.openstreetmap.org/copyright
