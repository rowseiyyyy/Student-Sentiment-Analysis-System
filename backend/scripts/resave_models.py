"""Re-save the classical ML artifacts in a version-safe format.

Fixes the startup warnings caused by pickled models that were created with
different library versions than the running environment:

  - UserWarning: "XGBoost model was saved with ... a newer version ...
    use Booster.save_model()"      -> re-saved as native JSON via
    XGBClassifier.save_model() (the format the service now prefers).
  - InconsistentVersionWarning (sklearn): TfidfVectorizer pickled with a
    different scikit-learn -> re-pickled with the *current* environment.

Usage (from the backend/ directory, venv activated):
    python scripts/resave_models.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Allow running from anywhere: resolve backend/ and import the app package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib  # noqa: E402
import sklearn  # noqa: E402
import xgboost  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

from app.core.config import settings  # noqa: E402


def main() -> int:
    print(f"Environment: scikit-learn {sklearn.__version__}, xgboost {xgboost.__version__}")

    pkl_path = Path(settings.XGB_MODEL_PATH)
    json_path = Path(settings.XGB_MODEL_JSON_PATH)
    vec_path = Path(settings.XGB_TFIDF_VECTORIZER_PATH)

    if not pkl_path.exists():
        print(f"ERROR: pickled model not found at {pkl_path} — nothing to convert.")
        return 1
    if not vec_path.exists():
        print(f"ERROR: TF-IDF vectorizer not found at {vec_path} — nothing to convert.")
        return 1

    # --- Load with warnings surfaced (they're the thing we're fixing) ---
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model: XGBClassifier = joblib.load(pkl_path)
        vectorizer: TfidfVectorizer = joblib.load(vec_path)
    for w in caught:
        print(f"  (expected on old artifacts) {w.category.__name__}: {w.message}")

    if not isinstance(model, XGBClassifier):
        print(f"ERROR: {pkl_path.name} is a {type(model).__name__}, expected XGBClassifier.")
        return 1
    if not hasattr(model, "save_model"):
        print("ERROR: model has no save_model(); cannot convert to native format.")
        return 1

    # --- 1) Version-safe native XGBoost format (Booster.save_model / JSON) ---
    model.save_model(json_path)
    print(f"Wrote native XGBoost model: {json_path}")

    # Keep a pickle copy for backward compatibility with older deployments,
    # but re-dump it with the CURRENT library versions so it loads cleanly here.
    joblib.dump(model, pkl_path)
    print(f"Re-pickled model with current xgboost: {pkl_path}")

    # --- 2) Re-pickle sklearn objects with the current scikit-learn ---
    joblib.dump(vectorizer, vec_path)
    print(f"Re-pickled vectorizer with current scikit-learn: {vec_path}")

    # --- 3) Verify: reload everything with warnings treated as errors ---
    fresh = XGBClassifier()
    fresh.load_model(json_path)
    vec2: TfidfVectorizer = joblib.load(vec_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning => failure
        probe_model: XGBClassifier = joblib.load(pkl_path)
        probe_vec: TfidfVectorizer = joblib.load(vec_path)

    # --- 4) Sanity check: same predictions before and after conversion ---
    sample = "The professor explains lessons clearly and is very approachable."
    import numpy as np

    from app.services.preprocessing import clean_for_classical

    old_proba = model.predict_proba(vectorizer.transform([clean_for_classical(sample)]))[0]
    new_proba = fresh.predict_proba(vec2.transform([clean_for_classical(sample)]))[0]
    if not np.allclose(old_proba, new_proba, atol=1e-6):
        print("ERROR: predictions differ after conversion!")
        print(f"  before: {old_proba}")
        print(f"  after:  {new_proba}")
        return 1
    print(f"Prediction check OK: {np.round(new_proba, 4).tolist()}")

    # Silence the deliberately-kept probe objects.
    _ = (probe_model, probe_vec)
    print("\nDone — models are now version-safe. Restart the API and the")
    print("pickle/xgboost/sklearn startup warnings will be gone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
