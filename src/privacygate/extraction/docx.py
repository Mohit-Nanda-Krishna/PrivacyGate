"""Native DOCX extraction: body, tables, headers/footers, text boxes and embedded images."""

from pathlib import Path
import posixpath
from uuid import uuid4

from docx import Document as DocxDocument
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from privacygate.extraction.embedded import EmbeddedImage, ocr_embedded_images
from privacygate.extraction.errors import ExtractionError
from privacygate.models import ContentBlock, Document

A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _paragraph_texts(element) -> list[str]:
    """Text of each w:p under element, skipping mc:Fallback duplicates of text boxes."""
    texts = []
    for paragraph in element.iter(qn("w:p")):
        if any(ancestor.tag == MC_FALLBACK for ancestor in paragraph.iterancestors()):
            continue
        text = "".join(node.text or "" for node in paragraph.iter(qn("w:t"))).strip()
        if text:
            texts.append(text)
    return texts


def _header_footer_blocks(source) -> list[ContentBlock]:
    """One block per non-empty paragraph of every header/footer part, each part once."""
    blocks = []
    parts = sorted(
        (rel.target_part for rel in source.part.rels.values() if rel.reltype in (RT.HEADER, RT.FOOTER)),
        key=lambda part: str(part.partname),
    )
    for part in parts:
        name = posixpath.splitext(posixpath.basename(str(part.partname)))[0]  # header1, footer2
        kind = "header" if name.startswith("header") else "footer"
        for order, text in enumerate(_paragraph_texts(part.element), start=1):
            blocks.append(ContentBlock(
                block_id=f"{name}_paragraph_{order}", text=text, extraction_method="docx_native",
                metadata={"kind": kind, "part": name, "block_order": order},
            ))
    return blocks


def _text_box_blocks(source) -> list[ContentBlock]:
    blocks = []
    boxes = [
        box for box in source.element.body.iter(qn("w:txbxContent"))
        if not any(ancestor.tag == MC_FALLBACK for ancestor in box.iterancestors())
    ]
    for box_number, box in enumerate(boxes, start=1):
        for order, text in enumerate(_paragraph_texts(box), start=1):
            blocks.append(ContentBlock(
                block_id=f"textbox_{box_number}_paragraph_{order}", text=text, extraction_method="docx_native",
                metadata={"kind": "text_box", "text_box_number": box_number, "block_order": order},
            ))
    return blocks


def _embedded_images(source) -> list[EmbeddedImage]:
    """Images in body order, then images used only in headers/footers."""
    images = []
    parts = [source.part] + [
        rel.target_part for rel in source.part.rels.values() if rel.reltype in (RT.HEADER, RT.FOOTER)
    ]
    for part in parts:
        for blip in part.element.iter(A_BLIP):
            rel_id = blip.get(qn("r:embed"))
            if not rel_id or rel_id not in part.rels:
                continue
            image_part = part.rels[rel_id].target_part
            name = posixpath.basename(str(image_part.partname))
            images.append(EmbeddedImage(
                name=name, data=image_part.blob, block_prefix=f"image_{posixpath.splitext(name)[0]}",
                location={"host_part": posixpath.basename(str(part.partname))},
            ))
    return images


def extract_docx(path: str | Path) -> Document:
    """Extract body paragraphs, top-level tables, headers/footers, text boxes and image text.

    Empty elements retain their source ordinal but produce no blocks. Tables
    are traversed row-major; merged cells are emitted once at their first grid
    position. Header/footer parts and text boxes become blocks with
    metadata["kind"] "header", "footer" or "text_box". Embedded raster images
    are OCR'd locally (extraction_method "embedded_image_ocr"); tiny and vector
    images are skipped with a warning. Nested tables are not covered.
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
        document.blocks.extend(_text_box_blocks(source))
        document.blocks.extend(_header_footer_blocks(source))
        embedded = ocr_embedded_images(_embedded_images(source))
        document.blocks.extend(embedded.blocks)
        if not document.blocks:
            raise ExtractionError("DOCX contains no extractable body paragraph or table text.")
        document.metadata = {
            "paragraph_count": paragraph_number, "table_count": table_number,
            "embedded_images": embedded.report,
            "embedded_images_failed": embedded.failed,
            "extraction_warnings": embedded.warnings,
        }
        return document
    except ExtractionError:
        raise
    except FileNotFoundError:
        raise ExtractionError("DOCX file not found.") from None
    except Exception:
        raise ExtractionError("Could not extract DOCX. Check that the file is readable and valid.") from None
