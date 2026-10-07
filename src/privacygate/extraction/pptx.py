"""Native slide text, tables, speaker notes and picture OCR in presentation order."""

from collections.abc import Iterable, Iterator
from pathlib import Path
import posixpath
from uuid import uuid4

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape

from privacygate.extraction.embedded import EmbeddedImage, ocr_embedded_images
from privacygate.extraction.errors import ExtractionError
from privacygate.models import ContentBlock, Document


def _shape_blocks(
    shapes: Iterable[BaseShape], slide_number: int, parent_path: tuple[int, ...] = (),
) -> Iterator[ContentBlock]:
    for shape_index, shape in enumerate(shapes, start=1):
        shape_path = (*parent_path, shape_index)
        if isinstance(shape, GroupShape):
            yield from _shape_blocks(shape.shapes, slide_number, shape_path)
            continue
        block_id = f"slide_{slide_number}_shape_" + "_".join(map(str, shape_path))
        location = {
            "shape_id": shape.shape_id, "shape_index": shape_index,
            "shape_path": list(shape_path),
        }
        if shape.has_text_frame and shape.text.strip():
            yield ContentBlock(
                block_id=block_id, text=shape.text.strip(), slide_number=slide_number,
                extraction_method="pptx_native", metadata={"kind": "shape_text", **location},
            )
        if shape.has_table:
            for row_number, row in enumerate(shape.table.rows, start=1):
                for column_number, cell in enumerate(row.cells, start=1):
                    if cell.is_spanned or not cell.text.strip():
                        continue
                    yield ContentBlock(
                        block_id=f"{block_id}_row_{row_number}_cell_{column_number}",
                        text=cell.text.strip(), slide_number=slide_number,
                        extraction_method="pptx_native",
                        metadata={
                            "kind": "table_cell", **location,
                            "row_number": row_number, "column_number": column_number,
                        },
                    )


def _pictures(shapes: Iterable[BaseShape], slide, slide_number: int,
              parent_path: tuple[int, ...] = ()) -> Iterator[EmbeddedImage]:
    for shape_index, shape in enumerate(shapes, start=1):
        shape_path = (*parent_path, shape_index)
        if isinstance(shape, GroupShape):
            yield from _pictures(shape.shapes, slide, slide_number, shape_path)
            continue
        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            continue
        image_part = slide.part.related_part(shape._element.blip_rId)
        name = posixpath.basename(str(image_part.partname))
        yield EmbeddedImage(
            name=name, data=image_part.blob,
            block_prefix=f"slide_{slide_number}_image_{posixpath.splitext(name)[0]}",
            location={"slide_number": slide_number, "shape_id": shape.shape_id,
                      "shape_path": ".".join(map(str, shape_path))},
        )


def extract_pptx(path: str | Path) -> Document:
    """Extract slide shapes (including groups), table cells, speaker notes and picture text.

    Slides and shape paths are 1-based. Shape order is XML/z-order, not inferred
    visual reading order. Speaker notes become one block per slide
    (metadata["kind"] == "notes"). Pictures are OCR'd locally
    (extraction_method "embedded_image_ocr"); each media file once, tiny and
    vector images skipped with a warning. Masters, charts and SmartArt are not
    extracted. Merged table cells are emitted once.
    """
    path = Path(path)
    try:
        with path.open("rb") as stream:
            source = Presentation(stream)
        document = Document(str(uuid4()), path.name, "pptx")
        images: list[EmbeddedImage] = []
        for slide_number, slide in enumerate(source.slides, start=1):
            document.blocks.extend(_shape_blocks(slide.shapes, slide_number))
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame
                text = notes.text.strip() if notes is not None else ""
                if text:
                    document.blocks.append(ContentBlock(
                        block_id=f"slide_{slide_number}_notes", text=text, slide_number=slide_number,
                        extraction_method="pptx_native", metadata={"kind": "notes"},
                    ))
            images.extend(_pictures(slide.shapes, slide, slide_number))
        embedded = ocr_embedded_images(images)
        document.blocks.extend(embedded.blocks)
        if not document.blocks:
            raise ExtractionError("PPTX contains no extractable slide shape or table text.")
        document.metadata = {
            "slide_count": len(source.slides),
            "embedded_images": embedded.report,
            "embedded_images_failed": embedded.failed,
            "extraction_warnings": embedded.warnings,
        }
        return document
    except ExtractionError:
        raise
    except FileNotFoundError:
        raise ExtractionError("PPTX file not found.") from None
    except Exception:
        raise ExtractionError("Could not extract PPTX. Check that the file is readable and valid.") from None
