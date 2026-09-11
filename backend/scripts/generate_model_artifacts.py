"""Regenerate app/ml/comparison_results.json + app/ml/model_metadata.json from a
Colab dashboard_export.json, using the same normalization logic the active
importer applies (mirror of app/services/training.py `_normalize_colab_model`
and `_write_comparison_artifacts`), so the runtime prediction config reflects
the *real* training run rather than the stale hand-edited files.

This ONLY rewrites those two JSON artifacts. It does NOT touch the database;
to update the in-app Admin comparison table / confusion-matrix /
classification-report you must still import into the DB (see README / the
POST /ml/import-results endpoint).

Usage:
    python scripts/generate_model_artifacts.py "path/to/dashboard_export.json" [production_name]
        production_name defaults to the export's recommended model.
        Accepted values (must equal an approach exactly): XGBoost (TF-DF),
        mDeBERTa, XLM-RoBERTa, mDeBERTa + XLM-RoBERTa.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CLASS_ORDER = ("Negative", "Neutral", "Positive")
ML_DIR = Path(__file__).resolve().parent.parent / "app" / "ml"


# --- Mirrors of app/services/training.py pure helpers -----------------------
def _canonicalize_key(key) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def colab_key_to_approach(key) -> str | None:
    canonical = _canonicalize_key(key)
    if "mdeberta" in canonical and (
        "xlmroberta" in canonical or canonical in ("mdebertaxlm", "mdebertaxlmr")
    ):
        return "mDeBERTa + XLM-RoBERTa"
    if "xlmroberta" in canonical and "mdeberta" in canonical:
        return "mDeBERTa + XLM-RoBERTa"
    if canonical in ("xgboost", "xgb"):
        return "XGBoost (TF-DF)"
    if canonical.startswith("mdeberta") or canonical in ("deberta", "debertabase"):
        return "mDeBERTa"
    if canonical.startswith("xlmroberta") or canonical in ("roberta", "robertabase"):
        return "XLM-RoBERTa"
    if canonical == "xlmr":
        return "XLM-RoBERTa"
    if canonical == "ensemble":
        return "XGBoost (TF-DF) + mDeBERTa + XLM-RoBERTa"
    return None


ENSEMBLES = {
    "mDeBERTa + XLM-RoBERTa": ["mDeBERTa", "XLM-RoBERTa"],
}


def _normalize_colab_model(model: dict, labels: list[str]) -> dict:
    per_class = model.get("per_class") or {}
    report: dict = {"accuracy": model.get("accuracy")}
    macro_vals: list[float] = []
    for label in labels:
        pc = per_class.get(label) or {}
        report[label] = {
            "precision": pc.get("precision"),
            "recall": pc.get("recall"),
            "f1-score": pc.get("f1"),
            "support": pc.get("support"),
        }
        if pc.get("f1") not in (None, ""):
            macro_vals.append(float(pc["f1"]))
    if macro_vals:
        report["macro avg"] = {"f1-score": sum(macro_vals) / len(macro_vals)}
    return {
        "accuracy": model.get("accuracy"),
        "precision": model.get("precision_weighted") or model.get("precision"),
        "recall": model.get("recall_weighted") or model.get("recall"),
        "f1_score": model.get("weighted_f1") or model.get("f1_score"),
        "macro_f1": model.get("macro_f1"),
        "weighted_f1": model.get("weighted_f1"),
        "labels": labels,
        "confusion_matrix": model.get("confusion_matrix"),
        "classification_report": report,
        "training_time_seconds": model.get("training_time_seconds"),
        "inference_time_ms": model.get("inference_time_ms"),
        "memory_usage_mb": model.get("memory_usage_mb"),
        "hyperparameters": model.get("hyperparameters"),
    }
# ---------------------------------------------------------------------------
def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/generate_model_artifacts.py <export.json> [production_name]")
        return 2
    export_path = Path(sys.argv[1])
    if not export_path.exists():
        print(f"file not found: {export_path}")
        return 2
    payload = json.loads(export_path.read_text(encoding="utf-8"))

    label_map = payload.get("label_map") or {}
    if isinstance(label_map, dict):
        labels = [str(name) for name in label_map.values()] if label_map else list(CLASS_ORDER)
    else:
        labels = [str(n) for n in label_map] or list(CLASS_ORDER)

    results: dict[str, dict] = {}
    skipped: list[str] = []
    for key, model in (payload.get("models") or {}).items():
        approach = colab_key_to_approach(key)
        if approach is None or not isinstance(model, dict):
            skipped.append(str(key))
            continue
        results[approach] = _normalize_colab_model(model, labels)

    if not results:
        print("ERROR: no approaches resolved from export.")
        return 1
    print(f"Resolved {len(results)} approaches: {', '.join(results)}")
    if skipped:
        print(f"WARNING: skipped unrecognized keys: {skipped}")

    recommended = colab_key_to_approach(payload.get("recommended_production_model"))
    best_algorithm = sys.argv[2] if len(sys.argv) > 2 else recommended
    if best_algorithm not in results:
        print(f"ERROR: production name {best_algorithm!r} not present in resolved results "
              f"({list(results)}).")
        return 1

    selection_metric = "weighted_f1"
    selection_score = float(results[best_algorithm].get(selection_metric) or 0.0)
    approach_type = "ensemble" if best_algorithm in ENSEMBLES else "single"

    metadata: dict = {
        "production_model": best_algorithm,
        "approach_type": approach_type,
        "selection_metric": selection_metric,
        "selection_score": selection_score,
        "models": results,
    }
    if approach_type == "ensemble":
        metadata["ensemble_members"] = ENSEMBLES[best_algorithm]
        metadata["ensemble_weights"] = (results[best_algorithm].get("hyperparameters") or {}).get("weights", {})

    ML_DIR.mkdir(parents=True, exist_ok=True)
    (ML_DIR / "comparison_results.json").write_text(
        json.dumps({"best_model": best_algorithm, "rows": results}, indent=2), encoding="utf-8"
    )
    (ML_DIR / "model_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"\nWrote comparison_results.json -> best_model = {best_algorithm!r}")
    print(f"Wrote model_metadata.json -> production_model = {best_algorithm!r} "
          f"(approach_type={approach_type}, selection_score={selection_score:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())