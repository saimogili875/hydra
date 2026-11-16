"""
Geographic coordinate conversion and GIS polygon utilities.
Designed for student projects calculating lake areas and boundaries.
Coordinate Reference Systems:
  - WGS84 (EPSG:4326): Latitude and Longitude in degrees.
  - UTM Zone 44N (EPSG:32644): Projected metric coordinates for Hyderabad/Telangana.
"""

import re
from typing import List, Tuple
from shapely.geometry import Polygon
import pyproj
from shapely.ops import transform

# 1 acre = 4046.8564224 square metres
SQM_PER_ACRE = 4046.8564224


def dms_to_decimal(dms_str: str) -> float:
    """
    Convert a DMS (Degrees, Minutes, Seconds) string into Decimal Degrees.
    Example inputs:
        '17°46\'25.856"N' -> 17.773848888...
        '78°38\'47.582"E' -> 78.646550555...
        '17°46\'24.41"N'  -> 17.773447222... (2 decimal places)
        '78°39\'0.587"E'  -> 78.650163055... (single-digit whole seconds)
    """
    if not isinstance(dms_str, str):
        raise TypeError(f"Expected string, got {type(dms_str)}")

    dms_str = dms_str.strip()
    # Regex to capture degrees, minutes, seconds (with decimals), and direction
    match = re.search(r"(\d+)[°\s]+(\d+)[\'\s]+([\d.]+)[\"\s]*([NSEWnsew])", dms_str)
    if not match:
        raise ValueError(f"Invalid DMS format: '{dms_str}'")

    deg, minutes, sec, direction = match.groups()
    decimal = float(deg) + float(minutes) / 60.0 + float(sec) / 3600.0

    # South and West coordinates are negative in standard GIS
    if direction.upper() in ["S", "W"]:
        decimal = -decimal

    return decimal


def build_polygon(coords: List[Tuple[float, float]]) -> Polygon:
    """
    Build a Shapely Polygon from a list of (lon, lat) or (x, y) coordinates.
    Points should form a closed or closable boundary in order.
    """
    if len(coords) < 3:
        raise ValueError(f"A polygon requires at least 3 points, got {len(coords)}")

    # Ensure the polygon ring is closed (first point equals last point)
    if coords[0] != coords[-1]:
        closed_coords = list(coords) + [coords[0]]
    else:
        closed_coords = coords

    poly = Polygon(closed_coords)
    if not poly.is_valid:
        # Attempt simple self-intersection repair if needed
        poly = poly.buffer(0)
    return poly


def area_perimeter(polygon: Polygon, src_epsg: int = 4326, dst_epsg: int = 32644) -> Tuple[float, float]:
    """
    Project a polygon from WGS84 (EPSG:4326) to UTM 44N (EPSG:32644),
    then calculate:
        - area in acres
        - perimeter in metres
    Returns:
        (area_acres, perimeter_m)
    """
    wgs84 = pyproj.CRS(f"EPSG:{src_epsg}")
    utm = pyproj.CRS(f"EPSG:{dst_epsg}")

    # Project coordinates from geographic (degrees) to projected (metres)
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
    projected_poly = transform(transformer, polygon)

    area_sqm = projected_poly.area
    area_acres = area_sqm / SQM_PER_ACRE
    perimeter_m = projected_poly.length

    return area_acres, perimeter_m

