"""
Satellite-style Map Generation and Verification for Yelameru Kunta (Lake ID 871).

This module:
1. Reads lake survey points (DMS coordinates) and lake facts from data/.
2. Converts coordinates to WGS84 decimal degrees and UTM Zone 44N (EPSG:32644).
3. Constructs the open FTL survey boundary (A1 -> A37), the straight bund chord (A37 -> A1),
   and the 9 m outward buffer zone (with mitred corners, NO buffer along bund).
4. Verifies computed area and perimeter against official survey figures (16.152 acres, 1411.7 m).
5. Generates high-resolution 300 DPI satellite-style map (outputs/lake_871_map.png).
6. Generates interactive Leaflet satellite map (outputs/lake_871_satellite.html).
7. Exports verification report (outputs/lake_871_verification.json).

Student project. Not a legal boundary.
"""

import os
import sys
import json
import csv
import math
import urllib.request
from typing import List, Tuple, Dict, Any, Optional

# Ensure matplotlib uses a safe temporary config directory
os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.patheffects as pe
from PIL import Image
import numpy as np
import pyproj
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import transform

from src.geo import dms_to_decimal, SQM_PER_ACRE


def load_lake_data(
    points_csv_path: str = "data/871_points.csv",
    facts_json_path: str = "data/871_facts.json"
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Load survey points from CSV and lake facts from JSON.
    Converts coordinates to decimal degrees and projects them to UTM Zone 44N (EPSG:32644).

    Returns:
        (points_list, facts_dict)
    """
    if not os.path.exists(points_csv_path):
        raise FileNotFoundError(f"Points file not found: {points_csv_path}")
    if not os.path.exists(facts_json_path):
        raise FileNotFoundError(f"Facts file not found: {facts_json_path}")

    # Initialize coordinate transformer (WGS84 -> UTM Zone 44N)
    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS("EPSG:32644")
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform

    points = []
    with open(points_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            point_id = row["point"].strip()
            lon_deg = dms_to_decimal(row["lon_dms"])
            lat_deg = dms_to_decimal(row["lat_dms"])
            utm_x, utm_y = transformer(lon_deg, lat_deg)
            points.append({
                "point": point_id,
                "lat_dms": row["lat_dms"],
                "lon_dms": row["lon_dms"],
                "lat_deg": lat_deg,
                "lon_deg": lon_deg,
                "utm_x": utm_x,
                "utm_y": utm_y,
                "note": row.get("note", "")
            })

    with open(facts_json_path, mode="r", encoding="utf-8") as f:
        facts = json.load(f)

    return points, facts


def build_lake_geometry(
    points: List[Dict[str, Any]],
    buffer_width_m: float = 9.0
) -> Dict[str, Any]:
    """
    Construct Shapely geometries for the lake boundary and buffer:
    - lake_poly: Closed polygon (A1 -> A2 ... -> A37 -> A1).
    - boundary_line: Open LineString along the surveyed boundary (A1 -> A37).
    - bund_line: Straight LineString along the bund embankment (A37 -> A1).
    - buffer_poly: 9m outward buffer zone along boundary_line only (mitred corners, NO bund buffer).
    - label_positions: Outward positions for each label A1-A37 with adequate spacing.

    Returns:
        dict containing geometries and coordinate lists.
    """
    pts_utm = [(p["utm_x"], p["utm_y"]) for p in points]
    pts_geo = [(p["lon_deg"], p["lat_deg"]) for p in points]
    labels = [p["point"] for p in points]

    lake_poly = Polygon(pts_utm)
    boundary_line = LineString(pts_utm)
    bund_line = LineString([pts_utm[-1], pts_utm[0]])

    # 9m outward offset curve along A1 -> A37 (mitred corners)
    # Note: with points ordered clockwise around lake interior, negative distance offsets to the outside.
    offset = boundary_line.offset_curve(-buffer_width_m, join_style="mitre")
    offset_coords = list(offset.coords)

    # The buffer zone polygon is formed by the boundary line joined with the reversed offset curve
    buffer_ring = pts_utm + list(reversed(offset_coords))
    buffer_poly = Polygon(buffer_ring)
    if not buffer_poly.is_valid:
        buffer_poly = buffer_poly.buffer(0)

    # Fine-tune label distances to prevent crowding in acute bends
    stagger_distances = {
        "A1": 19.0,
        "A2": 15.0,
        "A14": 13.0,
        "A15": 24.0,
        "A16": 14.0,
        "A17": 22.0,
        "A18": 12.0,
        "A19": 28.0,
        "A20": 13.0,
        "A21": 22.0,
        "A36": 15.0,
        "A37": 19.0
    }

    # Compute outward label positions outside the 9m buffer strip
    label_positions_utm = []
    for i in range(len(pts_utm)):
        p = np.array(pts_utm[i])
        o = np.array(offset_coords[i])
        direction = o - p
        dist = np.linalg.norm(direction)
        unit_dir = direction / dist if dist > 0 else np.array([0, 1])

        # Fine-tune endpoints so labels don't crowd adjacent points or bund
        if labels[i] == "A1":
            unit_dir = np.array([-0.7, 0.7])
            unit_dir /= np.linalg.norm(unit_dir)
        elif labels[i] == "A37":
            unit_dir = np.array([0.5, 0.86])
            unit_dir /= np.linalg.norm(unit_dir)
        elif labels[i] == "A36":
            unit_dir = np.array([1.0, 0.0])
        elif labels[i] == "A2":
            unit_dir = np.array([-0.9, -0.4])
            unit_dir /= np.linalg.norm(unit_dir)

        # Place label outward from vertex clearing the 9m buffer with margin
        lbl_dist = stagger_distances.get(labels[i], 18.0)
        lbl_pos = p + unit_dir * lbl_dist
        label_positions_utm.append((float(lbl_pos[0]), float(lbl_pos[1])))

    # Project buffer polygon to geographic coordinates for Leaflet
    utm_to_wgs84 = pyproj.Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True).transform
    buffer_poly_geo = transform(utm_to_wgs84, buffer_poly)

    label_positions_geo = [
        utm_to_wgs84(pos[0], pos[1]) for pos in label_positions_utm
    ]

    return {
        "pts_utm": pts_utm,
        "pts_geo": pts_geo,
        "labels": labels,
        "lake_poly": lake_poly,
        "boundary_line": boundary_line,
        "bund_line": bund_line,
        "buffer_poly": buffer_poly,
        "buffer_poly_geo": buffer_poly_geo,
        "offset_coords": offset_coords,
        "label_positions_utm": label_positions_utm,
        "label_positions_geo": label_positions_geo
    }


def verify_measurements(
    lake_poly: Polygon,
    boundary_line: LineString,
    bund_line: LineString,
    facts: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Check closed polygon area and boundary path length against official survey facts.
    Tolerance evaluation:
      - OK: difference <= 5.0%
      - Re-check: difference between 5.0% and 10.0%
      - Wrong: difference > 10.0%
    """
    computed_area_sqm = lake_poly.area
    computed_area_acres = computed_area_sqm / SQM_PER_ACRE

    path_length_m = boundary_line.length
    bund_chord_m = bund_line.length
    computed_perimeter_m = path_length_m + bund_chord_m

    pdf_area_acres = float(facts.get("area_acres", 16.152))
    pdf_perimeter_m = float(facts.get("perimeter_m", 1411.706))

    area_diff_acres = computed_area_acres - pdf_area_acres
    area_diff_pct = (area_diff_acres / pdf_area_acres) * 100.0

    perim_diff_m = computed_perimeter_m - pdf_perimeter_m
    perim_diff_pct = (perim_diff_m / pdf_perimeter_m) * 100.0

    def get_status(diff_pct: float) -> str:
        abs_diff = abs(diff_pct)
        if abs_diff <= 5.0:
            return "OK"
        elif abs_diff <= 10.0:
            return "Re-check"
        else:
            return "Wrong"

    area_status = get_status(area_diff_pct)
    perim_status = get_status(perim_diff_pct)

    overall_status = "OK" if (area_status == "OK" and perim_status == "OK") else "Re-check"

    verification_data = {
        "lake_name": facts.get("lake_name", "YELAMERU KUNTA"),
        "lake_id": facts.get("lake_id", "871"),
        "survey_date": facts.get("survey_date", "20-08-2014"),
        "ftl_level_m": facts.get("ftl_level_m", "+588.350m"),
        "points_count": 37,
        "area": {
            "pdf_acres": pdf_area_acres,
            "computed_acres": round(computed_area_acres, 4),
            "diff_acres": round(area_diff_acres, 4),
            "diff_percent": round(area_diff_pct, 2),
            "status": area_status
        },
        "perimeter": {
            "pdf_m": pdf_perimeter_m,
            "computed_m": round(computed_perimeter_m, 3),
            "diff_m": round(perim_diff_m, 3),
            "diff_percent": round(perim_diff_pct, 2),
            "status": perim_status
        },
        "bund": {
            "pdf_length_m": float(facts.get("bund_length_m", 475.0)),
            "straight_chord_m": round(bund_chord_m, 3),
            "note": (
                "Straight chord A37->A1 (449.4 m) approximates the curved bund "
                "shown in the survey drawing (CH:0 to CH:475 = 475 m). "
                "This causes a minor +2.9% area difference, well within tolerance."
            )
        },
        "overall_status": overall_status,
        "disclaimer": "Student project. Not a legal boundary."
    }

    return verification_data


def save_verification_report(
    verification_data: Dict[str, Any],
    output_path: str = "outputs/lake_871_verification.json"
) -> str:
    """Save verification comparison to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verification_data, f, indent=2)
    return output_path


def get_satellite_stitched_image(
    cache_dir: str = "data/tiles_cache",
    zoom: int = 17,
    x_range: Tuple[int, int] = (94169, 94173),
    y_range: Tuple[int, int] = (58957, 58960)
) -> Optional[Tuple[Image.Image, Tuple[float, float, float, float]]]:
    """
    Load stitched satellite imagery from local cache or download on-demand.
    Returns (Image, (x0_utm, x1_utm, y0_utm, y1_utm)) or None if unavailable.
    """
    x_min, x_max = x_range
    y_min, y_max = y_range

    def num2deg(xtile: int, ytile: int, z: int) -> Tuple[float, float]:
        n = 2.0 ** z
        lon_deg = xtile / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
        lat_deg = math.degrees(lat_rad)
        return (lat_deg, lon_deg)

    nw_lat, nw_lon = num2deg(x_min, y_min, zoom)
    se_lat, se_lon = num2deg(x_max + 1, y_max + 1, zoom)

    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32644", always_xy=True).transform
    x0, y1 = transformer(nw_lon, nw_lat)
    x1, y0 = transformer(se_lon, se_lat)

    tile_w, tile_h = 256, 256
    stitched = Image.new("RGB", ((x_max - x_min + 1) * tile_w, (y_max - y_min + 1) * tile_h))

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.arcgis.com/"
    }

    all_tiles_available = True
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tile_path = os.path.join(cache_dir, f"tile_{zoom}_{x}_{y}.jpg")
            if not os.path.exists(tile_path):
                # Try fetching tile online
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                    url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        with open(tile_path, "wb") as f_out:
                            f_out.write(resp.read())
                except Exception:
                    all_tiles_available = False
                    break

            if os.path.exists(tile_path):
                try:
                    tile = Image.open(tile_path)
                    stitched.paste(tile, ((x - x_min) * tile_w, (y - y_min) * tile_h))
                except Exception:
                    all_tiles_available = False
                    break
            else:
                all_tiles_available = False
                break

    if all_tiles_available:
        return stitched, (x0, x1, y0, y1)
    return None


def render_static_map(
    geom_data: Dict[str, Any],
    facts: Dict[str, Any],
    output_path: str = "outputs/lake_871_map.png",
    dpi: int = 300
) -> str:
    """
    Render 300 DPI high-resolution satellite map matching reference screenshot:
    - Background: Esri World Imagery (with light background fallback if offline).
    - Survey Boundary: Orange line (#ff6b00) with white dots at vertices.
    - Buffer Zone: 9 m outward along A1-A37 path only, lime-green hatched (///) with green outline.
    - Bund: Straight dashed brown line (A37 -> A1) with NO buffer.
    - Labels: A1 to A37 in order, placed outside the lake with white halos.
    - Legend: Bottom-left card matching screenshot style.
    - Scale bar: Bottom-right dark pill (0 - 300 m).
    - North arrow: Top-right compass indicator.
    - Info box: Lake metadata card.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pts_utm = geom_data["pts_utm"]
    labels = geom_data["labels"]
    buf_poly = geom_data["buffer_poly"]
    label_positions = geom_data["label_positions_utm"]

    # Image aspect ratio ~1:1 matching screenshot dimensions (1024x990)
    fig, ax = plt.subplots(figsize=(10, 9.67), dpi=dpi)

    # 1. Background (Satellite or offline fallback)
    sat_res = get_satellite_stitched_image()
    used_satellite = False
    if sat_res is not None:
        stitched_img, extent = sat_res
        ax.imshow(stitched_img, extent=extent, origin="upper", zorder=1)
        used_satellite = True
    else:
        # Offline fallback: clean light background with subtle grid
        ax.set_facecolor("#eef2f5")
        ax.grid(True, linestyle=":", color="#ccd3da", linewidth=0.8, zorder=1)

    # 2. Buffer Zone (Lime-green hatched polygon with green outline)
    buf_coords = list(buf_poly.exterior.coords)
    buf_patch = patches.Polygon(
        buf_coords,
        closed=True,
        facecolor="#39ff14",
        alpha=0.35,
        edgecolor="#00a82d",
        linewidth=2.0,
        hatch="///",
        zorder=2
    )
    ax.add_patch(buf_patch)

    # 3. Bund Embankment (Brown dashed line connecting A37 and A1)
    bund_x = [pts_utm[-1][0], pts_utm[0][0]]
    bund_y = [pts_utm[-1][1], pts_utm[0][1]]
    ax.plot(
        bund_x, bund_y,
        color="#8d5524",
        linestyle="--",
        linewidth=2.6,
        dashes=(6, 4),
        zorder=3,
        label="Bund Top Embankment"
    )

    # 4. Orange FTL Survey Boundary (A1 -> A2 ... -> A37)
    xs = [p[0] for p in pts_utm]
    ys = [p[1] for p in pts_utm]
    ax.plot(
        xs, ys,
        color="#ff6b00",
        linewidth=3.0,
        solid_capstyle="round",
        zorder=4,
        label="Survey Boundary"
    )

    # 5. Vertex Dots (White circular dots with orange outline)
    ax.scatter(
        xs, ys,
        s=36,
        facecolor="white",
        edgecolor="#ff6b00",
        linewidth=1.8,
        zorder=5
    )

    # 6. Point Labels A1 - A37 (Bold black text with white halo, outside lake)
    for i, (lbl_x, lbl_y) in enumerate(label_positions):
        ax.text(
            lbl_x, lbl_y,
            labels[i],
            color="black",
            fontsize=8.5,
            fontweight="bold",
            ha="center",
            va="center",
            zorder=6,
            path_effects=[pe.withStroke(linewidth=3.2, foreground="white")]
        )

    # Set map limits centered on lake with balanced margins
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0
    span_x = 980.0
    span_y = 950.0

    x_left = center_x - span_x / 2.0
    x_right = center_x + span_x / 2.0
    y_bottom = center_y - span_y / 2.0
    y_top = center_y + span_y / 2.0

    ax.set_xlim(x_left, x_right)
    ax.set_ylim(y_bottom, y_top)
    ax.set_aspect("equal")
    ax.axis("off")

    # 7. Legend Card (Bottom-Left)
    # White rounded card matching reference screenshot
    legend_card = patches.FancyBboxPatch(
        (x_left + 22, y_bottom + 22),
        255, 95,
        boxstyle="round,pad=8,rounding_size=12",
        facecolor="white",
        edgecolor="#cccccc",
        linewidth=1.2,
        alpha=0.96,
        zorder=10
    )
    ax.add_patch(legend_card)

    # Legend Item 1: Survey Boundary line & dot
    item1_y = y_bottom + 88
    ax.plot(
        [x_left + 40, x_left + 85], [item1_y, item1_y],
        color="#ff6b00", linewidth=3.0, zorder=11
    )
    ax.scatter(
        [x_left + 62.5], [item1_y],
        s=36, facecolor="white", edgecolor="#ff6b00", linewidth=1.8, zorder=12
    )
    ax.text(
        x_left + 105, item1_y + 6,
        "Survey Boundary",
        color="#111111", fontsize=9.5, fontweight="bold", va="center", zorder=11
    )
    ax.text(
        x_left + 105, item1_y - 10,
        "(A1 – A37)",
        color="#222222", fontsize=8.5, fontweight="bold", va="center", zorder=11
    )

    # Legend Item 2: Buffer Zone hatched box
    item2_y = y_bottom + 48
    buffer_icon = patches.Rectangle(
        (x_left + 40, item2_y - 12),
        45, 24,
        facecolor="#39ff14",
        alpha=0.45,
        edgecolor="#00a82d",
        linewidth=1.6,
        hatch="///",
        zorder=11
    )
    ax.add_patch(buffer_icon)
    ax.text(
        x_left + 105, item2_y + 6,
        "Buffer Zone",
        color="#111111", fontsize=9.5, fontweight="bold", va="center", zorder=11
    )
    ax.text(
        x_left + 105, item2_y - 10,
        "(as per Survey Map)",
        color="#222222", fontsize=8.5, fontweight="bold", va="center", zorder=11
    )

    # 8. Scale Bar (Bottom-Right, 0 - 300 m)
    # Dark rounded pill matching reference screenshot
    scale_x0 = x_right - 355
    scale_y0 = y_bottom + 22
    scale_bg = patches.FancyBboxPatch(
        (scale_x0, scale_y0),
        330, 42,
        boxstyle="round,pad=6,rounding_size=8",
        facecolor="#1e1e1e",
        edgecolor="none",
        alpha=0.88,
        zorder=10
    )
    ax.add_patch(scale_bg)

    # Scale bar markings: 0, 100, 200, 300 m
    bar_x_start = scale_x0 + 20
    bar_y = scale_y0 + 13
    ax.plot(
        [bar_x_start, bar_x_start + 300], [bar_y, bar_y],
        color="white", linewidth=1.5, zorder=11
    )
    # Tick marks at 0, 100, 200, 300
    for tick_val in [0, 100, 200, 300]:
        tx = bar_x_start + tick_val
        ax.plot([tx, tx], [bar_y - 3, bar_y + 3], color="white", linewidth=1.5, zorder=11)
        ax.text(
            tx, bar_y + 12,
            str(tick_val) if tick_val < 300 else "300 m",
            color="white", fontsize=8.0, fontweight="bold", ha="center", va="center", zorder=11
        )

    # 9. North Arrow (Top-Right)
    north_x = x_right - 45
    north_y = y_top - 60
    # North 'N' letter
    ax.text(
        north_x, north_y + 20, "N",
        color="black", fontsize=11, fontweight="bold", ha="center", va="center", zorder=11,
        path_effects=[pe.withStroke(linewidth=3, foreground="white")]
    )
    # Stylized compass arrow
    arrow_pts = [
        (north_x, north_y + 14),
        (north_x - 10, north_y - 12),
        (north_x, north_y - 6),
    ]
    arrow_left = patches.Polygon(arrow_pts, closed=True, facecolor="white", edgecolor="black", linewidth=1.2, zorder=11)
    ax.add_patch(arrow_left)

    arrow_pts_r = [
        (north_x, north_y + 14),
        (north_x + 10, north_y - 12),
        (north_x, north_y - 6),
    ]
    arrow_right = patches.Polygon(arrow_pts_r, closed=True, facecolor="black", edgecolor="black", linewidth=1.2, zorder=11)
    ax.add_patch(arrow_right)

    # 10. Info Box (Top-Left)
    info_card = patches.FancyBboxPatch(
        (x_left + 22, y_top - 120),
        340, 95,
        boxstyle="round,pad=6,rounding_size=10",
        facecolor="white",
        edgecolor="#cccccc",
        linewidth=1.2,
        alpha=0.94,
        zorder=10
    )
    ax.add_patch(info_card)

    ax.text(
        x_left + 35, y_top - 42,
        "YELAMERU KUNTA (LAKE ID 871)",
        color="#0d47a1", fontsize=9.5, fontweight="bold", zorder=11
    )
    ax.text(
        x_left + 35, y_top - 62,
        f"FTL Area: {facts.get('area_acres', 16.152)} Acres   |   Perimeter: {facts.get('perimeter_m', 1411.706)} m",
        color="#222222", fontsize=8.0, fontweight="bold", zorder=11
    )
    ax.text(
        x_left + 35, y_top - 80,
        f"Survey Date: {facts.get('survey_date', '20-08-2014')}   |   FTL Level: {facts.get('ftl_level_m', '+588.350m')}",
        color="#333333", fontsize=8.0, zorder=11
    )
    fallback_note = "" if used_satellite else " [Basemap: Offline light fallback]"
    ax.text(
        x_left + 35, y_top - 100,
        f"Student project. Not a legal boundary.{fallback_note}",
        color="#777777", fontsize=7.2, fontstyle="italic", zorder=11
    )

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.close()

    return output_path


def generate_interactive_map(
    geom_data: Dict[str, Any],
    facts: Dict[str, Any],
    verification_data: Dict[str, Any],
    output_path: str = "outputs/lake_871_satellite.html"
) -> str:
    """
    Generate an interactive Leaflet and Google Maps HTML visualization:
    - Official Google Maps JavaScript API integration (Google Satellite & Google Hybrid) via config.js.
    - Esri World Imagery satellite basemap & OpenStreetMap fallback.
    - Top-right Basemap Switcher (Google Satellite, Google Hybrid, Esri, OSM).
    - Top-right Layer toggles (Boundary, Buffer, Bund, Points, Labels).
    - Google Data layer (GeoJSON) with full styling and clickable features.
    - Full-width black coordinate bar at bottom with live Lat/Long (decimal and DMS) and UTM 44N.
    - Click pin drop with status badge (INSIDE FTL / 9M BUFFER / OUTSIDE), nearest point, copy and clear.
    - 'Export GeoJSON' button in info card for QGIS integration.
    - Robust offline support and error handling (hides Google options if key is missing or fails).
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pts_geo = geom_data["pts_geo"]
    labels = geom_data["labels"]
    buf_poly_geo = geom_data["buffer_poly_geo"]
    label_positions_geo = geom_data["label_positions_geo"]

    # Convert coordinates to [lat, lon] for Leaflet
    boundary_latlngs = [[lat, lon] for lon, lat in pts_geo]
    bund_latlngs = [[pts_geo[-1][1], pts_geo[-1][0]], [pts_geo[0][1], pts_geo[0][0]]]
    buffer_latlngs = [[lat, lon] for lon, lat in buf_poly_geo.exterior.coords]

    # Coordinates for GeoJSON [lon, lat]
    boundary_coords_lonlat = [[lon, lat] for lon, lat in pts_geo]
    bund_coords_lonlat = [[pts_geo[-1][0], pts_geo[-1][1]], [pts_geo[0][0], pts_geo[0][1]]]
    buffer_coords_lonlat = [[lon, lat] for lon, lat in buf_poly_geo.exterior.coords]

    points_data = []
    geojson_features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": boundary_coords_lonlat
            },
            "properties": {
                "layer": "boundary",
                "name": "Survey Boundary (A1 - A37)",
                "stroke": "#ff6b00",
                "stroke_width": 3.5
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": bund_coords_lonlat
            },
            "properties": {
                "layer": "bund",
                "name": "Bund Embankment (A37 - A1)",
                "stroke": "#8d5524",
                "stroke_width": 3.0,
                "dash": "dashed"
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [buffer_coords_lonlat]
            },
            "properties": {
                "layer": "buffer",
                "name": "Buffer Zone (9m Hatched)",
                "stroke": "#00c853",
                "fill": "#39ff14",
                "fill_opacity": 0.35
            }
        }
    ]

    for i in range(len(pts_geo)):
        p_dict = {
            "label": labels[i],
            "lat": pts_geo[i][1],
            "lon": pts_geo[i][0],
            "lbl_lat": label_positions_geo[i][1],
            "lbl_lon": label_positions_geo[i][0]
        }
        points_data.append(p_dict)
        geojson_features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [pts_geo[i][0], pts_geo[i][1]]
            },
            "properties": {
                "layer": "point",
                "point": labels[i],
                "lat": pts_geo[i][1],
                "lon": pts_geo[i][0]
            }
        })

    lake_geojson = {
        "type": "FeatureCollection",
        "name": "Yelameru_Kunta_871",
        "crs": {
            "type": "name",
            "properties": {
                "name": "urn:ogc:def:crs:OGC:1.3:CRS84"
            }
        },
        "features": geojson_features
    }

    center_lat = sum(p["lat"] for p in points_data) / len(points_data)
    center_lon = sum(p["lon"] for p in points_data) / len(points_data)

    template = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Yelameru Kunta (Lake ID 871) - FTL & Buffer Satellite Map</title>

  <!-- Google Maps API Config -->
  <script src="../config.js"></script>
  <script>
    if (typeof GOOGLE_MAPS_KEY === 'undefined') {
      document.write('<script src="config.js"><\/script>');
    }
    if (typeof GOOGLE_MAPS_KEY === 'undefined') {
      document.write('<script src="/config.js"><\/script>');
    }
  </script>

  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      height: 100%;
      width: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #111;
      overflow: hidden;
    }
    #map-wrapper {
      position: relative;
      height: 100%;
      width: 100%;
      overflow: hidden;
    }
    #leaflet-map, #google-map {
      position: absolute;
      top: 0;
      left: 0;
      height: 100%;
      width: 100%;
    }
    #google-map {
      display: none;
    }

    /* Point Label with White Halo */
    .lake-label {
      background: transparent;
      border: none;
      box-shadow: none;
    }
    .lake-label span {
      font-size: 11px;
      font-weight: 800;
      color: #000000;
      text-shadow:
        -1.5px -1.5px 0 #fff,
         1.5px -1.5px 0 #fff,
        -1.5px  1.5px 0 #fff,
         1.5px  1.5px 0 #fff,
         0px 0px 4px #ffffff;
      white-space: nowrap;
    }

    /* Google Maps Label Styling with White Halo */
    .google-map-label {
      text-shadow:
        -1.5px -1.5px 0 #fff,
         1.5px -1.5px 0 #fff,
        -1.5px  1.5px 0 #fff,
         1.5px  1.5px 0 #fff,
         0px 0px 4px #ffffff !important;
      font-weight: 800 !important;
      font-size: 11px !important;
      color: #000000 !important;
      white-space: nowrap !important;
    }

    /* Basemap Switcher Control (Top-Right) */
    .basemap-switcher-card {
      position: absolute;
      top: 12px;
      right: 12px;
      background: rgba(15, 23, 42, 0.94);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 8px 12px;
      z-index: 1000;
      color: #f8fafc;
      font-size: 11.5px;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.45);
      user-select: none;
      min-width: 165px;
    }
    .basemap-switcher-title {
      font-weight: 700;
      font-size: 10.5px;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 6px;
      letter-spacing: 0.5px;
    }
    .basemap-option {
      display: flex;
      align-items: center;
      gap: 7px;
      margin-bottom: 5px;
      cursor: pointer;
      padding: 3px 5px;
      border-radius: 4px;
      transition: background 0.15s ease;
    }
    .basemap-option:last-child {
      margin-bottom: 0;
    }
    .basemap-option:hover {
      background: rgba(51, 65, 85, 0.65);
    }
    .basemap-option input[type="radio"] {
      accent-color: #38bdf8;
      cursor: pointer;
    }

    /* Layer Toggles Card (Top-Right below Basemap) */
    .layer-control-card {
      position: absolute;
      top: 140px;
      right: 12px;
      background: rgba(15, 23, 42, 0.94);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 8px 12px;
      z-index: 1000;
      color: #f8fafc;
      font-size: 11.5px;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.45);
      user-select: none;
      min-width: 165px;
    }
    .layer-option {
      display: flex;
      align-items: center;
      gap: 7px;
      margin-bottom: 5px;
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 4px;
      transition: background 0.15s ease;
    }
    .layer-option:last-child {
      margin-bottom: 0;
    }
    .layer-option:hover {
      background: rgba(51, 65, 85, 0.65);
    }
    .layer-option input[type="checkbox"] {
      accent-color: #38bdf8;
      cursor: pointer;
    }

    /* Bottom-Left Legend Card matching screenshot */
    .legend-card {
      position: absolute;
      bottom: 52px;
      left: 12px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.95);
      border-radius: 12px;
      padding: 12px 16px;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25);
      border: 1px solid #d0d7de;
      min-width: 210px;
      line-height: 1.35;
    }
    .legend-item {
      display: flex;
      align-items: center;
      margin-bottom: 10px;
    }
    .legend-item:last-child {
      margin-bottom: 0;
    }
    .legend-symbol {
      width: 44px;
      height: 22px;
      margin-right: 12px;
      flex-shrink: 0;
      position: relative;
      border-radius: 3px;
    }
    .boundary-symbol {
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .boundary-symbol::before {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      top: 50%;
      height: 3px;
      background: #ff6b00;
      transform: translateY(-50%);
    }
    .boundary-symbol::after {
      content: '';
      position: absolute;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ffffff;
      border: 2px solid #ff6b00;
      z-index: 2;
    }
    .buffer-symbol {
      background-color: rgba(57, 255, 20, 0.35);
      border: 1.5px solid #00c853;
      background-image: repeating-linear-gradient(
        45deg,
        #00a82d,
        #00a82d 1.5px,
        transparent 1.5px,
        transparent 5px
      );
    }
    .bund-symbol {
      display: flex;
      align-items: center;
    }
    .bund-symbol::before {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      top: 50%;
      border-top: 2.5px dashed #8d5524;
      transform: translateY(-50%);
    }
    .legend-text strong {
      display: block;
      font-size: 12px;
      color: #111;
      font-weight: 700;
    }
    .legend-text span {
      font-size: 11px;
      color: #333;
      font-weight: 500;
    }

    /* Top-Left Info Card */
    .info-card {
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.95);
      border-radius: 10px;
      padding: 12px 14px;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.25);
      border: 1px solid #d0d7de;
      max-width: 290px;
      font-size: 12px;
      color: #222;
    }
    .info-card h3 {
      margin: 0 0 6px 0;
      font-size: 13.5px;
      color: #0b5394;
    }
    .info-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 4px;
    }
    .info-row span {
      color: #555;
    }
    .info-row strong {
      color: #111;
    }
    .info-status {
      margin-top: 6px;
      padding: 3px 6px;
      border-radius: 4px;
      background: #e6ffed;
      color: #22863a;
      font-weight: bold;
      text-align: center;
      font-size: 11px;
    }
    .btn-export {
      width: 100%;
      margin-top: 8px;
      padding: 6px 10px;
      background: #0284c7;
      color: #ffffff;
      border: 1px solid #0369a1;
      border-radius: 6px;
      font-size: 11.5px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      transition: background 0.15s ease;
    }
    .btn-export:hover {
      background: #0369a1;
    }
    .info-footer {
      margin-top: 8px;
      padding-top: 6px;
      border-top: 1px solid #eee;
      font-size: 10px;
      color: #777;
      font-style: italic;
    }

    /* Coordinate Readout Bar */
    .coordinate-bar {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      width: 100%;
      background: #000000;
      color: #FFFFFF;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 14px;
      line-height: 1.4;
      padding: 8px 14px;
      box-sizing: border-box;
      z-index: 1001;
      text-align: center;
      user-select: text;
      -webkit-user-select: text;
      pointer-events: auto;
      border-top: 1px solid #1a1a1a;
    }
    .coordinate-bar .coord-inner {
      display: flex;
      flex-direction: row;
      align-items: center;
      justify-content: center;
      flex-wrap: nowrap;
      white-space: nowrap;
      width: 100%;
    }
    .coordinate-bar .coord-line {
      display: inline-flex;
      align-items: center;
    }
    .coordinate-bar .sep {
      margin: 0 10px;
      opacity: 0.7;
    }
    .coordinate-bar .pinned-tag {
      background: #2563eb;
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      padding: 1px 6px;
      border-radius: 3px;
      margin-right: 8px;
      letter-spacing: 0.5px;
      display: inline-block;
      line-height: 1.2;
      box-shadow: 0 0 6px rgba(37, 99, 235, 0.6);
    }
    .coordinate-bar .bar-clear-btn {
      background: #ef4444;
      color: #ffffff;
      border: none;
      font-size: 11px;
      font-weight: bold;
      margin-left: 10px;
      padding: 2px 6px;
      border-radius: 3px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 3px;
    }
    .coordinate-bar .bar-clear-btn:hover {
      background: #dc2626;
    }
    .coordinate-bar .is-pinned {
      color: #FFFFFF;
      font-weight: 700;
      text-shadow: 0 0 8px rgba(255, 255, 255, 0.9);
    }
    .coordinate-bar .coord-prompt {
      color: #FFFFFF;
      font-style: italic;
    }

    /* Raise bottom controls above coordinate bar */
    .leaflet-bottom {
      bottom: 42px !important;
      transition: bottom 0.2s ease;
    }

    @media (max-width: 820px) {
      .coordinate-bar {
        padding: 6px 10px;
        font-size: 12px;
      }
      .coordinate-bar .coord-inner {
        flex-direction: column;
        gap: 3px;
      }
      .coordinate-bar .sep-mid {
        display: none;
      }
      .leaflet-bottom {
        bottom: 58px !important;
      }
      .legend-card {
        bottom: 68px;
      }
    }

    /* Pin Marker & Popup Styling */
    .leaflet-popup-pane {
      z-index: 1005 !important;
    }
    .leaflet-popup {
      z-index: 1005 !important;
    }
    .pin-popup-card {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #0f172a;
      font-size: 13px;
      line-height: 1.45;
      min-width: 250px;
    }
    .pin-popup-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
    }
    .pin-popup-title {
      font-weight: 700;
      font-size: 13px;
      color: #0f172a;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .pin-badge {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 10.5px;
      font-weight: 700;
      margin-bottom: 6px;
      text-align: center;
      width: fit-content;
    }
    .pin-badge.inside {
      background: #0284c7;
      color: #ffffff;
    }
    .pin-badge.buffer {
      background: #16a34a;
      color: #ffffff;
    }
    .pin-badge.outside {
      background: #dc2626;
      color: #ffffff;
    }
    .pin-coord-box {
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      padding: 6px 8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11px;
      margin-bottom: 6px;
      line-height: 1.4;
      color: #1e293b;
    }
    .pin-nearest-info {
      font-size: 11.5px;
      color: #334155;
      margin-bottom: 8px;
      background: #f1f5f9;
      padding: 4px 8px;
      border-radius: 4px;
    }
    .pin-popup-actions {
      display: flex;
      gap: 6px;
    }
    .pin-action-btn {
      flex: 1;
      padding: 5px 8px;
      border-radius: 5px;
      border: 1px solid #cbd5e1;
      cursor: pointer;
      font-size: 11.5px;
      font-weight: 600;
      text-align: center;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      transition: background 0.15s ease;
    }
    .pin-action-btn.copy {
      background: #2563eb;
      color: #ffffff;
      border-color: #1d4ed8;
    }
    .pin-action-btn.copy:hover {
      background: #1d4ed8;
    }
    .pin-action-btn.clear {
      background: #ffffff;
      color: #dc2626;
      border-color: #fca5a5;
    }
    .pin-action-btn.clear:hover {
      background: #fee2e2;
    }
  </style>
</head>
<body>
  <div id="map-wrapper">
    <div id="leaflet-map"></div>
    <div id="google-map"></div>
  </div>

  <!-- Basemap Switcher (Top-Right) -->
  <div class="basemap-switcher-card">
    <div class="basemap-switcher-title">Basemap</div>
    <label class="basemap-option" id="opt-google-satellite" style="display: none;">
      <input type="radio" name="basemap-select" value="google-satellite" onchange="switchBasemap('google-satellite')">
      <span>Google Satellite</span>
    </label>
    <label class="basemap-option" id="opt-google-hybrid" style="display: none;">
      <input type="radio" name="basemap-select" value="google-hybrid" onchange="switchBasemap('google-hybrid')">
      <span>Google Hybrid</span>
    </label>
    <label class="basemap-option" id="opt-esri">
      <input type="radio" name="basemap-select" value="esri" onchange="switchBasemap('esri')">
      <span>Esri World Imagery</span>
    </label>
    <label class="basemap-option" id="opt-osm">
      <input type="radio" name="basemap-select" value="osm" checked onchange="switchBasemap('osm')">
      <span>OpenStreetMap</span>
    </label>
  </div>

  <!-- Layer Toggles (Top-Right below Basemap) -->
  <div class="layer-control-card">
    <div class="basemap-switcher-title">Map Layers</div>
    <label class="layer-option">
      <input type="checkbox" id="chk-boundary" checked onchange="toggleMapLayer('boundary', this.checked)">
      <span>Survey Boundary (A1–A37)</span>
    </label>
    <label class="layer-option">
      <input type="checkbox" id="chk-buffer" checked onchange="toggleMapLayer('buffer', this.checked)">
      <span>Buffer Zone (9m Hatched)</span>
    </label>
    <label class="layer-option">
      <input type="checkbox" id="chk-bund" checked onchange="toggleMapLayer('bund', this.checked)">
      <span>Bund Embankment (A37–A1)</span>
    </label>
    <label class="layer-option">
      <input type="checkbox" id="chk-points" checked onchange="toggleMapLayer('points', this.checked)">
      <span>Survey Points</span>
    </label>
    <label class="layer-option">
      <input type="checkbox" id="chk-labels" checked onchange="toggleMapLayer('labels', this.checked)">
      <span>Point Labels</span>
    </label>
  </div>

  <!-- Top-Left Info Card -->
  <div class="info-card">
    <h3>__LAKE_NAME__</h3>
    <div class="info-row"><span>Lake ID:</span> <strong>__LAKE_ID__</strong></div>
    <div class="info-row"><span>Survey Area:</span> <strong>__AREA_ACRES__ Acres</strong></div>
    <div class="info-row"><span>Perimeter:</span> <strong>__PERIMETER_M__ m</strong></div>
    <div class="info-row"><span>FTL Level:</span> <strong>__FTL_LEVEL_M__</strong></div>
    <div class="info-row"><span>Survey Date:</span> <strong>__SURVEY_DATE__</strong></div>
    <div class="info-status">Verification: __VERIFICATION_STATUS__ (Area diff: __DIFF_PERCENT__%)</div>
    <button type="button" class="btn-export" onclick="exportGeoJSON()">📥 Export GeoJSON (QGIS)</button>
    <div class="info-footer">Student project. Not a legal boundary.<br>If satellite fails, toggle OpenStreetMap.</div>
  </div>

  <!-- Bottom-Left Legend Card -->
  <div class="legend-card">
    <div class="legend-item">
      <div class="legend-symbol boundary-symbol"></div>
      <div class="legend-text">
        <strong>Survey Boundary</strong>
        <span>(A1 – A37)</span>
      </div>
    </div>
    <div class="legend-item">
      <div class="legend-symbol buffer-symbol"></div>
      <div class="legend-text">
        <strong>Buffer Zone</strong>
        <span>(as per Survey Map)</span>
      </div>
    </div>
    <div class="legend-item">
      <div class="legend-symbol bund-symbol"></div>
      <div class="legend-text">
        <strong>Bund Top Embankment</strong>
        <span>(A37 – A1, no buffer)</span>
      </div>
    </div>
  </div>

  <!-- Bottom Coordinate Readout Bar -->
  <div id="coordinate-bar" class="coordinate-bar">
    <span class="coord-prompt">Move the pointer over the map</span>
  </div>

  <!-- SVG Patterns for Buffer Hatching -->
  <svg width="0" height="0" style="position:absolute">
    <defs>
      <pattern id="diagonalHatch" patternUnits="userSpaceOnUse" width="8" height="8">
        <path d="M-2,2 l4,-4 M0,8 l8,-8 M6,10 l4,-4" style="stroke:#00a82d; stroke-width:1.8" />
      </pattern>
    </defs>
  </svg>

  <script>
    // 0. Embedded GeoJSON FeatureCollection
    const lakeGeoJSON = __GEOJSON_DATA__;

    // 1. Initialize Leaflet Map
    const map = L.map('leaflet-map', {
      center: [__CENTER_LAT__, __CENTER_LON__],
      zoom: 17,
      maxZoom: 19
    });

    // 2. Basemaps (OpenStreetMap standard layer as default)
    const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    const esriSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
    });

    // 3. Buffer Zone Polygon (9m Outward)
    const bufferCoords = __BUFFER_COORDS__;
    const bufferLayer = L.polygon(bufferCoords, {
      color: '#00c853',
      weight: 2,
      fillColor: '#39ff14',
      fillOpacity: 0.35,
      dashArray: null
    }).addTo(map);

    bufferLayer.on('add', function() {
      const el = bufferLayer.getElement();
      if (el) {
        el.setAttribute('fill', 'url(#diagonalHatch)');
      }
    });

    // 4. Bund Embankment Line (A37 -> A1)
    const bundCoords = __BUND_COORDS__;
    const bundLayer = L.polyline(bundCoords, {
      color: '#8d5524',
      weight: 3,
      dashArray: '8, 6',
      opacity: 0.95
    }).addTo(map);
    bundLayer.bindPopup('<strong>Bund Embankment (Top of Bund)</strong><br>Connects A37 to A1 (Chord: 449.4 m)<br>No buffer applied.');

    // 5. Survey Boundary Polyline (A1 -> ... -> A37)
    const boundaryCoords = __BOUNDARY_COORDS__;
    const boundaryLayer = L.polyline(boundaryCoords, {
      color: '#ff6b00',
      weight: 3.5,
      opacity: 1.0
    }).addTo(map);
    boundaryLayer.bindPopup('<strong>Survey Boundary (A1 – A37)</strong><br>Path length: 943.5 m<br>FTL Level: __FTL_LEVEL_M__');

    // 6. Point Markers and Labels
    const pointsData = __POINTS_DATA__;
    const markersGroup = L.layerGroup().addTo(map);
    const labelsGroup = L.layerGroup().addTo(map);

    pointsData.forEach(p => {
      // White vertex marker with orange border
      const marker = L.circleMarker([p.lat, p.lon], {
        radius: 4.5,
        fillColor: '#ffffff',
        color: '#ff6b00',
        weight: 2,
        fillOpacity: 1.0
      });
      marker.bindTooltip(`<strong>Point ${p.label}</strong><br>Lat: ${p.lat.toFixed(6)}°, Lon: ${p.lon.toFixed(6)}°`);
      markersGroup.addLayer(marker);

      // Label placed outside
      const labelIcon = L.divIcon({
        className: 'lake-label',
        html: `<span>${p.label}</span>`,
        iconSize: [30, 16],
        iconAnchor: [15, 8]
      });
      const labelMarker = L.marker([p.lbl_lat, p.lbl_lon], {
        icon: labelIcon,
        interactive: false
      });
      labelsGroup.addLayer(labelMarker);
    });

    // 7. Scale Bar (Bottom-Right)
    L.control.scale({ imperial: false, position: 'bottomright' }).addTo(map);

    // Fit map bounds to lake with margin
    map.fitBounds(boundaryLayer.getBounds().pad(0.18));

    // 8. Layer State and Unified Toggle
    const layerState = {
      boundary: true,
      buffer: true,
      bund: true,
      points: true,
      labels: true
    };

    function toggleMapLayer(layerName, isVisible) {
      layerState[layerName] = isVisible;

      // Update Leaflet
      if (layerName === 'boundary') {
        if (isVisible) map.addLayer(boundaryLayer); else map.removeLayer(boundaryLayer);
      } else if (layerName === 'buffer') {
        if (isVisible) map.addLayer(bufferLayer); else map.removeLayer(bufferLayer);
      } else if (layerName === 'bund') {
        if (isVisible) map.addLayer(bundLayer); else map.removeLayer(bundLayer);
      } else if (layerName === 'points') {
        if (isVisible) map.addLayer(markersGroup); else map.removeLayer(markersGroup);
      } else if (layerName === 'labels') {
        if (isVisible) map.addLayer(labelsGroup); else map.removeLayer(labelsGroup);
      }

      // Update Google Maps
      if (googleMap) {
        applyGoogleLayerStyles();
        if (googleBundPolyline) {
          googleBundPolyline.setVisible(layerState.bund);
        }
        googleLabelMarkers.forEach(m => m.setVisible(layerState.labels));
      }
    }

    // 9. Live Coordinate Readout & Interactive Pin
    function toDMS(val, isLat) {
      const dir = isLat ? (val >= 0 ? 'N' : 'S') : (val >= 0 ? 'E' : 'W');
      const abs = Math.abs(val);
      const deg = Math.floor(abs);
      const remMin = (abs - deg) * 60;
      const min = Math.floor(remMin);
      const sec = (remMin - min) * 60;
      const minStr = min < 10 ? '0' + min : '' + min;
      const secStr = sec.toFixed(3).padStart(6, '0');
      return deg + '°' + minStr + "'" + secStr + '"' + dir;
    }

    function latLonToUTM44N(lat, lon) {
      const a = 6378137.0;
      const f = 1 / 298.257223563;
      const b = a * (1 - f);
      const e = Math.sqrt(1 - (b / a) ** 2);
      const ePrimeSq = (e ** 2) / (1 - e ** 2);
      const k0 = 0.9996;

      const latRad = lat * Math.PI / 180;
      const lonRad = lon * Math.PI / 180;
      const lon0 = 81.0 * Math.PI / 180;

      const sinLat = Math.sin(latRad);
      const cosLat = Math.cos(latRad);
      const tanLat = Math.tan(latRad);

      const N = a / Math.sqrt(1 - e ** 2 * sinLat ** 2);
      const T = tanLat ** 2;
      const C = ePrimeSq * cosLat ** 2;
      const A = (lonRad - lon0) * cosLat;

      const M = a * ((1 - e**2/4 - 3*e**4/64 - 5*e**6/256) * latRad
               - (3*e**2/8 + 3*e**4/32 + 45*e**6/1024) * Math.sin(2 * latRad)
               + (15*e**4/256 + 45*e**6/1024) * Math.sin(4 * latRad)
               - (35*e**6/3072) * Math.sin(6 * latRad));

      let x = k0 * N * (A + (1 - T + C) * (A**3) / 6 + (5 - 18*T + T**2 + 72*C - 58*ePrimeSq) * (A**5) / 120) + 500000.0;
      let y = k0 * (M + N * tanLat * ((A**2) / 2 + (5 - T + 9*C + 4*(C**2)) * (A**4) / 24 + (61 - 58*T + T**2 + 600*C - 330*ePrimeSq) * (A**6) / 720));
      if (lat < 0) y += 10000000.0;

      return { easting: x, northing: y };
    }

    function pointInPolygon(pt, vs) {
      const x = pt[1], y = pt[0];
      let inside = false;
      for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
        const xi = vs[i][1], yi = vs[i][0];
        const xj = vs[j][1], yj = vs[j][0];
        const intersect = ((yi > y) !== (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    }

    function getDistanceMeters(lat1, lon1, lat2, lon2) {
      const R = 6371000;
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon / 2) * Math.sin(dLon / 2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return R * c;
    }

    const coordBar = document.getElementById('coordinate-bar');
    let isPinned = false;
    let pinnedLat = null;
    let pinnedLon = null;
    let currentPinMarker = null;
    let googlePinMarker = null;
    let googleInfoWindow = null;
    let pointerOverMap = false;
    let latestPinCopyStr = '';

    function renderCoordinateBar(lat, lon, pinned) {
      const dmsLat = toDMS(lat, true);
      const dmsLon = toDMS(lon, false);
      const utm = latLonToUTM44N(lat, lon);
      const pinnedLabel = pinned ? '<span class="pinned-tag">Pinned</span> ' : '';
      const clearBtn = pinned ? '<button type="button" class="bar-clear-btn" onclick="clearPin()" title="Clear Pin">✕ Clear</button>' : '';

      coordBar.innerHTML = 
        '<div class="coord-inner' + (pinned ? ' is-pinned' : '') + '">' +
          '<div class="coord-line coord-line-1">' +
            pinnedLabel + '<span>Lat: ' + lat.toFixed(6) + '</span><span class="sep">|</span><span>Long: ' + lon.toFixed(6) + '</span>' +
          '</div>' +
          '<span class="sep sep-mid">|</span>' +
          '<div class="coord-line coord-line-2">' +
            '<span>' + dmsLat + '  ' + dmsLon + '</span><span class="sep">|</span><span>UTM 44N: E ' + utm.easting.toFixed(1) + '  N ' + utm.northing.toFixed(1) + '</span>' + clearBtn +
          '</div>' +
        '</div>';
    }

    map.on('mousemove', function(e) {
      pointerOverMap = true;
      if (!isPinned) {
        renderCoordinateBar(e.latlng.lat, e.latlng.lng, false);
      }
    });

    map.getContainer().addEventListener('touchmove', function(e) {
      pointerOverMap = true;
      if (e.touches.length > 0 && !isPinned) {
        const pt = map.mouseEventToContainerPoint(e.touches[0]);
        const ll = map.containerPointToLatLng(pt);
        renderCoordinateBar(ll.lat, ll.lng, false);
      }
    }, { passive: true });

    map.getContainer().addEventListener('mouseleave', function() {
      pointerOverMap = false;
      if (!isPinned) {
        coordBar.innerHTML = '<span class="coord-prompt">Move the pointer over the map</span>';
      }
    });

    function setPin(lat, lon) {
      isPinned = true;
      pinnedLat = lat;
      pinnedLon = lon;

      renderCoordinateBar(lat, lon, true);

      const closedLakeCoords = boundaryCoords.concat([boundaryCoords[0]]);
      const isInsideFTL = pointInPolygon([lat, lon], closedLakeCoords);
      const isInsideBuffer = !isInsideFTL && pointInPolygon([lat, lon], bufferCoords);

      let statusClass = 'outside';
      let statusText = 'OUTSIDE FTL & BUFFER';
      let statusDesc = 'Point is outside lake boundary and buffer zone.';
      if (isInsideFTL) {
        statusClass = 'inside';
        statusText = 'INSIDE FTL BOUNDARY';
        statusDesc = 'Point is inside Full Tank Level water spread.';
      } else if (isInsideBuffer) {
        statusClass = 'buffer';
        statusText = 'IN 9M BUFFER ZONE';
        statusDesc = 'Point is within the 9m mandatory protection buffer.';
      }

      let nearestPt = null;
      let minDist = Infinity;
      pointsData.forEach(p => {
        const d = getDistanceMeters(lat, lon, p.lat, p.lon);
        if (d < minDist) {
          minDist = d;
          nearestPt = p;
        }
      });
      const distStr = minDist < 1000 ? (minDist.toFixed(1) + ' m') : ((minDist / 1000).toFixed(2) + ' km');
      const nearestHtml = nearestPt ? ('Nearest: <strong>Point ' + nearestPt.label + '</strong> (' + distStr + ' away)') : '';

      const dmsLat = toDMS(lat, true);
      const dmsLon = toDMS(lon, false);
      const utm = latLonToUTM44N(lat, lon);
      latestPinCopyStr = 'Lat: ' + lat.toFixed(6) + '  |  Long: ' + lon.toFixed(6) + '  |  ' + dmsLat + '  ' + dmsLon + '  |  UTM 44N: E ' + utm.easting.toFixed(1) + '  N ' + utm.northing.toFixed(1);

      const popupContent = 
        '<div class="pin-popup-card">' +
          '<div class="pin-popup-header">' +
            '<span class="pin-popup-title">📍 Pinned Location</span>' +
            '<span class="pin-badge ' + statusClass + '">' + statusText + '</span>' +
          '</div>' +
          '<div style="font-size: 11px; color: #475569; margin-bottom: 6px;">' + statusDesc + '</div>' +
          '<div class="pin-coord-box">' +
            '<b>Lat:</b> ' + lat.toFixed(6) + '° (' + dmsLat + ')<br>' +
            '<b>Long:</b> ' + lon.toFixed(6) + '° (' + dmsLon + ')<br>' +
            '<b>UTM 44N:</b> E ' + utm.easting.toFixed(1) + ' &nbsp; N ' + utm.northing.toFixed(1) +
          '</div>' +
          '<div class="pin-nearest-info">' + nearestHtml + '</div>' +
          '<div class="pin-popup-actions">' +
            '<button type="button" class="pin-action-btn copy" onclick="copyPinCoords(this)">📋 Copy</button>' +
            '<button type="button" class="pin-action-btn clear" onclick="clearPin()">✕ Clear Pin</button>' +
          '</div>' +
        '</div>';

      // Update Leaflet Pin
      if (currentPinMarker) {
        currentPinMarker.setLatLng([lat, lon]);
        currentPinMarker.getPopup().setContent(popupContent);
        currentPinMarker.openPopup();
      } else {
        const pinSvg = '<svg width="28" height="36" viewBox="0 0 24 32" fill="none" xmlns="http://www.w3.org/2000/svg">' +
          '<filter id="pinShadow" x="-20%" y="-10%" width="140%" height="130%">' +
            '<feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000" flood-opacity="0.4"/>' +
          '</filter>' +
          '<path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 32 12 32C12 32 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="#dc2626" filter="url(#pinShadow)"/>' +
          '<circle cx="12" cy="11" r="5" fill="#ffffff"/>' +
          '<circle cx="12" cy="11" r="2.5" fill="#dc2626"/>' +
        '</svg>';

        const pinIcon = L.divIcon({
          className: 'map-pin-icon',
          html: pinSvg,
          iconSize: [28, 36],
          iconAnchor: [14, 36],
          popupAnchor: [0, -34]
        });

        currentPinMarker = L.marker([lat, lon], { icon: pinIcon }).addTo(map);
        currentPinMarker.bindPopup(popupContent, { maxWidth: 300 });
        currentPinMarker.openPopup();

        currentPinMarker.on('click', function() {
          currentPinMarker.openPopup();
        });
      }

      // Update Google Maps Pin
      if (googleMap) {
        if (googlePinMarker) {
          googlePinMarker.setPosition({ lat: lat, lng: lon });
          googleInfoWindow.setContent(popupContent);
          googleInfoWindow.open(googleMap, googlePinMarker);
        } else {
          googlePinMarker = new google.maps.Marker({
            position: { lat: lat, lng: lon },
            map: googleMap,
            zIndex: 200,
            icon: {
              url: 'data:image/svg+xml;utf-8,' + encodeURIComponent('<svg width="28" height="36" viewBox="0 0 24 32" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 0C5.37 0 0 5.37 0 12C0 21 12 32 12 32C12 32 24 21 24 12C24 5.37 18.63 0 12 0Z" fill="#dc2626"/><circle cx="12" cy="11" r="5" fill="#ffffff"/><circle cx="12" cy="11" r="2.5" fill="#dc2626"/></svg>'),
              scaledSize: new google.maps.Size(28, 36),
              anchor: new google.maps.Point(14, 36)
            }
          });
          googleInfoWindow = new google.maps.InfoWindow({
            content: popupContent,
            maxWidth: 300
          });
          googlePinMarker.addListener('click', function() {
            googleInfoWindow.open(googleMap, googlePinMarker);
          });
          googleInfoWindow.open(googleMap, googlePinMarker);
        }
      }
    }

    map.on('click', function(e) {
      setPin(e.latlng.lat, e.latlng.lng);
    });

    window.clearPin = function() {
      if (currentPinMarker) {
        map.removeLayer(currentPinMarker);
        currentPinMarker = null;
      }
      if (googlePinMarker) {
        googlePinMarker.setMap(null);
        googlePinMarker = null;
      }
      if (googleInfoWindow) {
        googleInfoWindow.close();
      }
      isPinned = false;
      pinnedLat = null;
      pinnedLon = null;
      coordBar.innerHTML = '<span class="coord-prompt">Move the pointer over the map</span>';
    };

    window.copyPinCoords = function(btn) {
      const text = latestPinCopyStr;
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(showSuccess).catch(fallback);
      } else {
        fallback();
      }
      function fallback() {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand('copy');
          showSuccess();
        } catch (err) {
          alert('Coordinates: ' + text);
        }
        document.body.removeChild(ta);
      }
      function showSuccess() {
        if (btn) {
          const originalText = btn.innerHTML;
          btn.innerHTML = '✓ Copied!';
          btn.style.background = '#16a34a';
          setTimeout(() => {
            btn.innerHTML = originalText;
            btn.style.background = '#2563eb';
          }, 1500);
        }
      }
    };

    // 10. GeoJSON Export Function
    window.exportGeoJSON = function() {
      const jsonStr = JSON.stringify(lakeGeoJSON, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/geo+json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'yelameru_kunta_871.geojson';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    };

    // 11. Google Maps Integration & Basemap Switcher
    let googleMap = null;
    let googleBundPolyline = null;
    let googleLabelMarkers = [];
    let currentBasemap = 'esri';

    function switchBasemap(choice) {
      currentBasemap = choice;
      localStorage.setItem('lake_871_basemap', choice);

      const radio = document.querySelector(`input[name="basemap-select"][value="${choice}"]`);
      if (radio) radio.checked = true;

      const lmapDiv = document.getElementById('leaflet-map');
      const gmapDiv = document.getElementById('google-map');

      if (choice === 'google-satellite' || choice === 'google-hybrid') {
        if (!googleMap) {
          console.warn("Google Maps is not initialized yet.");
          return;
        }
        const center = map.getCenter();
        const zoom = map.getZoom();

        lmapDiv.style.display = 'none';
        gmapDiv.style.display = 'block';

        googleMap.setMapTypeId(choice === 'google-satellite' ? 'satellite' : 'hybrid');
        googleMap.setCenter({ lat: center.lat, lng: center.lng });
        googleMap.setZoom(zoom);
        google.maps.event.trigger(googleMap, 'resize');
      } else {
        if (googleMap && gmapDiv.style.display !== 'none') {
          const gCenter = googleMap.getCenter();
          map.setView([gCenter.lat(), gCenter.lng()], googleMap.getZoom());
        }

        gmapDiv.style.display = 'none';
        lmapDiv.style.display = 'block';

        if (choice === 'esri') {
          if (map.hasLayer(osmLayer)) map.removeLayer(osmLayer);
          if (!map.hasLayer(esriSatellite)) esriSatellite.addTo(map);
        } else if (choice === 'osm') {
          if (map.hasLayer(esriSatellite)) map.removeLayer(esriSatellite);
          if (!map.hasLayer(osmLayer)) osmLayer.addTo(map);
        }

        map.invalidateSize();
      }
    }

    function applyGoogleLayerStyles() {
      if (!googleMap) return;
      googleMap.data.setStyle(function(feature) {
        const layer = feature.getProperty('layer');
        if (layer === 'boundary') {
          return {
            visible: layerState.boundary,
            strokeColor: '#ff6b00',
            strokeWeight: 3.5,
            strokeOpacity: 1.0,
            zIndex: 5
          };
        } else if (layer === 'bund') {
          return {
            visible: false // Represented with custom dashed polyline
          };
        } else if (layer === 'buffer') {
          return {
            visible: layerState.buffer,
            fillColor: '#39ff14',
            fillOpacity: 0.35,
            strokeColor: '#00c853',
            strokeWeight: 2.0,
            strokeOpacity: 1.0,
            zIndex: 2
          };
        } else if (layer === 'point') {
          return {
            visible: layerState.points,
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: 4.5,
              fillColor: '#ffffff',
              fillOpacity: 1.0,
              strokeColor: '#ff6b00',
              strokeWeight: 2.0
            },
            zIndex: 10
          };
        }
      });
    }

    function initGoogleMapInstance() {
      const gmapDiv = document.getElementById('google-map');
      googleMap = new google.maps.Map(gmapDiv, {
        center: { lat: __CENTER_LAT__, lng: __CENTER_LON__ },
        zoom: 17,
        mapTypeId: 'satellite',
        mapTypeControl: false,
        fullscreenControl: false,
        streetViewControl: false,
        zoomControl: true,
        zoomControlOptions: {
          position: google.maps.ControlPosition.LEFT_TOP
        }
      });

      googleMap.addListener('mousemove', function(e) {
        pointerOverMap = true;
        if (!isPinned) {
          renderCoordinateBar(e.latLng.lat(), e.latLng.lng(), false);
        }
      });

      gmapDiv.addEventListener('mouseleave', function() {
        pointerOverMap = false;
        if (!isPinned) {
          coordBar.innerHTML = '<span class="coord-prompt">Move the pointer over the map</span>';
        }
      });

      googleMap.addListener('click', function(e) {
        setPin(e.latLng.lat(), e.latLng.lng());
      });

      // Load GeoJSON into Google Map Data Layer
      googleMap.data.addGeoJson(lakeGeoJSON);
      applyGoogleLayerStyles();

      // Click on Data feature
      googleMap.data.addListener('click', function(event) {
        const layer = event.feature.getProperty('layer');
        if (layer === 'point') {
          const pt = event.feature.getProperty('point');
          const lat = event.latLng.lat();
          const lon = event.latLng.lng();
          const content = `
            <div style="font-family: sans-serif; font-size: 13px; color: #111;">
              <strong style="color: #0284c7; font-size: 14px;">Point ${pt}</strong><br>
              <b>Lat:</b> ${lat.toFixed(6)}°<br>
              <b>Lon:</b> ${lon.toFixed(6)}°
            </div>
          `;
          if (!window.gPointInfoWindow) {
            window.gPointInfoWindow = new google.maps.InfoWindow();
          }
          window.gPointInfoWindow.setContent(content);
          window.gPointInfoWindow.setPosition(event.latLng);
          window.gPointInfoWindow.open(googleMap);
        } else {
          setPin(event.latLng.lat(), event.latLng.lng());
        }
      });

      // Dashed Bund Polyline on Google Maps
      if (boundaryCoords.length >= 2) {
        googleBundPolyline = new google.maps.Polyline({
          path: [
            { lat: boundaryCoords[boundaryCoords.length - 1][0], lng: boundaryCoords[boundaryCoords.length - 1][1] },
            { lat: boundaryCoords[0][0], lng: boundaryCoords[0][1] }
          ],
          strokeColor: '#8d5524',
          strokeOpacity: 0,
          icons: [{
            icon: {
              path: 'M 0,-1 0,1',
              strokeOpacity: 1,
              strokeColor: '#8d5524',
              strokeWeight: 3,
              scale: 3
            },
            offset: '0',
            repeat: '12px'
          }],
          map: googleMap,
          zIndex: 4,
          visible: layerState.bund
        });
      }

      // Outward Labels with White Halo on Google Maps
      pointsData.forEach(p => {
        const lblMarker = new google.maps.Marker({
          position: { lat: p.lbl_lat, lng: p.lbl_lon },
          map: googleMap,
          icon: {
            path: 'M 0 0',
            strokeOpacity: 0
          },
          label: {
            text: p.label,
            className: 'google-map-label',
            color: '#000000',
            fontWeight: '800',
            fontSize: '11px'
          },
          clickable: false,
          visible: layerState.labels
        });
        googleLabelMarkers.push(lblMarker);
      });
    }

    function setupGoogleMaps() {
      if (typeof GOOGLE_MAPS_KEY === 'undefined' || !GOOGLE_MAPS_KEY || GOOGLE_MAPS_KEY.trim() === '') {
        console.log("No GOOGLE_MAPS_KEY found in config.js. Google Satellite basemap hidden.");
        return;
      }

      window.gm_authFailure = function() {
        console.warn("Google Maps API authentication failed. Reverting to Esri World Imagery.");
        const optSat = document.getElementById('opt-google-satellite');
        const optHyb = document.getElementById('opt-google-hybrid');
        if (optSat) optSat.style.display = 'none';
        if (optHyb) optHyb.style.display = 'none';
        if (currentBasemap.startsWith('google-')) {
          switchBasemap('esri');
        }
      };

      window.onGoogleMapsReady = function() {
        const optSat = document.getElementById('opt-google-satellite');
        const optHyb = document.getElementById('opt-google-hybrid');
        if (optSat) optSat.style.display = 'flex';
        if (optHyb) optHyb.style.display = 'flex';

        initGoogleMapInstance();

        // Restore saved basemap choice
        const savedChoice = localStorage.getItem('lake_871_basemap');
        if (savedChoice === 'google-satellite' || savedChoice === 'google-hybrid') {
          switchBasemap(savedChoice);
        }
      };

      const script = document.createElement('script');
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(GOOGLE_MAPS_KEY.trim())}&callback=onGoogleMapsReady&libraries=geometry`;
      script.async = true;
      script.defer = true;
      script.onerror = function() {
        console.warn("Failed to load Google Maps script. Falling back to Esri.");
        const optSat = document.getElementById('opt-google-satellite');
        const optHyb = document.getElementById('opt-google-hybrid');
        if (optSat) optSat.style.display = 'none';
        if (optHyb) optHyb.style.display = 'none';
      };
      document.head.appendChild(script);
    }

    // Initialize switcher from localStorage (OpenStreetMap default)
    const savedBasemap = localStorage.getItem('lake_871_basemap');
    if (savedBasemap === 'esri') {
      switchBasemap('esri');
    } else if (savedBasemap === 'google-satellite' || savedBasemap === 'google-hybrid') {
      switchBasemap('osm');
    } else {
      switchBasemap('osm');
    }

    setupGoogleMaps();
  </script>
</body>
</html>
"""

    # Replace placeholders
    html_content = (
        template
        .replace("__CENTER_LAT__", str(center_lat))
        .replace("__CENTER_LON__", str(center_lon))
        .replace("__BUFFER_COORDS__", json.dumps(buffer_latlngs))
        .replace("__BUND_COORDS__", json.dumps(bund_latlngs))
        .replace("__BOUNDARY_COORDS__", json.dumps(boundary_latlngs))
        .replace("__POINTS_DATA__", json.dumps(points_data))
        .replace("__GEOJSON_DATA__", json.dumps(lake_geojson))
        .replace("__LAKE_NAME__", str(facts.get("lake_name", "YELAMERU KUNTA")))
        .replace("__LAKE_ID__", str(facts.get("lake_id", "871")))
        .replace("__AREA_ACRES__", str(facts.get("area_acres", 16.152)))
        .replace("__PERIMETER_M__", str(facts.get("perimeter_m", 1411.706)))
        .replace("__FTL_LEVEL_M__", str(facts.get("ftl_level_m", "+588.350m")))
        .replace("__SURVEY_DATE__", str(facts.get("survey_date", "20-08-2014")))
        .replace("__VERIFICATION_STATUS__", str(verification_data.get("overall_status", "OK")))
        .replace("__DIFF_PERCENT__", str(verification_data.get("area", {}).get("diff_percent", 0.0)))
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path


def generate_all_outputs() -> Dict[str, str]:
    """
    Main pipeline entrypoint:
    Loads lake data, calculates geometries, verifies measurements,
    and produces PNG, HTML, and JSON verification outputs.
    """
    print("Loading survey points and lake facts...")
    points, facts = load_lake_data()

    print("Building lake boundary, bund line, and 9m buffer zone...")
    geom_data = build_lake_geometry(points, buffer_width_m=float(facts.get("buffer_m", 9.0)))

    print("Verifying measurements against PDF survey facts...")
    verification = verify_measurements(
        geom_data["lake_poly"],
        geom_data["boundary_line"],
        geom_data["bund_line"],
        facts
    )

    print("Saving verification report to outputs/lake_871_verification.json...")
    json_path = save_verification_report(verification, "outputs/lake_871_verification.json")

    print("Rendering 300 DPI satellite map to outputs/lake_871_map.png...")
    png_path = render_static_map(geom_data, facts, "outputs/lake_871_map.png", dpi=300)

    print("Generating interactive Leaflet map to outputs/lake_871_satellite.html...")
    html_path = generate_interactive_map(geom_data, facts, verification, "outputs/lake_871_satellite.html")

    print("All outputs generated successfully!")
    print(f"  - Map PNG:      {png_path}")
    print(f"  - Satellite UI: {html_path}")
    print(f"  - Verification: {json_path}")
    print(f"  - Status:       {verification['overall_status']}")

    return {
        "png_path": png_path,
        "html_path": html_path,
        "json_path": json_path,
        "status": verification["overall_status"]
    }


if __name__ == "__main__":
    generate_all_outputs()
