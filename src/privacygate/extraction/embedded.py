"""Local OCR of raster images embedded in PDF/DOCX/PPTX files.

Screenshots and figures embedded in documents often carry names, e-mail addresses
and IDs that native text extraction never sees. Each embedded raster image is
OCR'd with the same Tesseract settings and retry policy as scanned PDF pages.

* Raster images are enlarged in memory using Lanczos resampling and inspected locally.
* Unsupported vector formats (.emf, .wmf, .svg, etc.) cannot be safely inspected for PII;
  they are recorded in warnings, reported as skipped_vector, and added to metadata["embedded_images_failed"].
* Any uninspected image or OCR failure causes the privacy gate to block the document fail-closed.
* An inspected raster image with no recognisable text yields no blocks and no error.
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


def _ocr_one(image: EmbeddedImage) -> tuple[list[tuple], int, str | None]:
    label = f"image {image.name}"
    try:
        with Image.open(io.BytesIO(image.data)) as source:
            picture = source.convert("RGB")
    except Exception:
        return [], 0, f"Could not decode {label}."
    try:
        if picture.width <= 0 or picture.height <= 0:
            return [], 0, f"Invalid dimensions for {label}."
        min_dim = min(picture.width, picture.height)
        if picture.width < UPSCALE_BELOW_WIDTH or min_dim < 150:
            scale = max(2, min(8, 300 // max(1, min_dim)))
            resized = picture.resize(
                (picture.width * scale, picture.height * scale),
                resample=Image.Resampling.LANCZOS,
            )
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
    import hashlib

    result = EmbeddedOcrResult()
    if not images:
        return result
    # The same image placed twice (a logo in two headers) must not give two blocks one id.
    prefix_uses: dict[str, int] = {}

    digest_candidates: dict[bytes, EmbeddedImage] = {}
    occurrences_by_digest: dict[bytes, list[EmbeddedImage]] = {}
    digest_status: dict[bytes, tuple[str, str]] = {}

    for image in images:
        digest = hashlib.sha256(image.data).digest()
        occurrences_by_digest.setdefault(digest, []).append(image)

        if digest in digest_status or digest in digest_candidates:
            continue

        if image.extension in VECTOR_EXTENSIONS:
            digest_status[digest] = ("skipped_vector", f"vector image ({image.extension}) not inspected")
            continue
        try:
            with Image.open(io.BytesIO(image.data)) as probe:
                width, height = probe.size
        except Exception:
            digest_status[digest] = ("failed", "could not decode image")
            continue
        if width <= 0 or height <= 0:
            digest_status[digest] = ("failed", f"invalid image dimensions ({width}x{height})")
            continue

        digest_candidates[digest] = image

    # Record non-candidate outcomes (vectors, decode failures) once per unique image
    for digest, (status, reason) in digest_status.items():
        primary = occurrences_by_digest[digest][0]
        if status == "skipped_vector":
            result.warnings.append({"image": primary.name, "reason": f"vector image ({primary.extension}) not OCR'd"})
            result.report.append({"image": primary.name, "status": "skipped_vector", "reason": reason})
        else:
            result.report.append({"image": primary.name, "status": "failed", "reason": reason})
        result.failed.append(primary.name)

    candidates = list(digest_candidates.values())
    if not candidates:
        return result
    if shutil.which("tesseract") is None:
        raise OCRRequiredError(
            f"{len(candidates)} embedded image(s) require OCR, but Tesseract is unavailable. "
            "Install the Tesseract executable with English language data and add it to PATH."
        )
    with ThreadPoolExecutor(max_workers=EMBEDDED_OCR_WORKERS) as executor:
        outcomes = list(executor.map(_ocr_one, candidates))

    for primary_image, (lines, attempts, error) in zip(candidates, outcomes):
        digest = hashlib.sha256(primary_image.data).digest()
        occurrences = occurrences_by_digest[digest]

        if error:
            result.failed.append(primary_image.name)
            result.report.append({"image": primary_image.name, "status": "failed", "attempts": attempts, "reason": error})
            continue
        result.report.append({"image": primary_image.name, "status": "ocr", "attempts": attempts, "lines": len(lines)})

        for occurrence in occurrences:
            uses = prefix_uses[occurrence.block_prefix] = prefix_uses.get(occurrence.block_prefix, 0) + 1
            prefix = occurrence.block_prefix if uses == 1 else f"{occurrence.block_prefix}_{uses}"
            page_number = occurrence.location.get("page_number")
            slide_number = occurrence.location.get("slide_number")
            for order, item in enumerate(lines, start=1):
                key, text, bbox = item[0], item[1], item[2]
                word_boxes = item[3] if len(item) > 3 else None
                meta = {
                    "kind": "image", "image_name": occurrence.name, "block_order": order,
                    "source_block_number": key[0], "source_paragraph_number": key[1],
                    "source_line_number": key[2], "bbox_pixels": bbox,
                    **{k: v for k, v in occurrence.location.items() if k != "slide_number"},
                }
                if word_boxes is not None:
                    meta["word_boxes_pixels"] = word_boxes
                result.blocks.append(ContentBlock(
                    block_id=f"{prefix}_line_{order}",
                    text=text,
                    page_number=page_number,
                    slide_number=slide_number,
                    extraction_method="embedded_image_ocr",
                    metadata=meta,
                ))
    return result
