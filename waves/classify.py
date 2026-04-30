from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from osgeo import gdal, ogr, osr
from shapely.geometry import MultiPolygon, Polygon
import topojson

gdal.UseExceptions()

# ── NiN 3 classification table ────────────────────────────────────────────────

CLASSES = pd.DataFrame(
    {
        "class_int": range(1, 11),
        "trinn": ["0", "a", "b", "c", "d", "e", "f", "g", "h", "y"],
        "navn_no": [
            "minimal vannforstyrrelsesintensitet",
            "svært beskyttet",
            "temmelig beskyttet",
            "litt beskyttet",
            "svakt eksponert",
            "litt eksponert",
            "temmelig eksponert",
            "svært eksponert",
            "ekstremt eksponert",
            "disruptivt eksponert",
        ],
        "navn_en": [
            "still water",
            "very sheltered",
            "moderately sheltered",
            "slightly sheltered",
            "weakly sheltered",
            "slightly exposed",
            "moderately exposed",
            "very exposed",
            "extremely exposed",
            "disruptively exposed",
        ],
        # Lower bound (inclusive), upper bound (exclusive); None = no bound
        "swm_lower": [None, 1_200, 4_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 2_000_000, 4_000_000],
        "swm_upper": [1_200, 4_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 2_000_000, 4_000_000, None],
    }
)

# Breakpoints for numpy.digitize (right=False: bins[i] <= x < bins[i+1])
SWM_BINS = [1_200, 4_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 2_000_000, 4_000_000]


# ── Pure classification function (testable) ───────────────────────────────────


def classify_swm_values(data: np.ndarray, nodata: int = 0) -> np.ndarray:
    """Map SWM raster values to NiN 3 class integers 1–10.

    Nodata pixels (value == nodata) are returned as 0 in the output.
    Values < 1 200 → 1, ≥ 1 200 < 4 000 → 2, …, ≥ 4 000 000 → 10.
    """
    mask = data == nodata
    classified = (np.digitize(data, SWM_BINS) + 1).astype(np.uint8)
    classified[mask] = 0
    return classified


# ── GDAL raster operations ────────────────────────────────────────────────────


def reclassify_raster(src_path: Path | str, dst_path: Path | str, block_size: int = 4096) -> None:
    """Reclassify an SWM raster to NiN 3 class integers (1–10, nodata=0).

    Processes the large raster in blocks to avoid loading it into memory.

    Args:
        src_path: Path to input SWM raster (Int32, nodata=0).
        dst_path: Path for output classified raster (Byte, nodata=0).
        block_size: Block size in pixels for tiled processing.
    """
    src_ds = gdal.Open(str(src_path), gdal.GA_ReadOnly)
    src_band = src_ds.GetRasterBand(1)
    nodata_val = int(src_band.GetNoDataValue() or 0)

    xsize, ysize = src_ds.RasterXSize, src_ds.RasterYSize

    driver = gdal.GetDriverByName("GTiff")
    dst_ds = driver.Create(
        str(dst_path),
        xsize,
        ysize,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "BIGTIFF=IF_SAFER"],
    )
    dst_ds.SetGeoTransform(src_ds.GetGeoTransform())
    dst_ds.SetProjection(src_ds.GetProjection())
    dst_band = dst_ds.GetRasterBand(1)
    dst_band.SetNoDataValue(0)

    n_x = (xsize + block_size - 1) // block_size
    n_y = (ysize + block_size - 1) // block_size
    total = n_x * n_y
    done = 0

    for y0 in range(0, ysize, block_size):
        bh = min(block_size, ysize - y0)
        for x0 in range(0, xsize, block_size):
            bw = min(block_size, xsize - x0)
            data = src_band.ReadAsArray(x0, y0, bw, bh)
            dst_band.WriteArray(classify_swm_values(data, nodata_val), x0, y0)
            done += 1
            gdal.TermProgress_nocb(done / total)

    dst_band.FlushCache()
    dst_ds = src_ds = None


def sieve_filter(
    src_path: Path | str,
    dst_path: Path | str,
    threshold: int = 1,
    connectedness: int = 8,
) -> None:
    """Remove isolated pixel regions from a classified raster.

    Args:
        src_path: Input classified raster.
        dst_path: Output sieved raster.
        threshold: Regions with ≤ threshold pixels are removed.
        connectedness: 4 or 8 pixel connectivity.
    """
    src_ds = gdal.Open(str(src_path), gdal.GA_ReadOnly)
    src_band = src_ds.GetRasterBand(1)

    driver = gdal.GetDriverByName("GTiff")
    print("Copying classified raster...")
    dst_ds = driver.CreateCopy(
        str(dst_path),
        src_ds,
        options=["COMPRESS=LZW", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "BIGTIFF=IF_SAFER"],
        callback=gdal.TermProgress_nocb,
    )
    dst_band = dst_ds.GetRasterBand(1)

    print(f"Applying sieve filter (threshold={threshold}, connectedness={connectedness})...")
    gdal.SieveFilter(src_band, None, dst_band, threshold=threshold, connectedness=connectedness, callback=gdal.TermProgress_nocb)

    dst_band.FlushCache()
    dst_ds = src_ds = None


def polygonize(src_path: Path | str, dst_path: Path | str) -> None:
    """Convert classified raster to vector polygons (GeoPackage).

    The output layer is named ``wave_exposure`` with a ``class_int`` field.

    Args:
        src_path: Input classified raster (nodata=0 pixels are excluded).
        dst_path: Output GeoPackage path.
    """
    src_ds = gdal.Open(str(src_path), gdal.GA_ReadOnly)
    src_band = src_ds.GetRasterBand(1)
    mask_band = src_band.GetMaskBand()

    ogr_driver = ogr.GetDriverByName("GPKG")
    dst_path = Path(dst_path)
    if dst_path.exists():
        ogr_driver.DeleteDataSource(str(dst_path))
    vec_ds = ogr_driver.CreateDataSource(str(dst_path))

    srs = osr.SpatialReference()
    srs.ImportFromWkt(src_ds.GetProjection())
    layer = vec_ds.CreateLayer("wave_exposure", srs=srs, geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("class_int", ogr.OFTInteger))

    print("Polygonizing (this may take a while)...")
    gdal.Polygonize(src_band, mask_band, layer, 0, callback=gdal.TermProgress_nocb)

    vec_ds = src_ds = None


def clip_to_aoi(src_path: Path | str, dst_path: Path | str, aoi_path: str) -> None:
    """Clip a polygonized GeoPackage to an AOI boundary using GDAL.

    Uses ``gdal.VectorTranslate`` (C++) for fast clipping.  GCS paths
    (``gs://``) are automatically converted to GDAL's ``/vsigs/`` prefix so
    the AOI parquet can be read directly without downloading it first.

    Args:
        src_path: Input GeoPackage (``wave_exposure`` layer).
        dst_path: Output GeoPackage path.
        aoi_path: Path or URI to the AOI GeoParquet (local or ``gs://``).
    """
    root_path = Path(__file__).resolve().parent.parent
 
    tmp_gpkg = root_path / "niva" / "tmp_mv_outline.gpkg"

    gpd.read_parquet(aoi_path).to_file(tmp_gpkg, driver="GPKG", layer="aoi")
    ds = gdal.VectorTranslate(
        str(dst_path),
        str(src_path),
        options=gdal.VectorTranslateOptions(
            clipSrc=str(tmp_gpkg),
            callback=gdal.TermProgress_nocb,
        ),
    )
    ds = None
    tmp_gpkg.unlink()
    print(f"Clipped vectors saved: {dst_path}")


# ── Geometry smoothing ────────────────────────────────────────────────────────


def _smooth_ring(coords: list, iters: int = 3) -> list:
    """Chaikin corner-cutting smoothing for a single closed ring."""
    pts = list(coords)
    for _ in range(iters):
        new = []
        n = len(pts) - 1  # last == first for a closed ring
        for i in range(n):
            p0, p1 = pts[i], pts[(i + 1) % n]
            new.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            new.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        new.append(new[0])
        pts = new
    return pts


def smooth_geometry(geom, iters: int = 3):
    """Apply Chaikin smoothing to all rings of a Polygon or MultiPolygon."""
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == "Polygon":
        ext = _smooth_ring(list(geom.exterior.coords), iters)
        holes = [_smooth_ring(list(r.coords), iters) for r in geom.interiors]
        return Polygon(ext, holes)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([smooth_geometry(p, iters) for p in geom.geoms])
    return geom


def smooth_vectors(
    src_path: Path | str,
    dst_path: Path | str,
    simplify_tolerance: float = 25.0,
    aoi_path: str | None = None,
) -> gpd.GeoDataFrame:
    """Topology-aware simplification of raw polygonized vectors, with optional AOI clipping.

    Uses ``topojson`` to simplify shared polygon edges *once*, so adjacent
    polygons remain perfectly aligned with no gaps or overlaps.

    Args:
        src_path: Input GeoPackage (``wave_exposure`` layer with ``class_int``).
        dst_path: Output GeoPackage path.
        simplify_tolerance: Douglas-Peucker epsilon in CRS units (default 25 m
            matches one 25 m raster pixel).

    Returns:
        The simplified GeoDataFrame (also written to ``dst_path``).
    """

    print("Reading raw polygons...")
    gdf = gpd.read_file(src_path, layer="wave_exposure")

    # Topology-aware simplification: shared edges are processed once so
    # adjacent class polygons remain perfectly aligned (no gaps).
    print(f"Topology-aware simplification (tolerance={simplify_tolerance} m)...")
    topo = topojson.Topology(gdf, prequantize=False)
    gdf = topo.toposimplify(
        simplify_tolerance,
        simplify_with="dp",
        prevent_oversimplify=True,
    ).to_gdf()

    gdf.to_file(str(dst_path), driver="GPKG", layer="wave_exposure")
    print(f"Smoothed vectors saved: {dst_path}")
    return gdf
