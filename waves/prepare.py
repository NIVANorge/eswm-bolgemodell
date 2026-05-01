from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio as rio
from osgeo import gdal
from osgeo_utils import gdal_calc
from shapely.ops import unary_union
import numpy as np
from shapely.geometry import box

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
    raster_path = root_path / "niva" / "EswmRaster.tif"
    filled_path = root_path / "niva" / "EswmRaster_to_fill.tif"
    clipped_path = root_path / "niva" / "EswmRaster_filled_clipped.tif"
    cog_path = root_path / "niva" / "EswmRaster_filled_clipped_cog.tif"
    outline_mask_path = root_path / "niva" / "tmp_outline_mask.tif"
    tmp_gpkg = root_path / "niva" / "tmp_mv_outline.gpkg"
    tmp_coarse_path = root_path / "niva" / "tmp_coarse.tif"
    tmp_coarse_upsampled_path = root_path / "niva" / "tmp_coarse_upsampled.tif"
    tmp_coarse_merged_path = root_path / "niva" / "tmp_coarse_merged.tif"

    # Load and preprocess marine vanntyper
    aoi = gpd.read_parquet("gs://niva-geodata/MarintNaturKart/aux/aoi_from_marine_vanntyper.geo.parquet").to_crs(crs)
    aoi[["geometry"]].to_file(tmp_gpkg, driver="GPKG", layer="aoi")

    # Read source raster metadata
    with rio.open(raster_path) as src:
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

    # Copy raster with nodata=0 for in-place filling
    print("Copying raster for filling...")
    gdal.Translate(
        str(filled_path),
        str(raster_path),
        noData=0,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
    )

    ds = gdal.Open(str(filled_path), gdal.GA_Update)
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
        str(filled_path),
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
        A=str(filled_path),
        B=str(tmp_coarse_upsampled_path),
        type="Int32",
        NoDataValue=0,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )

    src_nodata = 0
    print("Clipping raster to outline...")
    gdal_calc.Calc(
        calc=f"numpy.where(A==0, {src_nodata}, B)",
        outfile=clipped_path,
        A=outline_mask_path,
        B=tmp_coarse_merged_path,
        type="Int32",
        NoDataValue=src_nodata,
        hideNoData=True,
        creation_options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER"],
        overwrite=True,
    )


    filled_cog_path = root_path / "niva" / "EswmRaster_filled_cog.tif"
    gdal.Translate(
        filled_cog_path,
        tmp_coarse_merged_path,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "BIGTIFF=IF_SAFER"
        ],
        format="COG"
    )
    print("Filled COG saved:", filled_cog_path)

    cog_path = root_path / "niva" / "EswmRaster_clipped_cog.tif"
    gdal.Translate(
        cog_path,
        clipped_path,
        creationOptions=[
            "COMPRESS=DEFLATE",
            "BIGTIFF=IF_SAFER"
        ],
        format="COG"
    )
    print("COG saved:", cog_path)
    outline_mask_path.unlink()
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


def subtract_land(
    land: gpd.GeoDataFrame,
    checkpoint_path: Path | str,
) -> gpd.GeoDataFrame:
    """Subtract land polygons from a wave exposure GeoDataFrame and save a checkpoint.

    Args:
        gdf: Wave exposure polygons (e.g. from polygonize step).
        land: Land polygons to subtract, in the same CRS as ``gdf``.
        checkpoint_path: Path where the result is saved as a GeoPackage.

    Returns:
        GeoDataFrame with land areas removed.
    """

    checkpoint_gpkg = waves.paths.CHECKPOINT_FILE + ".gpkg"
    checkpoint_idx = waves.paths.CHECKPOINT_FILE + ".idx"
    if checkpoint_gpkg.exists():
        print(f"Checkpoint already exists at {checkpoint_path}, loading...")
        gdf = gpd.read_file(str(checkpoint_path))
        with open(checkpoint_idx, "r") as f:
            idx = int(f.read().strip())
    else:
        idx = 0
        gdf = gpd.read_file(waves.paths.VRAW)
    grunnlinje = gpd.read_file(waves.paths.GRUNNLINJE)

    gdf = gpd.clip(gdf, grunnlinje)
    gdf = gdf[~gdf.is_empty].reset_index(drop=True)

    land  = gpd.read_file(waves.paths.LAND)

    n = len(land.geometry)
    for i, land_geom in enumerate(land.geometry[idx:], start=idx+1):
        print(f"Subtracting land geometry {i} of {n}")
        if land_geom.area > AREA_THRESHOLD:
            pieces = split_geometry_grid(land_geom, n=10)
            for j, piece in enumerate(pieces, 1):
                print(f"  Processing piece {j}/{len(pieces)} of {land_geom.area/10000:.2f} ha")
                mask = gdf.sindex.query(piece, predicate="intersects")
                if len(mask) > 0:
                    gdf.geometry.iloc[mask] = gdf.geometry.iloc[mask].difference(piece)
            save_checkpoint(gdf, checkpoint_gpkg)
            with open(checkpoint_idx, "w") as f:
                f.write(str(i-1))
        else:
            mask = gdf.sindex.query(land_geom, predicate="intersects")
            if len(mask) > 0:
                gdf.geometry.iloc[mask] = gdf.geometry.iloc[mask].difference(land_geom)

        if i % 10000 == 0:
            print(f"  Checkpoint at {i} – saving to {checkpoint_gpkg}")
            save_checkpoint(gdf, checkpoint_gpkg)
            with open(checkpoint_idx, "w") as f:
                f.write(str(i-1))

    gdf = gdf[~gdf.is_empty].reset_index(drop=True)
    save_checkpoint(gdf, checkpoint_gpkg)
    print(f"Final checkpoint saved: {checkpoint_gpkg}")
    gdf[~gdf.is_empty].to_file(waves.paths.CLIPPED, driver="GPKG")


def save_checkpoint(gdf: gpd.GeoDataFrame, checkpoint_path: Path | str):
    """Save a GeoDataFrame checkpoint."""
    gdf[~gdf.is_empty].to_file(checkpoint_path, driver="GPKG")