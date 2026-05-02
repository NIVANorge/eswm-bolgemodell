"""Smooth zigzag (raster-derived staircase) polygon boundaries using GRASS GIS v.generalize.

Only boundaries detected as zigzag are smoothed; genuinely straight or curved lines are
left untouched.  Shared boundaries between adjacent polygons are smoothed together, so
topology is preserved throughout.

Usage (pixi task):
    pixi run smooth

Or directly:
    pixi run python -m waves.smooth
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import waves.paths as paths

# ── tuning knobs ──────────────────────────────────────────────────────────────
# Segment length (m) typical of raster-derived staircase edges.
RASTER_SEG_M: float = 25.0
# Tolerance: segments within this fraction of RASTER_SEG_M count as "raster" segments.
SEG_TOL: float = 0.10
# A polygon is "zigzag" when at least this share of its turns are 90° on raster-length segs.
ZIGZAG_RATIO_THRESH: float = 0.20
# Chaiken smoothing threshold (m) — just under half a cell so staircases collapse.
SMOOTH_THRESHOLD: float = 12.0
# Chaiken iterations — 3 passes give a naturally smooth curve.
SMOOTH_ITERATIONS: int = 3
# ─────────────────────────────────────────────────────────────────────────────

# ── GRASS inner entry point ───────────────────────────────────────────────────
# When the script is re-launched via `grass --tmp-project --exec`, GISBASE is set.
# All GRASS commands run here inside an already-initialised GRASS session.

def _run_inside_grass(input_gpkg: str, output_gpkg: str, cats_str: str) -> None:
    import sqlite3  # noqa: PLC0415

    import grass.script as gs  # noqa: PLC0415

    print("Importing vector into GRASS …")
    gs.run_command(
        "v.import",
        input=input_gpkg,
        output="polys",
        snap=1e-4,
        overwrite=True,
    )

    cats = [int(c) for c in cats_str.split(",")]
    n_cats = len(cats)
    print(
        f"Running v.generalize (chaiken, threshold={SMOOTH_THRESHOLD}m, "
        f"iterations={SMOOTH_ITERATIONS}) on {n_cats} features …"
    )

    # Mark zigzag areas directly in the SQLite attribute table.
    # Passing 100k+ cat IDs via the cats= argument hits the OS arg-list limit,
    # so we add a boolean column and use where="is_zigzag=1" instead.
    gs.run_command("v.db.addcolumn", map="polys", columns="is_zigzag INTEGER DEFAULT 0")

    env = gs.gisenv()
    db_path = (
        Path(env["GISDBASE"])
        / env["LOCATION_NAME"]
        / env["MAPSET"]
        / "sqlite"
        / "sqlite.db"
    )
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE zz_cats (cat INTEGER PRIMARY KEY)")
    cur.executemany("INSERT OR IGNORE INTO zz_cats VALUES (?)", [(c,) for c in cats])
    cur.execute("UPDATE polys SET is_zigzag=1 WHERE cat IN (SELECT cat FROM zz_cats)")
    conn.commit()
    conn.close()

    gs.run_command(
        "v.generalize",
        input="polys",
        output="polys_smooth",
        method="chaiken",
        threshold=SMOOTH_THRESHOLD,
        iterations=SMOOTH_ITERATIONS,
        layer=1,
        where="is_zigzag=1",
        type="area",
        overwrite=True,
    )

    print(f"Exporting to {output_gpkg} …")
    gs.run_command(
        "v.out.ogr",
        input="polys_smooth",
        output=output_gpkg,
        format="GPKG",
        overwrite=True,
        quiet=True,
    )


# ── zigzag detection (plain Python / geopandas, no GRASS) ────────────────────

def _zigzag_score(coords) -> float:
    """Return fraction of turns that are ~90° between two raster-length segments."""
    import numpy as np

    coords = np.asarray(coords)
    if len(coords) < 4:
        return 0.0
    segs = np.diff(coords[:-1], axis=0)  # drop closing vertex before diff
    lengths = np.linalg.norm(segs, axis=1)
    lo = RASTER_SEG_M * (1 - SEG_TOL)
    hi = RASTER_SEG_M * (1 + SEG_TOL)
    is_raster = (lengths >= lo) & (lengths <= hi)

    if len(segs) < 2:
        return 0.0

    dot = np.einsum("ij,ij->i", segs[:-1], segs[1:])
    mag = lengths[:-1] * lengths[1:]
    mag = np.where(mag == 0, 1e-12, mag)
    cos_a = np.clip(dot / mag, -1, 1)
    angles = np.degrees(np.arccos(cos_a))

    both_raster = is_raster[:-1] & is_raster[1:]
    near_90 = np.abs(angles - 90) < 10
    zigzag_turns = both_raster & near_90

    return float(zigzag_turns.sum()) / max(len(angles), 1)


def detect_zigzag_cats(gdf) -> list[int]:
    """Return 1-based row indices (GRASS cats) for features with zigzag boundaries."""
    zigzag_cats: list[int] = []
    n = len(gdf)
    step = max(1, n // 20)  # report every ~5%
    for i, row in enumerate(gdf.itertuples(), start=1):
        if i % step == 0 or i == n:
            print(f"  {i}/{n} ({100*i//n}%)", end="\r", flush=True)
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        scores = []
        for poly in polys:
            scores.append(_zigzag_score(poly.exterior.coords))
            for ring in poly.interiors:
                scores.append(_zigzag_score(ring.coords))
        if scores and max(scores) >= ZIGZAG_RATIO_THRESH:
            zigzag_cats.append(i)
    print()  # newline after \r progress
    return zigzag_cats


# ── public API ────────────────────────────────────────────────────────────────

def smooth_zigzag(
    input_gpkg: Path | str = paths.CHECKPOINT_FILE,
    output_gpkg: Path | str | None = None,
) -> Path:
    """Smooth zigzag boundaries in *input_gpkg* and write to *output_gpkg*.

    If *output_gpkg* is None the result is written next to the input with the
    suffix ``_smooth.gpkg``.

    Returns the path to the output file.
    """
    import geopandas as gpd

    input_gpkg = Path(input_gpkg).resolve()
    if output_gpkg is None:
        output_gpkg = input_gpkg.with_name(input_gpkg.stem + "_smooth.gpkg")
    output_gpkg = Path(output_gpkg).resolve()

    # ── 1. detect zigzag features ─────────────────────────────────────────────
    print(f"Reading {input_gpkg} …")
    gdf = gpd.read_file(input_gpkg)
    print(f"  {len(gdf)} features, CRS={gdf.crs}")

    print("Detecting zigzag boundaries …")
    zigzag_cats = detect_zigzag_cats(gdf)
    print(f"  {len(zigzag_cats)} / {len(gdf)} features have zigzag boundaries")

    if not zigzag_cats:
        print("No zigzag features found — copying input to output unchanged.")
        gdf.to_file(output_gpkg, driver="GPKG")
        return output_gpkg

    cats_str = ",".join(map(str, zigzag_cats))

    # ── 2. re-launch this script inside a temporary GRASS project ─────────────

    print("Launching GRASS session …")
    with tempfile.TemporaryDirectory(prefix="grass_smooth_out_") as tmpdir:
        # Embed the original 0-based row index as an attribute so it survives
        # GRASS topology reordering.  GRASS cats are assigned by centroid order
        # after snapping/cleaning and are NOT guaranteed to match geopandas rows.
        # Note: OGR strips leading underscores, so use "row_idx" not "_row_idx".
        staged = Path(tmpdir) / "staged.gpkg"
        gdf_staged = gdf.copy()
        gdf_staged["row_idx"] = range(len(gdf))
        gdf_staged.to_file(staged, driver="GPKG")

        grass_out = Path(tmpdir) / "grass_output.gpkg"
        cats_file = Path(tmpdir) / "cats.txt"
        cats_file.write_text(cats_str)

        cmd = [
            "grass",
            "--tmp-project", "EPSG:25833",
            "--exec",
            sys.executable, str(Path(__file__).resolve()),
            "--inner",
            str(staged),
            str(grass_out),
            str(cats_file),
        ]
        subprocess.run(cmd, check=True)

        # ── 3. dissolve GRASS output back to MultiPolygons by original row index ──
        print("Reassembling MultiPolygons …")
        grass_gdf = gpd.read_file(grass_out)

    # Dissolve individual polygons → MultiPolygon per original row (row_idx)
    smooth_geoms = grass_gdf.dissolve(by="row_idx")["geometry"]

    # Apply smoothed geometries back onto the original GeoDataFrame
    result = gdf.copy()
    n = len(smooth_geoms)
    step = max(1, n // 20)
    for j, (row_idx, smooth_geom) in enumerate(smooth_geoms.items(), start=1):
        if j % step == 0 or j == n:
            print(f"  {j}/{n} ({100*j//n}%)", end="\r", flush=True)
        if 0 <= row_idx < len(result):
            result.at[row_idx, "geometry"] = smooth_geom
    print()

    result = result[~result.geometry.is_empty].reset_index(drop=True)
    result.to_file(output_gpkg, driver="GPKG")

    print(f"Done → {output_gpkg}")
    return output_gpkg


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--inner":
        # Running inside GRASS (launched by smooth_zigzag via subprocess).
        _, _, input_gpkg, output_gpkg, cats_file = sys.argv
        cats_str = Path(cats_file).read_text().strip()
        _run_inside_grass(input_gpkg, output_gpkg, cats_str)
    else:
        smooth_zigzag()
