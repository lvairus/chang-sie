from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUTS_ROOT = ROOT / "outputs"
DEFAULT_TRUTH_SETUPS = ROOT / "data" / "truth_setups.csv"
DEFAULT_TRUTH_RESPONSES = ROOT / "data" / "truth_responses.csv"
DEFAULT_VAR_TYPES = ROOT / "data" / "var_task_types.csv"

SETUP_MATCH_THRESHOLD = 0.55
RESPONSE_MATCH_THRESHOLD = 0.55
TAXON_MATCH_THRESHOLD = 0.90

SETUP_MATCH_COLUMNS = [
    "Current genus name",
    "Current species name",
    "Sediment composition",
    "Sediment level",
    "Sediment exposure duration",
]

IDENTIFIER_COLUMNS = {
    "setup_id",
    "response_id",
    "response_slot",
}

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def numeric_value(value: Any) -> float | None:
    text = norm(value).replace(",", "")
    if not text or text in {"nan", "inf", "+inf", "-inf"}:
        return None
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?", text):
        return None
    return float(text)


def exact_equal(left: Any, right: Any) -> bool:
    left_num = numeric_value(left)
    right_num = numeric_value(right)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    return norm(left) == norm(right)


def fuzzy_score(left: Any, right: Any) -> float:
    left_n = norm(left)
    right_n = norm(right)
    if not left_n and not right_n:
        return 1.0
    if not left_n or not right_n:
        return 0.0
    return SequenceMatcher(None, left_n, right_n).ratio()


def prf(num_matched: int, num_truth: int, num_pred: int) -> dict[str, float]:
    precision = num_matched / num_pred if num_pred else 0.0
    recall = num_matched / num_truth if num_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def by_ref(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("RefID", "")].append(row)
    return grouped


def by_column(rows: list[dict[str, str]], column: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(column, "")].append(row)
    return grouped


def ref_ids_with_extractions(
    paper_info: list[dict[str, str]],
    setups: list[dict[str, str]],
    responses: list[dict[str, str]],
) -> set[str]:
    ref_ids = {row.get("RefID", "") for row in paper_info}
    ref_ids.update(row.get("RefID", "") for row in setups)
    ref_ids.update(row.get("RefID", "") for row in responses)
    return {ref_id for ref_id in ref_ids if ref_id}


def filter_by_ref(rows: list[dict[str, str]], ref_ids: set[str]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("RefID", "") in ref_ids]


def load_task_types(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(path)
    return {row["ground_truth_name"]: row for row in rows if row.get("ground_truth_name")}
    # return {row["name"]: row for row in rows if row.get("name")}


def setup_match_score(truth: dict[str, str], pred: dict[str, str]) -> tuple[float, dict[str, float]]:
    component_scores: dict[str, float] = {}
    genus = fuzzy_score(truth.get("Current genus name"), pred.get("Current genus name"))
    species = fuzzy_score(truth.get("Current species name"), pred.get("Current species name"))
    component_scores["Current genus name"] = genus
    component_scores["Current species name"] = species
    if genus < TAXON_MATCH_THRESHOLD or species < TAXON_MATCH_THRESHOLD:
        return 0.0, component_scores
    weighted_scores = [(genus, 0.3), (species, 0.3)]
    optional_components = [
        ("Sediment level", 0.15, lambda: 1.0 if exact_equal(truth.get("Sediment level"), pred.get("Sediment level")) else 0.0),
        ("Sediment exposure duration", 0.15, lambda: 1.0 if exact_equal(truth.get("Sediment exposure duration"), pred.get("Sediment exposure duration")) else 0.0),
        ("Sediment composition", 0.1, lambda: fuzzy_score(truth.get("Sediment composition"), pred.get("Sediment composition"))),
    ]
    for column, weight, scorer in optional_components:
        if column not in pred:
            continue
        score = scorer()
        component_scores[column] = score
        weighted_scores.append((score, weight))
    total_weight = sum(weight for _, weight in weighted_scores)
    score = sum(score * weight for score, weight in weighted_scores) / total_weight if total_weight else 0.0
    return score, component_scores


def response_match_score(truth: dict[str, str], pred: dict[str, str]) -> tuple[float, dict[str, float]]:
    response_type = fuzzy_score(truth.get("Response type"), pred.get("Response type"))
    return response_type, {"Response type": response_type}


def rounded_scores(scores: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 2) for key, value in scores.items()}


def best_one_to_one_matches(
    truth_rows: list[dict[str, str]],
    pred_rows: list[dict[str, str]],
    *,
    scorer: Any,
    threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    candidates: list[tuple[float, int, int, dict[str, float]]] = []
    best_by_truth: dict[int, tuple[float, dict[str, str], dict[str, float]]] = {}
    for truth_idx, truth in enumerate(truth_rows):
        for pred_idx, pred in enumerate(pred_rows):
            score, components = scorer(truth, pred)
            current_best = best_by_truth.get(truth_idx)
            if current_best is None or score > current_best[0]:
                best_by_truth[truth_idx] = (score, pred, components)
            if score >= threshold:
                candidates.append((score, truth_idx, pred_idx, components))

    candidates.sort(key=lambda item: item[0], reverse=True)
    used_truth: set[int] = set()
    used_pred: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, truth_idx, pred_idx, components in candidates:
        if truth_idx in used_truth or pred_idx in used_pred:
            continue
        used_truth.add(truth_idx)
        used_pred.add(pred_idx)
        matches.append(
            {
                "truth": truth_rows[truth_idx],
                "pred": pred_rows[pred_idx],
                "match_score": score,
                "component_scores": components,
            }
        )

    unmatched_truth = []
    for idx, row in enumerate(truth_rows):
        if idx in used_truth:
            continue
        best = best_by_truth.get(idx)
        annotated = {
            "best_score": "" if best is None else best[0],
            "best_match": "" if best is None else best[1].get("setup_id", best[1].get("response_id", "")),
            "best_pred_response_type": "" if best is None else best[1].get("Response type", ""),
            "best_component_scores": "" if best is None else json.dumps(rounded_scores(best[2]), sort_keys=True),
        }
        annotated.update(row)
        unmatched_truth.append(annotated)
    unmatched_pred = [row for idx, row in enumerate(pred_rows) if idx not in used_pred]
    return matches, unmatched_truth, unmatched_pred


def matched_fieldnames(columns: list[str]) -> list[str]:
    names = ["match_score", "component_scores"]
    for col in columns:
        names.extend([f"pred_{col}", f"truth_{col}"])
    return names


def matched_rows(matches: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    for match in matches:
        row = {
            "match_score": match["match_score"],
            "component_scores": json.dumps(rounded_scores(match["component_scores"]), sort_keys=True),
        }
        for col in columns:
            row[f"truth_{col}"] = match["truth"].get(col, "")
            row[f"pred_{col}"] = match["pred"].get(col, "")
        rows.append(row)
    return rows


def matched_response_fieldnames(columns: list[str]) -> list[str]:
    names = ["pred_response_type", "truth_response_type", "match_score", "pred_setup_id", "truth_setup_id"]
    for col in columns:
        names.extend([f"pred_{col}", f"truth_{col}"])
    return names


def matched_response_rows(matches: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    for match in matches:
        row = {
            "pred_response_type": match["pred"].get("Response type", ""),
            "truth_response_type": match["truth"].get("Response type", ""),
            "match_score": match["match_score"],
            "pred_setup_id": match["pred"].get("setup_id", ""),
            "truth_setup_id": match["truth"].get("setup_id", ""),
        }
        for col in columns:
            row[f"pred_{col}"] = match["pred"].get(col, "")
            row[f"truth_{col}"] = match["truth"].get(col, "")
        rows.append(row)
    return rows


def unmatched_truth_response_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted = []
    for row in rows:
        out = dict(row)
        out.pop("best_component_scores", None)
        out.pop("best_pred_response_type", None)
        out["truth_response_type"] = row.get("Response type", "")
        out["pred_response_type"] = row.get("best_pred_response_type", "")
        formatted.append(out)
    return formatted


def comparable_columns(pred_rows: list[dict[str, str]], truth_rows: list[dict[str, str]]) -> list[str]:
    pred_cols = set(pred_rows[0].keys()) if pred_rows else set()
    truth_cols = set(truth_rows[0].keys()) if truth_rows else set()
    return [col for col in pred_rows[0].keys() if col in truth_cols and col not in IDENTIFIER_COLUMNS] if pred_rows else [
        col for col in truth_rows[0].keys() if col not in IDENTIFIER_COLUMNS
    ]


def add_variable_scores(
    counts: dict[str, dict[str, float]],
    matches: list[dict[str, Any]],
    columns: list[str],
    task_types: dict[str, dict[str, str]],
) -> None:
    for match in matches:
        pred = match["pred"]
        truth = match["truth"]
        for col in columns:
            if col in IDENTIFIER_COLUMNS or col == "RefID":
                continue
            variable = col
            exact_score = 1.0 if exact_equal(pred.get(col), truth.get(col)) else 0.0
            variable_type = task_types.get(variable, {}).get("cat/bin/num/desc", "")
            fuzzy_match_score = fuzzy_score(pred.get(col), truth.get(col)) if variable_type in {"cat", "desc"} else exact_score
            counts[variable]["total"] += 1
            counts[variable]["fuzzy_score_sum"] += fuzzy_match_score
            if exact_score:
                counts[variable]["correct"] += 1


def add_variable_scores_by_arity(
    counts: dict[str, dict[int, dict[str, dict[str, float]]]],
    matches: list[dict[str, Any]],
    columns: list[str],
    arities_by_ref: dict[str, dict[str, int]],
    task_types: dict[str, dict[str, str]],
) -> None:
    for match in matches:
        pred = match["pred"]
        truth = match["truth"]
        arities = arities_by_ref.get(truth.get("RefID", ""), {})
        for col in columns:
            if col in IDENTIFIER_COLUMNS or col == "RefID":
                continue
            variable = col
            exact_score = 1.0 if exact_equal(pred.get(col), truth.get(col)) else 0.0
            variable_type = task_types.get(variable, {}).get("cat/bin/num/desc", "")
            fuzzy_match_score = fuzzy_score(pred.get(col), truth.get(col)) if variable_type in {"cat", "desc"} else exact_score
            for arity_type, arity_value in arities.items():
                bucket = counts[arity_type][arity_value][variable]
                bucket["total"] += 1
                bucket["fuzzy_score_sum"] += fuzzy_match_score
                if exact_score:
                    bucket["correct"] += 1


def truth_num_species(truth_setups: list[dict[str, str]]) -> int:
    species = set()
    for row in truth_setups:
        genus = norm(row.get("Current genus name"))
        species_name = norm(row.get("Current species name"))
        if genus and species_name and genus not in {"n/r", "n/a"} and species_name not in {"n/r", "n/a"}:
            species.add((genus, species_name))
    return len(species)


def truth_num_responses(truth_responses: list[dict[str, str]]) -> int:
    return len({norm(row.get("Response type")) for row in truth_responses if norm(row.get("Response type"))})


def truth_arities_by_ref(
    truth_setups_by_ref: dict[str, list[dict[str, str]]],
    truth_responses_by_ref: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, int]]:
    return {
        ref_id: {
            "num_species": truth_num_species(truth_setups),
            "num_setups": len(truth_setups),
            "num_responses": truth_num_responses(truth_responses_by_ref.get(ref_id, [])),
        }
        for ref_id, truth_setups in truth_setups_by_ref.items()
    }


def response_type_summary(
    matches: list[dict[str, Any]],
    unmatched_truth: list[dict[str, str]],
    unmatched_pred: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    summary = {}
    ref_ids = set()
    for match in matches:
        ref_ids.add(match["truth"].get("RefID", ""))
        ref_ids.add(match["pred"].get("RefID", ""))
    ref_ids.update(row.get("RefID", "") for row in unmatched_truth)
    ref_ids.update(row.get("RefID", "") for row in unmatched_pred)
    for ref_id in sorted(ref for ref in ref_ids if ref):
        truth_types = sorted({row.get("Response type", "") for row in unmatched_truth if row.get("RefID", "") == ref_id and row.get("Response type", "")})
        pred_types = sorted({row.get("Response type", "") for row in unmatched_pred if row.get("RefID", "") == ref_id and row.get("Response type", "")})
        matched = {
            match["truth"].get("Response type", ""): match["pred"].get("Response type", "")
            for match in matches
            if match["truth"].get("RefID", "") == ref_id and match["truth"].get("Response type", "")
        }
        summary[ref_id] = {"truth": truth_types, "pred": pred_types, "matched": matched}
    return summary


def add_paper_count_scores(
    counts: dict[str, dict[str, float]],
    paper_info: list[dict[str, str]],
    truth_setups_by_ref: dict[str, list[dict[str, str]]],
    truth_responses_by_ref: dict[str, list[dict[str, str]]],
) -> None:
    paper_by_ref = {row.get("RefID", ""): row for row in paper_info}
    for ref_id, truth_setups in truth_setups_by_ref.items():
        pred = paper_by_ref.get(ref_id)
        if pred is None:
            continue
        expectations = {
            "num_species": truth_num_species(truth_setups),
            "num_setups": len(truth_setups),
            "num_responses": truth_num_responses(truth_responses_by_ref.get(ref_id, [])),
        }
        for variable, truth_value in expectations.items():
            exact_score = 1.0 if exact_equal(pred.get(variable), str(truth_value)) else 0.0
            counts[variable]["total"] += 1
            counts[variable]["fuzzy_score_sum"] += exact_score
            if exact_score:
                counts[variable]["correct"] += 1


def performance_rows(counts: dict[str, dict[str, float]], task_types: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for variable in counts:
        total = counts[variable]["total"]
        correct = counts[variable]["correct"]
        fuzzy_score_sum = counts[variable]["fuzzy_score_sum"]
        meta = task_types.get(variable, {})
        rows.append(
            {
                "variable": variable,
                "accuracy": correct / total if total else 0.0,
                "fuzzy_score": fuzzy_score_sum / total if total else 0.0,
                "numcat": meta.get("cat/bin/num/desc", ""),
                "oginf": meta.get("og/calc/inf/summ", ""),
                "speco": meta.get("SPECO", ""),
            }
        )
    return rows


def performance_by_arity_rows(
    counts: dict[str, dict[int, dict[str, dict[str, float]]]],
    task_types: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for arity_type in sorted(counts):
        for arity_value in sorted(counts[arity_type]):
            for variable in sorted(counts[arity_type][arity_value]):
                total = counts[arity_type][arity_value][variable]["total"]
                correct = counts[arity_type][arity_value][variable]["correct"]
                fuzzy_score_sum = counts[arity_type][arity_value][variable]["fuzzy_score_sum"]
                meta = task_types.get(variable, {})
                rows.append(
                    {
                        "arity_type": arity_type,
                        "arity_value": arity_value,
                        "variable": variable,
                        "correct": int(correct),
                        "total": int(total),
                        "accuracy": correct / total if total else 0.0,
                        "fuzzy_score": fuzzy_score_sum / total if total else 0.0,
                        "numcat": meta.get("cat/bin/num/desc", ""),
                        "oginf": meta.get("og/calc/inf/summ", ""),
                        "speco": meta.get("SPECO", ""),
                    }
                )
    return rows


def run(args: argparse.Namespace) -> None:
    out_dir = OUTPUTS_ROOT / args.run_name
    eval_dir = out_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    pred_paper_info = read_csv(out_dir / "paper_info.csv")
    pred_setups = read_csv(out_dir / "setups.csv")
    pred_responses = read_csv(out_dir / "responses.csv")
    truth_setups = read_csv(args.truth_setups)
    truth_responses = read_csv(args.truth_responses)
    task_types = load_task_types(args.var_task_types)
    evaluated_ref_ids = ref_ids_with_extractions(pred_paper_info, pred_setups, pred_responses)
    truth_setups = filter_by_ref(truth_setups, evaluated_ref_ids)
    truth_responses = filter_by_ref(truth_responses, evaluated_ref_ids)

    pred_setups_by_ref = by_ref(pred_setups)
    pred_responses_by_ref = by_ref(pred_responses)
    truth_setups_by_ref = by_ref(truth_setups)
    truth_responses_by_ref = by_ref(truth_responses)
    pred_responses_by_setup = by_column(pred_responses, "setup_id")
    truth_responses_by_setup = by_column(truth_responses, "setup_id")
    ref_ids = sorted(evaluated_ref_ids or set(pred_setups_by_ref) or set(pred_responses_by_ref))
    arities_by_ref = truth_arities_by_ref(truth_setups_by_ref, truth_responses_by_ref)

    all_setup_matches: list[dict[str, Any]] = []
    all_unmatched_truth_setups: list[dict[str, str]] = []
    all_unmatched_pred_setups: list[dict[str, str]] = []
    all_response_matches: list[dict[str, Any]] = []
    all_unmatched_truth_responses: list[dict[str, str]] = []
    all_unmatched_pred_responses: list[dict[str, str]] = []
    variable_counts: dict[str, dict[str, float]] = defaultdict(lambda: {"correct": 0, "total": 0, "fuzzy_score_sum": 0.0})
    arity_variable_counts: dict[str, dict[int, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {"correct": 0, "total": 0, "fuzzy_score_sum": 0.0}))
    )

    for ref_id in ref_ids:
        setup_matches, unmatched_truth_setups, unmatched_pred_setups = best_one_to_one_matches(
            truth_setups_by_ref.get(ref_id, []),
            pred_setups_by_ref.get(ref_id, []),
            scorer=setup_match_score,
            threshold=args.setup_threshold,
        )
        all_setup_matches.extend(setup_matches)
        all_unmatched_truth_setups.extend(unmatched_truth_setups)
        all_unmatched_pred_setups.extend(unmatched_pred_setups)

        setup_columns = comparable_columns(pred_setups, truth_setups)
        add_variable_scores(variable_counts, setup_matches, setup_columns, task_types)
        add_variable_scores_by_arity(arity_variable_counts, setup_matches, setup_columns, arities_by_ref, task_types)

        response_columns = comparable_columns(pred_responses, truth_responses)
        matched_truth_setup_ids = {match["truth"].get("setup_id", "") for match in setup_matches}
        matched_pred_setup_ids = {match["pred"].get("setup_id", "") for match in setup_matches}

        for setup_match in setup_matches:
            truth_setup_id = setup_match["truth"].get("setup_id", "")
            pred_setup_id = setup_match["pred"].get("setup_id", "")
            response_matches, unmatched_truth_responses, unmatched_pred_responses = best_one_to_one_matches(
                truth_responses_by_setup.get(truth_setup_id, []),
                pred_responses_by_setup.get(pred_setup_id, []),
                scorer=response_match_score,
                threshold=args.response_threshold,
            )
            all_response_matches.extend(response_matches)
            all_unmatched_truth_responses.extend(unmatched_truth_responses)
            all_unmatched_pred_responses.extend(unmatched_pred_responses)
            add_variable_scores(variable_counts, response_matches, response_columns, task_types)
            add_variable_scores_by_arity(arity_variable_counts, response_matches, response_columns, arities_by_ref, task_types)

        for setup in unmatched_truth_setups:
            all_unmatched_truth_responses.extend(truth_responses_by_setup.get(setup.get("setup_id", ""), []))
        for setup in unmatched_pred_setups:
            all_unmatched_pred_responses.extend(pred_responses_by_setup.get(setup.get("setup_id", ""), []))

        for response in truth_responses_by_ref.get(ref_id, []):
            if response.get("setup_id", "") not in matched_truth_setup_ids and not any(
                response is row for row in all_unmatched_truth_responses
            ):
                all_unmatched_truth_responses.append(response)
        for response in pred_responses_by_ref.get(ref_id, []):
            if response.get("setup_id", "") not in matched_pred_setup_ids and not any(
                response is row for row in all_unmatched_pred_responses
            ):
                all_unmatched_pred_responses.append(response)

    add_paper_count_scores(variable_counts, pred_paper_info, truth_setups_by_ref, truth_responses_by_ref)

    setup_metrics = prf(len(all_setup_matches), len(truth_setups), len(pred_setups))
    response_metrics = prf(len(all_response_matches), len(truth_responses), len(pred_responses))
    summary = {
        "evaluated_ref_ids": sorted(evaluated_ref_ids),
        "setup_rows": {
            "num_matched": len(all_setup_matches),
            "num_unmatched_pred": len(all_unmatched_pred_setups),
            "num_unmatched_truth": len(all_unmatched_truth_setups),
            **setup_metrics,
        },
        "response_rows": {
            "num_matched": len(all_response_matches),
            "num_unmatched_pred": len(all_unmatched_pred_responses),
            "num_unmatched_truth": len(all_unmatched_truth_responses),
            **response_metrics,
        },
        "response_types": response_type_summary(
            all_response_matches,
            all_unmatched_truth_responses,
            all_unmatched_pred_responses,
        ),
    }

    setup_columns = comparable_columns(pred_setups, truth_setups)
    response_columns = comparable_columns(pred_responses, truth_responses)
    (eval_dir / "matching_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(
        eval_dir / "matched_setups.csv",
        matched_rows(all_setup_matches, setup_columns),
        matched_fieldnames(setup_columns),
    )
    write_csv(
        eval_dir / "matched_responses.csv",
        matched_response_rows(all_response_matches, response_columns),
        matched_response_fieldnames(response_columns),
    )
    write_csv(
        eval_dir / "unmatched_truth_setups.csv",
        all_unmatched_truth_setups,
        [
            "best_score",
            "best_match",
            "best_component_scores",
            *[col for col in (truth_setups[0].keys() if truth_setups else [])],
        ],
    )
    write_csv(eval_dir / "unmatched_pred_setups.csv", all_unmatched_pred_setups)
    write_csv(
        eval_dir / "unmatched_truth_responses.csv",
        unmatched_truth_response_rows(all_unmatched_truth_responses),
        [
            "best_score",
            "truth_response_type",
            "pred_response_type",
            "best_match",
            *[col for col in (truth_responses[0].keys() if truth_responses else [])],
        ],
    )
    write_csv(eval_dir / "unmatched_pred_responses.csv", all_unmatched_pred_responses)
    write_csv(
        eval_dir / "avg_performance.csv",
        performance_rows(variable_counts, task_types),
        ["variable", "accuracy", "fuzzy_score", "numcat", "oginf", "speco"],
    )
    write_csv(
        eval_dir / "avg_performance_by_arity.csv",
        performance_by_arity_rows(arity_variable_counts, task_types),
        ["arity_type", "arity_value", "variable", "correct", "total", "accuracy", "fuzzy_score", "numcat", "oginf", "speco"],
    )

    print(f"Wrote evaluation outputs to {eval_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate CoralSIE normalized extraction CSVs against ground truth.")
    parser.add_argument("--run-name", required=True, help="Prediction run folder name under CoralSIE/outputs.")
    parser.add_argument("--truth-setups", type=Path, default=DEFAULT_TRUTH_SETUPS)
    parser.add_argument("--truth-responses", type=Path, default=DEFAULT_TRUTH_RESPONSES)
    parser.add_argument("--var-task-types", type=Path, default=DEFAULT_VAR_TYPES)
    parser.add_argument("--setup-threshold", type=float, default=SETUP_MATCH_THRESHOLD)
    parser.add_argument("--response-threshold", type=float, default=RESPONSE_MATCH_THRESHOLD)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
