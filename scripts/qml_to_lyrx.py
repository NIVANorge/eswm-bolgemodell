"""Convert QGIS paletted raster styles (.qml) to ArcGIS Pro layer files (.lyrx)."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path


def hex_to_rgb(hex_color: str) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)]


def parse_qml(qml_path: Path) -> list[dict]:
    """Extract palette entries from a QGIS paletted raster QML file."""
    tree = ET.parse(qml_path)
    root = tree.getroot()
    entries = []
    for entry in root.iter("paletteEntry"):
        entries.append(
            {
                "value": entry.attrib["value"],
                "color": entry.attrib["color"],
                "label": entry.attrib["label"],
            }
        )
    return entries


def build_lyrx(name: str, entries: list[dict]) -> dict:
    """Build an ArcGIS Pro CIM layer document (lyrx) for a unique value raster."""
    classes = []
    for entry in entries:
        r, g, b = hex_to_rgb(entry["color"])
        classes.append(
            {
                "type": "CIMRasterUniqueValueClass",
                "values": [entry["value"]],
                "label": entry["label"],
                "color": {"type": "CIMRGBColor", "values": [r, g, b, 100]},
                "visible": True,
            }
        )

    return {
        "type": "CIMLayerDocument",
        "version": "3.2.0",
        "build": 36057,
        "layers": [f"CIMPATH=raster/{name}.json"],
        "layerDefinitions": [
            {
                "type": "CIMRasterLayer",
                "name": name,
                "uRI": f"CIMPATH=raster/{name}.json",
                "visibility": True,
                "showPopups": True,
                "colorizer": {
                    "type": "CIMRasterUniqueValueColorizer",
                    "defaultColor": {
                        "type": "CIMRGBColor",
                        "values": [130, 130, 130, 100],
                    },
                    "defaultLabel": "<all other values>",
                    "fieldName": "Value",
                    "groups": [
                        {
                            "type": "CIMRasterUniqueValueGroup",
                            "classes": classes,
                            "heading": "Value",
                        }
                    ],
                    "useDefaultColor": False,
                },
            }
        ],
    }


def convert(qml_path: Path) -> Path:
    name = qml_path.stem
    entries = parse_qml(qml_path)
    doc = build_lyrx(name, entries)
    lyrx_path = qml_path.with_suffix(".lyrx")
    lyrx_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return lyrx_path


if __name__ == "__main__":
    stylesheet_dir = Path(__file__).parent.parent / "stylesheets"
    for qml_file in sorted(stylesheet_dir.glob("*.qml")):
        out = convert(qml_file)
        print(f"{qml_file.name} → {out.name}")
