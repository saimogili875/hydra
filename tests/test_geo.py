"""
Unit and integration tests for src/geo.py.
Run with: pytest
"""

import os
import csv
import pytest
from shapely.geometry import Polygon
from src.geo import dms_to_decimal, build_polygon, area_perimeter


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

