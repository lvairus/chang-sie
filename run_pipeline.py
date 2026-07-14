from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"


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
        try:
            return float(stripped)
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


def path_arg(value: Any) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else ROOT / path)


def add_optional_path(cmd: list[str], flag: str, value: Any) -> None:
    if value is not None:
        cmd.extend([flag, path_arg(value)])


def add_optional_value(cmd: list[str], flag: str, value: Any) -> None:
    if value is not None:
        cmd.extend([flag, str(value)])


def run_command(cmd: list[str]) -> None:
    print(f"Running: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CoralSIE extraction, evaluation, and plotting.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="JSON/YAML config file.")
    parser.add_argument("--run-name", default=None, help="Override run_name from config.")
    parser.add_argument("--skip-extract", action="store_true", help="Skip extraction.")
    parser.add_argument("--skip-eval", action="store_true", help="Skip evaluation.")
    parser.add_argument("--skip-plot", action="store_true", help="Skip plotting.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_config(config_path)
    run_name = args.run_name or config.get("run_name")
    if not run_name:
        raise SystemExit("run_name is required in config or with --run-name.")

    if not args.skip_extract:
        extract_cmd = [
            sys.executable,
            str(ROOT / "extract.py"),
            "--config",
            str(config_path),
            "--run-name",
            str(run_name),
        ]
        run_command(extract_cmd)

    if not args.skip_eval:
        eval_config = config.get("eval", {}) or {}
        eval_cmd = [
            sys.executable,
            str(ROOT / "eval.py"),
            "--run-name",
            str(run_name),
        ]
        add_optional_path(eval_cmd, "--truth-setups", eval_config.get("truth_setups"))
        add_optional_path(eval_cmd, "--truth-responses", eval_config.get("truth_responses"))
        add_optional_path(eval_cmd, "--var-task-types", eval_config.get("var_task_types"))
        add_optional_value(eval_cmd, "--setup-threshold", eval_config.get("setup_threshold"))
        add_optional_value(eval_cmd, "--response-threshold", eval_config.get("response_threshold"))
        run_command(eval_cmd)

    if not args.skip_plot:
        plot_config = config.get("plot", {}) or {}
        plot_cmd = [
            sys.executable,
            str(ROOT / "plot_performance.py"),
            "--run-name",
            str(run_name),
        ]
        add_optional_path(plot_cmd, "--performance-csv", plot_config.get("performance_csv"))
        add_optional_path(plot_cmd, "--plots-dir", plot_config.get("plots_dir"))
        add_optional_value(plot_cmd, "--top-n", plot_config.get("top_n"))
        run_command(plot_cmd)


if __name__ == "__main__":
    main()
