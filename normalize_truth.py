from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "tuttle2022.csv"
DEFAULT_OUT_DIR = ROOT / "data"
DEFAULT_REF_IDS = [
    "DS03", "SS05", "SS15", "DS10", "DS45",
    "SS06", "DS04", "DS43", "DS16", "DS25",
    "DS02", "SS04", "DS37", "SS12", "DS17",
    "DS18", "DS20", "DS21", "DS28", "DS36",
]

RESPONSE_FIELDS = [
    "Response type",
    "Response level",
    "Unit of measurement",
    "Average type",
    "N for computing average",
    "N UoM",
    "Lower error bound, if taken from Figure",
    "Upper error bound, if taken from Figure",
    "Lower error estimate",
    "Upper error estimate",
    "Error type",
    "Time to response, numeric",
    "Time to response, UoM",
    "Duration of response, numeric",
    "Duration of response, UoM",
    "Source of data",
]


def unique_name(name: str, seen: dict[str, int]) -> str:
    seen[name] += 1
    if seen[name] == 1:
        return name
    return f"{name}__{seen[name]}"


def read_two_header_csv(path: Path) -> tuple[list[str], list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise ValueError(f"{path} must contain two header rows")
    section_header = rows[0]
    field_header = rows[1]
    data_rows = rows[2:]
    return section_header, field_header, data_rows


def build_columns(section_header: list[str], field_header: list[str]) -> tuple[list[str], list[dict[str, str | int]]]:
    seen: dict[str, int] = defaultdict(int)
    unique_headers: list[str] = []
    metadata: list[dict[str, str | int]] = []
    current_section = ""
    for index, field in enumerate(field_header):
        if index < len(section_header) and section_header[index].strip():
            current_section = section_header[index].strip()
        field_name = field.strip()
        unique_header = unique_name(field_name, seen)
        unique_headers.append(unique_header)
        metadata.append(
            {
                "index": index,
                "section": current_section,
                "field": field_name,
                "unique_header": unique_header,
            }
        )
    return unique_headers, metadata


def response_slots(metadata: list[dict[str, str | int]]) -> dict[int, list[dict[str, str | int]]]:
    slots: dict[int, list[dict[str, str | int]]] = defaultdict(list)
    for column in metadata:
        section = str(column["section"])
        if not section.startswith("RESPONSE ") or " SPECIFICATIONS" not in section:
            continue
        try:
            slot = int(section.split()[1])
        except (IndexError, ValueError):
            continue
        slots[slot].append(column)
    return dict(sorted(slots.items()))


def setup_columns(metadata: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    return [
        column
        for column in metadata
        if not (str(column["section"]).startswith("RESPONSE ") and " SPECIFICATIONS" in str(column["section"]))
    ]


def row_value(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def normal_value(value: str) -> str:
    return value.strip().lower()


def is_reported_value(value: str) -> bool:
    return normal_value(value) not in {"", "n/a", "n/r", "na", "nan"}


def first_field_index(metadata: list[dict[str, str | int]], field: str) -> int:
    index = next((int(column["index"]) for column in metadata if column["field"] == field), None)
    if index is None:
        raise ValueError(f"Input CSV must contain a {field} column in the second header row")
    return index


def selected_paper_id(ref_id: str, selected_ref_ids: set[str]) -> str | None:
    if ref_id in selected_ref_ids:
        return ref_id
    paper_id = ref_id[:4]
    if paper_id in selected_ref_ids:
        return paper_id
    return None


def normalize_truth(input_csv: Path, out_dir: Path, ref_ids: list[str]) -> tuple[Path, Path, Path]:
    section_header, field_header, data_rows = read_two_header_csv(input_csv)
    _unique_headers, metadata = build_columns(section_header, field_header)
    response_by_slot = response_slots(metadata)
    setup_meta = setup_columns(metadata)

    ref_idx = first_field_index(metadata, "RefID")
    author_idx = first_field_index(metadata, "Author(s)")
    genus_idx = first_field_index(metadata, "Current genus name")
    species_idx = first_field_index(metadata, "Current species name")

    selected_ref_ids = set(ref_ids)
    selected_rows = [
        row for row in data_rows if selected_paper_id(row_value(row, ref_idx), selected_ref_ids) is not None
    ]

    setup_header = ["setup_id"] + [str(column["field"]) for column in setup_meta]
    response_header = ["response_id", "setup_id", "RefID"] + RESPONSE_FIELDS
    paper_header = ["RefID", "Author(s)", "num_setups", "num_responses", "num_species"]

    setup_rows: list[list[str]] = []
    response_rows: list[list[str]] = []
    counts_by_ref: dict[str, int] = defaultdict(int)
    setup_counts_by_paper: dict[str, int] = defaultdict(int)
    author_by_paper: dict[str, str] = {}
    species_by_paper: dict[str, set[tuple[str, str]]] = defaultdict(set)
    response_types_by_paper: dict[str, set[str]] = defaultdict(set)

    for row in selected_rows:
        ref_id = row_value(row, ref_idx)
        paper_id = selected_paper_id(ref_id, selected_ref_ids)
        if paper_id is None:
            continue
        counts_by_ref[ref_id] += 1
        setup_counts_by_paper[paper_id] += 1
        setup_id = f"{ref_id}_{counts_by_ref[ref_id]:02d}"
        setup_rows.append([setup_id] + [row_value(row, int(column["index"])) for column in setup_meta])

        author_by_paper.setdefault(paper_id, row_value(row, author_idx))
        genus = row_value(row, genus_idx).strip()
        species = row_value(row, species_idx).strip()
        if is_reported_value(genus) and is_reported_value(species):
            species_by_paper[paper_id].add((normal_value(genus), normal_value(species)))

        for slot, columns in response_by_slot.items():
            lookup = {str(column["field"]): row_value(row, int(column["index"])) for column in columns}
            response_type = lookup.get("Response type", "").strip()
            if not response_type:
                continue
            response_types_by_paper[paper_id].add(normal_value(response_type))
            response_id = f"{setup_id}_R{slot}"
            response_rows.append([response_id, setup_id, ref_id] + [lookup.get(field, "") for field in RESPONSE_FIELDS])

    paper_rows = [
        [
            ref_id,
            author_by_paper.get(ref_id, ""),
            str(setup_counts_by_paper[ref_id]),
            str(len(response_types_by_paper[ref_id])),
            str(len(species_by_paper[ref_id])),
        ]
        for ref_id in ref_ids
        if setup_counts_by_paper.get(ref_id, 0)
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    papers_path = out_dir / "truth_papers.csv"
    setups_path = out_dir / "truth_setups.csv"
    responses_path = out_dir / "truth_responses.csv"
    with papers_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(paper_header)
        writer.writerows(paper_rows)
    with setups_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(setup_header)
        writer.writerows(setup_rows)
    with responses_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(response_header)
        writer.writerows(response_rows)
    return papers_path, setups_path, responses_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Tuttle 2022 ground-truth CSV into setup and response tables.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ref-id", action="append", dest="ref_ids", default=None, help="RefID to include. Can be passed multiple times.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ref_ids = args.ref_ids or DEFAULT_REF_IDS
    papers_path, setups_path, responses_path = normalize_truth(args.input_csv, args.out_dir, ref_ids)
    print(f"Wrote {papers_path}")
    print(f"Wrote {setups_path}")
    print(f"Wrote {responses_path}")


if __name__ == "__main__":
    main()
