"""Stage 1 - Download the Copernicus GLO-30 DEM tile.

The tile is hosted on the AWS Open Data public bucket, so no account or API
key is needed. The full 1deg x 1deg tile (N16 E120) is stored once in
data/raw/ and clipped to the AOI in the terrain stage. Keeping the raw tile
supports reproducibility: the analysis can be re-run offline at any time.
"""
from __future__ import annotations

from pathlib import Path
import requests

from .config import Config, RAW, banner


def raw_dem_path(cfg: Config) -> Path:
    """Local path of the downloaded DEM tile."""
    return RAW / Path(cfg["dem"]["tile_url"]).name


def run(cfg: Config) -> Path:
    banner("STAGE 1/5  -  Download DEM (Copernicus GLO-30)")
    url = cfg["dem"]["tile_url"]
    dest = raw_dem_path(cfg)

    if dest.exists() and dest.stat().st_size > 0:
        size_mb = dest.stat().st_size / 1e6
        print(f"  Already downloaded: {dest.name}  ({size_mb:.1f} MB)")
        return dest

    print(f"  Source : {url}")
    print(f"  Target : {dest}")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r  Downloading... {pct:5.1f}%  "
                          f"({done/1e6:6.1f} / {total/1e6:.1f} MB)", end="")
        print()
    print(f"  Done. Saved {dest.stat().st_size/1e6:.1f} MB.")
    return dest


if __name__ == "__main__":
    run(Config.load())
