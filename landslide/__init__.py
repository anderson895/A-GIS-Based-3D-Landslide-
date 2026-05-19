"""GIS-Based 3D Landslide Hazard Visualization Model - pipeline package.

Study area: Malico, San Nicolas, Pangasinan, Philippines.

Pipeline stages (in default execution order)
--------------------------------------------
download      fetch the Copernicus GLO-30 DEM tile from AWS Open Data
terrain       clip / reproject / slope / aspect / hillshade
features      download OSM buildings + roads (Overpass API)
hydrology     D8 flow direction + drainage accumulation
scenarios     run susceptibility + runout for 4 rainfall scenarios
exposure      count buildings + road kilometres in each scenario's runout
export_web    bundle viewer assets + render thesis figures
diagnostics   sanity-check every output

Utility modules (not in default order)
--------------------------------------
susceptibility   single-scenario FS (used internally by scenarios)
runout           single-scenario runout (used internally by scenarios)
lidar            optional LiDAR DEM preparation (manual invocation)
"""

__all__ = [
    "config", "download", "terrain", "features", "hydrology", "imagery",
    "susceptibility", "runout", "scenarios", "exposure",
    "export_web", "diagnostics", "lidar",
]
