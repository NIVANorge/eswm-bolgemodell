"""Vectorize and clean classified polygons via GRASS GIS.

Vectorize pipeline (r.in.gdal → r.to.vect -s → v.generalize → v.out.ogr)
writes to paths.VRAW.  A separate merge step (v.clean rmarea) merges small
polygons into their largest neighbour and writes to paths.VMERGED for
prepare.subtract_land().
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from osgeo import gdal, osr

import waves.paths as paths

# Douglas-Peucker threshold: collapses 25 m raster staircase steps (~18 m max deviation).
SMOOTH_THRESHOLD: float = 12.0

# v.clean rmarea threshold in m²: polygons smaller than this are merged into their largest neighbour.
RMAREA_THRESHOLD: float = 500.0


def _run_inside_grass(input_raster: str, output_gpkg: str) -> None:
    import grass.script as gs  # noqa: PLC0415

    print("Importing raster into GRASS …")
    gs.run_command("r.in.gdal", input=input_raster, output="raster", overwrite=True)
    gs.run_command("g.region", raster="raster")

    print("Vectorizing (r.to.vect -s) …")
    gs.run_command(
        "r.to.vect",
        flags="s",
        input="raster",
        output="vector",
        type="area",
        column="class_int",
        overwrite=True,
    )

    print(f"Generalizing with Douglas (threshold={SMOOTH_THRESHOLD} m) …")
    gs.run_command(
        "v.generalize",
        input="vector",
        output="vector_smooth",
        method="douglas",
        threshold=SMOOTH_THRESHOLD,
        type="area",
        overwrite=True,
    )

    print(f"Exporting to {output_gpkg} …")
    gs.run_command(
        "v.out.ogr",
        input="vector_smooth",
        output=output_gpkg,
        output_layer="wave_exposure",
        format="GPKG",
        overwrite=True,
        quiet=True,
    )


def vectorize_raster(
    input_raster: Path | str = paths.CLASSIFIED_SIEVED,
    output_gpkg: Path | str = paths.RAW_VECTOR,
) -> Path:
    """Vectorize *input_raster* and write polygons to *output_gpkg*."""
    input_raster = Path(input_raster).resolve()
    output_gpkg = Path(output_gpkg).resolve()

    ds = gdal.Open(str(input_raster))
    epsg = osr.SpatialReference(ds.GetProjection()).GetAuthorityCode(None)
    ds = None

    print(f"Vectorizing {input_raster} (EPSG:{epsg}) …")

    subprocess.run(
        [
            "grass", "--tmp-project", f"EPSG:{epsg}", "--exec",
            sys.executable, str(Path(__file__).resolve()),
            "--inner", str(input_raster), str(output_gpkg),
        ],
        check=True,
    )

    print(f"Done → {output_gpkg}")
    return output_gpkg


def _merge_inside_grass(input_gpkg: str, output_gpkg: str, threshold: float) -> None:
    import grass.script as gs  # noqa: PLC0415

    print("Importing vector into GRASS …")
    gs.run_command("v.in.ogr", input=input_gpkg, output="raw_polygons", overwrite=True)

    print(f"Merging small areas (v.clean rmarea, threshold={threshold} m²) …")
    gs.run_command(
        "v.clean",
        input="raw_polygons",
        output="merged_polygons",
        tool="rmarea",
        threshold=threshold,
        type="area",
        overwrite=True,
    )

    print(f"Exporting to {output_gpkg} …")
    gs.run_command(
        "v.out.ogr",
        input="merged_polygons",
        output=output_gpkg,
        output_layer="wave_exposure",
        format="GPKG",
        overwrite=True,
        quiet=True,
    )


def merge_small_polygons(
    input_gpkg: Path | str = paths.RAW_VECTOR,
    output_gpkg: Path | str = paths.CLEANED_VECTOR,
    threshold: float = RMAREA_THRESHOLD,
) -> Path:
    """Merge polygons smaller than *threshold* m² into their largest neighbour.

    Uses GRASS ``v.clean tool=rmarea`` inside a temporary project.
    """
    from osgeo import ogr  # noqa: PLC0415

    input_gpkg = Path(input_gpkg).resolve()
    output_gpkg = Path(output_gpkg).resolve()

    ds = ogr.Open(str(input_gpkg))
    epsg = ds.GetLayer().GetSpatialRef().GetAuthorityCode(None)
    ds = None

    print(f"Merging small polygons (threshold={threshold} m²) in {input_gpkg} …")

    subprocess.run(
        [
            "grass", "--tmp-project", f"EPSG:{epsg}", "--exec",
            sys.executable, str(Path(__file__).resolve()),
            "--merge", str(input_gpkg), str(output_gpkg), str(threshold),
        ],
        check=True,
    )

    print(f"Done → {output_gpkg}")
    return output_gpkg


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--inner":
        _, _, input_raster, output_gpkg = sys.argv
        _run_inside_grass(input_raster, output_gpkg)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--merge":
        _, _, input_gpkg, output_gpkg, threshold = sys.argv
        _merge_inside_grass(input_gpkg, output_gpkg, float(threshold))
    else:
        vectorize_raster()
