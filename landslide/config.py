"""Configuration loading and shared project paths."""
from __future__ import annotations

from pathlib import Path
import yaml

# Project root = parent of this package directory.
ROOT = Path(__file__).resolve().parent.parent

# Standard directories (created on import so every stage can rely on them).
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
OUTPUTS = DATA / "outputs"
VIEWER = ROOT / "viewer"
DOCS = ROOT / "docs"
FIGURES = DOCS / "figures"

for _d in (RAW, PROCESSED, OUTPUTS, VIEWER, FIGURES):
    _d.mkdir(parents=True, exist_ok=True)


class Config(dict):
    """Dict-like wrapper around config.yaml with attribute-style section access."""

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        path = Path(path) if path else ROOT / "config.yaml"
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(data)

    @property
    def aoi_bounds(self) -> tuple[float, float, float, float]:
        """AOI as (min_lon, min_lat, max_lon, max_lat) in WGS84 degrees."""
        a = self["aoi"]
        return (a["min_lon"], a["min_lat"], a["max_lon"], a["max_lat"])


def banner(stage: str) -> None:
    """Print a consistent stage header to the console."""
    print("\n" + "=" * 72)
    print(f"  {stage}")
    print("=" * 72)


def update_meta(extra: dict) -> None:
    """Merge a dict of stage results into data/processed/meta.json."""
    import json
    path = PROCESSED / "meta.json"
    meta = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    meta.update(extra)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
