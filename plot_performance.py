from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".matplotlib"))

import matplotlib.pyplot as plt
from matplotlib.patches import Patch


DEFAULT_DPI = 180
ROOT = Path(__file__).resolve().parent
OUTPUTS_ROOT = ROOT / "outputs"


def read_performance(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ["accuracy", "fuzzy_score"]:
            try:
                row[key] = float(row.get(key, 0) or 0)
            except ValueError:
                row[key] = 0.0
    return rows


def read_performance_by_arity(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ["arity_value", "correct", "total"]:
            try:
                row[key] = int(float(row.get(key, 0) or 0))
            except ValueError:
                row[key] = 0
        for key in ["accuracy", "fuzzy_score"]:
            try:
                row[key] = float(row.get(key, 0) or 0)
            except ValueError:
                row[key] = 0.0
    return rows


SPECO_COLORS = {
    "species": "#4c78a8",
    "sp": "#4c78a8",
    "exposure": "#f58518",
    "e": "#f58518",
    "coral": "#54a24b",
    "c": "#54a24b",
    "population": "#54a24b",
    "outcome": "#e45756",
    "o": "#e45756",
    "data reported?": "#e45756",
    "biblio": "#72b7b2",
    "arity": "#b279a2",
    "": "#9ca3af",
}


def speco_color(speco: Any) -> str:
    label = str(speco or "").strip().lower()
    return SPECO_COLORS.get(label, "#6b7280")


def save_bar_plot(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    title: str,
    metric: str = "accuracy",
    ylabel: str = "Accuracy",
    width: float | None = None,
    color_by_speco: bool = False,
    show_values: bool = False,
) -> None:
    if not rows:
        return
    labels = [row["variable"] for row in rows]
    values = [row[metric] for row in rows]
    colors = [speco_color(row.get("speco", "")) for row in rows] if color_by_speco else "#4c78a8"
    fig_width = width or max(10, len(rows) * 0.45)
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    bars = ax.bar(range(len(rows)), values, color=colors)
    ax.set_title(title)
    ax.set_xlabel("Variable")
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, 1.15 if show_values else 1.05)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(labels, rotation=50, ha="right")
    ax.grid(axis="y", alpha=0.25)
    if show_values:
        for bar, value in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                min(value + 0.02, 1.12),
                f"{value:.2f}",
                ha="center",
                va="bottom",
                rotation=0,
                fontsize=6,
            )
    if color_by_speco:
        speco_labels = []
        seen = set()
        for row in rows:
            label = str(row.get("speco", "") or "").strip()
            if label not in seen:
                seen.add(label)
                speco_labels.append(label)
        handles = [Patch(color=speco_color(label), label=label or "(blank)") for label in speco_labels]
        ax.legend(handles=handles, title="speco", loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=DEFAULT_DPI)
    plt.close(fig)


def save_violin_plot(rows: list[dict[str, Any]], group_col: str, path: Path, *, title: str) -> None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        group = str(row.get(group_col, "")).strip()
        if group:
            grouped[group].append(float(row["accuracy"]))
    if not grouped:
        return

    labels = sorted(grouped)
    values = [grouped[label] for label in labels]
    fig_width = max(8, len(labels) * 1.2)
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    parts = ax.violinplot(values, showmeans=True, showextrema=True)
    for body in parts["bodies"]:
        body.set_facecolor("#72b7b2")
        body.set_edgecolor("#3b6f6c")
        body.set_alpha(0.55)
    for idx, group_values in enumerate(values, start=1):
        ax.scatter([idx] * len(group_values), group_values, color="#1f2933", s=18, alpha=0.75, zorder=3)
    ax.set_title(title)
    ax.set_xlabel(group_col)
    ax.set_ylabel("Accuracy")
    ax.set_ylim(-0.05, 1.05)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=DEFAULT_DPI)
    plt.close(fig)


def save_arity_heatmap(rows: list[dict[str, Any]], arity_type: str, path: Path) -> None:
    filtered = [row for row in rows if row.get("arity_type") == arity_type]
    if not filtered:
        return

    variables = sorted({str(row["variable"]) for row in filtered})
    arity_values = sorted({int(row["arity_value"]) for row in filtered})
    accuracy_by_cell = {
        (str(row["variable"]), int(row["arity_value"])): float(row["accuracy"])
        for row in filtered
    }
    total_by_cell = {
        (str(row["variable"]), int(row["arity_value"])): int(row["total"])
        for row in filtered
    }
    matrix = [
        [accuracy_by_cell.get((variable, arity_value), float("nan")) for arity_value in arity_values]
        for variable in variables
    ]

    fig_width = max(8, len(arity_values) * 0.7)
    fig_height = max(6, len(variables) * 0.28)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    image = ax.imshow(matrix, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_title(f"Variable Accuracy by {arity_type}")
    ax.set_xlabel(arity_type)
    ax.set_ylabel("Variable")
    ax.set_xticks(range(len(arity_values)))
    ax.set_xticklabels([str(value) for value in arity_values])
    ax.set_yticks(range(len(variables)))
    ax.set_yticklabels(variables)

    if len(variables) * len(arity_values) <= 180:
        for y, variable in enumerate(variables):
            for x, arity_value in enumerate(arity_values):
                total = total_by_cell.get((variable, arity_value), 0)
                if total:
                    ax.text(x, y, str(total), ha="center", va="center", color="white", fontsize=7)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Accuracy")
    # cbar.set_label("Row-normalized accuracy")
    fig.tight_layout()
    fig.savefig(path, dpi=DEFAULT_DPI)
    plt.close(fig)


def plot_performance(performance_csv: Path, plots_dir: Path, *, top_n: int) -> list[Path]:
    rows = read_performance(performance_csv)
    plots_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    all_rows = rows
    path = plots_dir / "accuracy_by_variable_all.png"
    save_bar_plot(
        all_rows,
        path,
        title="Accuracy by Variable",
        color_by_speco=True,
        show_values=True,
    )
    outputs.append(path)

    path = plots_dir / "fuzzy_score_by_variable_all.png"
    save_bar_plot(
        all_rows,
        path,
        title="Fuzzy Score by Variable",
        metric="fuzzy_score",
        ylabel="Fuzzy Score",
        color_by_speco=True,
        show_values=True,
    )
    outputs.append(path)

    lowest_rows = sorted(rows, key=lambda row: (row["accuracy"], row["variable"]))[:top_n]
    path = plots_dir / f"accuracy_by_variable_lowest{top_n}.png"
    save_bar_plot(lowest_rows, path, title=f"Lowest {top_n} Variable Accuracies", width=10)
    outputs.append(path)

    highest_rows = sorted(rows, key=lambda row: (-row["accuracy"], row["variable"]))[:top_n]
    path = plots_dir / f"accuracy_by_variable_highest{top_n}.png"
    save_bar_plot(highest_rows, path, title=f"Highest {top_n} Variable Accuracies", width=10)
    outputs.append(path)

    for group_col in ["numcat", "oginf", "speco"]:
        path = plots_dir / f"accuracy_violin_by_{group_col}.png"
        save_violin_plot(rows, group_col, path, title=f"Accuracy Distribution by {group_col}")
        outputs.append(path)

    arity_rows = read_performance_by_arity(performance_csv.with_name("avg_performance_by_arity.csv"))
    for arity_type in ["num_species", "num_setups", "num_responses"]:
        path = plots_dir / f"accuracy_heatmap_by_{arity_type}.png"
        save_arity_heatmap(arity_rows, arity_type, path)
        if path.exists():
            outputs.append(path)

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot CoralSIE evaluation average performance metrics.")
    parser.add_argument("--run-name", required=True, help="Prediction run folder name under CoralSIE/outputs.")
    parser.add_argument("--performance-csv", type=Path, default=None, help="Optional explicit avg_performance.csv path.")
    parser.add_argument("--plots-dir", type=Path, default=None, help="Optional explicit output plot folder.")
    parser.add_argument("--top-n", type=int, default=10, help="Number of variables for highest/lowest bar plots.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_dir = OUTPUTS_ROOT / args.run_name / "eval"
    performance_csv = args.performance_csv or eval_dir / "avg_performance.csv"
    plots_dir = args.plots_dir or eval_dir / "plots"
    outputs = plot_performance(performance_csv, plots_dir, top_n=args.top_n)
    for path in outputs:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
