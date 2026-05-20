# 3D viewer screenshots

Drop PNG screenshots here using the exact filenames listed below. After
adding/replacing any file, re-run:

```powershell
.\.venv\Scripts\python.exe make_docx.py
```

…and the new images will appear in Section 11.B of
`docs/Development_Documentation.docx`. Missing files render as orange
`[SCREENSHOT PLACEHOLDER ...]` blocks, so it's obvious what is left to fill.

## How to capture

Open the viewer (`http://localhost:8000/viewer/` or the Vercel URL),
configure the controls listed for each slot, then click the **Screenshot**
button in the panel (it downloads a same-resolution PNG). Save it here with
the matching filename.

## Filename map

| Filename                              | Viewer controls                                              |
|---------------------------------------|--------------------------------------------------------------|
| `screenshot_oblique_plain.png`        | Layer: Plain (white)   ·  Trees: Hidden  ·  Preset: Oblique  |
| `screenshot_hillshade.png`            | Layer: Hillshade       ·  Preset: Oblique                    |
| `screenshot_slope.png`                | Layer: Slope           ·  Preset: Oblique                    |
| `screenshot_channels.png`             | Layer: Channels        ·  Preset: Oblique                    |
| `screenshot_susceptibility_wet.png`   | Layer: Susceptibility  ·  Scenario: Wet      ·  Oblique      |
| `screenshot_susceptibility_extreme.png` | Layer: Susceptibility ·  Scenario: Extreme  ·  Oblique      |
| `screenshot_runout_extreme.png`       | Layer: Runout          ·  Scenario: Extreme  ·  Oblique      |
| `screenshot_satellite.png`            | Layer: Satellite       ·  Preset: Oblique                    |
| `screenshot_boundaries.png`           | Boundaries toggle: ON  ·  Preset: Oblique                    |
| `screenshot_minimap.png`              | Minimap toggle: ON     ·  (internet needed for tiles)        |
| `screenshot_top_down.png`             | Layer: Susceptibility  ·  Scenario: Wet  ·  Preset: Top-down |
| `screenshot_simulation.png`           | Hit **Play** under "Live Runout Simulation" — capture mid-frame |
