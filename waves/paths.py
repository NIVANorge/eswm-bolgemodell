from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent
_NIVA_DIR = ROOT_PATH / "niva"
AUX = ROOT_PATH / "aux"

SRC = _NIVA_DIR / "EswmRaster_filled_cog.tif"
"""Source raster (filled COG)"""
CLF = _NIVA_DIR / "EswmRaster_classified.tif"
"""Classified raster"""
SIE = _NIVA_DIR / "EswmRaster_classified_sieved.tif"
"""Sieved classified raster"""
VRAW = _NIVA_DIR / "Eswm_classified_raw.gpkg"
"""Raw classified vector"""
CLIPPED = _NIVA_DIR / "Eswm_clipped.gpkg"
"""Clipped vector"""
FIN = _NIVA_DIR / "Eswm_mapped_classified.gpkg"
"""Final mapped/classified vector"""
CHECKPOINT_FILE = _NIVA_DIR / "Eswm_land_subtract_checkpoint.gpkg"
"""Checkpoint for land subtraction"""
LAND = AUX / "land_union-from-NDH-DTM-Norge.gpkg"
"""Land polygons for subtraction from field"""
GRUNNLINJE = AUX / "grunnlinje_1nautisk_mil_polygon-Norge.gpkg"
"""Baseline grunnlinje polygon inside norway"""