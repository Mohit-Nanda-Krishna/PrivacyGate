"""Native slide text and tables in presentation and shape-tree order."""

from collections.abc import Iterable, Iterator
from pathlib import Path
from uuid import uuid4

from pptx import Presentation
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape

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


def extract_pptx(path: str | Path) -> Document:
    """Extract slide shapes (including groups) and row-major table cells.

    Slides and shape paths are 1-based. Shape order is XML/z-order, not inferred
    visual reading order. Notes, masters, charts, SmartArt, and images are not
    extracted; no OCR is performed. Merged table cells are emitted once.
    """
    path = Path(path)
    try:
        with path.open("rb") as stream:
            source = Presentation(stream)
        document = Document(str(uuid4()), path.name, "pptx")
        for slide_number, slide in enumerate(source.slides, start=1):
            document.blocks.extend(_shape_blocks(slide.shapes, slide_number))
        if not document.blocks:
            raise ExtractionError("PPTX contains no extractable slide shape or table text.")
        document.metadata = {"slide_count": len(source.slides)}
        return document
    except ExtractionError:
        raise
    except FileNotFoundError:
        raise ExtractionError("PPTX file not found.") from None
    except Exception:
        raise ExtractionError("Could not extract PPTX. Check that the file is readable and valid.") from None
