"""
Drawing extraction and transparency processing for FTL Lake Maps.
Uses PyMuPDF to render vector/raster PDF maps at 300 DPI, crops the
active drawing area, removes outer legend/tables/stamps, and creates
a transparent PNG for GIS satellite overlays.
"""

import os
import json
from typing import Tuple, Dict, Any
import pymupdf  # PyMuPDF
from PIL import Image
import numpy as np


def render_pdf_to_image(pdf_path: str, page_num: int = 0, dpi: int = 300) -> Image.Image:
    """
    Render a specific page of a PDF document to a high-resolution PIL Image.
    Standard PDF resolution is 72 DPI; 300 DPI gives ~4.167x scaling.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    doc = pymupdf.open(pdf_path)
    if page_num < 0 or page_num >= len(doc):
        raise IndexError(f"Page {page_num} out of bounds for PDF with {len(doc)} pages")

    page = doc[page_num]
    scale = dpi / 72.0
    matrix = pymupdf.Matrix(scale, scale)

    # Render page to pixmap
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    # Convert PyMuPDF pixmap to PIL Image
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def crop_and_clean_drawing(
    image: Image.Image,
    crop_box: Tuple[int, int, int, int] = (400, 50, 3780, 2460),
    table_mask_box: Tuple[int, int, int] = (0, 1190, 1015)
) -> Image.Image:
    """
    Crops the full rendered image to the lake drawing area and blanks out the
    bottom-left coordinate table.
    
    Parameters:
      image: Original rendered full PIL image.
      crop_box: (x1, y1, x2, y2) bounding box in original pixels.
                x1=400: leaves margin left of Temple/TBMB-18, cuts sheet margin.
                y1=50: keeps full North arrow, cuts top sheet border.
                x2=3780: keeps full North arrow and bund end, cuts Legend/Details/Title block.
                y2=2460: keeps A25 and southern buffer, cuts signatures/stamps at y > 2500.
      table_mask_box: (x_start, y_start, x_end) within cropped image to remove
                      the coordinates table without touching the lake boundary.
    """
    cropped = image.crop(crop_box)
    arr = np.array(cropped)

    # Blank out the table area in the bottom-left of the cropped image
    x_start, y_start, x_end = table_mask_box
    arr[y_start:, x_start:x_end] = [255, 255, 255]

    return Image.fromarray(arr)


def make_transparent(image: Image.Image, threshold: int = 240) -> Image.Image:
    """
    Converts white and near-white pixels to fully transparent (alpha = 0),
    while preserving linework, text, orange FTL line, and green buffer hatching.
    
    Parameters:
      image: PIL Image (RGB or RGBA).
      threshold: RGB cutoff (default 240). Pixels where R >= threshold,
                 G >= threshold, and B >= threshold become transparent.
    """
    rgba = image.convert("RGBA")
    arr = np.array(rgba)

    # Identify white and near-white paper pixels
    is_white = (
        (arr[:, :, 0] >= threshold) &
        (arr[:, :, 1] >= threshold) &
        (arr[:, :, 2] >= threshold)
    )

    # Set alpha channel to 0 for paper pixels
    arr[is_white, 3] = 0

    return Image.fromarray(arr)


def process_drawing(
    pdf_path: str = "data/871Yelameru_Kunta_FTL.pdf",
    output_dir: str = "outputs",
    dpi: int = 300
) -> Dict[str, Any]:
    """
    Full pipeline for Step 1:
      1. Renders PDF page 1 to outputs/drawing_full.png at 300 DPI.
      2. Crops drawing area and blanks out table.
      3. Makes background transparent and saves to outputs/drawing_transparent.png.
      4. Saves crop metadata to outputs/drawing_crop.json.
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. Render full PDF page
    full_img = render_pdf_to_image(pdf_path, page_num=0, dpi=dpi)
    full_path = os.path.join(output_dir, "drawing_full.png")
    full_img.save(full_path)

    # Crop box in original 300 DPI pixels: (x, y, x2, y2)
    crop_x, crop_y = 400, 50
    crop_x2, crop_y2 = 3780, 2460
    crop_w = crop_x2 - crop_x
    crop_h = crop_y2 - crop_y

    # 2. Crop drawing area and remove table
    cleaned_img = crop_and_clean_drawing(
        full_img,
        crop_box=(crop_x, crop_y, crop_x2, crop_y2),
        table_mask_box=(0, 1190, 1015)
    )

    # 3. Make transparent
    trans_img = make_transparent(cleaned_img, threshold=240)
    trans_path = os.path.join(output_dir, "drawing_transparent.png")
    trans_img.save(trans_path)

    # 4. Save crop metadata
    crop_meta = {
        "x": crop_x,
        "y": crop_y,
        "width": crop_w,
        "height": crop_h,
        "dpi": dpi,
        "full_width": full_img.width,
        "full_height": full_img.height
    }
    crop_json_path = os.path.join(output_dir, "drawing_crop.json")
    with open(crop_json_path, "w", encoding="utf-8") as f:
        json.dump(crop_meta, f, indent=2)

    return {
        "full_path": full_path,
        "trans_path": trans_path,
        "crop_json_path": crop_json_path,
        "crop_meta": crop_meta,
        "pixel_size": (crop_w, crop_h)
    }


if __name__ == "__main__":
    result = process_drawing()
    print("Drawing extraction complete:")
    print(f"  Cropped & transparent image size: {result['pixel_size'][0]} x {result['pixel_size'][1]} px")
    print(f"  Saved: {result['trans_path']}")

