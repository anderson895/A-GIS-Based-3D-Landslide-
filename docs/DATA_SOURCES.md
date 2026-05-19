# Data Sources

The pipeline is built on free, openly-licensed datasets so every result is
fully reproducible.

## Primary terrain dataset (USED — already downloaded)

**Copernicus GLO-30 Digital Surface Model**
* Resolution: 30 m (1 arc-second)
* Coverage: global
* Vertical accuracy: < 4 m mean absolute error
* Licence: free for any use, see Copernicus DEM EULA
* Tile in this study: `N16 E120` (1° × 1° covering the AOI around Malico)
* Source URL (no key required):
  `https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N16_00_E120_00_DEM/Copernicus_DSM_COG_10_N16_00_E120_00_DEM.tif`
* Stored locally at: `data/raw/Copernicus_DSM_COG_10_N16_00_E120_00_DEM.tif`
* Browse / search the catalogue: <https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3>

## Recommended supplementary datasets (NOT auto-downloaded)

These are valuable for the thesis defense — calibration, validation,
discussion — but they cannot be downloaded autonomously because they sit
behind a portal / require manual selection per municipality.

### 1. MGB Geohazard Maps (Mines and Geosciences Bureau, DENR)
* Coverage: per municipality, 1:10,000 landslide and flood susceptibility
* Format: PDF / GIS layers
* Where: MGB Region 1 portal, *Per Municipality & Quadrants → Pangasinan →
  San Nicolas* — <https://region1.mgb.gov.ph/geology-and-geohazard-maps/1-10-000-geohazard-maps>
* MGB interactive Geohazard Portal:
  <https://experience.arcgis.com/experience/c48f83f81f1548bdb0a76c61638d52d6>
* Use it for: validating the susceptibility classes produced by the FS
  model, and as the “official baseline” map to compare against.

### 2. HazardHunterPH (DOST / Project NOAH / PHIVOLCS)
* Site-specific hazard reports for any pin in the Philippines (rain-induced
  landslide, ground shaking, storm surge, etc.).
* Where: <https://hazardhunter.georisk.gov.ph/map>
* Use it for: confirming Malico’s reported hazard exposure and pulling a
  one-page authoritative assessment to cite in the thesis.

### 3. PHIVOLCS landslide hazard maps
* Where: <https://www.phivolcs.dost.gov.ph/index.php/landslide/gisweb-landslide-hazard-maps>
* Use it for: regional-scale corroboration of the susceptibility model.

### 4. Higher-resolution LiDAR DEM (optional upgrade)
The Philippine DREAM / Phil-LiDAR programme produced 1-metre and 5-metre
LiDAR DEMs covering most of Luzon. They are administered by UP-TCAGP /
DOST-PCIEERD; requests are non-public. If a LiDAR DEM is obtained for
San Nicolas, drop the GeoTIFF into `data/raw/` and update the `dem.tile_url`
in `config.yaml` to point at the local file (rasterio accepts a path or a URL).
Everything downstream (slope, FS, runout, viewer) will pick up the
finer-resolution input with no other changes.

### 5. Climate / rainfall (optional, for trigger calibration)
* PAGASA daily rainfall stations near San Nicolas.
* CHIRPS satellite rainfall (open).
* Use it for: setting the groundwater-ratio `m` in the FS model to a wet-season
  worst case.

## Reference media (administrative / context only)

* PhilAtlas profile of Brgy. Malico — <https://www.philatlas.com/luzon/r01/pangasinan/san-nicolas/malico.html>
* Municipality of San Nicolas official site — <https://sannicolaspangasinan.gov.ph/malico/>
* Reported landslide events (news, for Discussion):
  <https://dagupan.bomboradyo.com/pangasinan-nueva-vizcaya-road-pansamantalang-sinara-dahil-sa-landslide/>
  and <https://rmn.ph/sunod-sunod-na-landslide-sa-san-nicolas-naitala-dahil-sa-diretsong-buhos-ng-ulan/>
