"""GIS-Based 3D Landslide Hazard Visualization Model - pipeline runner.

Usage (from the project root, with the project virtual environment):

    .venv\\Scripts\\python.exe run_pipeline.py            # full pipeline
    .venv\\Scripts\\python.exe run_pipeline.py --only runout
    .venv\\Scripts\\python.exe run_pipeline.py --from scenarios
    .venv\\Scripts\\python.exe run_pipeline.py --list

Default stages, in order:
    download  terrain  features  hydrology  scenarios  exposure  export  diagnostics
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime
from importlib.metadata import version as pkg_version, PackageNotFoundError
from pathlib import Path

from landslide.config import Config, OUTPUTS, ROOT
from landslide import (
    download, terrain, features, hydrology, imagery,
    susceptibility, runout, scenarios, exposure,
    export_web, diagnostics,
)

STAGES = [
    ("download",      download.run),
    ("terrain",       terrain.run),
    ("features",      features.run),
    ("hydrology",     hydrology.run),
    ("imagery",       imagery.run),
    ("scenarios",     scenarios.run),
    ("exposure",      exposure.run),
    ("export",        export_web.run),
    ("diagnostics",   diagnostics.run),
]
# Single-scenario stages remain available for debugging via --only.
STAGE_LOOKUP = dict(STAGES) | {
    "susceptibility": susceptibility.run,
    "runout": runout.run,
}


def write_manifest(cfg: Config, results: dict, duration_s: float) -> Path:
    """Write a reproducibility manifest of this pipeline run."""
    libs = {}
    for name in ("numpy", "scipy", "rasterio", "pillow", "requests",
                 "pyyaml", "matplotlib"):
        try:
            libs[name] = pkg_version(name)
        except PackageNotFoundError:
            libs[name] = None

    hashes = {}
    for p in sorted(OUTPUTS.iterdir()):
        if p.is_file():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            hashes[p.name] = {"sha256": h, "size": p.stat().st_size}

    manifest = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "duration_seconds": round(duration_s, 1),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "libraries": libs,
        "config_snapshot": dict(cfg),
        "stage_results": {k: v for k, v in results.items()
                          if isinstance(v, (dict, list, int, float, str, bool))},
        "output_hashes": hashes,
    }
    path = OUTPUTS / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Landslide hazard pipeline.")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--only", choices=list(STAGE_LOOKUP.keys()),
                    help="run a single stage")
    ap.add_argument("--from", dest="from_stage",
                    choices=[n for n, _ in STAGES],
                    help="run from this stage onward")
    ap.add_argument("--list", action="store_true",
                    help="list pipeline stages and exit")
    args = ap.parse_args()

    if args.list:
        for n, _ in STAGES:
            print(f"  {n}")
        return

    cfg = Config.load(args.config)
    names = [n for n, _ in STAGES]
    if args.only:
        selected = [(args.only, STAGE_LOOKUP[args.only])]
    elif args.from_stage:
        start = names.index(args.from_stage)
        selected = STAGES[start:]
    else:
        selected = STAGES

    print("\n" + "#" * 74)
    print(f"#  {cfg['project']['name']}")
    print(f"#  {cfg['project']['area']}")
    print("#" * 74)

    t0 = time.time()
    results = {}
    for name, fn in selected:
        results[name] = fn(cfg)
    duration = time.time() - t0

    manifest_path = write_manifest(cfg, results, duration)

    print("\n" + "#" * 74)
    print(f"#  PIPELINE COMPLETE in {duration:.1f} s")
    print(f"#  Manifest : {manifest_path.relative_to(ROOT)}")
    print(f"#  Viewer   : python -m http.server 8000  then  "
          "http://localhost:8000/viewer/")
    print("#" * 74 + "\n")


if __name__ == "__main__":
    main()
