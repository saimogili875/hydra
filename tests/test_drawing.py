"""
Tests for src/drawing.py.
Verifies PDF rendering, cropping, transparency processing, and output metadata.
Run with: pytest
"""

import os
import json
import pytest
from PIL import Image
import numpy as np
from src.drawing import make_transparent, crop_and_clean_drawing, process_drawing


def test_make_transparent_pure_white():
    """
    Test that make_transparent() makes a pure white pixel (255, 255, 255)
    completely transparent (alpha = 0).
    """
    white_img = Image.new("RGB", (10, 10), (255, 255, 255))
    result = make_transparent(white_img, threshold=240)

    assert result.mode == "RGBA"
    arr = np.array(result)

    # All pixels should have alpha = 0
    assert np.all(arr[:, :, 3] == 0), "Pure white pixels must have alpha = 0 (transparent)"


def test_make_transparent_pure_orange():
    """
    Test that make_transparent() keeps a pure orange pixel unchanged
    with full opacity (alpha = 255).
    """
    # Pure orange: RGB(255, 102, 0)
    orange_color = (255, 102, 0)
    orange_img = Image.new("RGB", (10, 10), orange_color)
    result = make_transparent(orange_img, threshold=240)

    assert result.mode == "RGBA"
    arr = np.array(result)

    # All pixels should have alpha = 255
    assert np.all(arr[:, :, 3] == 255), "Orange pixels must remain opaque (alpha = 255)"
    # RGB values must remain unchanged
    assert np.all(arr[:, :, 0] == 255)
    assert np.all(arr[:, :, 1] == 102)
    assert np.all(arr[:, :, 2] == 0)


def test_make_transparent_green_and_black():
    """
    Test that green buffer hatching and black text linework remain opaque.
    """
    green_img = Image.new("RGB", (10, 10), (0, 200, 0))
    res_green = make_transparent(green_img, threshold=240)
    arr_green = np.array(res_green)
    assert np.all(arr_green[:, :, 3] == 255), "Green buffer hatching must remain opaque"

    black_img = Image.new("RGB", (10, 10), (0, 0, 0))
    res_black = make_transparent(black_img, threshold=240)
    arr_black = np.array(res_black)
    assert np.all(arr_black[:, :, 3] == 255), "Black lines/text must remain opaque"


def test_drawing_pipeline_outputs():
    """
    Verify full drawing extraction output files and metadata.
    """
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "data", "871Yelameru_Kunta_FTL.pdf")
    assert os.path.exists(pdf_path), "PDF must exist in data/"

    result = process_drawing(pdf_path=pdf_path, output_dir="outputs", dpi=300)

    # Check files exist
    assert os.path.exists(result["full_path"])
    assert os.path.exists(result["trans_path"])
    assert os.path.exists(result["crop_json_path"])

    # Check transparent image
    trans_img = Image.open(result["trans_path"])
    assert trans_img.mode == "RGBA"
    assert trans_img.size == (3380, 2410)

    # Check crop JSON keys
    with open(result["crop_json_path"], "r", encoding="utf-8") as f:
        crop_data = json.load(f)
    for key in ["x", "y", "width", "height", "dpi"]:
        assert key in crop_data
    assert crop_data["width"] == 3380
    assert crop_data["height"] == 2410

