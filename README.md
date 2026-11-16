# HMDA Lakes Register to FTL Polygons

A Python data pipeline for processing the Hyderabad Metropolitan Development Authority (HMDA) lake register into GIS polygons with an interactive Excel tracker.

## Overview
This project processes HMDA lake records, downloads Full Tank Level (FTL) and cadastral maps, extracts boundary points via OCR, generates verified GIS polygons, and tracks the lifecycle in an Excel workbook.

### Pipeline Stages
- **Stage 1: Register Parsing & Tracker Setup** (`src/stage1_register.py`)
  - Parses `data/HMDA-Lakes.pdf` (71 pages) using `pdfplumber`.
  - Fixes hyphenated district line-wraps (e.g., `Medchal-Malkajgiri`, `Yadadri-Bhongiri`).
  - Preserves Lake IDs as text strings (`871`, `1000/53`, `3100/EN/01`).
  - Extracts FTL and Cadastral map URLs from clickable links.
  - Computes `legal_status` (`Final`, `Preliminary only`, `Not notified`) and parses dates.
  - Initializes `outputs/lakes_tracker.xlsx` (openpyxl) with 5 sheets (`Lakes`, `FTL_points`, `Parcels`, `Events`, `Results`) and preserves manual edits.
- **Stage 2: Map Downloads** (`src/stage2_download.py`)
  - Automated downloading of FTL and cadastral maps using Playwright.
  - Politeness rules (3-5s delays, custom User-Agent, retries, resume capability).
- **Stage 3: FTL Point Extraction** (`src/stage3_ocr.py`)
  - OCR extraction of boundary coordinates (DMS format) using Tesseract.
  - Generates `outputs/review/<lake_id>.csv` for manual verification.
- **Stage 4: Lake Details Extraction** (`src/stage4_facts.py`)
  - Extracts lake facts (water spread area, FTL area, perimeter, bund length, survey date, buffer width).
- **Stage 5: Polygon Generation & Verification** (`src/stage5_polygon.py`)
  - Converts DMS coordinates to decimal degrees.
  - Constructs EPSG:4326 polygons, reprojects to EPSG:32644 (UTM 44N).
  - Calculates area in acres and compares against map values (tolerance checks: OK, Re-check, Wrong).
  - Exports GeoJSON with per-lake buffer polygons.

## Project Structure
```text
.
├── data/                  # HMDA lake register PDF
├── downloads/
│   ├── ftl/               # Downloaded FTL maps (.png)
│   └── cadastral/         # Downloaded cadastral maps (.png)
├── logs/                  # Execution logs (run.log)
├── outputs/
│   ├── lakes_tracker.xlsx # Live Excel workbook
│   └── review/            # OCR coordinate review CSVs
├── src/                   # Source code modules
│   └── __init__.py
├── main.py                # Main orchestrator
├── requirements.txt       # Python dependencies
└── README.md
```

## Setup & Installation
```bash
# 1. Clone repository
git clone https://github.com/saimogili875/hydra.git
cd hydra

# 2. Install dependencies
pip install -r requirements.txt
playwright install chromium
```
