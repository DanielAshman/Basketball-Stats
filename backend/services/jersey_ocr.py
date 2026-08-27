"""Jersey number OCR: given a frame and a detected person's bounding box, try
to read a jersey number off their torso.

This is a best-effort guess, not reliable player identification - real
jerseys are printed in all kinds of fonts/sizes, often partly obscured by
motion blur or another player, and this crops a fixed torso region rather
than actually locating the printed number. Matches the docs' own accuracy
framing (architecture_decisions.md decision #6): auto-detect where possible,
let a human correct it. There is no "assign this number to a tracked player
across frames" step here - each detection is OCR'd independently.

Verified against a real jersey ("24", clearly legible to a human eye after
binarization) that Tesseract still could not read reliably even with
correct cropping and upscaling - trying multiple threshold polarities and
page-segmentation modes here recovers a partial/inconsistent read at best.
Tesseract is a document-OCR engine; stylized athletic-font digits on fabric
are a scene-text problem it isn't well suited for. A specialized
jersey-number model (a small CNN classifier trained on cropped digit
datasets) would do meaningfully better - tracked as future work, not
something more image preprocessing alone fixes.
"""

import re

import cv2
import pytesseract

# Torso region as a fraction of the person bbox: skip the head/legs, keep the
# vertical band where a jersey number is normally printed.
TORSO_TOP_FRACTION = 0.15
TORSO_BOTTOM_FRACTION = 0.75

# Upscale the crop to roughly this height before OCR - tesseract does much
# better with taller text.
TARGET_CROP_HEIGHT = 200

# psm 8 (single word) and 7 (single line) each occasionally catch a digit the
# other misses; jersey number/background polarity isn't known in advance, so
# both binarization directions are tried too.
TESSERACT_CONFIGS = [
    "--psm 8 -c tessedit_char_whitelist=0123456789",
    "--psm 7 -c tessedit_char_whitelist=0123456789",
]

MIN_CROP_SIZE = 10


def _best_reading(gray):
    best_number, best_conf = None, -1.0
    for polarity in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        _, binarized = cv2.threshold(gray, 0, 255, polarity + cv2.THRESH_OTSU)
        for config in TESSERACT_CONFIGS:
            data = pytesseract.image_to_data(binarized, config=config, output_type=pytesseract.Output.DICT)
            for text, conf in zip(data["text"], data["conf"]):
                digits = re.sub(r"\D", "", text)
                if not digits:
                    continue
                conf = float(conf)
                if conf > best_conf:
                    best_number, best_conf = int(digits), conf
    return best_number, best_conf


def read_jersey_number(frame_path: str, bbox_x: int, bbox_y: int, bbox_width: int, bbox_height: int):
    """Returns (number: int, confidence: float) or (None, None) if no
    plausible number was read."""
    image = cv2.imread(frame_path)
    if image is None:
        return None, None

    frame_h, frame_w = image.shape[:2]

    top = max(0, bbox_y + int(bbox_height * TORSO_TOP_FRACTION))
    bottom = min(frame_h, bbox_y + int(bbox_height * TORSO_BOTTOM_FRACTION))
    left = max(0, bbox_x)
    right = min(frame_w, bbox_x + bbox_width)

    if (right - left) < MIN_CROP_SIZE or (bottom - top) < MIN_CROP_SIZE:
        return None, None

    crop = image[top:bottom, left:right]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = max(1.0, TARGET_CROP_HEIGHT / gray.shape[0])
    if scale > 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    best_number, best_conf = _best_reading(gray)
    if best_number is None or best_conf < 0:
        return None, None

    return best_number, round(best_conf / 100, 3)
