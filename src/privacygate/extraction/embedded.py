"""Local OCR of raster images embedded in DOCX/PPTX files.

Screenshots pasted into Office documents often carry names, e-mail addresses
and IDs that native text extraction never sees. Each embedded raster image is
OCR'd with the same Tesseract settings and retry policy as scanned PDF pages.

* Tiny images (logos, icons) are skipped and recorded in the warnings.
* Vector formats (EMF/WMF/SVG) cannot be OCR'd; they are skipped with a
  warning so the gap is visible in the audit report.
* An image whose OCR fails is recorded in metadata["embedded_images_failed"];
  the privacy gate blocks such documents because the content was not inspected.
* An image with no recognisable text yields no blocks and no error.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import io
import os
import shutil
from typing import Any, Sequence

from PIL import Image

from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.extraction.ocr import group_lines, run_ocr
from privacygate.models import ContentBlock

VECTOR_EXTENSIONS = frozenset({"emf", "wmf", "svg", "emz", "wmz"})
MIN_IMAGE_PIXELS = 100_000  # e.g. 400 x 250; smaller images are logos and icons
MIN_IMAGE_SIDE = 60
UPSCALE_BELOW_WIDTH = 1000  # small screenshots OCR better at 2x
EMBEDDED_OCR_WORKERS = max(1, min(4, os.cpu_count() or 1))


@dataclass
class EmbeddedImage:
    """One embedded image: its package name (e.g. "image12.png") and where it sits."""

    name: str
    data: bytes
    block_prefix: str
    location: dict[str, Any] = field(default_factory=dict)  # e.g. {"slide_number": 3}

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""


@dataclass
class EmbeddedOcrResult:
    blocks: list[ContentBlock] = field(default_factory=list)
    report: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _ocr_one(image: EmbeddedImage) -> tuple[list[tuple[tuple[int, int, int], str, list[int]]], int, str | None]:
    label = f"image {image.name}"
    try:
        with Image.open(io.BytesIO(image.data)) as source:
            picture = source.convert("RGB")
    except Exception:
        return [], 0, f"Could not decode {label}."
    try:
        if picture.width < UPSCALE_BELOW_WIDTH:
            resized = picture.resize((picture.width * 2, picture.height * 2))
            picture.close()
            picture = resized
        data, attempts = run_ocr(picture, label, dpi=None)
        return group_lines(data, label), attempts, None
    except OCRRequiredError:
        raise
    except ExtractionError as error:
        return [], 2 if "after a retry" in str(error) else 1, str(error)
    finally:
        picture.close()


def ocr_embedded_images(images: Sequence[EmbeddedImage]) -> EmbeddedOcrResult:
    """OCR raster images concurrently; blocks are returned in input order."""
    result = EmbeddedOcrResult()
    candidates: list[EmbeddedImage] = []
    seen: set[str] = set()
    for image in images:
        if image.name in seen:
            # The same media file reused (e.g. a logo on every slide) is OCR'd once.
            continue
        seen.add(image.name)
        if image.extension in VECTOR_EXTENSIONS:
            result.warnings.append({"image": image.name, "reason": f"vector image ({image.extension}) not OCR'd"})
            result.report.append({"image": image.name, "status": "skipped_vector"})
            continue
        try:
            with Image.open(io.BytesIO(image.data)) as probe:
                width, height = probe.size
        except Exception:
            result.failed.append(image.name)
            result.report.append({"image": image.name, "status": "failed", "reason": "could not decode image"})
            continue
        if width * height < MIN_IMAGE_PIXELS or min(width, height) < MIN_IMAGE_SIDE:
            result.warnings.append({"image": image.name, "reason": f"tiny image ({width}x{height}) not OCR'd"})
            result.report.append({"image": image.name, "status": "skipped_tiny"})
            continue
        candidates.append(image)

    if not candidates:
        return result
    if shutil.which("tesseract") is None:
        raise OCRRequiredError(
            f"{len(candidates)} embedded image(s) require OCR, but Tesseract is unavailable. "
            "Install the Tesseract executable with English language data and add it to PATH."
        )
    with ThreadPoolExecutor(max_workers=EMBEDDED_OCR_WORKERS) as executor:
        outcomes = list(executor.map(_ocr_one, candidates))

    for image, (lines, attempts, error) in zip(candidates, outcomes):
        if error:
            result.failed.append(image.name)
            result.report.append({"image": image.name, "status": "failed", "attempts": attempts, "reason": error})
            continue
        result.report.append({"image": image.name, "status": "ocr", "attempts": attempts, "lines": len(lines)})
        for order, (key, text, bbox) in enumerate(lines, start=1):
            result.blocks.append(ContentBlock(
                block_id=f"{image.block_prefix}_line_{order}",
                text=text,
                slide_number=image.location.get("slide_number"),
                extraction_method="embedded_image_ocr",
                metadata={
                    "kind": "image", "image_name": image.name, "block_order": order,
                    "source_block_number": key[0], "source_paragraph_number": key[1],
                    "source_line_number": key[2], "bbox_pixels": bbox,
                    **{k: v for k, v in image.location.items() if k != "slide_number"},
                },
            ))
    return result
