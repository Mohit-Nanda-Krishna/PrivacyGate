"""Figures inside scanned pages: find them, OCR them properly, flag what cannot be read.

Whole-page OCR reads figures badly: small text, coloured panels, light text on
dark backgrounds. For each framed figure on a scanned page this module

1. finds the figure: a frame (thin rectangular border) cropped to its content,
   or a solid tinted panel (an image pasted without a border, such as a badge),
2. upscales 3x and 2x and OCRs grayscale, locally normalised (dark
   backgrounds inverted area by area, so a screenshot's dark sidebar and light
   table both read as dark text on white) and sharpened variants with page
   segmentation modes 6 (block) and 11 (sparse text), keeping the reading with
   the most confidently read characters and stopping early once one variant
   reads the figure with high confidence,
3. returns the text as lines with word boxes mapped back to page pixels,
4. reports photo regions (textured areas without text) and barcodes (they
   encode the holder's data, which OCR cannot read), and whether the figure's
   OCR is confident enough to trust.

The redacted PDF masks photo and barcode regions and every figure that is not
readable, so a figure is never left visible without having been scanned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from privacygate.extraction.ocr import run_ocr

UPSCALES = (3, 2)
# Stop trying variants once one reads the figure this confidently.
GOOD_ENOUGH_CONFIDENCE = 90.0
# Borders: rows/columns of light-grey ink spanning a large part of the page.
FRAME_INK = 235
FRAME_ROW_SHARE = 0.45
FRAME_COLUMN_SHARE = 0.95
MIN_FRAME_HEIGHT = 80
# Panels: connected cells (CELL px) that are almost entirely tinted.
PANEL_CELL = 10
PANEL_TINT = 245
PANEL_SOLID = 0.95
MIN_PANEL_WIDTH = 300
MIN_PANEL_HEIGHT = 150
# Local normalisation: background estimated with a box blur of this radius.
BACKGROUND_RADIUS = 20
# A figure is readable when OCR is reasonably sure about most of what it read.
MIN_READABLE_CONFIDENCE = 55.0
MIN_CONFIDENT_SHARE = 0.5
CONFIDENT_WORD = 60.0
# Photo detection on a grid of cells (page pixels at 300 DPI).
PHOTO_CELL = 12
PHOTO_TEXTURE = 28.0
MIN_PHOTO_SIDE = 60
# Barcodes: cells whose column means differ strongly while their row means do not.
BARCODE_CELL = 12
BARCODE_ACROSS = 60.0
BARCODE_DOWN = 20.0
MIN_BARCODE_WIDTH = 96
MIN_BARCODE_HEIGHT = 24
BARCODE_TEXT_BELOW = 0.75  # share of the barcode height masked below it


@dataclass
class FigureLine:
    key: tuple[int, int, int]
    text: str
    bbox: list[int]
    word_boxes: list[list[int]]
    confidence: float


@dataclass
class Figure:
    index: int
    bbox: tuple[int, int, int, int]  # page pixels at the render DPI
    lines: list[FigureLine] = field(default_factory=list)
    confidence: float = 0.0
    readable: bool = False
    photos: list[tuple[int, int, int, int]] = field(default_factory=list)
    variant: str = ""


def _components(mask: np.ndarray):
    """4-connected components of a boolean grid as (cell count, (x0, y0, x1, y1)) in grid units."""
    seen = np.zeros_like(mask)
    rows, columns = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, count = [(y, x)], 0
        seen[y, x] = True
        y0 = y1 = y
        x0 = x1 = x
        while stack:
            a, b = stack.pop()
            count += 1
            y0, y1, x0, x1 = min(y0, a), max(y1, a), min(x0, b), max(x1, b)
            for na, nb in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if 0 <= na < rows and 0 <= nb < columns and mask[na, nb] and not seen[na, nb]:
                    seen[na, nb] = True
                    stack.append((na, nb))
        yield count, (int(x0), int(y0), int(x1) + 1, int(y1) + 1)


def _line_groups(indices: list[int]) -> list[int]:
    starts = []
    for value in indices:
        if not starts or value - previous > 2:
            starts.append(value)
        previous = value
    return starts


def find_frames(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Rectangles drawn as thin borders: two long horizontal lines joined by vertical edges."""
    height, width = gray.shape
    ink = gray < FRAME_INK
    rows = [y for y in range(height) if ink[y].sum() > FRAME_ROW_SHARE * width and ink[y].mean() < 0.9]
    tops = _line_groups(rows)
    boxes = []
    for top, bottom in zip(tops, tops[1:]):
        if bottom - top < MIN_FRAME_HEIGHT:
            continue
        columns = np.where(ink[top:bottom].mean(axis=0) > FRAME_COLUMN_SHARE)[0]
        if len(columns) >= 2 and columns[-1] - columns[0] > 0.3 * width:
            boxes.append((int(columns[0]), int(top), int(columns[-1]), int(bottom)))
    return boxes


def find_panels(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Solid tinted areas large enough to be a pasted image; text and table rules are too thin."""
    height, width = gray.shape
    rows, columns = height // PANEL_CELL, width // PANEL_CELL
    tinted = gray[:rows * PANEL_CELL, :columns * PANEL_CELL] < PANEL_TINT
    solid = tinted.reshape(rows, PANEL_CELL, columns, PANEL_CELL).mean(axis=(1, 3)) >= PANEL_SOLID
    return [
        (x0 * PANEL_CELL, y0 * PANEL_CELL, x1 * PANEL_CELL, y1 * PANEL_CELL)
        for _, (x0, y0, x1, y1) in _components(solid)
        if (x1 - x0) * PANEL_CELL >= MIN_PANEL_WIDTH and (y1 - y0) * PANEL_CELL >= MIN_PANEL_HEIGHT
    ]


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def find_figures(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Figure content boxes: framed figures, then panels that no frame already covers."""
    boxes = [box for box in (_content_box(gray, frame) for frame in find_frames(gray)) if box]
    boxes += [panel for panel in find_panels(gray) if not any(_overlaps(panel, box) for box in boxes)]
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def _content_box(gray: np.ndarray, frame: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = frame
    region = gray[y0 + 4:y1 - 4, x0 + 4:x1 - 4]
    ink = region < FRAME_INK
    rows, columns = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    if len(rows) == 0 or len(columns) == 0:
        return None
    return (x0 + 4 + int(columns[0]), y0 + 4 + int(rows[0]),
            x0 + 4 + int(columns[-1]) + 1, y0 + 4 + int(rows[-1]) + 1)


def local_normalise(gray: Image.Image) -> Image.Image:
    """Dark text on white everywhere: invert where the local background is dark, divide by background."""
    array = np.asarray(gray).astype(float)
    background = np.asarray(gray.filter(ImageFilter.BoxBlur(BACKGROUND_RADIUS))).astype(float)
    dark = background < 128
    text = np.where(dark, 255 - array, array)
    paper = np.where(dark, 255 - background, background)
    return Image.fromarray(np.clip(text / np.maximum(paper, 1) * 255, 0, 255).astype("uint8"))


def _preprocessed(crop: Image.Image):
    """(name, scale, image) variants, most often best first: grayscale, local normalisation, sharpened."""
    gray = ImageOps.grayscale(crop)
    local = local_normalise(gray)
    if np.asarray(gray).mean() < 128:  # light text on a dark panel
        gray = ImageOps.invert(gray)
    for scale in UPSCALES:
        size = (gray.width * scale, gray.height * scale)
        yield f"gray{scale}x", scale, gray.resize(size, Image.LANCZOS)
        upscaled = local.resize(size, Image.LANCZOS)
        yield f"local{scale}x", scale, upscaled
        yield f"sharp{scale}x", scale, upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))


def _lines_from(data: dict, origin: tuple[int, int], scale: int) -> list[FigureLine]:
    x0, y0 = origin
    lines: dict[tuple[int, int, int], FigureLine] = {}
    for index, text in enumerate(data["text"]):
        word = text.strip()
        if not word:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        left = x0 + data["left"][index] / scale
        top = y0 + data["top"][index] / scale
        box = [int(left), int(top), int(left + data["width"][index] / scale + 0.999),
               int(top + data["height"][index] / scale + 0.999)]
        confidence = float(data["conf"][index])
        line = lines.setdefault(key, FigureLine(key, "", list(box), [], 0.0))
        line.text = f"{line.text} {word}" if line.text else word
        line.word_boxes.append(box)
        line.bbox = [min(line.bbox[0], box[0]), min(line.bbox[1], box[1]),
                     max(line.bbox[2], box[2]), max(line.bbox[3], box[3])]
        line.confidence += confidence
    for line in lines.values():
        line.confidence /= max(1, len(line.word_boxes))
    return list(lines.values())


def _photo_regions(gray: np.ndarray, box: tuple[int, int, int, int],
                   text_boxes: list[list[int]]) -> list[tuple[int, int, int, int]]:
    """Textured areas (high local contrast) that contain no recognised text."""
    x0, y0, x1, y1 = box
    cells_x, cells_y = (x1 - x0) // PHOTO_CELL, (y1 - y0) // PHOTO_CELL
    if cells_x < 2 or cells_y < 2:
        return []
    region = gray[y0:y0 + cells_y * PHOTO_CELL, x0:x0 + cells_x * PHOTO_CELL].astype(float)
    tiles = region.reshape(cells_y, PHOTO_CELL, cells_x, PHOTO_CELL)
    busy = tiles.std(axis=(1, 3)) > PHOTO_TEXTURE
    for left, top, right, bottom in text_boxes:
        busy[max(0, (top - y0) // PHOTO_CELL - 1):(bottom - y0) // PHOTO_CELL + 2,
             max(0, (left - x0) // PHOTO_CELL - 1):(right - x0) // PHOTO_CELL + 2] = False
    seen = np.zeros_like(busy)
    photos = []
    for cy in range(cells_y):
        for cx in range(cells_x):
            if not busy[cy, cx] or seen[cy, cx]:
                continue
            stack, cells = [(cy, cx)], []
            seen[cy, cx] = True
            while stack:
                a, b = stack.pop()
                cells.append((a, b))
                for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    na, nb = a + da, b + db
                    if 0 <= na < cells_y and 0 <= nb < cells_x and busy[na, nb] and not seen[na, nb]:
                        seen[na, nb] = True
                        stack.append((na, nb))
            rows, cols = [c[0] for c in cells], [c[1] for c in cells]
            width = (max(cols) - min(cols) + 1) * PHOTO_CELL
            height = (max(rows) - min(rows) + 1) * PHOTO_CELL
            fill = len(cells) / ((max(cols) - min(cols) + 1) * (max(rows) - min(rows) + 1))
            if width >= MIN_PHOTO_SIDE and height >= MIN_PHOTO_SIDE and fill >= 0.5:
                photos.append((x0 + min(cols) * PHOTO_CELL, y0 + min(rows) * PHOTO_CELL,
                               x0 + (max(cols) + 1) * PHOTO_CELL, y0 + (max(rows) + 1) * PHOTO_CELL))
    return photos


def _barcode_regions(gray: np.ndarray, box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Vertical-stripe areas (1D barcodes, which encode the holder's data): contrast across columns, none down rows."""
    x0, y0, x1, y1 = box
    cell = BARCODE_CELL
    cells_x, cells_y = (x1 - x0) // cell, (y1 - y0) // cell
    if cells_x < 2 or cells_y < 1:
        return []
    tiles = gray[y0:y0 + cells_y * cell, x0:x0 + cells_x * cell].astype(float).reshape(cells_y, cell, cells_x, cell)
    across = tiles.mean(axis=1).std(axis=2)  # column means vary: stripes
    down = tiles.mean(axis=3).std(axis=1)  # row means steady: the stripes run the full cell height
    stripes = (across > BARCODE_ACROSS) & (down < BARCODE_DOWN)
    regions = []
    for _, (cx0, cy0, cx1, cy1) in _components(stripes):
        if (cx1 - cx0) * cell >= MIN_BARCODE_WIDTH and (cy1 - cy0) * cell >= MIN_BARCODE_HEIGHT:
            # The human-readable line printed under a barcode repeats its content: mask it too.
            below = int((cy1 - cy0) * cell * BARCODE_TEXT_BELOW)
            regions.append((x0 + cx0 * cell, y0 + cy0 * cell, x0 + cx1 * cell, min(y1, y0 + cy1 * cell + below)))
    return regions


def extract_figures(image: Image.Image, page_number: int) -> list[Figure]:
    """Find and OCR the framed figures of one rendered page (does not close the image)."""
    gray = np.asarray(ImageOps.grayscale(image))
    figures = []
    for index, box in enumerate(find_figures(gray), start=1):
        figure = Figure(index=index, bbox=box)
        best_score = -1
        crop = image.crop(box)
        try:
            for name, scale, variant in _preprocessed(crop):
                if figure.confidence >= GOOD_ENOUGH_CONFIDENCE:
                    break  # an earlier variant already read the figure confidently
                for psm in (6, 11):
                    data, _ = run_ocr(variant, f"page {page_number} figure {index} ({name}, psm {psm})",
                                      dpi=None, config=f"--psm {psm}")
                    confidences = [float(c) for t, c in zip(data["text"], data["conf"]) if t.strip()]
                    score = sum(len(t) for t, c in zip(data["text"], data["conf"])
                                if t.strip() and float(c) >= CONFIDENT_WORD)
                    if score > best_score:
                        best_score = score
                        total = sum(len(t) for t in data["text"] if t.strip())
                        figure.lines = _lines_from(data, (box[0], box[1]), scale)
                        figure.variant = f"{name}/psm{psm}"
                        figure.confidence = float(np.mean(confidences)) if confidences else 0.0
                        figure.readable = (
                            figure.confidence >= MIN_READABLE_CONFIDENCE
                            and total > 0 and score / total >= MIN_CONFIDENT_SHARE
                        )
        finally:
            crop.close()
        figure.photos = (_photo_regions(gray, box, [w for line in figure.lines for w in line.word_boxes])
                         + _barcode_regions(gray, box))
        figures.append(figure)
    return figures
