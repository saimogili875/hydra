"""
Unit and integration tests for src/mapview.py.
Verifies:
  - 9m buffer is strictly outside the lake polygon.
  - No buffer on the A37 -> A1 bund side.
  - Exactly 37 unique labels in order (A1 to A37), all placed outside the lake.
  - Computed area and perimeter are within tolerance of the official survey facts.
  - Verification JSON and map outputs are correctly produced.

Run with: pytest tests/test_mapview.py
"""

import os
import json
import pytest
from shapely.geometry import Point, LineString, Polygon

from src.mapview import (
    load_lake_data,
    build_lake_geometry,
    verify_measurements,
    generate_all_outputs
)


def test_load_lake_data():
    """Verify loading of 37 points and lake facts."""
    points, facts = load_lake_data()
    assert len(points) == 37, f"Expected 37 points, got {len(points)}"
    assert facts.get("lake_id") == "871"
    assert facts.get("lake_name") == "YELAMERU KUNTA"

    # Verify first and last points
    assert points[0]["point"] == "A1"
    assert points[-1]["point"] == "A37"

    # Verify UTM coordinates are valid positive numbers in Zone 44N
    for pt in points:
        assert 240000 < pt["utm_x"] < 260000
        assert 1960000 < pt["utm_y"] < 1970000


def test_buffer_is_outside_polygon():
    """
    Verify the 9 m buffer zone is strictly on the exterior (outside) of the lake polygon,
    with zero intersection with the lake interior.
    """
    points, facts = load_lake_data()
    geom = build_lake_geometry(points, buffer_width_m=9.0)

    lake_poly = geom["lake_poly"]
    buf_poly = geom["buffer_poly"]

    assert lake_poly.is_valid, "Lake polygon must be valid"
    assert buf_poly.is_valid, "Buffer polygon must be valid"

    # The area of intersection between lake interior and buffer must be 0
    inter_area = lake_poly.intersection(buf_poly).area
    assert inter_area == pytest.approx(0.0, abs=1e-3), (
        f"Buffer must not overlap lake interior (found {inter_area} sqm overlap)"
    )

    # Representative point of buffer must be outside the lake polygon
    rep_pt = buf_poly.representative_point()
    assert not lake_poly.contains(rep_pt), "Buffer point must be outside the lake polygon"


def test_no_buffer_on_a37_a1_bund_side():
    """
    Verify that the A37 -> A1 chord (top bund embankment) has NO buffer.
    """
    points, facts = load_lake_data()
    geom = build_lake_geometry(points, buffer_width_m=9.0)

    buf_poly = geom["buffer_poly"]
    bund_line = geom["bund_line"]

    # Midpoint of the bund chord must be far away from the buffer zone
    mid_bund = bund_line.interpolate(0.5, normalized=True)
    dist_to_buffer = mid_bund.distance(buf_poly)
    assert dist_to_buffer > 50.0, (
        f"Bund midpoint should be well separated from the buffer (got {dist_to_buffer:.1f} m)"
    )

    # Intersection of bund chord with buffer must only be the terminal vertices A1 and A37 (length 0)
    bund_inter = bund_line.intersection(buf_poly)
    assert bund_inter.length == pytest.approx(0.0, abs=1e-3), (
        "Bund chord must have zero shared segment with the buffer zone"
    )


def test_unique_labels_in_order():
    """
    Verify that:
      - Each label from A1 to A37 appears exactly once, in sequential order.
      - All 37 labels are positioned outside the lake polygon.
    """
    points, facts = load_lake_data()
    geom = build_lake_geometry(points, buffer_width_m=9.0)

    labels = geom["labels"]
    lake_poly = geom["lake_poly"]
    label_positions = geom["label_positions_utm"]

    # Exactly 37 labels
    assert len(labels) == 37
    expected_labels = [f"A{i+1}" for i in range(37)]
    assert labels == expected_labels, "Labels must be A1 through A37 in exact sequential order"

    # No duplicates
    assert len(set(labels)) == 37, "Labels must be unique (no duplicate labels)"

    # All label positions must be outside the lake polygon
    assert len(label_positions) == 37
    for i, (lbl_x, lbl_y) in enumerate(label_positions):
        pt = Point(lbl_x, lbl_y)
        assert not lake_poly.contains(pt), (
            f"Label {labels[i]} at ({lbl_x:.1f}, {lbl_y:.1f}) must be outside the lake polygon"
        )


def test_area_and_perimeter_tolerance():
    """
    Verify that computed area and perimeter are within 5% tolerance of PDF survey facts,
    and the verification status reports 'OK'.
    """
    points, facts = load_lake_data()
    geom = build_lake_geometry(points, buffer_width_m=9.0)

    verification = verify_measurements(
        geom["lake_poly"],
        geom["boundary_line"],
        geom["bund_line"],
        facts
    )

    # Check status is OK
    assert verification["area"]["status"] == "OK"
    assert verification["perimeter"]["status"] == "OK"
    assert verification["overall_status"] == "OK"

    # Area tolerance check (<= 5% difference)
    area_diff_pct = abs(verification["area"]["diff_percent"])
    assert area_diff_pct < 5.0, f"Area difference ({area_diff_pct}%) exceeds 5% tolerance"

    # Perimeter tolerance check (<= 5% difference)
    perim_diff_pct = abs(verification["perimeter"]["diff_percent"])
    assert perim_diff_pct < 5.0, f"Perimeter difference ({perim_diff_pct}%) exceeds 5% tolerance"


def test_generate_all_outputs():
    """
    Verify that generate_all_outputs() creates all required output files
    and populates valid metadata.
    """
    results = generate_all_outputs()

    assert os.path.exists(results["png_path"]), f"Missing PNG: {results['png_path']}"
    assert os.path.exists(results["html_path"]), f"Missing HTML: {results['html_path']}"
    assert os.path.exists(results["json_path"]), f"Missing JSON: {results['json_path']}"
    assert results["status"] == "OK"

    # Verify JSON structure
    with open(results["json_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["lake_id"] == "871"
    assert data["overall_status"] == "OK"
    assert "area" in data
    assert "perimeter" in data
    assert "bund" in data


def test_live_coordinate_readout_look_and_position():
    """
    Verify the updated Task 2 live coordinate readout look, position, and behaviors:
    - Pinned to bottom of the map, spans full width (position: absolute, bottom: 0, left: 0, right: 0, width: 100%)
    - Solid black background (#000000), pure white text (#FFFFFF), no transparency
    - Monospace font, 14px, padding 8px 14px
    - Leaflet bottom controls (scale bar and legend) raised above the bar (bottom: 42px !important)
    - Initial prompt: 'Move the pointer over the map'
    - Formats decimal, DMS, and UTM 44N coordinates (Lat: ... | Long: ... | ... | UTM 44N: E ... N ...)
    - Mobile 2-line wrap: decimal line 1, DMS + UTM line 2
    - Pinned status, brighter white, and 'Pinned' badge
    - Task 2 features intact: pin popup, inside/buffer/outside status, nearest point, copy button, clear pin
    """
    results = generate_all_outputs()
    html_path = results["html_path"]
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. POSITION: pinned to bottom edge, full width, fixed during zoom/pan
    assert 'id="coordinate-bar"' in html or "id='coordinate-bar'" in html
    assert "position: absolute" in html
    assert "bottom: 0" in html
    assert "width: 100%" in html
    # Scale bar and legend raised above the bar
    assert "bottom: 42px !important" in html

    # 2. COLORS: solid black background, pure white text, 14px monospace font, 8px 14px padding
    assert "#000000" in html
    assert "#FFFFFF" in html
    assert "padding: 8px 14px" in html
    assert "font-size: 14px" in html
    assert "monospace" in html

    # 3. CONTENT & BEHAVIOR:
    # Prompt before pointer enters map
    assert "Move the pointer over the map" in html
    # Formatting segments
    assert "Lat: " in html
    assert "Long: " in html
    assert "UTM 44N: E " in html
    assert "toDMS" in html
    assert "latLonToUTM44N" in html

    # Pinned badge and brighter white
    assert "pinned-tag" in html
    assert "Pinned" in html
    assert "is-pinned" in html

    # Mobile 2-line wrap
    assert "coord-line-1" in html
    assert "coord-line-2" in html
    assert "sep-mid" in html

    # Task 2 features intact: pin popup, inside/buffer/outside status, nearest point, copy button, clear pin
    assert "INSIDE FTL" in html
    assert "BUFFER" in html
    assert "OUTSIDE" in html
    assert "Nearest:" in html
    assert "copyPinCoords" in html
    assert "clearPin" in html


def test_config_and_security():
    """
    Verify security setup for Google Maps API:
    - config.example.js exists and defines empty GOOGLE_MAPS_KEY.
    - config.js is ignored in .gitignore so keys are never checked into git.
    """
    assert os.path.exists("config.example.js"), "config.example.js must exist"
    with open("config.example.js", "r", encoding="utf-8") as f:
        example_content = f.read()
    assert "GOOGLE_MAPS_KEY" in example_content
    assert '""' in example_content or "''" in example_content

    assert os.path.exists(".gitignore"), ".gitignore must exist"
    with open(".gitignore", "r", encoding="utf-8") as f:
        gitignore = f.read().splitlines()
    assert any(line.strip() == "config.js" for line in gitignore), "config.js must be in .gitignore"


def test_google_maps_basemap_switcher_and_export():
    """
    Verify Google Maps integration, basemap switcher, overlays, and GeoJSON export
    in both index.html and outputs/lake_871_satellite.html:
    - Loads Google Maps JS API dynamically with key from config.js.
    - Basemap switcher options: Google Satellite, Google Hybrid, Esri, OSM.
    - Google options hidden when key is empty or invalid (gm_authFailure handler).
    - Google Data layer (GeoJSON) used for boundary, buffer, and points.
    - Dashed brown bund chord line (A37 -> A1).
    - Outward point labels (A1 - A37) with white halo.
    - 'Export GeoJSON' button and download handler.
    - Remembers last chosen basemap in localStorage.
    """
    for file_path in ["index.html", "outputs/lake_871_satellite.html"]:
        assert os.path.exists(file_path), f"File {file_path} must exist"
        with open(file_path, "r", encoding="utf-8") as f:
            html = f.read()

        # 1. Config and official API loader
        assert "config.js" in html
        assert "GOOGLE_MAPS_KEY" in html
        assert "maps.googleapis.com/maps/api/js" in html

        # 2. Basemap switcher options
        assert "google-satellite" in html
        assert "google-hybrid" in html
        assert "esri" in html
        assert "osm" in html
        assert "localStorage" in html
        assert "lake_871_basemap" in html

        # 3. Graceful fallback on auth failure
        assert "gm_authFailure" in html

        # 4. Overlays: Google Data Layer, dashed bund line, white halo labels
        assert "googleMap.data" in html or "map.data" in html
        assert "#ff6b00" in html  # Orange boundary
        assert "#00c853" in html or "#39ff14" in html  # Green buffer
        assert "#8d5524" in html  # Brown bund
        assert "google-map-label" in html  # White halo

        # 5. Export GeoJSON functionality
        assert "Export GeoJSON" in html
        assert "exportGeoJSON" in html
        assert "yelameru_kunta_871.geojson" in html


