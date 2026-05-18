from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio
from osgeo import gdal
from osgeo_utils import gdal_calc
from shapely.ops import unary_union
import numpy as np
from shapely.geometry import box, MultiPolygon, Polygon
from time import time

import waves

AREA_THRESHOLD = 37_611_003

def bolge_model_data():
    """Prepare bølgemodell (wave exposure) raster data for processing.

    Clips the wave exposure raster (EswmRaster.tif) to the marine vanntyper outline,
    fills nodata (0) values inside the outline and in bølgeeksponert areas, and saves
    the result as a Cloud Optimized GeoTIFF (COG).

    Bølgeeksponeringsmodellen er utviklet av Norsk institutt for vannforskning (NIVA), tilgjengeliggjort som en del av kartgrunnlaget beskrevet i Bekkby m.fl. (2025
    Input raster expected at:  <root_path>/niva/EswmRaster.tif
    Outputs written to:
        <root_path>/niva/EswmRaster_filled_cog.tif         (filled, before clipping)
        <root_path>/niva/EswmRaster_clipped_cog.tif        (filled and clipped to outline)

    """

    crs = "EPSG:25833"
    gdal.UseExceptions()

    root_path = Path(__file__).resolve().parent.parent
    tmp_filled_path = root_path / "niva" / "EswmRaster_to_fill.tif"
    tmp_clipped_path = root_path / "niva" / "EswmRaster_filled_clipped.tif"
    outline_mask_path = root_path / "niva" / "tmp_outline_mask.tif"
    tmp_gpkg = root_path / "niva" / "tmp_mv_outline.gpkg"
    tmp_coarse_path = root_path / "niva" / "tmp_coarse.tif"
    tmp_coarse_upsampled_path = root_path / "niva" / "tmp_coarse_upsampled.tif"
    tmp_coarse_merged_path = root_path / "niva" / "tmp_coarse_merged.tif"
    tmp_aoi_proximity_path = root_path / "niva" / "tmp_aoi_proximity.tif"
    tmp_filled_padded_path = root_path / "niva" / "tmp_filled_padded.tif"

    # Load and preprocess marine vanntyper
    aoi = gpd.read_parquet("gs://niva-geodata/eswm/aoi_from_marine_vanntyper.geo.parquet").to_crs(crs)
    aoi[["geometry"]].to_file(tmp_gpkg, driver="GPKG", layer="aoi")

    # Read source raster metadata
    with rio.open(waves.paths.SOURCE) as src:
        b = src.bounds
        res_x, res_y = src.res
        src_width, src_height = src.width, src.height

    rasterize_opts = dict(
        burnValues=[1],
        outputType=gdal.GDT_Byte,
        initValues=[0],
        noData=255,
        outputBounds=[b.left, b.bottom, b.right, b.top],
        xRes=res_x,
        yRes=res_y,
        allTouched=True,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        callback=gdal.TermProgress_nocb,
    )

    print("Rasterizing aoi mask...")
    ds = gdal.Rasterize(str(outline_mask_path), str(tmp_gpkg), layers=["aoi"], **rasterize_opts)
    assert ds is not None, "gdal.Rasterize failed for aoi"
    ds = None
    print("AOI mask ready:", outline_mask_path)

    print("Computing AOI proximity for padded clip...")
    ds_aoi = gdal.Open(str(outline_mask_path))
    driver = gdal.GetDriverByName("GTiff")
    ds_prox = driver.Create(
        str(tmp_aoi_proximity_path),
        ds_aoi.RasterXSize, ds_aoi.RasterYSize, 1, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )
    ds_prox.SetGeoTransform(ds_aoi.GetGeoTransform())
    ds_prox.SetProjection(ds_aoi.GetProjection())
    gdal.ComputeProximity(
        ds_aoi.GetRasterBand(1), ds_prox.GetRasterBand(1),
        ["VALUES=1", "DISTUNITS=PIXEL"],
        callback=gdal.TermProgress_nocb,
    )
    ds_prox.FlushCache()
    ds_prox = None
    ds_aoi = None
    print("AOI proximity ready:", tmp_aoi_proximity_path)

    # Copy raster with nodata=0 for in-place filling
    print("Copying raster for filling...")
    gdal.Translate(
        str(tmp_filled_path),
        str(waves.paths.SOURCE),
        noData=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )

    ds = gdal.Open(str(tmp_filled_path), gdal.GA_Update)
    band = ds.GetRasterBand(1)

    print("Filling nodata (0) inside outline...")
    gdal.FillNodata(band, maskBand=band.GetMaskBand(), maxSearchDist=200, smoothingIterations=0, callback=gdal.TermProgress_nocb)
    ds.FlushCache()
    ds = None

    # Coarse fill: downsample → FillNodata → upsample → merge back.
    downsample_factor = 20
    print(f"Coarse fill: downsampling {downsample_factor}× ...")
    gdal.Warp(
        str(tmp_coarse_path),
        str(tmp_filled_path),
        xRes=res_x * downsample_factor,
        yRes=res_y * downsample_factor,
        resampleAlg=gdal.GRA_Average,
        srcNodata=0,
        dstNodata=0,
        creationOptions=["COMPRESS=DEFLATE"],
    )

    ds_coarse = gdal.Open(str(tmp_coarse_path), gdal.GA_Update)
    band_coarse = ds_coarse.GetRasterBand(1)
    print("Coarse fill: FillNodata at low resolution...")
    gdal.FillNodata(band_coarse, maskBand=band_coarse.GetMaskBand(), maxSearchDist=500, smoothingIterations=0, callback=gdal.TermProgress_nocb)
    ds_coarse.FlushCache()
    ds_coarse = None

    print("Coarse fill: upsampling back to original resolution...")
    gdal.Warp(
        str(tmp_coarse_upsampled_path),
        str(tmp_coarse_path),
        width=src_width,
        height=src_height,
        outputBounds=[b.left, b.bottom, b.right, b.top],
        resampleAlg=gdal.GRA_Bilinear,
        srcNodata=0,
        dstNodata=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )

    print("Coarse fill: merging into raster (remaining nodata only)...")
    gdal_calc.Calc(
        calc="numpy.where(A==0, B, A)",
        outfile=str(tmp_coarse_merged_path),
        A=str(tmp_filled_path),
        B=str(tmp_coarse_upsampled_path),
        type="Int32",
        NoDataValue=0,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )


    print("Clipping filled raster to AOI + 2-pixel padding...")
    gdal_calc.Calc(
        calc="numpy.where(B <= 2, A, 0)",
        outfile=str(tmp_filled_padded_path),
        A=str(tmp_coarse_merged_path),
        B=str(tmp_aoi_proximity_path),
        type="Int32",
        NoDataValue=0,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )

    gdal.Translate(
         waves.paths.FILLED_COG,
        tmp_filled_padded_path,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "BIGTIFF=IF_SAFER"
        ],
        format="COG"
    )
    print("Filled COG saved:", waves.paths.FILLED_COG)

    src_nodata = 0
    print("Clipping raster to outline...")
    gdal_calc.Calc(
        calc=f"numpy.where(A==0, {src_nodata}, B)",
        outfile=tmp_clipped_path,
        A=outline_mask_path,
        B=tmp_coarse_merged_path,
        type="Int32",
        NoDataValue=src_nodata,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )
    gdal.Translate(
        waves.paths.FILLED_CLIPPED_COG,
        tmp_clipped_path,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "BIGTIFF=IF_SAFER"
        ],
        format="COG"
    )
    print("COG saved:", waves.paths.FILLED_CLIPPED_COG)
    outline_mask_path.unlink()
    tmp_aoi_proximity_path.unlink(missing_ok=True)
    tmp_filled_padded_path.unlink(missing_ok=True)
    tmp_filled_path.unlink(missing_ok=True)
    tmp_clipped_path.unlink(missing_ok=True)
    tmp_coarse_path.unlink(missing_ok=True)
    tmp_coarse_upsampled_path.unlink(missing_ok=True)
    tmp_coarse_merged_path.unlink(missing_ok=True)


def split_geometry_grid(geom, n=10):
    """Split geometry into n x n grid cells."""
    minx, miny, maxx, maxy = geom.bounds
    xs = np.linspace(minx, maxx, n + 1)
    ys = np.linspace(miny, maxy, n + 1)
    pieces = []
    for i in range(n):
        for j in range(n):
            print(f"  Creating grid cell {i * n + j + 1}/{n * n}")
            cell = box(xs[i], ys[j], xs[i + 1], ys[j + 1])
            piece = geom.intersection(cell)
            if not piece.is_empty:
                pieces.append(piece)
    return pieces


def _to_multipolygon(geom):
    """Normalize a geometry to MultiPolygon, extracting only polygon parts."""
    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    if not hasattr(geom, "geoms"):
        # LineString, Point, etc. — no polygon content, treat as empty
        return Polygon()
    # GeometryCollection: extract polygon parts
    polys = []
    for part in geom.geoms:
        if isinstance(part, Polygon):
            polys.append(part)
        elif isinstance(part, MultiPolygon):
            polys.extend(part.geoms)
    return MultiPolygon(polys) if polys else Polygon()


def subtract_land():
    """Subtract land polygons from a wave exposure GeoDataFrame and save a checkpoint.

    """
    crs = "EPSG:25833"
    checkpoint_gpkg = waves.paths.CHECKPOINT_FILE
    checkpoint_idx = waves.paths.CHECKPOINT_FILE.with_suffix(".idx")
    if checkpoint_gpkg.exists():
        print(f"Checkpoint already exists at {checkpoint_gpkg}, loading...")
        gdf = gpd.read_file(str(checkpoint_gpkg))
        with open(checkpoint_idx, "r") as f:
            idx = int(f.read().strip())
    else:
        idx = 0
        gdf = gpd.read_file(waves.paths.CLEANED_VECTOR)

    gdf = gdf.to_crs(crs)

    print(f"Starting land subtraction from geometry with {len(gdf)} features, starting at index {idx}...")
    land  = gpd.read_file(waves.paths.LAND, layer="landareal")

    time_start = time()
    n = len(land.geometry)
    for i, land_geom in enumerate(land.geometry[idx:], start=idx+1):
        if i % 200 == 0:
            print(f"Subtracting land geometry {i} of {n}")
            time_elapsed = (time() - time_start) / 60
            print(f"  Time elapsed: {time_elapsed:.2f} minutes")
            n_pr_m = (i-idx)/(time_elapsed)
            print(f"{n_pr_m:.1f} geometries/minute")
            n_remaining = n - i
            print(f"  Estimated time remaining: {n_remaining / n_pr_m:.2f} minutes")
        mask = gdf.geometry.intersects(land_geom)
        if mask.any():
            gdf.loc[mask, "geometry"] = gdf.loc[mask, "geometry"].difference(land_geom)
            gdf["geometry"] = gdf["geometry"].apply(_to_multipolygon)
        if i % 10000 == 0:
            print(f"  Checkpoint at {i} – saving to {checkpoint_gpkg}")
            save_checkpoint(gdf, checkpoint_gpkg)
            with open(checkpoint_idx, "w") as f:
                f.write(str(i-1))

    gdf = gdf[~gdf.is_empty].reset_index(drop=True)
    save_checkpoint(gdf, checkpoint_gpkg)
    print(f"Final checkpoint saved: {checkpoint_gpkg}")
    gdf[~gdf.is_empty].to_file(waves.paths.LAND_CLIPPED_VECTOR, driver="GPKG")


def save_checkpoint(gdf: gpd.GeoDataFrame, checkpoint_path: Path | str):
    """Save a GeoDataFrame checkpoint."""
    checkpoint_path = Path(checkpoint_path)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
    gdf[~gdf.is_empty].to_file(checkpoint_path, driver="GPKG")