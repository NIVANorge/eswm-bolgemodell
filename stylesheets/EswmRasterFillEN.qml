<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis styleCategories="Symbology" version="3.44.7-Solothurn">
  <pipe-data-defined-properties>
    <Option type="Map">
      <Option value="" name="name" type="QString"/>
      <Option name="properties"/>
      <Option value="collection" name="type" type="QString"/>
    </Option>
  </pipe-data-defined-properties>
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedOutResamplingMethod="nearestNeighbour" zoomedInResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer nodataColor="" band="1" opacity="1" type="paletted" alphaBand="-1">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <colorPalette>
        <paletteEntry value="1" alpha="255" color="#EDF8FB" label="LM-VF_0 — Minimal water movement, ≤ 1 200"/>
        <paletteEntry value="2" alpha="255" color="#B2E2E2" label="LM-VF_a — Very sheltered, > 1 200, ≤ 4 000"/>
        <paletteEntry value="3" alpha="255" color="#66C2A4" label="LM-VF_b — Moderately sheltered, > 4 000, ≤ 10 000"/>
        <paletteEntry value="4" alpha="255" color="#238B45" label="LM-VF_c — Slightly sheltered, > 10 000, ≤ 50 000"/>
        <paletteEntry value="5" alpha="255" color="#FFFFB2" label="LM-VF_d — Weakly exposed, > 50 000, ≤ 100 000"/>
        <paletteEntry value="6" alpha="255" color="#FECC5C" label="LM-VF_e — Slightly exposed, > 100 000, ≤ 500 000"/>
        <paletteEntry value="7" alpha="255" color="#FD8D3C" label="LM-VF_f — Exposed, > 500 000, ≤ 1 000 000"/>
        <paletteEntry value="8" alpha="255" color="#F03B20" label="LM-VF_g — Very exposed, > 1 000 000, ≤ 2 000 000"/>
        <paletteEntry value="9" alpha="255" color="#BD0026" label="LM-VF_h — Extremely exposed, > 2 000 000, ≤ 4 000 000"/>
      </colorPalette>
      <colorramp name="[source]" type="randomcolors">
        <Option/>
      </colorramp>
    </rasterrenderer>
    <brightnesscontrast gamma="1" contrast="0" brightness="0"/>
    <huesaturation colorizeStrength="100" colorizeRed="255" colorizeBlue="128" saturation="0" grayscaleMode="0" colorizeOn="0" colorizeGreen="128" invertColors="0"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
