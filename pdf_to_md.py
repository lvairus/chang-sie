from __future__ import annotations

import argparse
import base64
import csv
import math
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


REFERENCE_HEADING_MIN_POSITION = 0.60
REFERENCE_HEADING_FUZZY_THRESHOLD = 0.90
ROTATED_TEXT_MIN_LINES = 4
ROTATED_TEXT_ANGLE_TOLERANCE = 10
ROTATED_ROW_TOLERANCE = 8
ROTATED_INSERT_Y_TOLERANCE = 8
ROTATED_IMAGE_DPI = 300
ROTATED_IMAGE_PADDING = 18
OPENAI_CONVERSION_MODEL = "gpt-5.4-nano"
OPENAI_CONVERSION_MAX_RETRIES = 4
OPENAI_CONVERSION_RETRY_BACKOFF_SECONDS = 1.0
OPENAI_PDF_MAX_BYTES = 50 * 1024 * 1024
CAMELOT_FLAVORS = ("lattice", "stream")
CAMELOT_MIN_ROWS = 2
CAMELOT_MIN_COLUMNS = 2
CAMELOT_MIN_ACCURACY = 50.0
OPENAI_PDF_TO_MARKDOWN_PROMPT = """Convert the attached PDF into faithful, extraction-friendly Markdown.
Requirements:
- Preserve the document's reading order, section headings, captions, tables, equations, units, and numeric values.
- Convert tables to Markdown tables when possible.
- Keep figure and table captions near the related content.
- Do not summarize, interpret, or add commentary.
- Do not invent missing text.
- Do not wrap the response in a code fence.
- Return only Markdown.
"""
REFERENCE_TITLES = {
    "references",
    "bibliography",
    "literature cited",
    "works cited",
    "cited references",
}


@dataclass(frozen=True)
class RotatedTable:
    y: float
    angle: float
    bbox: tuple[float, float, float, float]
    markdown: str


@dataclass(frozen=True)
class CamelotExtractedTable:
    page: int
    order: int
    flavor: str
    accuracy: float | None
    whitespace: float | None
    csv_path: Path
    markdown: str


def discover_pdfs(papers_dir: Path) -> list[Path]:
    return sorted(path for path in papers_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")


def line_text(line: dict[str, Any]) -> str:
    return " ".join(span.get("text", "").strip() for span in line.get("spans", []) if span.get("text", "").strip())


def line_bbox(line: dict[str, Any]) -> tuple[float, float, float, float]:
    rects = [span["bbox"] for span in line.get("spans", []) if "bbox" in span]
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def line_angle(line: dict[str, Any]) -> float:
    dx, dy = line.get("dir", (1.0, 0.0))
    return math.degrees(math.atan2(dy, dx))


def is_rotated_line(line: dict[str, Any]) -> bool:
    return abs(abs(line_angle(line)) - 90) <= ROTATED_TEXT_ANGLE_TOLERANCE and bool(line_text(line))


def cluster_positions(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - (sum(clusters[-1]) / len(clusters[-1]))) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def nearest_cluster(value: float, clusters: list[float]) -> int:
    return min(range(len(clusters)), key=lambda index: abs(value - clusters[index]))


def markdown_table_from_grid(grid: list[list[str]]) -> str | None:
    rows = [[cell.strip() for cell in row] for row in grid if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    if width < 2:
        return None

    header = rows[0]
    body = rows[1:]
    table = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" if cell else "---" for cell in header) + " |",
    ]
    table.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(table)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_pymupdf_artifacts(markdown: str) -> str:
    markdown = re.sub(r"(?<=\d)�(?=\s*(?:\d|\[0\]|[NSEW]|'|\"|′|″))", "°", markdown)
    markdown = re.sub(r"(?<=\d)\s*\[0\]\s*", "'", markdown)
    return markdown


def block_text(block: dict[str, Any], *, include_rotated: bool) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        if include_rotated or not is_rotated_line(line):
            text = line_text(line)
            if text:
                lines.append(text)
    return compact_text(" ".join(lines))


def normal_text_blocks_for_page(page: Any) -> list[tuple[float, str]]:
    text_dict = page.get_text("dict")
    blocks: list[tuple[float, str]] = []
    for block in text_dict.get("blocks", []):
        text = block_text(block, include_rotated=False)
        if text and "bbox" in block:
            blocks.append((float(block["bbox"][1]), text))
    return sorted(blocks, key=lambda item: item[0])


def text_snippets(text: str) -> list[str]:
    words = compact_text(text).split()
    snippets: list[str] = []
    for size in (16, 12, 8, 5):
        if len(words) >= size:
            snippets.append(" ".join(words[:size]))
    if words:
        snippets.append(" ".join(words))
    return snippets


def insertion_index_for_table(page_parts: list[str], blocks: list[tuple[float, str]], y: float) -> int:
    preceding_blocks = [text for block_y, text in blocks if block_y <= y + ROTATED_INSERT_Y_TOLERANCE]
    for text in reversed(preceding_blocks):
        for snippet in text_snippets(text):
            snippet_normalized = compact_text(snippet)
            for index, part in enumerate(page_parts):
                if snippet_normalized and snippet_normalized in compact_text(part):
                    return index + 1
    return len(page_parts)


def union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def rotated_lines_to_table(lines: list[dict[str, Any]]) -> RotatedTable | None:
    entries: list[dict[str, float | str]] = []
    boxes: list[tuple[float, float, float, float]] = []
    for line in lines:
        text = line_text(line)
        if not text:
            continue
        x0, y0, x1, y1 = line_bbox(line)
        boxes.append((x0, y0, x1, y1))
        angle = line_angle(line)
        entries.append(
            {
                "text": text,
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
                "angle": angle,
                "y0": y0,
            }
        )

    if len(entries) < ROTATED_TEXT_MIN_LINES:
        return None

    angle = sum(float(entry["angle"]) for entry in entries) / len(entries)
    row_values = [float(entry["cx"]) for entry in entries]
    col_values = [float(entry["cy"]) for entry in entries]
    row_clusters = cluster_positions(row_values, ROTATED_ROW_TOLERANCE)
    col_clusters = cluster_positions(col_values, ROTATED_ROW_TOLERANCE)
    if len(row_clusters) < 2 or len(col_clusters) < 2:
        return None

    rows: list[list[list[str]]] = [[[] for _ in col_clusters] for _ in row_clusters]
    for entry in entries:
        row_index = nearest_cluster(float(entry["cx"]), row_clusters)
        col_index = nearest_cluster(float(entry["cy"]), col_clusters)
        rows[row_index][col_index].append(str(entry["text"]))

    if angle < 0:
        ordered_rows = rows
        ordered_col_indexes = list(reversed(range(len(col_clusters))))
    else:
        ordered_rows = list(reversed(rows))
        ordered_col_indexes = list(range(len(col_clusters)))

    grid = [
        [" ".join(row[col_index]).strip() for col_index in ordered_col_indexes]
        for row in ordered_rows
    ]
    table = markdown_table_from_grid(grid)
    if not table:
        return None
    return RotatedTable(
        y=min(float(entry["y0"]) for entry in entries),
        angle=angle,
        bbox=union_bbox(boxes),
        markdown=table,
    )


def rotated_tables_for_page(page: Any) -> list[RotatedTable]:
    text_dict = page.get_text("dict")
    left_rotated_lines: list[dict[str, Any]] = []
    right_rotated_lines: list[dict[str, Any]] = []
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            if not is_rotated_line(line):
                continue
            if line_angle(line) < 0:
                left_rotated_lines.append(line)
            else:
                right_rotated_lines.append(line)

    tables: list[RotatedTable] = []
    for lines in (left_rotated_lines, right_rotated_lines):
        table = rotated_lines_to_table(lines)
        if table:
            tables.append(table)
    return sorted(tables, key=lambda table: table.y)


def page_markdown_chunks(pdf_path: Path) -> tuple[list[str], str]:
    import pymupdf4llm

    try:
        chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
    except TypeError:
        return [pymupdf4llm.to_markdown(str(pdf_path), page_chunks=False)], "pymupdf4llm"

    if not isinstance(chunks, list):
        return [str(chunks)], "pymupdf4llm"

    markdown_chunks: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            markdown_chunks.append(str(chunk.get("text", "")))
        else:
            markdown_chunks.append(str(chunk))
    return markdown_chunks, "pymupdf4llm"


def save_rotated_table_image(page: Any, table: RotatedTable, image_dir: Path, page_number: int, table_number: int) -> Path:
    import fitz

    image_dir.mkdir(parents=True, exist_ok=True)
    rect = fitz.Rect(table.bbox)
    rect.x0 = max(page.rect.x0, rect.x0 - ROTATED_IMAGE_PADDING)
    rect.y0 = max(page.rect.y0, rect.y0 - ROTATED_IMAGE_PADDING)
    rect.x1 = min(page.rect.x1, rect.x1 + ROTATED_IMAGE_PADDING)
    rect.y1 = min(page.rect.y1, rect.y1 + ROTATED_IMAGE_PADDING)

    image_path = image_dir / f"page-{page_number:03d}-rotated-table-{table_number:02d}.png"
    pix = page.get_pixmap(clip=rect, dpi=ROTATED_IMAGE_DPI)
    pix.save(image_path)

    try:
        from PIL import Image
    except Exception:
        return image_path

    rotation = -90 if table.angle < 0 else 90
    image = Image.open(image_path)
    try:
        image.rotate(rotation, expand=True).save(image_path)
    finally:
        image.close()
    return image_path


def inject_rotated_tables(pdf_path: Path, markdown_chunks: list[str], image_dir: Path | None = None) -> tuple[str, int]:
    import fitz

    doc = fitz.open(pdf_path)
    output_chunks: list[str] = []
    recovered = 0

    for page_index, markdown in enumerate(markdown_chunks):
        if page_index >= len(doc):
            output_chunks.append(markdown)
            continue

        page = doc[page_index]
        tables = rotated_tables_for_page(page)
        if not tables:
            output_chunks.append(markdown)
            continue

        blocks = normal_text_blocks_for_page(page)
        page_parts = [part for part in re.split(r"\n{2,}", markdown.strip()) if part.strip()]

        for table_number, table in enumerate(tables, start=1):
            if image_dir is not None:
                try:
                    save_rotated_table_image(page, table, image_dir, page_index + 1, table_number)
                except Exception as exc:
                    print(
                        f"Warning: could not save rotated table image from "
                        f"{pdf_path.name} page {page_index + 1}: {exc}"
                    )

            insert_at = min(insertion_index_for_table(page_parts, blocks, table.y), len(page_parts))
            if table.markdown not in markdown:
                page_parts.insert(insert_at, table.markdown)
                recovered += 1

        output_chunks.append("\n\n".join(page_parts))

    return "\n\n".join(chunk for chunk in output_chunks if chunk.strip()), recovered


def pymupdf_markdown_for_pdf(pdf_path: Path, image_dir: Path | None = None) -> tuple[str, str]:
    try:
        markdown_chunks, method = page_markdown_chunks(pdf_path)
    except Exception:
        import fitz

        doc = fitz.open(pdf_path)
        parts: list[str] = []
        for i, page in enumerate(doc, start=1):
            parts.append(f"\n\n## Page {i}\n\n{page.get_text('blocks')}")
        return "\n".join(parts), "pymupdf_blocks"

    markdown = "\n\n".join(chunk for chunk in markdown_chunks if chunk.strip())
    try:
        markdown, recovered = inject_rotated_tables(pdf_path, markdown_chunks, image_dir)
    except Exception as exc:
        print(f"Warning: could not recover rotated tables from {pdf_path.name}: {exc}")
        return markdown, method

    if recovered:
        method = f"{method}+rotated_tables:{recovered}"
    return markdown, method


def response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def openai_markdown_for_pdf(pdf_path: Path) -> tuple[str, str]:
    from openai import OpenAI

    pdf_bytes = pdf_path.read_bytes()
    if len(pdf_bytes) > OPENAI_PDF_MAX_BYTES:
        raise ValueError(f"{pdf_path} is larger than the {OPENAI_PDF_MAX_BYTES} byte OpenAI PDF input limit")

    client = OpenAI()
    pdf_data = base64.b64encode(pdf_bytes).decode("utf-8")
    last_exc: Exception | None = None

    for attempt in range(1, OPENAI_CONVERSION_MAX_RETRIES + 1):
        try:
            response = client.responses.create(
                model=OPENAI_CONVERSION_MODEL,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": pdf_path.name,
                                "file_data": f"data:application/pdf;base64,{pdf_data}",
                            },
                            {
                                "type": "input_text",
                                "text": OPENAI_PDF_TO_MARKDOWN_PROMPT,
                            },
                        ],
                    }
                ],
            )
            markdown = response_output_text(response)
            if not markdown:
                raise RuntimeError("OpenAI returned an empty Markdown response")
            return markdown, f"openai:{OPENAI_CONVERSION_MODEL}"
        except Exception as exc:
            last_exc = exc
            if attempt == OPENAI_CONVERSION_MAX_RETRIES:
                break
            time.sleep(min(20, OPENAI_CONVERSION_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))))

    raise last_exc if last_exc is not None else RuntimeError("OpenAI PDF conversion failed without an exception")


def markdown_escape_cell(value: Any) -> str:
    return compact_text(str(value)).replace("|", r"\|")


def dataframe_to_markdown_table(dataframe: Any) -> str | None:
    rows = [
        [markdown_escape_cell(cell) for cell in row]
        for row in dataframe.fillna("").astype(str).values.tolist()
        if any(compact_text(str(cell)) for cell in row)
    ]
    return markdown_table_from_grid(rows)


def camelot_table_shape(table: Any) -> tuple[int, int]:
    dataframe = table.df
    return int(dataframe.shape[0]), int(dataframe.shape[1])


def camelot_parsing_value(report: dict[str, Any], key: str) -> float | None:
    value = report.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def should_keep_camelot_table(table: Any) -> bool:
    rows, columns = camelot_table_shape(table)
    if rows < CAMELOT_MIN_ROWS or columns < CAMELOT_MIN_COLUMNS:
        return False

    report = getattr(table, "parsing_report", {}) or {}
    accuracy = camelot_parsing_value(report, "accuracy")
    return accuracy is None or accuracy >= CAMELOT_MIN_ACCURACY


def write_camelot_table_csv(table: Any, csv_path: Path) -> None:
    try:
        table.to_csv(str(csv_path))
    except Exception:
        table.df.to_csv(csv_path, index=False, header=False)


def extract_camelot_tables(pdf_path: Path, artifact_dir: Path) -> list[CamelotExtractedTable]:
    try:
        import camelot
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Camelot conversion requires the `camelot-py` package. Install it with your project package manager "
            "and make sure Camelot's PDF/image dependencies are available."
        ) from exc

    camelot_dir = artifact_dir / "camelot"
    camelot_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[CamelotExtractedTable] = []
    seen_tables: set[str] = set()
    metadata_rows: list[dict[str, Any]] = []

    for flavor in CAMELOT_FLAVORS:
        try:
            tables = camelot.read_pdf(str(pdf_path), pages="all", flavor=flavor)
        except Exception as exc:
            print(f"Warning: Camelot {flavor} extraction failed for {pdf_path.name}: {exc}")
            continue

        for index, table in enumerate(tables, start=1):
            if not should_keep_camelot_table(table):
                continue

            markdown = dataframe_to_markdown_table(table.df)
            if not markdown:
                continue

            fingerprint = compact_text(markdown).lower()
            if fingerprint in seen_tables:
                continue
            seen_tables.add(fingerprint)

            report = getattr(table, "parsing_report", {}) or {}
            page = int(report.get("page") or getattr(table, "page", 0) or 0)
            order = int(report.get("order") or index)
            accuracy = camelot_parsing_value(report, "accuracy")
            whitespace = camelot_parsing_value(report, "whitespace")
            csv_path = camelot_dir / f"page-{page:03d}-table-{order:02d}-{flavor}.csv"
            write_camelot_table_csv(table, csv_path)

            extracted.append(
                CamelotExtractedTable(
                    page=page,
                    order=order,
                    flavor=flavor,
                    accuracy=accuracy,
                    whitespace=whitespace,
                    csv_path=csv_path,
                    markdown=markdown,
                )
            )
            rows, columns = camelot_table_shape(table)
            metadata_rows.append(
                {
                    "page": page,
                    "order": order,
                    "flavor": flavor,
                    "accuracy": accuracy if accuracy is not None else "",
                    "whitespace": whitespace if whitespace is not None else "",
                    "rows": rows,
                    "columns": columns,
                    "csv_path": str(csv_path),
                }
            )

    if metadata_rows:
        metadata_path = camelot_dir / "tables_metadata.csv"
        with metadata_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["page", "order", "flavor", "accuracy", "whitespace", "rows", "columns", "csv_path"],
            )
            writer.writeheader()
            writer.writerows(metadata_rows)

    return sorted(extracted, key=lambda table: (table.page, table.order, table.flavor))


def inject_camelot_tables_into_chunks(
    markdown_chunks: list[str],
    tables: list[CamelotExtractedTable],
) -> list[str]:
    tables_by_page: dict[int, list[CamelotExtractedTable]] = {}
    for table in tables:
        tables_by_page.setdefault(table.page, []).append(table)

    output_chunks: list[str] = []
    for page_index, markdown in enumerate(markdown_chunks, start=1):
        page_tables = tables_by_page.get(page_index, [])
        if not page_tables:
            output_chunks.append(markdown)
            continue

        table_markdown = "\n\n".join(table.markdown for table in page_tables)
        output_chunks.append("\n\n".join(part for part in (markdown.strip(), table_markdown) if part))

    extra_tables = [table.markdown for table in tables if table.page < 1 or table.page > len(markdown_chunks)]
    if extra_tables:
        output_chunks.append("\n\n".join(extra_tables))

    return output_chunks


def camelot_markdown_for_pdf(pdf_path: Path, artifact_dir: Path) -> tuple[str, str]:
    try:
        markdown_chunks, method = page_markdown_chunks(pdf_path)
    except Exception:
        markdown, method = pymupdf_markdown_for_pdf(pdf_path, artifact_dir)
        tables = extract_camelot_tables(pdf_path, artifact_dir)
        if tables:
            markdown = "\n\n".join(inject_camelot_tables_into_chunks([markdown], tables))
        return markdown, f"{method}+camelot:{len(tables)}"

    tables = extract_camelot_tables(pdf_path, artifact_dir)
    if tables:
        markdown_chunks = inject_camelot_tables_into_chunks(markdown_chunks, tables)

    try:
        markdown, recovered = inject_rotated_tables(pdf_path, markdown_chunks, artifact_dir)
        if recovered:
            method = f"{method}+rotated_tables:{recovered}"
    except Exception as exc:
        print(f"Warning: could not recover rotated tables from {pdf_path.name}: {exc}")
        markdown = "\n\n".join(chunk for chunk in markdown_chunks if chunk.strip())

    return markdown, f"{method}+camelot:{len(tables)}"


def normalize_heading(text: str) -> str:
    text = re.sub(r"^#+\s*", "", text).strip().lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_reference_heading(heading: str) -> bool:
    normalized = normalize_heading(heading)
    if normalized in REFERENCE_TITLES:
        return True
    return max(SequenceMatcher(None, normalized, title).ratio() for title in REFERENCE_TITLES) >= REFERENCE_HEADING_FUZZY_THRESHOLD


def remove_references_section(markdown: str) -> tuple[str, str | None]:
    headings = list(re.finditer(r"(?m)^(#{1,6}\s+.+?)\s*$", markdown))
    if not headings:
        return markdown, None

    min_start = int(len(markdown) * REFERENCE_HEADING_MIN_POSITION)
    for index, heading in enumerate(headings):
        if heading.start() < min_start:
            continue
        heading_text = heading.group(1)
        if not is_reference_heading(heading_text):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        trimmed = markdown[: heading.start()].rstrip() + "\n\n" + markdown[end:].lstrip()
        return trimmed, heading_text
    return markdown, None


def filter_pdfs_by_manifest(pdfs: list[Path], manifest: Path) -> list[Path]:
    with manifest.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if rows and "source_file" not in rows[0]:
        raise ValueError(f"Manifest {manifest} must contain a source_file column")

    selected = {row["source_file"] for row in rows}
    selected_names = {Path(source).name for source in selected}
    return [pdf for pdf in pdfs if str(pdf) in selected or pdf.name in selected_names]


def convert_pdfs_to_markdown(
    papers_dir: Path,
    out_dir: Path,
    *,
    converter: str = "pymupdf",
    limit: int | None = None,
    pdf_filter: str | None = None,
    manifest: Path | None = None,
    force: bool = False,
    keep_references: bool = False,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = discover_pdfs(papers_dir)
    if pdf_filter:
        pdfs = [pdf for pdf in pdfs if pdf_filter.lower() in pdf.name.lower()]
    if manifest:
        pdfs = filter_pdfs_by_manifest(pdfs, manifest)
    if limit is not None:
        pdfs = pdfs[:limit]

    written: list[Path] = []
    for pdf in pdfs:
        md_path = out_dir / f"{pdf.stem}.md"
        if md_path.exists() and not force:
            print(f"Skipping existing markdown: {md_path}")
            continue

        if converter == "openai":
            markdown, method = openai_markdown_for_pdf(pdf)
        elif converter == "camelot":
            markdown, method = camelot_markdown_for_pdf(pdf, out_dir / pdf.stem)
        else:
            markdown, method = pymupdf_markdown_for_pdf(pdf, out_dir / pdf.stem)
        if converter in {"pymupdf", "camelot"}:
            markdown = clean_pymupdf_artifacts(markdown)
        if not keep_references:
            markdown, removed_heading = remove_references_section(markdown)
            if removed_heading:
                print(f"Removed references section from {pdf.name}: {removed_heading}")
        md_path.write_text(markdown, encoding="utf-8")
        written.append(md_path)
        print(f"Wrote {md_path} using {method}")

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert PaperSIE PDFs to Markdown without chunking.")
    converter_group = parser.add_mutually_exclusive_group()
    converter_group.add_argument(
        "--pymupdf",
        action="store_const",
        const="pymupdf",
        dest="converter",
        default="pymupdf",
        help="Convert PDFs with the local PyMuPDF/pymupdf4llm workflow. This is the default.",
    )
    converter_group.add_argument(
        "--openai",
        action="store_const",
        const="openai",
        dest="converter",
        help="Convert PDFs by sending each whole PDF directly to the OpenAI API.",
    )
    converter_group.add_argument(
        "--camelot",
        action="store_const",
        const="camelot",
        dest="converter",
        help="Convert PDFs with PyMuPDF text extraction plus Camelot table extraction.",
    )
    parser.add_argument(
        "--papers-dir",
        type=Path,
        default=Path("pdfs"),
        help="Directory containing PDF papers.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("mds"),
        help="Directory where Markdown files will be written.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs to convert.")
    parser.add_argument("--pdf", type=str, default=None, help="Only convert PDFs whose filename contains this text.")
    parser.add_argument("--manifest", type=Path, default=None, help="CSV manifest with a source_file column.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing Markdown files.")
    parser.add_argument("--keep-references", action="store_true", help="Do not remove reference-like Markdown sections.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    written = convert_pdfs_to_markdown(
        args.papers_dir,
        args.out_dir,
        converter=args.converter,
        limit=args.limit,
        pdf_filter=args.pdf,
        manifest=args.manifest,
        force=args.force,
        keep_references=args.keep_references,
    )
    print(f"Converted {len(written)} PDFs to Markdown in {args.out_dir}")


if __name__ == "__main__":
    main()
