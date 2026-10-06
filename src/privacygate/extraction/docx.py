"""Native DOCX body paragraphs and table cells in document order."""

from pathlib import Path
from uuid import uuid4

from docx import Document as DocxDocument
from docx.text.paragraph import Paragraph

from privacygate.extraction.errors import ExtractionError
from privacygate.models import ContentBlock, Document


def extract_docx(path: str | Path) -> Document:
    """Extract body paragraphs and top-level tables with 1-based locations.

    Empty elements retain their source ordinal but produce no blocks. Tables
    are traversed row-major; merged cells are emitted once at their first grid
    position. Headers, footers, nested tables, and text boxes are not covered.
    """
    path = Path(path)
    try:
        with path.open("rb") as stream:
            source = DocxDocument(stream)
        document = Document(str(uuid4()), path.name, "docx")
        paragraph_number = table_number = 0
        for body_index, item in enumerate(source.iter_inner_content(), start=1):
            if isinstance(item, Paragraph):
                paragraph_number += 1
                if item.text.strip():
                    document.blocks.append(ContentBlock(
                        block_id=f"paragraph_{paragraph_number}", text=item.text.strip(),
                        paragraph_number=paragraph_number, extraction_method="docx_native",
                        metadata={"kind": "paragraph", "body_index": body_index},
                    ))
            else:
                table_number += 1
                seen_cells = set()
                for row_number, row in enumerate(item.rows, start=1):
                    for column_number, cell in enumerate(row.cells, start=row.grid_cols_before + 1):
                        # python-docx repeats the same XML cell for merged grid positions.
                        if cell._tc in seen_cells:
                            continue
                        seen_cells.add(cell._tc)
                        if not cell.text.strip():
                            continue
                        document.blocks.append(ContentBlock(
                            block_id=f"table_{table_number}_row_{row_number}_cell_{column_number}",
                            text=cell.text.strip(), extraction_method="docx_native",
                            metadata={
                                "kind": "table_cell", "body_index": body_index,
                                "table_number": table_number, "row_number": row_number,
                                "column_number": column_number,
                            },
                        ))
        if not document.blocks:
            raise ExtractionError("DOCX contains no extractable body paragraph or table text.")
        document.metadata = {"paragraph_count": paragraph_number, "table_count": table_number}
        return document
    except ExtractionError:
        raise
    except FileNotFoundError:
        raise ExtractionError("DOCX file not found.") from None
    except Exception:
        raise ExtractionError("Could not extract DOCX. Check that the file is readable and valid.") from None
