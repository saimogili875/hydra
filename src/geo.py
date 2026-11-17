"""
Geographic coordinate conversion and GIS polygon utilities.
Designed for lake survey projects calculating areas, boundaries, and buffer zones.

Supported Coordinate Reference Systems:
  - WGS84 (EPSG:4326): Latitude and Longitude in decimal degrees.
  - UTM Zone 43N (EPSG:32643): Western Telangana / India (lon < 78.0°E).
  - UTM Zone 44N (EPSG:32644): Central / Eastern Telangana & Hyderabad (lon >= 78.0°E).
"""

import re
import math
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import pyproj
import shapely
from shapely.geometry import Polygon, LineString

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
    match = re.search(r"(\d+)[°\s]+(\d+)[\'\s]+([\d.]+)[\"\s]*([NSEWnsew])", dms_str)
    if not match:
        raise ValueError(f"Invalid DMS format: '{dms_str}'")

    deg, minutes, sec, direction = match.groups()
    decimal = float(deg) + float(minutes) / 60.0 + float(sec) / 3600.0

    if direction.upper() in ["S", "W"]:
        decimal = -decimal

    return decimal


def get_utm_epsg(lon: float, lat: float = 17.5) -> int:
    """
    Determine the appropriate UTM EPSG code based on longitude.
    In Telangana / India:
      - Longitude < 78.0°E -> UTM Zone 43N (EPSG:32643)
      - Longitude >= 78.0°E -> UTM Zone 44N (EPSG:32644)
    General standard formula:
      zone = int((lon + 180) / 6) + 1
      EPSG: 32600 + zone (for Northern Hemisphere)
    """
    zone = int((lon + 180.0) / 6.0) + 1
    if lat >= 0:
        return 32600 + zone
    else:
        return 32700 + zone


def build_polygon(coords: List[Tuple[float, float]]) -> Polygon:
    """
    Build a Shapely Polygon from a list of (lon, lat) or (x, y) coordinates.
    Points should form a closed or closable boundary in order.
    
    Raises:
        ValueError if fewer than 3 coordinates are provided,
        or if the resulting geometry is self-intersecting or invalid.
    """
    if len(coords) < 3:
        raise ValueError(f"A polygon requires at least 3 points, got {len(coords)}")

    # Ensure the polygon ring is closed (first point equals last point)
    if coords[0] != coords[-1]:
        closed_coords = list(coords) + [coords[0]]
    else:
        closed_coords = list(coords)

    poly = Polygon(closed_coords)
    if not poly.is_valid:
        reason = shapely.is_valid_reason(poly)
        raise ValueError(f"Invalid polygon geometry: {reason}")

    return poly


def area_perimeter(
    polygon: Polygon,
    src_epsg: int = 4326,
    dst_epsg: Optional[int] = None
) -> Tuple[float, float]:
    """
    Project a polygon to its metric UTM zone (auto-selected from centroid if dst_epsg is None)
    and calculate:
        - area in acres
        - perimeter in metres
    
    Uses modern vectorized Shapely 2.0+ transform without deprecated functions.

    Returns:
        (area_acres, perimeter_m)
    """
    if dst_epsg is None:
        centroid = polygon.centroid
        dst_epsg = get_utm_epsg(centroid.x, centroid.y)

    wgs84 = pyproj.CRS(f"EPSG:{src_epsg}")
    utm = pyproj.CRS(f"EPSG:{dst_epsg}")

    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True)

    # Modern vectorized Shapely 2.0+ coordinate transformation
    projected_poly = shapely.transform(
        polygon,
        lambda coords: np.column_stack(transformer.transform(coords[:, 0], coords[:, 1]))
    )

    area_sqm = projected_poly.area
    area_acres = area_sqm / SQM_PER_ACRE
    perimeter_m = projected_poly.length

    return area_acres, perimeter_m


def build_lake_path(
    survey_points: List[Tuple[float, float]],
    bund_points: Optional[List[Tuple[float, float]]] = None
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    Build the open survey boundary and bund line coordinates:
      - survey_boundary: A1 -> A2 ... -> An
      - bund_line: connects An to A1.
        If bund_points is provided (non-empty), traces the curved bund embankment.
        Otherwise falls back to the straight chord [An, A1].

    Returns:
        (boundary_coords, bund_coords)
    """
    if len(survey_points) < 2:
        raise ValueError(f"At least 2 survey points required, got {len(survey_points)}")

    boundary_coords = list(survey_points)

    if bund_points and len(bund_points) >= 2:
        bund_coords = list(bund_points)
        # Ensure continuity: start at last survey point and end at first survey point
        if bund_coords[0] != boundary_coords[-1]:
            bund_coords.insert(0, boundary_coords[-1])
        if bund_coords[-1] != boundary_coords[0]:
            bund_coords.append(boundary_coords[0])
    else:
        # Fallback to straight chord from last point to first point
        bund_coords = [boundary_coords[-1], boundary_coords[0]]

    return boundary_coords, bund_coords


def compute_segment_lengths(
    coords: List[Tuple[float, float]],
    utm_epsg: Optional[int] = None
) -> List[float]:
    """
    Compute projected segment lengths in metres between consecutive points in coords.
    
    Returns:
        List of lengths of size len(coords) - 1.
    """
    if len(coords) < 2:
        return []

    if utm_epsg is None:
        utm_epsg = get_utm_epsg(coords[0][0], coords[0][1])

    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS(f"EPSG:{utm_epsg}")
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True)

    utm_pts = [transformer.transform(lon, lat) for lon, lat in coords]

    lengths = []
    for i in range(1, len(utm_pts)):
        dx = utm_pts[i][0] - utm_pts[i - 1][0]
        dy = utm_pts[i][1] - utm_pts[i - 1][1]
        lengths.append(math.hypot(dx, dy))

    return lengths
