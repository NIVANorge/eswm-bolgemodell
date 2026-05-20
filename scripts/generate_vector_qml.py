"""Generate QGIS categorized-symbol QML files for EswmVectorDirect.gpkg.

Produces:
  stylesheets/boelgeeksponering_nin_basistrinn_norge_vektor_no.qml  (Norwegian labels)
  stylesheets/boelgeeksponering_nin_basistrinn_norge_vektor_en.qml  (English labels)

Labels and colors are read from the corresponding paletted raster QML files so
that vector and raster stylesheets stay in sync.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import waves

STYLESHEET_DIR = Path(__file__).resolve().parent.parent / "stylesheets"


def hex_to_rgba(h: str) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b},255"


def _read_raster_entries(lang: str) -> list[dict]:
    """Parse paletteEntry elements from the NIN basistrinn raster QML for *lang*."""
    raster_qml = STYLESHEET_DIR / f"boelgeeksponering_nin_basistrinn_norge_raster_{lang}.qml"
    root = ET.parse(raster_qml).getroot()
    return [
        {"value": e.attrib["value"], "color": e.attrib["color"], "label": e.attrib["label"]}
        for e in root.iter("paletteEntry")
    ]


def build_qml(lang: str) -> str:
    entries = _read_raster_entries(lang)

    categories_xml = ""
    symbols_xml = ""

    for i, entry in enumerate(entries):
        val = entry["value"]
        label = entry["label"]
        color_hex = entry["color"]
        color_rgba = hex_to_rgba(color_hex)

        categories_xml += (
            f'      <category value="{val}" label="{label}" '
            f'symbol="{i}" render="true"/>\n'
        )

        symbols_xml += f"""      <symbol name="{i}" alpha="1" clip_to_extent="1" type="fill" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleFill" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option value="3x:0,0,0,0,0,0" name="border_width_map_unit_scale" type="QString"/>
            <Option value="{color_rgba}" name="color" type="QString"/>
            <Option value="miter" name="joinstyle" type="QString"/>
            <Option value="0,0" name="offset" type="QString"/>
            <Option value="3x:0,0,0,0,0,0" name="offset_map_unit_scale" type="QString"/>
            <Option value="MM" name="offset_unit" type="QString"/>
            <Option value="35,35,35,255" name="outline_color" type="QString"/>
            <Option value="no" name="outline_style" type="QString"/>
            <Option value="0.26" name="outline_width" type="QString"/>
            <Option value="MM" name="outline_width_unit" type="QString"/>
            <Option value="solid" name="style" type="QString"/>
          </Option>
        </layer>
      </symbol>\n"""

    return f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis styleCategories="Symbology" version="3.44.7-Solothurn">
  <renderer-v2 forceraster="0" symbollevels="0" type="categorizedSymbol"
               enableorderby="0" referencescale="-1" attr="class_int">
    <categories>
{categories_xml.rstrip()}
    </categories>
    <symbols>
{symbols_xml.rstrip()}
    </symbols>
    <source-symbol>
      <symbol name="0" alpha="1" clip_to_extent="1" type="fill" force_rhr="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" name="name" type="QString"/>
            <Option name="properties"/>
            <Option value="collection" name="type" type="QString"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleFill" enabled="1" pass="0" locked="0">
          <Option type="Map">
            <Option value="solid" name="style" type="QString"/>
            <Option value="no" name="outline_style" type="QString"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
    <rotation/>
    <sizescale/>
    <data_defined_properties>
      <Option type="Map">
        <Option value="" name="name" type="QString"/>
        <Option name="properties"/>
        <Option value="collection" name="type" type="QString"/>
      </Option>
    </data_defined_properties>
  </renderer-v2>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
</qgis>
"""


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent.parent / "stylesheets"
    for lang in ("no", "en"):
        name = waves.paths.DIRECT_VECTOR.name.split(".")[0].replace("2004_25833_", "")
        path = out_dir / f"{name}_vektor_{lang}.qml"
        path.write_text(build_qml(lang), encoding="utf-8")
        print(f"Written: {path}")
