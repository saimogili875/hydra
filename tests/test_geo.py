"""
Unit and integration tests for src/geo.py.
Run with: pytest
"""

import os
import csv
import pytest
from shapely.geometry import Polygon
from src.geo import (
    dms_to_decimal,
    build_polygon,
    area_perimeter,
    get_utm_epsg,
    build_lake_path,
    compute_segment_lengths
)


def test_dms_to_decimal_standard():
    """Test standard DMS coordinate conversion."""
    dms = '17°46\'25.856"N'
    expected = 17 + 46 / 60.0 + 25.856 / 3600.0
    assert pytest.approx(dms_to_decimal(dms), rel=1e-7) == expected


def test_dms_to_decimal_two_decimals():
    """Test DMS coordinate with 2 decimal places in seconds (e.g. A5, A10)."""
    dms = '17°46\'24.41"N'
    expected = 17 + 46 / 60.0 + 24.41 / 3600.0
    assert pytest.approx(dms_to_decimal(dms), rel=1e-7) == expected


def test_dms_to_decimal_single_digit_seconds():
    """Test DMS coordinate with single-digit whole seconds (e.g. A21: 0.587)."""
    dms = '78°39\'0.587"E'
    expected = 78 + 39 / 60.0 + 0.587 / 3600.0
    assert pytest.approx(dms_to_decimal(dms), rel=1e-7) == expected


def test_dms_to_decimal_directions():
    """Test that S and W produce negative decimal degrees."""
    assert dms_to_decimal('10°30\'00"S') < 0
    assert dms_to_decimal('70°15\'30"W') < 0
    assert dms_to_decimal('10°30\'00"N') > 0
    assert dms_to_decimal('70°15\'30"E') > 0


def test_dms_to_decimal_invalid():
    """Test invalid input handling."""
    with pytest.raises(ValueError):
        dms_to_decimal("invalid-string")
    with pytest.raises(TypeError):
        dms_to_decimal(12345)


def test_build_polygon():
    """Test building a valid polygon from coordinate tuples."""
    coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    poly = build_polygon(coords)
    assert isinstance(poly, Polygon)
    assert poly.is_valid
    # Polygon should auto-close with 5 vertices (initial 4 + closing point)
    assert len(poly.exterior.coords) == 5

    with pytest.raises(ValueError):
        build_polygon([(0.0, 0.0), (1.0, 1.0)])


def test_area_perimeter_with_lake_points():
    """
    Integration test reading data/871_points.csv.
    Verifies area is close to map's 16.152 acres (~16.6 acres with straight bund line)
    and perimeter is close to map's 1411.7 m (~1393 m).
    """
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "871_points.csv")
    assert os.path.exists(csv_path), "data/871_points.csv must exist"

    coords = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lon = dms_to_decimal(row["lon_dms"])
            lat = dms_to_decimal(row["lat_dms"])
            coords.append((lon, lat))

    assert len(coords) == 37, f"Expected 37 points, found {len(coords)}"

    poly = build_polygon(coords)
    area_acres, perimeter_m = area_perimeter(poly)

    # Area is ~16.6 acres (straight line from A37 to A1 adds slight area over curved bund)
    assert 15.0 < area_acres < 17.5
    # Perimeter is ~1393 m
    assert 1300.0 < perimeter_m < 1500.0


def test_get_utm_epsg():
    """Verify UTM zone auto-detection from longitude."""
    assert get_utm_epsg(77.5) == 32643  # Zone 43N
    assert get_utm_epsg(78.5) == 32644  # Zone 44N
    assert get_utm_epsg(78.0) == 32644  # Boundary


def test_build_polygon_invalid_raises_error():
    """Verify self-intersecting polygon raises a clear ValueError instead of silent buffer(0)."""
    # Self-intersecting hourglass / bowtie shape
    invalid_coords = [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)]
    with pytest.raises(ValueError) as excinfo:
        build_polygon(invalid_coords)
    assert "Invalid polygon geometry" in str(excinfo.value)
    assert "Self-intersection" in str(excinfo.value)


def test_build_lake_path_straight_and_curved():
    """Verify build_lake_path with straight bund chord vs optional curved bund points."""
    survey_pts = [(78.64, 17.77), (78.65, 17.77), (78.65, 17.76)]

    # 1. Without bund_points -> fallback to straight chord [last, first]
    boundary, bund = build_lake_path(survey_pts, bund_points=None)
    assert len(boundary) == 3
    assert len(bund) == 2
    assert bund[0] == survey_pts[-1]
    assert bund[1] == survey_pts[0]

    # 2. With curved bund_points
    curved_pts = [(78.65, 17.76), (78.645, 17.765), (78.64, 17.77)]
    boundary_c, bund_c = build_lake_path(survey_pts, bund_points=curved_pts)
    assert len(boundary_c) == 3
    assert len(bund_c) == 3
    assert bund_c[0] == survey_pts[-1]
    assert bund_c[-1] == survey_pts[0]


def test_segment_lengths_against_scan_distances():
    """
    Compare computed UTM segment lengths between points A1..A37 with the official scan distance column.
    Tolerance is 0.05 m per segment (all 36 segments match within 0.03 m).
    """
    # Expected distance for segment i (from point i to point i+1 in A1..A37)
    scan_distances = [
        13.80, 10.26, 21.80, 28.07, 25.14, 29.20, 57.56, 28.40, 23.22,
        55.61, 19.29, 26.00, 35.64, 11.71, 24.54, 18.58, 24.45, 20.79,
        24.60, 27.11, 29.78, 34.03, 29.97, 29.63, 26.32, 24.46, 19.30,
        21.67, 37.56, 27.36, 29.04, 22.37, 26.53, 25.38, 23.69, 10.57
    ]

    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "871_points.csv")
    coords = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            coords.append((dms_to_decimal(row["lon_dms"]), dms_to_decimal(row["lat_dms"])))

    assert len(coords) == 37
    computed_lengths = compute_segment_lengths(coords, utm_epsg=32644)
    assert len(computed_lengths) == len(scan_distances)

    for i, (computed, expected) in enumerate(zip(computed_lengths, scan_distances)):
        diff = abs(computed - expected)
        assert diff < 0.05, f"Segment A{i+1}->A{i+2} length {computed:.3f}m differs from scan {expected}m by {diff:.3f}m (>0.05m tolerance)"


