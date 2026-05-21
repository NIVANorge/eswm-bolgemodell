"""Convert QGIS raster and vector styles (.qml) to ArcGIS Pro layer files (.lyrx).

Supported QML renderer types:
- paletteEntry       → CIMRasterUniqueValueColorizer   (paletted/classified raster)
- singlebandpseudocolor → CIMRasterClassifyColorizer  (continuous/discrete raster)
- categorizedSymbol  → CIMUniqueValueRenderer           (vector polygon layer)
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path


def hex_to_rgb(hex_color: str) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)]


def _css_to_rgb(css_color: str) -> list[int]:
    """Parse a QGIS 'R,G,B,A' color string and return [R, G, B]."""
    parts = css_color.split(",")
    return [int(parts[0]), int(parts[1]), int(parts[2])]


def detect_qml_type(qml_path: Path) -> str:
    """Return 'paletted_raster', 'continuous_raster', or 'vector'."""
    tree = ET.parse(qml_path)
    root = tree.getroot()
    if root.find(".//paletteEntry") is not None:
        return "paletted_raster"
    renderer = root.find(".//renderer-v2")
    if renderer is not None and renderer.attrib.get("type") == "categorizedSymbol":
        return "vector"
    if root.find(".//colorrampshader") is not None:
        return "continuous_raster"
    raise ValueError(f"Unrecognised QML renderer type in {qml_path}")


# ---------------------------------------------------------------------------
# Paletted raster
# ---------------------------------------------------------------------------


def parse_paletted_raster(qml_path: Path) -> list[dict]:
    tree = ET.parse(qml_path)
    root = tree.getroot()
    return [
        {
            "value": e.attrib["value"],
            "color": e.attrib["color"],
            "label": e.attrib["label"],
        }
        for e in root.iter("paletteEntry")
    ]


def build_lyrx_paletted_raster(name: str, entries: list[dict]) -> dict:
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
                    "defaultColor": {"type": "CIMRGBColor", "values": [130, 130, 130, 100]},
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


# ---------------------------------------------------------------------------
# Continuous / discrete-class raster  (singlebandpseudocolor / colorrampshader)
# ---------------------------------------------------------------------------


def parse_continuous_raster(qml_path: Path) -> tuple[list[dict], float]:
    """Return (entries, minimum_break) parsed from a singlebandpseudocolor QML."""
    tree = ET.parse(qml_path)
    root = tree.getroot()
    shader = root.find(".//colorrampshader")
    minimum_break = float(shader.attrib.get("minimumValue", 0)) if shader is not None else 0.0
    entries = [
        {
            "value": float(item.attrib["value"]),
            "color": item.attrib["color"],
            "label": item.attrib["label"],
        }
        for item in root.iter("item")
    ]
    return entries, minimum_break


def build_lyrx_continuous_raster(name: str, entries: list[dict], minimum_break: float = 0.0) -> dict:
    class_breaks = []
    for entry in entries:
        r, g, b = hex_to_rgb(entry["color"])
        class_breaks.append(
            {
                "type": "CIMColorClassBreak",
                "upperBound": entry["value"],
                "label": entry["label"],
                "color": {"type": "CIMRGBColor", "values": [r, g, b, 100]},
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
                    "type": "CIMRasterClassifyColorizer",
                    "classificationMethod": "Manual",
                    "minimumBreak": minimum_break,
                    "classBreaks": class_breaks,
                    "defaultColor": {"type": "CIMRGBColor", "values": [130, 130, 130, 100]},
                    "defaultLabel": "<all other values>",
                    "fieldName": "Value",
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Vector (categorized polygon)
# ---------------------------------------------------------------------------


def parse_vector(qml_path: Path) -> tuple[list[dict], str]:
    """Return (entries, field_name) where each entry has value, label, color."""
    tree = ET.parse(qml_path)
    root = tree.getroot()
    renderer = root.find(".//renderer-v2")
    field = renderer.attrib.get("attr", "Value")

    # Build symbol index → fill color map
    sym_colors: dict[str, list[int]] = {}
    for symbol in renderer.findall(".//symbols/symbol"):
        sym_name = symbol.attrib["name"]
        for option in symbol.findall(".//layer/Option/Option[@name='color']"):
            sym_colors[sym_name] = _css_to_rgb(option.attrib["value"])
            break

    entries = []
    for cat in renderer.findall(".//categories/category"):
        sym_idx = cat.attrib["symbol"]
        entries.append(
            {
                "value": cat.attrib["value"],
                "label": cat.attrib["label"],
                "color": sym_colors.get(sym_idx, [130, 130, 130]),
            }
        )
    return entries, field


def _solid_fill_symbol(r: int, g: int, b: int) -> dict:
    return {
        "type": "CIMSymbolReference",
        "symbol": {
            "type": "CIMPolygonSymbol",
            "symbolLayers": [
                {
                    "type": "CIMSolidFill",
                    "enable": True,
                    "color": {"type": "CIMRGBColor", "values": [r, g, b, 100]},
                },
                {
                    "type": "CIMSolidStroke",
                    "enable": True,
                    "width": 0,
                    "color": {"type": "CIMRGBColor", "values": [0, 0, 0, 0]},
                },
            ],
        },
    }


def build_lyrx_vector(name: str, entries: list[dict], field: str) -> dict:
    classes = []
    for entry in entries:
        r, g, b = entry["color"]
        classes.append(
            {
                "type": "CIMUniqueValueClass",
                "values": [{"type": "CIMUniqueValue", "fieldValues": [entry["value"]]}],
                "label": entry["label"],
                "symbol": _solid_fill_symbol(r, g, b),
                "visible": True,
            }
        )
    return {
        "type": "CIMLayerDocument",
        "version": "3.2.0",
        "build": 36057,
        "layers": [f"CIMPATH=map/{name}.json"],
        "layerDefinitions": [
            {
                "type": "CIMFeatureLayer",
                "name": name,
                "uRI": f"CIMPATH=map/{name}.json",
                "visibility": True,
                "showPopups": True,
                "renderer": {
                    "type": "CIMUniqueValueRenderer",
                    "defaultSymbol": _solid_fill_symbol(130, 130, 130),
                    "defaultLabel": "<all other values>",
                    "useDefaultSymbol": True,
                    "fields": [field],
                    "groups": [
                        {
                            "type": "CIMUniqueValueGroup",
                            "classes": classes,
                            "heading": field,
                        }
                    ],
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def convert(qml_path: Path) -> Path:
    name = qml_path.stem
    qml_type = detect_qml_type(qml_path)

    if qml_type == "paletted_raster":
        entries = parse_paletted_raster(qml_path)
        doc = build_lyrx_paletted_raster(name, entries)
    elif qml_type == "continuous_raster":
        entries, minimum_break = parse_continuous_raster(qml_path)
        doc = build_lyrx_continuous_raster(name, entries, minimum_break)
    elif qml_type == "vector":
        entries, field = parse_vector(qml_path)
        doc = build_lyrx_vector(name, entries, field)

    lyrx_path = qml_path.with_suffix(".lyrx")
    lyrx_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return lyrx_path


if __name__ == "__main__":
    stylesheet_dir = Path(__file__).parent.parent / "stylesheets"
    for qml_file in sorted(stylesheet_dir.glob("*.qml")):
        out = convert(qml_file)
        print(f"{qml_file.name} → {out.name}")
