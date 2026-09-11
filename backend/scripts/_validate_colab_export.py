"""Dry-run validation of a Colab dashboard_export.json against the active
import logic (standalone mirror of the pure functions in
app/services/training.py, runnable without the heavy ML stack).

The two helper bodies below (`_canonicalize_key`, `colab_key_to_approach`)
are copied verbatim from the app plus the label-assembly logic, so this
confirms: (1) every export model key resolves to an approved approach,
(2) the recommended production model, and (3) that class labels resolve to
the human names (Negative/Neutral/Positive) so the confusion-matrix and
per-class report are not blank/wrong. It does NOT write to the DB or to
app/ml artifacts.

Usage:
    python scripts/_validate_colab_export.py "path/to/dashboard_export.json"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CLASS_ORDER = ("Negative", "Neutral", "Positive")

# --- Copied verbatim from app/services/training.py -------------------------
def _canonicalize_key(key) -> str:
    """Lowercase and strip everything except a-z / 0-9 for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def colab_key_to_approach(key) -> str | None:
    """Resolve a Colab-export model key to a canonical approved approach name."""
    canonical = _canonicalize_key(key)
    if (
        "mdeberta" in canonical
        and ("xlmroberta" in canonical or canonical in ("mdebertaxlm", "mdebertaxlmr"))
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
# ---------------------------------------------------------------------------


APPROACH_TO_ALGORITHM = {
    "XGBoost (TF-DF)": "XGBOOST_TFDF",
    "mDeBERTa": "MDEBERTA",
    "XLM-RoBERTa": "XLM_ROBERTA",
    "mDeBERTa + XLM-RoBERTa": "ENSEMBLE_MDEBERTA_XLM",
}
APPROVED = set(APPROACH_TO_ALGORITHM)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/_validate_colab_export.py <export.json>")
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"file not found: {path}")
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))

    # Mirror normalize_metrics_payload: dict value = human label names.
    label_map = payload.get("label_map") or {}
    if isinstance(label_map, dict):
        labels = [str(name) for name in label_map.values()] if label_map else list(CLASS_ORDER)
    else:
        labels = [str(n) for n in label_map] or list(CLASS_ORDER)

    flat: dict[str, dict] = {}
    skipped: list[str] = []
    for key, model in (payload.get("models") or {}).items():
        approach = colab_key_to_approach(key)
        if approach is None or not isinstance(model, dict):
            skipped.append(str(key))
            continue
        per_class = model.get("per_class") or {}
        report = {"accuracy": model.get("accuracy")}
        macro_vals = []
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
        flat[approach] = {
            "accuracy": model.get("accuracy"),
            "weighted_f1": model.get("weighted_f1"),
            "macro_f1": model.get("macro_f1"),
            "labels": labels,
            "confusion_matrix": model.get("confusion_matrix"),
            "report_Negative": report.get("Negative"),
            "report_macro_avg": report.get("macro avg"),
        }

    recommended_raw = payload.get("recommended_production_model")
    recommended = colab_key_to_approach(recommended_raw) if recommended_raw else None

    print("Resolved approaches -> algorithm (approved?):")
    for name, m in flat.items():
        approved = name in APPROVED
        print(f"  {name!r:34} -> {APPROACH_TO_ALGORITHM.get(name, '?')}  approved={approved}")
        print(f"      labels={m['labels']}")
        print(f"      accuracy={m['accuracy']} weighted_f1={m['weighted_f1']} macro_f1={m['macro_f1']}")
        print(f"      report[Negative]={m['report_Negative']}")
        mean = m['report_macro_avg']['f1-score'] if m['report_macro_avg'] else None
        print(f"      report[macro avg]={m['report_macro_avg']}  (mean per-class f1={round(mean,4) if mean is not None else None})")

    if skipped:
        print(f"\nWARNING: skipped unrecognized keys: {skipped}")
    print(f"\nRecommended production model (raw) : {recommended_raw!r}")
    print(f"Resolved production approach       : {recommended!r}")
    print(f"Approved as production             : {recommended in APPROVED}")

    if not flat:
        print("ERROR: no approaches resolved.")
        return 1
    bad = [n for n, m in flat.items() if m["labels"] != list(CLASS_ORDER)]
    if bad:
        print(f"ERROR: label mismatch on {bad}")
        return 1
    print("OK: all model labels resolve to the human class names "
          "(confusion-matrix labels + per-class report rows will be correct).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())