"""Generate QGIS categorized-symbol QML files for EswmVectorDirect.gpkg.

Produces:
  stylesheets/EswmVectorDirectNO.qml  (Norwegian labels)
  stylesheets/EswmVectorDirectEN.qml  (English labels)

Colors match the existing raster QML stylesheets.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from waves.classify import CLASSES

# Same color sequence as the raster QMLs (classes 1–9 only)
COLORS_HEX = [
    "#EDF8FB",  # 1 – minimal
    "#B2E2E2",  # 2 – svært beskyttet
    "#66C2A4",  # 3 – temmelig beskyttet
    "#238B45",  # 4 – litt beskyttet
    "#FFFFB2",  # 5 – svakt eksponert
    "#FECC5C",  # 6 – litt eksponert
    "#FD8D3C",  # 7 – temmelig eksponert
    "#F03B20",  # 8 – svært eksponert
    "#BD0026",  # 9 – ekstremt eksponert
]


def hex_to_rgba(h: str) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b},255"


def build_qml(lang: str) -> str:
    label_col = "navn_no" if lang == "NO" else "navn_en"
    rows = CLASSES[CLASSES["class_int"] <= 9][["class_int", "trinn", label_col]].to_dict("records")

    categories_xml = ""
    symbols_xml = ""

    for i, row in enumerate(rows):
        val = row["class_int"]
        trinn = row["trinn"]
        label = f"LM-VF_{trinn} \u2014 {row[label_col].capitalize()}"
        color_hex = COLORS_HEX[i]
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
    for lang in ("NO", "EN"):
        path = out_dir / f"EswmVectorDirectClasses{lang}.qml"
        path.write_text(build_qml(lang), encoding="utf-8")
        print(f"Written: {path}")
