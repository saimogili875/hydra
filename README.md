# HMDA Lakes Register to FTL Polygons & GIS Viewer

A data-driven GIS pipeline and interactive web viewer for the Hyderabad Metropolitan Development Authority (HMDA) lake survey records in Telangana, India.

> **Disclaimer:** Student project. Not a legal boundary.

---

## 🌟 Overview

This system converts official HMDA lake survey drawings and coordinate tables into high-precision GIS polygons and buffers. Designed to scale seamlessly across ~500 lakes in the extended HMDA area with **zero per-lake hardcoded logic**:

1. **Self-Contained Per-Lake Structure (`lakes/<id>/`)**: Each lake directory encapsulates its coordinate scan, survey facts, CAD crop definitions, and generated GeoJSON.
2. **Automated Geodesy & UTM Projection**:
   - Parses Degrees-Minutes-Seconds (DMS) coordinates to decimal degrees.
   - Automatically selects the appropriate UTM Zone based on lake longitude (**EPSG:32643** for lon < 78.0°E, **EPSG:32644** for lon ≥ 78.0°E).
   - Validates polygon topology (raises explicit errors on self-intersections, no silent `buffer(0)` smoothing).
   - Verifies Euclidean segment distances against scanned survey distances within a 0.05 m tolerance.
   - Computes 9 m outward buffer along the boundary line while keeping the bund line buffer-free.
3. **Interactive Multi-Basemap Web Viewer (`index.html`)**:
   - Dynamic lake selector populated from `lakes/index.json`.
   - Multi-layer basemap switcher: **OpenStreetMap**, **Esri World Imagery**, **Google Satellite**, and **Google Hybrid**.
   - Live pointer coordinate readout bar pinned to the bottom (Decimal Lat/Long, DMS, and UTM Northing/Easting).
   - Click-to-pin inspection tool displaying FTL status (`INSIDE FTL`, `BUFFER`, `OUTSIDE`) and distance to the nearest survey vertex.
   - Tabbed view switching between the interactive GIS satellite map and the aligned scanned CAD drawing.
   - One-click **Export GeoJSON** (EPSG:4326) ready for QGIS or ArcGIS.

---

## 📁 Repository Structure

```text
.
├── lakes/
│   ├── index.json             # Generated lakes catalog (id, name, mandal, status)
│   └── 871/                   # Example: Yelameru Kunta (Lake ID 871)
│       ├── points.csv         # Boundary coordinates (A1..A37), scan distances & notes
│       ├── facts.json         # Survey facts (FTL area, perimeter, bund, buffer, levels)
│       ├── crop.json          # Bounding box coordinates for the scanned drawing
│       ├── drawing.jpg        # Scanned CAD survey drawing
│       └── lake.geojson       # Generated GIS layers (lake_polygon, buffer, boundary, bund, points)
├── src/
│   ├── __init__.py
│   ├── geo.py                 # Coordinate conversion, dynamic UTM selection, and topology
│   ├── drawing.py             # PDF rendering, crop box processing, and transparency masking
│   └── mapview.py             # Generic pipeline, outward label vectors, and GeoJSON generator
├── templates/
│   └── lake_satellite.html    # Modular HTML template for standalone satellite export
├── tests/
│   ├── test_drawing.py        # PDF extraction, cropping, and alpha transparency tests
│   ├── test_geo.py            # Geodesy, UTM selection, segment lengths, and topology tests
│   └── test_mapview.py        # Buffer exclusion, label placement, GeoJSON & frontend tests
├── outputs/                   # Generated static artifacts (gitignored)
│   ├── lake_871_map.png       # 300 DPI high-resolution map
│   ├── lake_871_satellite.html# Standalone interactive satellite view
│   └── lake_871_verification.json # Computed vs official survey facts comparison
├── config.example.js          # Google Maps API key template
├── index.html                 # Main data-driven GIS Viewer
├── main.py                    # Unified CLI pipeline runner
├── requirements.txt           # Python package dependencies
└── README.md
```

---

## 🚀 Quickstart

### 1. Installation

Requires Python 3.10+ (tested on Python 3.10 – 3.14):

```bash
git clone https://github.com/saimogili875/hydra.git
cd hydra
pip install -r requirements.txt
```

### 2. Optional: Google Maps API Setup

OpenStreetMap and Esri World Imagery work out of the box with zero configuration. To enable Google Maps Satellite and Hybrid layers:

```bash
cp config.example.js config.js
```

Edit `config.js` and set your key:
```javascript
const GOOGLE_MAPS_KEY = "YOUR_GOOGLE_MAPS_API_KEY";
```
*(Note: `config.js` is automatically excluded by `.gitignore` so your API key is never committed).*

---

## 💻 CLI Usage

The pipeline can process a single lake, all lakes in `lakes/`, or run specific stages:

```bash
# Process a single lake (generates lakes/<id>/lake.geojson and updates index.json)
python3 main.py --lake 871

# Process all lakes found in lakes/
python3 main.py --all

# Run Stage 3 directly via module
python3 -m src.mapview

# Launch the interactive web viewer locally
python3 -m http.server 8000
```

Once the server is running, open [http://localhost:8000](http://localhost:8000) or navigate directly to a lake with `?lake=<id>` (e.g., [http://localhost:8000/?lake=871](http://localhost:8000/?lake=871)).

---

## 🧪 Testing

The test suite includes 29 unit and integration tests verifying mathematical precision, geometry rules, and UI features:

```bash
python3 -m pytest
```

### What the tests cover:
- **Geometry & Topology (`tests/test_geo.py`)**:
  - Validates dynamic UTM zone selection (Zone 43 vs 44).
  - Validates that self-intersecting polygons raise explicit `ValueError` exceptions.
  - Validates straight chord vs curved bund (`bund_points.csv`) geometry.
  - Validates that computed UTM Euclidean distances match scanned survey distances within 0.05 m tolerance.
- **Drawing Processing (`tests/test_drawing.py`)**:
  - Tests 300 DPI PDF rendering, crop box application from `crop.json`, and white-to-alpha transparency masking.
- **Pipeline & GIS Viewer (`tests/test_mapview.py`)**:
  - Verifies the 9 m buffer is strictly outside the lake boundary with 0 overlap.
  - Verifies the bund line has **no buffer**.
  - Verifies sequential vertex labels (A1..An) placed outside the polygon using normal vectors.
  - Verifies computed area (acres) and perimeter (m) match official PDF facts within tolerance.
  - Verifies `lakes/<id>/lake.geojson` schema and `lakes/index.json` catalog.
  - Verifies `index.html` has zero hardcoded lake values, uses Subresource Integrity (SRI) hashes, and supports GeoJSON export.

---

## 📄 License

Educational and research use under the MIT License.
