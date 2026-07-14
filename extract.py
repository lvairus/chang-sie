from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError


ROOT = Path(__file__).resolve().parent
DEFAULT_MD_DIR = ROOT / "mds"
DEFAULT_MANIFEST = ROOT / "data" / "md_to_id_map.csv"
OUTPUTS_ROOT = ROOT / "outputs"
PROMPT_PATH = ROOT / "prompt.py"
SCHEMA_PATH = ROOT / "schema-small-req.py"
DEFAULT_CONFIG = ROOT / "config.json"


def load_env_file() -> None:
    env_path = ROOT / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return
    load_dotenv(env_path)


load_env_file()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_LLM_MAX_RETRIES = 4
DEFAULT_LLM_RETRY_BACKOFF_SECONDS = 1.0
MODEL = DEFAULT_MODEL
LLM_MAX_RETRIES = DEFAULT_LLM_MAX_RETRIES
LLM_RETRY_BACKOFF_SECONDS = DEFAULT_LLM_RETRY_BACKOFF_SECONDS


def load_prompt_module() -> Any:
    spec = importlib.util.spec_from_file_location("prompt_tuttle", PROMPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load prompt module from {PROMPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prompt_tuttle = load_prompt_module()
SYSTEM_PROMPT = prompt_tuttle.SYSTEM_PROMPT
build_user_prompt = prompt_tuttle.build_user_prompt
build_user_prompt_with_structure = prompt_tuttle.build_user_prompt_with_structure


def load_schema_module() -> Any:
    spec = importlib.util.spec_from_file_location("schema_tuttle", SCHEMA_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load schema module from {SCHEMA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


schema_tuttle = load_schema_module()
PaperExtraction = schema_tuttle.PaperExtraction


def unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def field_aliases(model: type[BaseModel], *, exclude: set[str] | None = None) -> list[str]:
    excluded = exclude or set()
    return [
        field.alias or name
        for name, field in model.model_fields.items()
        if name not in excluded
    ]


def is_model_class(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, BaseModel)


def response_model_from_setup() -> type[BaseModel]:
    responses_field = schema_tuttle.ExperimentalSetup.model_fields.get("responses")
    if responses_field is None:
        return schema_tuttle.ResponseMeasurement
    args = get_args(responses_field.annotation)
    for arg in args:
        if is_model_class(arg):
            return arg
    return schema_tuttle.ResponseMeasurement


def setup_schema_columns() -> list[str]:
    columns = ["setup_id", "RefID"]
    for name, field in schema_tuttle.ExperimentalSetup.model_fields.items():
        if name == "responses":
            continue
        annotation = field.annotation
        if is_model_class(annotation):
            columns.extend(field_aliases(annotation))
        elif get_origin(annotation) is None:
            columns.append(field.alias or name)
    columns.extend(["Data extracted by", "Date of completion of data extraction"])
    return unique(columns)


PAPER_INFO_COLUMNS = unique(
    [
        "RefID",
        *field_aliases(schema_tuttle.BibliographicMetadata, exclude={"ref_id"}),
        *field_aliases(PaperExtraction, exclude={"schema_version", "bibliography", "setups"}),
    ]
)
SETUP_COLUMNS = setup_schema_columns()
RESPONSE_COLUMNS = unique(["response_id", "setup_id", "RefID", *field_aliases(response_model_from_setup())])

EXTRACTIONS_INFO_COLUMNS = [
    "md_filename",
    "ref_id",
    "model",
    "status",
    "parse_mode",
    "extraction_seconds",
    "input_tokens",
    "output_tokens",
    "total_tokens",
]


@dataclass(frozen=True)
class ManifestRow:
    md_filename: str
    ref_id: str


class LLMParseError(Exception):
    def __init__(self, parse_mode: str, exc: Exception) -> None:
        super().__init__(str(exc))
        self.parse_mode = parse_mode
        self.original_exception = exc


def value_for_csv(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return value


def usage_to_row(
    md_filename: str,
    ref_id: str,
    status: str,
    usage: Any,
    parse_mode: str = "",
    extraction_seconds: float | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if usage is not None:
        if hasattr(usage, "model_dump"):
            data = usage.model_dump()
        elif isinstance(usage, dict):
            data = usage
    input_tokens = data.get("input_tokens", data.get("prompt_tokens", 0)) or 0
    output_tokens = data.get("output_tokens", data.get("completion_tokens", 0)) or 0
    total_tokens = data.get("total_tokens", 0) or 0
    return {
        "md_filename": md_filename,
        "ref_id": ref_id,
        "model": MODEL,
        "status": status,
        "parse_mode": parse_mode,
        "extraction_seconds": "" if extraction_seconds is None else round(extraction_seconds, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def load_manifest(path: Path) -> list[ManifestRow]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    required = {"md_filename", "ref_id"}
    if rows and not required.issubset(rows[0]):
        raise ValueError(f"{path} must contain columns: md_filename, ref_id")
    return [ManifestRow(md_filename=row["md_filename"], ref_id=row["ref_id"]) for row in rows]


def prepare_out_dir(out_dir: Path, *, force: bool) -> None:
    if out_dir.exists():
        existing = [path for path in out_dir.iterdir() if path.name != ".DS_Store"]
        if existing and not force:
            raise FileExistsError(f"Output folder already contains files: {out_dir}. Use --force or choose a new run name.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_logs").mkdir(exist_ok=True)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def log_error(log_dir: Path, row: ManifestRow, stage: str, exc: Exception, parse_mode: str = "") -> None:
    payload = [
        f"ref_id: {row.ref_id}",
        f"md_filename: {row.md_filename}",
        f"stage: {stage}",
        f"parse_mode: {parse_mode}",
        f"error_type: {type(exc).__name__}",
        f"message: {exc}",
    ]
    validation_error = exc.original_exception if isinstance(exc, LLMParseError) else exc
    if isinstance(validation_error, ValidationError):
        payload.append("validation_errors:")
        payload.append(json.dumps(validation_error.errors(), indent=2))
    (log_dir / f"{row.ref_id}.error.txt").write_text("\n".join(payload), encoding="utf-8")


def response_schema() -> dict[str, Any]:
    return PaperExtraction.model_json_schema()


def response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "PaperExtraction",
            "strict": True,
            "schema": response_schema(),
        },
    }


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    return stripped[start : end + 1]


def replace_none_with_na(value: Any) -> Any:
    if value is None:
        return "n/a"
    if isinstance(value, dict):
        return {key: replace_none_with_na(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_none_with_na(item) for item in value]
    return value


def validate_extraction_json(content: str) -> PaperExtraction:
    raw_data = json.loads(extract_json_object(content))
    raw_data = replace_none_with_na(raw_data)
    return PaperExtraction.model_validate(raw_data)


def call_openrouter_structured(client: Any, *, markdown: str) -> tuple[PaperExtraction, Any, str]:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(markdown=markdown)},
        ],
        response_format=response_format(),
        extra_body={
            "provider": {
                "require_parameters": True,
            }
        },
    )
    content = response.choices[0].message.content or ""
    try:
        extraction = validate_extraction_json(content)
    except Exception as exc:
        raise LLMParseError("structured", exc) from exc
    return extraction, getattr(response, "usage", None), "structured"


def call_openrouter_prompt_schema(client: Any, *, markdown: str) -> tuple[PaperExtraction, Any, str]:
    schema_json = json.dumps(response_schema(), indent=2)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt_with_structure(markdown=markdown, schema_json=schema_json)},
        ],
    )
    content = response.choices[0].message.content or ""
    try:
        extraction = validate_extraction_json(content)
    except Exception as exc:
        raise LLMParseError("fallback", exc) from exc
    return extraction, getattr(response, "usage", None), "fallback"


def is_structured_output_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = [
        "response_format",
        "structured output",
        "structured_outputs",
        "require_parameters",
        "unsupported parameter",
        "not supported",
    ]
    return any(marker in text for marker in markers)


def call_llm_once(client: Any, *, markdown: str, md_path: Path, ref_id: str) -> tuple[PaperExtraction, Any, str]:
    try:
        extraction, usage, parse_mode = call_openrouter_structured(client, markdown=markdown)
    except Exception as exc:
        if not is_structured_output_error(exc):
            raise
        extraction, usage, parse_mode = call_openrouter_prompt_schema(client, markdown=markdown)
    extraction.bibliography.ref_id = ref_id
    extraction.bibliography.source_file_path = str(md_path)
    return extraction, usage, parse_mode


def call_llm(client: Any, *, markdown: str, md_path: Path, ref_id: str) -> tuple[PaperExtraction, Any, str]:
    last_exc: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            return call_llm_once(client, markdown=markdown, md_path=md_path, ref_id=ref_id)
        except Exception as exc:
            last_exc = exc
            if attempt == LLM_MAX_RETRIES:
                break
            import time

            time.sleep(min(20, LLM_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))))
    raise last_exc if last_exc is not None else RuntimeError("OpenRouter call failed without an exception")


def no_api_extraction(md_path: Path, ref_id: str) -> PaperExtraction:
    return PaperExtraction.model_validate(
        {
            "schema_version": getattr(schema_tuttle, "SCHEMA_VERSION", SCHEMA_PATH.stem),
            "bibliography": {
                "source_file_path": str(md_path),
                "ref_id": ref_id,
                "title": "n/r",
                "authors": [],
                "year": "n/r",
                "doi": "n/r",
            },
            "num_species": 0,
            "num_setups": 0,
            "num_responses": 0,
            "setups": [],
            "warnings": ["no-api dry run: extraction skipped"],
        }
    )


def csv_ready_mapping(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value_for_csv(value) for key, value in data.items()}


def model_csv_mapping(model: BaseModel) -> dict[str, Any]:
    return csv_ready_mapping(model.model_dump(by_alias=True))


def setup_csv_mapping(setup: BaseModel) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for name, value in setup:
        if name == "responses":
            continue
        if isinstance(value, BaseModel):
            row.update(model_csv_mapping(value))
        else:
            field = setup.__class__.model_fields[name]
            row[field.alias or name] = value_for_csv(value)
    return row


def normalize_extractions(extractions: list[PaperExtraction]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    paper_rows: list[dict[str, Any]] = []
    setup_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []

    extraction_date = datetime.now(timezone.utc).date().isoformat()
    for extraction in extractions:
        bibliography = model_csv_mapping(extraction.bibliography)
        ref_id = str(bibliography.get("RefID", "") or getattr(extraction.bibliography, "ref_id", ""))
        paper_data = extraction.model_dump(
            by_alias=True,
            exclude={"schema_version", "bibliography", "setups"},
        )
        paper_row = {"RefID": ref_id}
        paper_row.update(bibliography)
        paper_row.update(csv_ready_mapping(paper_data))
        paper_rows.append({column: paper_row.get(column, "") for column in PAPER_INFO_COLUMNS})

        for setup_index, setup in enumerate(extraction.setups, start=1):
            setup_id = f"{ref_id}_{setup_index:03d}"
            setup_row = {
                "setup_id": setup_id,
                "RefID": ref_id,
                **setup_csv_mapping(setup),
                "Data extracted by": MODEL,
                "Date of completion of data extraction": extraction_date,
            }
            setup_rows.append({column: setup_row.get(column, "") for column in SETUP_COLUMNS})

            for response_index, response in enumerate(setup.responses, start=1):
                response_row = {
                    "response_id": f"{setup_id}_R{response_index:02d}",
                    "setup_id": setup_id,
                    "RefID": ref_id,
                    **model_csv_mapping(response),
                }
                response_rows.append({column: response_row.get(column, "") for column in RESPONSE_COLUMNS})

    return paper_rows, setup_rows, response_rows


def parse_config_scalar(value: str) -> Any:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", ""}:
        return None
    if stripped.startswith(("\"", "'")) and stripped.endswith(("\"", "'")):
        return stripped[1:-1]
    try:
        return int(stripped)
    except ValueError:
        return stripped


def load_simple_yaml(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        config[key.strip()] = parse_config_scalar(value)
    return config


def load_config(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError:
            return load_simple_yaml(path)
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raise SystemExit("--config must point to a .json, .yaml, or .yml file.")


def normalize_config_keys(config: dict[str, Any]) -> dict[str, Any]:
    return {str(key).replace("-", "_"): value for key, value in config.items()}


def config_path(value: Any) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def merge_config_args(cli_args: argparse.Namespace) -> argparse.Namespace:
    ignored_config_keys = {"eval", "plot"}
    defaults: dict[str, Any] = {
        "md_dir": DEFAULT_MD_DIR,
        "manifest": DEFAULT_MANIFEST,
        "run_name": None,
        "domain": "coral",
        "limit": None,
        "force": False,
        "use_api": True,
        "model": DEFAULT_MODEL,
        "llm_max_retries": DEFAULT_LLM_MAX_RETRIES,
        "llm_retry_backoff_seconds": DEFAULT_LLM_RETRY_BACKOFF_SECONDS,
    }
    config = normalize_config_keys(load_config(cli_args.config)) if cli_args.config else {}
    config = {key: value for key, value in config.items() if key not in ignored_config_keys}
    for key in config:
        if key not in defaults:
            raise SystemExit(f"Unknown config key: {key}")

    merged = {**defaults, **config}
    for key, value in vars(cli_args).items():
        if key == "config" or value is None:
            continue
        merged[key] = value

    if not merged.get("run_name"):
        raise SystemExit("--run-name is required, either in config or command line.")
    for key in ["md_dir", "manifest"]:
        if key in config and getattr(cli_args, key) is None:
            merged[key] = config_path(merged[key])
        else:
            merged[key] = Path(merged[key])
    return argparse.Namespace(**merged)


def run(args: argparse.Namespace) -> None:
    global MODEL, LLM_MAX_RETRIES, LLM_RETRY_BACKOFF_SECONDS
    MODEL = args.model
    LLM_MAX_RETRIES = args.llm_max_retries
    LLM_RETRY_BACKOFF_SECONDS = args.llm_retry_backoff_seconds

    if args.use_api:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SystemExit("The openai package is required to run extraction through OpenRouter. Install project dependencies, then try again.") from exc
    else:
        OpenAI = None

    md_dir = args.md_dir
    manifest_path = args.manifest
    out_dir = OUTPUTS_ROOT / args.run_name
    print(f"Starting CoralSIE extraction run: {args.run_name}", flush=True)
    print("API provider: OpenRouter", flush=True)
    print(f"Model: {MODEL}", flush=True)
    print(f"Markdown folder: {md_dir}", flush=True)
    print(f"Manifest: {manifest_path}", flush=True)
    print(f"Output folder: {out_dir}", flush=True)
    print(f"Use API: {args.use_api}", flush=True)
    prepare_out_dir(out_dir, force=args.force)

    manifest_rows = load_manifest(manifest_path)
    if args.limit is not None:
        manifest_rows = manifest_rows[: args.limit]
    print(f"Loaded {len(manifest_rows)} manifest rows", flush=True)

    if args.use_api:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY must be set in the environment or CoralSIE/.env.")
        client = OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://localhost",
                "X-OpenRouter-Title": "CoralSIE Tuttle",
            },
        )
    else:
        client = None
    extractions: list[PaperExtraction] = []
    extractions_info_rows: list[dict[str, Any]] = []
    num_successful_extractions = 0
    schema_version = ""
    jsonl_path = out_dir / "extractions.jsonl"
    log_dir = out_dir / "run_logs"

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for index, row in enumerate(manifest_rows, start=1):
            extraction_start = time.perf_counter()
            print(f"Extracting file {index}/{len(manifest_rows)} || File: {row.md_filename} || ID: {row.ref_id}", flush=True)
            md_path = md_dir / row.md_filename
            print(f"Reading markdown: {md_path}", flush=True)
            if not md_path.exists():
                exc = FileNotFoundError(f"Markdown file not found: {md_path}")
                log_error(log_dir, row, "load_markdown", exc)
                extraction_seconds = time.perf_counter() - extraction_start
                extractions_info_rows.append(usage_to_row(row.md_filename, row.ref_id, "failed", None, extraction_seconds=extraction_seconds))
                print(f"Failed file {index}/{len(manifest_rows)}: {row.md_filename} (ref_id={row.ref_id})", flush=True)
                print(f"Writing error log: {log_dir / (row.ref_id + '.error.txt')}", flush=True)
                print("Continuing to next file", flush=True)
                continue
            try:
                markdown = md_path.read_text(encoding="utf-8")
                print(f"Read {len(markdown)} characters from markdown", flush=True)
                if not args.use_api:
                    print("Skipping LLM call because --no-use-api is set", flush=True)
                    extraction = no_api_extraction(md_path, row.ref_id)
                    usage = None
                    parse_mode = "no_api"
                else:
                    print(f"Prompting LLM with model {MODEL}...", flush=True)
                    extraction, usage, parse_mode = call_llm(client, markdown=markdown, md_path=md_path, ref_id=row.ref_id)
                    # print(f"Received LLM response for {row.md_filename}", flush=True)
                    # print(f"Injecting pipeline-controlled ref_id: {row.ref_id}", flush=True)
                print(f"Writing response to JSONL: {jsonl_path}", flush=True)
                jsonl.write(extraction.model_dump_json() + "\n")
                jsonl.flush()
                extractions.append(extraction)
                num_successful_extractions += 1
                if not schema_version:
                    schema_version = str(getattr(extraction, "schema_version", "") or "")
                extraction_seconds = time.perf_counter() - extraction_start
                extractions_info_rows.append(
                    usage_to_row(
                        row.md_filename,
                        row.ref_id,
                        "no_api" if not args.use_api else "success",
                        usage,
                        parse_mode,
                        extraction_seconds,
                    )
                )
                num_responses = sum(len(setup.responses) for setup in extraction.setups)
                print(
                    f"Finished file {index}/{len(manifest_rows)}: {row.md_filename} "
                    f"(setups={len(extraction.setups)}, responses={num_responses})",
                    flush=True,
                )
            except Exception as exc:
                parse_mode = exc.parse_mode if isinstance(exc, LLMParseError) else ""
                log_error(log_dir, row, "openrouter_parse", exc, parse_mode=parse_mode)
                extraction_seconds = time.perf_counter() - extraction_start
                extractions_info_rows.append(usage_to_row(row.md_filename, row.ref_id, "failed", None, parse_mode, extraction_seconds))
                print(f"Failed file {index}/{len(manifest_rows)}: {row.md_filename} (ref_id={row.ref_id})", flush=True)
                print(f"Writing error log: {log_dir / (row.ref_id + '.error.txt')}", flush=True)
                # print("Continuing to next file", flush=True)

    print("Normalizing extractions to CSV for evaluation", flush=True)
    paper_rows, setup_rows, response_rows = normalize_extractions(extractions)
    # print(f"Writing paper info CSV: {out_dir / 'paper_info.csv'}", flush=True)
    write_csv(out_dir / "paper_info.csv", PAPER_INFO_COLUMNS, paper_rows)
    # print(f"Writing setups CSV: {out_dir / 'setups.csv'}", flush=True)
    write_csv(out_dir / "setups.csv", SETUP_COLUMNS, setup_rows)
    # print(f"Writing responses CSV: {out_dir / 'responses.csv'}", flush=True)
    write_csv(out_dir / "responses.csv", RESPONSE_COLUMNS, response_rows)
    write_csv(out_dir / "extractions_info.csv", EXTRACTIONS_INFO_COLUMNS, extractions_info_rows)
    run_info = {
        "run_name": args.run_name,
        "domain": args.domain,
        "model": MODEL,
        "schema": schema_version or SCHEMA_PATH.stem,
        "num_papers": num_successful_extractions,
    }
    (out_dir / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")

    print(f"Wrote {jsonl_path}")
    print(f"Wrote {out_dir / 'paper_info.csv'} ({len(paper_rows)} rows)")
    print(f"Wrote {out_dir / 'setups.csv'} ({len(setup_rows)} rows)")
    print(f"Wrote {out_dir / 'responses.csv'} ({len(response_rows)} rows)")
    print(f"Wrote {out_dir / 'extractions_info.csv'}")
    print(f"Wrote {out_dir / 'run_info.json'}")
    print("Extraction run complete", flush=True)
    print(f"Successful papers: {len(extractions)}", flush=True)
    print(f"Failed papers: {len(extractions_info_rows) - num_successful_extractions}", flush=True)
    print(f"Total setups: {len(setup_rows)}", flush=True)
    print(f"Total responses: {len(response_rows)}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract CoralSIE structured data from Markdown papers with OpenRouter.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Optional JSON/YAML config file. Command-line arguments override config values.")
    parser.add_argument("--md-dir", type=Path, default=None, help="Folder containing Markdown files.")
    parser.add_argument("--manifest", type=Path, default=None, help="CSV with md_filename and ref_id columns.")
    parser.add_argument("--run-name", default=None, help="Run folder name created under CoralSIE/outputs.")
    parser.add_argument("--domain", default=None, help="Domain label written to run_info.json.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of manifest rows to process.")
    parser.add_argument("--force", action=argparse.BooleanOptionalAction, default=None, help="Allow writing into a non-empty run folder.")
    parser.add_argument("--use-api", action=argparse.BooleanOptionalAction, default=None, help="Run extraction through OpenRouter.")
    parser.add_argument("--model", default=None, help="OpenRouter model used for extraction.")
    parser.add_argument("--llm-max-retries", type=int, default=None, help="Maximum retry attempts for each LLM extraction.")
    parser.add_argument("--llm-retry-backoff-seconds", type=float, default=None, help="Base retry backoff in seconds.")
    return merge_config_args(parser.parse_args())


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
