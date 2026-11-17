"""
Generic Satellite-style Map Pipeline and GeoJSON Generator for HMDA Lakes.

Supports ~500 lakes without per-lake code:
1. Loads survey points, facts, and optional bund points from lakes/<id>/ (or legacy data/).
2. Auto-determines UTM zone (EPSG:32643 or EPSG:32644) from coordinates.
3. Builds verified FTL polygon, 9m outward buffer, and bund line (straight or curved).
4. Exports complete lakes/<id>/lake.geojson so the viewer requires zero other computed data.
5. Generates high-res static map (outputs/lake_<id>_map.png) and interactive view.
6. Builds lakes/index.json catalog.

Student project. Not a legal boundary.
"""

import os
import sys
import json
import csv
import math
from typing import List, Tuple, Dict, Any, Optional

# Matplotlib configuration for headless environment
os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.patheffects as pe
from PIL import Image
import numpy as np
import pyproj
import shapely
from shapely.geometry import LineString, Polygon, Point

from src.geo import (
    dms_to_decimal,
    get_utm_epsg,
    build_polygon,
    build_lake_path,
    SQM_PER_ACRE
)


def load_lake_data(
    points_csv_path: str = "data/871_points.csv",
    facts_json_path: str = "data/871_facts.json",
    lake_id: Optional[str] = None,
    lakes_dir: str = "lakes"
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Load survey points and lake facts. Supports both legacy data/ paths and
    standard lakes/<id>/ paths. Automatically determines UTM zone.

    Returns:
        (points_list, facts_dict)
    """
    # If lake_id specified, prefer lakes/<lake_id>/
    if lake_id:
        p_path = os.path.join(lakes_dir, str(lake_id), "points.csv")
        f_path = os.path.join(lakes_dir, str(lake_id), "facts.json")
        if os.path.exists(p_path):
            points_csv_path = p_path
        if os.path.exists(f_path):
            facts_json_path = f_path
    elif not os.path.exists(points_csv_path):
        # Fallback to lakes/871/ if data/871_points.csv is missing
        alt_p = os.path.join(lakes_dir, "871", "points.csv")
        alt_f = os.path.join(lakes_dir, "871", "facts.json")
        if os.path.exists(alt_p):
            points_csv_path = alt_p
        if os.path.exists(alt_f):
            facts_json_path = alt_f

    if not os.path.exists(points_csv_path):
        raise FileNotFoundError(f"Points file not found: {points_csv_path}")
    if not os.path.exists(facts_json_path):
        raise FileNotFoundError(f"Facts file not found: {facts_json_path}")

    # First pass: read raw coordinates and determine UTM zone from first point
    raw_points = []
    with open(points_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            point_id = row.get("point") or row.get("TEXT") or row.get("id") or ""
            lat_dms = row.get("lat_dms") or row.get("LATITUDE") or ""
            lon_dms = row.get("lon_dms") or row.get("LONGITUDE") or ""
            dist_val = row.get("distance_m") or row.get("DISTANCE") or row.get("distance")
            raw_points.append({
                "point": point_id.strip(),
                "lat_dms": lat_dms.strip(),
                "lon_dms": lon_dms.strip(),
                "lat_deg": dms_to_decimal(lat_dms),
                "lon_deg": dms_to_decimal(lon_dms),
                "distance_m": float(dist_val) if dist_val and dist_val.strip() else None,
                "note": row.get("note", "")
            })

    if not raw_points:
        raise ValueError(f"No points found in {points_csv_path}")

    utm_epsg = get_utm_epsg(raw_points[0]["lon_deg"], raw_points[0]["lat_deg"])
    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS(f"EPSG:{utm_epsg}")
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform

    points = []
    for rp in raw_points:
        utm_x, utm_y = transformer(rp["lon_deg"], rp["lat_deg"])
        points.append({
            "point": rp["point"],
            "lat_dms": rp["lat_dms"],
            "lon_dms": rp["lon_dms"],
            "lat_deg": rp["lat_deg"],
            "lon_deg": rp["lon_deg"],
            "utm_x": utm_x,
            "utm_y": utm_y,
            "utm_epsg": utm_epsg,
            "distance_m": rp["distance_m"],
            "note": rp["note"]
        })

    with open(facts_json_path, mode="r", encoding="utf-8") as f:
        facts = json.load(f)
    facts["utm_epsg"] = utm_epsg
    facts["utm_zone"] = f"{utm_epsg - 32600}N"

    return points, facts


def build_lake_geometry(
    points: List[Dict[str, Any]],
    buffer_width_m: float = 9.0,
    bund_points: Optional[List[Tuple[float, float]]] = None
) -> Dict[str, Any]:
    """
    Construct validated Shapely geometries:
    - lake_poly: closed FTL polygon.
    - boundary_line: open LineString along survey points.
    - bund_line: LineString along bund (curved if bund_points provided, else straight chord).
    - buffer_poly: outward buffer along boundary_line only (mitred corners, no bund buffer).
    - label positions: offset outside the lake boundary.
    """
    pts_geo = [(p["lon_deg"], p["lat_deg"]) for p in points]
    pts_utm = [(p["utm_x"], p["utm_y"]) for p in points]
    labels = [p["point"] for p in points]
    utm_epsg = points[0].get("utm_epsg", 32644)

    # 1. Open survey boundary line
    boundary_line = LineString(pts_utm)

    # 2. Bund line (A37 -> A1)
    if bund_points and len(bund_points) >= 2:
        wgs84 = pyproj.CRS("EPSG:4326")
        utm = pyproj.CRS(f"EPSG:{utm_epsg}")
        tr = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
        bund_utm = [tr(lon, lat) for lon, lat in bund_points]
        bund_line = LineString(bund_utm)
    else:
        bund_line = LineString([pts_utm[-1], pts_utm[0]])

    # 3. Closed lake polygon
    poly_pts = list(pts_utm)
    if bund_points and len(bund_points) >= 2:
        # Include intermediate bund points
        wgs84 = pyproj.CRS("EPSG:4326")
        utm = pyproj.CRS(f"EPSG:{utm_epsg}")
        tr = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
        for bp in bund_points[1:-1]:
            poly_pts.append(tr(bp[0], bp[1]))
    poly_pts.append(pts_utm[0])

    lake_poly = build_polygon(poly_pts)

    # 4. 9m outward buffer along boundary line only (mitred corners, no bund buffer)
    # Single-sided offset outward (right side for clockwise survey points)
    raw_offset = boundary_line.offset_curve(
        distance=-buffer_width_m,
        quad_segs=16,
        join_style="mitre",
        mitre_limit=5.0
    )

    offset_coords = list(raw_offset.coords)
    # Close buffer polygon: boundary points followed by reversed offset curve
    buf_poly_coords = list(pts_utm) + offset_coords[::-1] + [pts_utm[0]]
    buffer_poly = Polygon(buf_poly_coords)

    # Ensure buffer has zero overlap with lake interior
    if buffer_poly.intersects(lake_poly):
        buffer_poly = buffer_poly.difference(lake_poly)

    # 5. Outward label positions outside the 9m buffer
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

    label_positions_utm = []
    for i in range(len(pts_utm)):
        p = np.array(pts_utm[i])
        if i < len(offset_coords):
            o = np.array(offset_coords[i])
            direction = o - p
            dist = np.linalg.norm(direction)
            unit_dir = direction / dist if dist > 0 else np.array([0.0, 1.0])
        else:
            unit_dir = np.array([0.0, 1.0])

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

        lbl_dist = stagger_distances.get(labels[i], 18.0)
        lbl_pos = p + unit_dir * lbl_dist

        # Ensure label is strictly outside lake polygon
        step = 2.0
        while lake_poly.contains(Point(lbl_pos[0], lbl_pos[1])) and step < 50.0:
            lbl_pos = p + unit_dir * (lbl_dist + step)
            step += 5.0

        label_positions_utm.append((float(lbl_pos[0]), float(lbl_pos[1])))

    # Project geometries back to WGS84 (lon, lat)
    utm_crs = pyproj.CRS(f"EPSG:{utm_epsg}")
    wgs84_crs = pyproj.CRS("EPSG:4326")
    inv_transformer = pyproj.Transformer.from_crs(utm_crs, wgs84_crs, always_xy=True)

    buffer_poly_geo = shapely.transform(
        buffer_poly,
        lambda coords: np.column_stack(inv_transformer.transform(coords[:, 0], coords[:, 1]))
    )
    lake_poly_geo = shapely.transform(
        lake_poly,
        lambda coords: np.column_stack(inv_transformer.transform(coords[:, 0], coords[:, 1]))
    )

    label_positions_geo = [
        inv_transformer.transform(lx, ly) for lx, ly in label_positions_utm
    ]

    return {
        "points": points,
        "labels": labels,
        "pts_utm": pts_utm,
        "pts_geo": pts_geo,
        "lake_poly": lake_poly,
        "lake_poly_geo": lake_poly_geo,
        "boundary_line": boundary_line,
        "bund_line": bund_line,
        "buffer_poly": buffer_poly,
        "buffer_poly_geo": buffer_poly_geo,
        "label_positions_utm": label_positions_utm,
        "label_positions_geo": label_positions_geo,
        "utm_epsg": utm_epsg
    }


def verify_measurements(
    lake_poly: Polygon,
    boundary_line: LineString,
    bund_line: LineString,
    facts: Dict[str, Any]
) -> Dict[str, Any]:
    """Verify computed area and perimeter against official survey facts."""
    computed_area_sqm = lake_poly.area
    computed_area_acres = computed_area_sqm / SQM_PER_ACRE

    survey_path_length = boundary_line.length
    bund_length = bund_line.length
    computed_perimeter_m = survey_path_length + bund_length

    target_area = float(facts.get("area_acres", 16.152))
    target_perimeter = float(facts.get("perimeter_m", 1411.706))
    target_bund = float(facts.get("bund_length", 475.0))

    area_diff = computed_area_acres - target_area
    area_diff_pct = (area_diff / target_area) * 100.0

    perim_diff = computed_perimeter_m - target_perimeter
    perim_diff_pct = (perim_diff / target_perimeter) * 100.0

    area_status = "OK" if abs(area_diff_pct) <= 5.0 else ("RE-CHECK" if abs(area_diff_pct) <= 10.0 else "WRONG")
    perim_status = "OK" if abs(perim_diff_pct) <= 5.0 else ("RE-CHECK" if abs(perim_diff_pct) <= 10.0 else "WRONG")
    overall = "OK" if (area_status == "OK" and perim_status == "OK") else "RE-CHECK"

    return {
        "lake_id": str(facts.get("lake_id", "")),
        "lake_name": facts.get("lake_name", ""),
        "overall_status": overall,
        "area": {
            "computed_acres": round(computed_area_acres, 3),
            "survey_acres": target_area,
            "diff_acres": round(area_diff, 3),
            "diff_percent": round(area_diff_pct, 2),
            "status": area_status
        },
        "perimeter": {
            "computed_m": round(computed_perimeter_m, 3),
            "survey_m": target_perimeter,
            "diff_m": round(perim_diff, 3),
            "diff_percent": round(perim_diff_pct, 2),
            "status": perim_status
        },
        "boundary_survey_length_m": round(survey_path_length, 3),
        "bund": {
            "computed_chord_m": round(bund_length, 3),
            "survey_bund_m": target_bund,
            "note": "Straight chord if no bund_points.csv provided"
        }
    }


def generate_lake_geojson(
    lake_id: str,
    geom_data: Dict[str, Any],
    facts: Dict[str, Any],
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate comprehensive lakes/<id>/lake.geojson containing:
    - FTL water spread polygon
    - 9m buffer zone polygon
    - Survey boundary line
    - Bund line (straight chord or curved)
    - All survey points with coordinates, UTM x/y, DMS, and notes
    - Full lake facts metadata

    The frontend viewer needs ZERO other computed data.
    """
    pts_geo = geom_data["pts_geo"]
    pts_utm = geom_data["pts_utm"]
    labels = geom_data["labels"]
    points = geom_data["points"]
    buf_poly_geo = geom_data["buffer_poly_geo"]
    lake_poly_geo = geom_data["lake_poly_geo"]
    label_positions_geo = geom_data["label_positions_geo"]
    utm_epsg = geom_data["utm_epsg"]
    utm_zone = f"{utm_epsg - 32600}N"

    boundary_coords = [[lon, lat] for lon, lat in pts_geo]
    bund_coords = [
        [geom_data["bund_line"].coords[i][0], geom_data["bund_line"].coords[i][1]]
        for i in range(len(geom_data["bund_line"].coords))
    ]
    # Convert bund_coords to geo
    utm_crs = pyproj.CRS(f"EPSG:{utm_epsg}")
    wgs84 = pyproj.CRS("EPSG:4326")
    inv_tr = pyproj.Transformer.from_crs(utm_crs, wgs84, always_xy=True).transform
    bund_coords_geo = [list(inv_tr(x, y)) for x, y in bund_coords]

    buffer_coords_geo = [list(c) for c in buf_poly_geo.exterior.coords]
    lake_poly_coords_geo = [list(c) for c in lake_poly_geo.exterior.coords]

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [lake_poly_coords_geo]
            },
            "properties": {
                "layer": "lake_polygon",
                "name": f"{facts.get('lake_name', 'Lake')} FTL Water Spread",
                "lake_id": lake_id,
                "area_acres": facts.get("area_acres"),
                "perimeter_m": facts.get("perimeter_m")
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [buffer_coords_geo]
            },
            "properties": {
                "layer": "buffer",
                "name": f"Buffer Zone ({facts.get('buffer_m', 9)}m Hatched)",
                "lake_id": lake_id,
                "stroke": "#00c853",
                "fill": "#39ff14",
                "fill_opacity": 0.35
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": boundary_coords
            },
            "properties": {
                "layer": "boundary",
                "name": f"Survey Boundary ({labels[0]} – {labels[-1]})",
                "lake_id": lake_id,
                "stroke": "#ff6b00",
                "stroke_width": 3.5
            }
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": bund_coords_geo
            },
            "properties": {
                "layer": "bund",
                "name": "Bund Embankment (Top of Bund)",
                "lake_id": lake_id,
                "stroke": "#8d5524",
                "stroke_width": 3.0,
                "dash": "dashed"
            }
        }
    ]

    # Add each survey point with UTM x/y and labels
    for i, p in enumerate(points):
        lbl_lon, lbl_lat = label_positions_geo[i]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [p["lon_deg"], p["lat_deg"]]
            },
            "properties": {
                "layer": "point",
                "point": p["point"],
                "lat": p["lat_deg"],
                "lon": p["lon_deg"],
                "lat_dms": p["lat_dms"],
                "lon_dms": p["lon_dms"],
                "utm_x": round(p["utm_x"], 2),
                "utm_y": round(p["utm_y"], 2),
                "utm_zone": utm_zone,
                "utm_epsg": utm_epsg,
                "lbl_lat": lbl_lat,
                "lbl_lon": lbl_lon,
                "distance_m": p.get("distance_m"),
                "note": p.get("note", "")
            }
        })

    center_lat = sum(p["lat_deg"] for p in points) / len(points)
    center_lon = sum(p["lon_deg"] for p in points) / len(points)

    geojson_obj = {
        "type": "FeatureCollection",
        "name": facts.get("lake_name", f"Lake_{lake_id}"),
        "lake_id": str(lake_id),
        "utm_epsg": utm_epsg,
        "utm_zone": utm_zone,
        "center": [center_lat, center_lon],
        "facts": facts,
        "features": features
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(geojson_obj, f, indent=2)

    return geojson_obj


def generate_interactive_map(
    geom_data: Dict[str, Any],
    facts: Dict[str, Any],
    verification_data: Dict[str, Any],
    output_path: str = "outputs/lake_871_satellite.html"
) -> str:
    """
    Renders interactive HTML map from templates/lake_satellite.html.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "lake_satellite.html")

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found at {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    lake_id = str(facts.get("lake_id", "871"))
    lake_geojson = generate_lake_geojson(lake_id, geom_data, facts)

    pts_geo = geom_data["pts_geo"]
    labels = geom_data["labels"]
    buf_poly_geo = geom_data["buffer_poly_geo"]
    label_positions_geo = geom_data["label_positions_geo"]

    boundary_latlngs = [[lat, lon] for lon, lat in pts_geo]
    bund_latlngs = [[pts_geo[-1][1], pts_geo[-1][0]], [pts_geo[0][1], pts_geo[0][0]]]
    buffer_latlngs = [[lat, lon] for lon, lat in buf_poly_geo.exterior.coords]

    points_data = []
    for i in range(len(pts_geo)):
        points_data.append({
            "label": labels[i],
            "lat": pts_geo[i][1],
            "lon": pts_geo[i][0],
            "lbl_lat": label_positions_geo[i][1],
            "lbl_lon": label_positions_geo[i][0]
        })

    center_lat = sum(p["lat"] for p in points_data) / len(points_data)
    center_lon = sum(p["lon"] for p in points_data) / len(points_data)

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
        .replace("__LAKE_ID__", lake_id)
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


def render_static_map(
    geom_data: Dict[str, Any],
    facts: Dict[str, Any],
    output_path: str = "outputs/lake_871_map.png",
    dpi: int = 300
) -> str:
    """Render high-resolution 300 DPI publication map."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pts_utm = geom_data["pts_utm"]
    labels = geom_data["labels"]
    lake_poly = geom_data["lake_poly"]
    bund_line = geom_data["bund_line"]
    buffer_poly = geom_data["buffer_poly"]
    label_positions = geom_data["label_positions_utm"]

    fig, ax = plt.subplots(figsize=(10, 10), dpi=dpi)
    fig.patch.set_facecolor("#223322")
    ax.set_facecolor("#2b3d2b")

    # Water body
    lake_x, lake_y = lake_poly.exterior.xy
    ax.fill(lake_x, lake_y, color="#1e4d58", alpha=0.95, zorder=2)

    # 9m Buffer zone
    buf_x, buf_y = buffer_poly.exterior.xy
    ax.fill(buf_x, buf_y, color="#39ff14", alpha=0.35, hatch="///", zorder=3)
    ax.plot(buf_x, buf_y, color="#00c853", linewidth=1.5, zorder=3)

    # Orange survey boundary (A1 -> A37)
    bx = [p[0] for p in pts_utm]
    by = [p[1] for p in pts_utm]
    ax.plot(bx, by, color="#ff6b00", linewidth=2.8, solid_capstyle="round", zorder=4)

    # Brown dashed bund line (A37 -> A1)
    bund_x, bund_y = bund_line.xy
    ax.plot(bund_x, bund_y, color="#8d5524", linewidth=2.2, linestyle="--", dashes=(6, 4), zorder=4)

    # White vertex dots with orange border
    ax.scatter(bx, by, s=28, facecolors="#ffffff", edgecolors="#ff6b00", linewidth=1.5, zorder=5)

    # Outward labels
    for i in range(len(pts_utm)):
        lx, ly = label_positions[i]
        txt = ax.text(lx, ly, labels[i], fontsize=6.8, fontweight="bold", color="#000000",
                      ha="center", va="center", zorder=6)
        txt.set_path_effects([pe.withStroke(linewidth=2.5, foreground="#ffffff")])

    ax.set_aspect("equal")
    ax.axis("off")
    plt.tight_layout(pad=1.0)
    plt.savefig(output_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    return output_path


def save_verification_report(
    verification_data: Dict[str, Any],
    output_path: str = "outputs/lake_871_verification.json"
) -> str:
    """Save verification report to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verification_data, f, indent=2)
    return output_path


def process_lake(
    lake_id: str = "871",
    lakes_dir: str = "lakes",
    outputs_dir: str = "outputs"
) -> Dict[str, Any]:
    """
    Run full pipeline for a single lake ID:
    1. Loads survey points, facts, and optional bund points.
    2. Builds geometry with auto-detected UTM zone.
    3. Exports lakes/<id>/lake.geojson (self-contained data).
    4. Generates outputs/lake_<id>_satellite.html, map.png, and verification.json.
    """
    points, facts = load_lake_data(lake_id=lake_id, lakes_dir=lakes_dir)

    # Check for optional bund_points.csv in lakes/<id>/
    bund_csv = os.path.join(lakes_dir, str(lake_id), "bund_points.csv")
    bund_pts = None
    if os.path.exists(bund_csv):
        bund_pts = []
        with open(bund_csv, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lat_dms = row.get("lat_dms") or row.get("LATITUDE")
                lon_dms = row.get("lon_dms") or row.get("LONGITUDE")
                if lat_dms and lon_dms:
                    bund_pts.append((dms_to_decimal(lon_dms), dms_to_decimal(lat_dms)))

    geom_data = build_lake_geometry(
        points,
        buffer_width_m=float(facts.get("buffer_m", 9.0)),
        bund_points=bund_pts
    )

    verification = verify_measurements(
        geom_data["lake_poly"],
        geom_data["boundary_line"],
        geom_data["bund_line"],
        facts
    )

    # 1. Output lake.geojson in lakes/<id>/lake.geojson
    lake_geojson_path = os.path.join(lakes_dir, str(lake_id), "lake.geojson")
    generate_lake_geojson(lake_id, geom_data, facts, output_path=lake_geojson_path)

    # 2. Output verification JSON
    json_path = os.path.join(outputs_dir, f"lake_{lake_id}_verification.json")
    save_verification_report(verification, json_path)

    # 3. Output 300 DPI Map PNG
    png_path = os.path.join(outputs_dir, f"lake_{lake_id}_map.png")
    render_static_map(geom_data, facts, png_path, dpi=300)

    # 4. Output Interactive HTML
    html_path = os.path.join(outputs_dir, f"lake_{lake_id}_satellite.html")
    generate_interactive_map(geom_data, facts, verification, html_path)

    return {
        "lake_id": lake_id,
        "lake_geojson": lake_geojson_path,
        "png_path": png_path,
        "html_path": html_path,
        "json_path": json_path,
        "status": verification["overall_status"]
    }


def generate_lakes_index(lakes_dir: str = "lakes") -> List[Dict[str, Any]]:
    """
    Scans all lake directories in lakes_dir and generates lakes/index.json:
    [
      { "id": "871", "name": "YELAMERU KUNTA", "mandal": "Wargal", "status": "verified" }
    ]
    """
    if not os.path.exists(lakes_dir):
        os.makedirs(lakes_dir, exist_ok=True)

    index_entries = []
    # Sort subdirectories numerically or alphabetically
    subdirs = [d for d in os.listdir(lakes_dir) if os.path.isdir(os.path.join(lakes_dir, d))]
    try:
        subdirs.sort(key=lambda x: int(x))
    except ValueError:
        subdirs.sort()

    for d in subdirs:
        facts_path = os.path.join(lakes_dir, d, "facts.json")
        if os.path.exists(facts_path):
            try:
                with open(facts_path, "r", encoding="utf-8") as f:
                    facts = json.load(f)
                index_entries.append({
                    "id": str(facts.get("lake_id", d)),
                    "name": facts.get("lake_name", f"Lake {d}"),
                    "village": facts.get("village", ""),
                    "mandal": facts.get("mandal", ""),
                    "district": facts.get("district", ""),
                    "area_acres": facts.get("area_acres"),
                    "status": facts.get("status", "verified")
                })
            except Exception as e:
                print(f"Warning: could not read facts for lake {d}: {e}")

    index_path = os.path.join(lakes_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_entries, f, indent=2)

    return index_entries


def generate_all_outputs() -> Dict[str, str]:
    """
    Backward-compatible entrypoint used by existing tests and CLI.
    Processes Lake 871 and generates lakes/index.json.
    """
    res = process_lake("871")
    generate_lakes_index()
    return {
        "png_path": res["png_path"],
        "html_path": res["html_path"],
        "json_path": res["json_path"],
        "status": res["status"]
    }


def run_pipeline(
    lake_id: Optional[str] = None,
    all_lakes: bool = False,
    lakes_dir: str = "lakes"
) -> Dict[str, Any]:
    """CLI orchestrator for single lake or bulk processing."""
    if all_lakes:
        subdirs = [d for d in os.listdir(lakes_dir) if os.path.isdir(os.path.join(lakes_dir, d))]
        print(f"Processing all {len(subdirs)} lakes in {lakes_dir}/...")
        for d in subdirs:
            print(f"  -> Processing Lake {d}...")
            process_lake(lake_id=d, lakes_dir=lakes_dir)
        generate_lakes_index(lakes_dir)
        print(f"Updated index at {os.path.join(lakes_dir, 'index.json')}")
        return {"status": "OK", "processed": subdirs}
    elif lake_id:
        print(f"Processing Lake {lake_id}...")
        res = process_lake(lake_id=lake_id, lakes_dir=lakes_dir)
        generate_lakes_index(lakes_dir)
        print(f"Lake {lake_id} processed successfully: status={res['status']}")
        return res
    else:
        return generate_all_outputs()


if __name__ == "__main__":
    generate_all_outputs()
