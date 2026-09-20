"""Re-save the classical ML artifacts in a version-safe format.

The approved classical research models (SVM, Naive Bayes, Logistic
Regression) are persisted as joblib pickles (each bundling its fitted
TF-IDF vectorizer with the classifier). Pickles created with different
scikit-learn versions than the running environment surface
InconsistentVersionWarning on load — this script re-pickles every
classical artifact with the *current* environment so it loads cleanly.

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

from app.core.config import settings  # noqa: E402


def main() -> int:
    print(f"Environment: scikit-learn {sklearn.__version__}")

    artifact_paths = (
        Path(settings.SVM_MODEL_PATH),
        Path(settings.NAIVE_BAYES_MODEL_PATH),
        Path(settings.LOGREG_MODEL_PATH),
    )

    missing = [str(p) for p in artifact_paths if not p.exists()]
    if missing:
        print("ERROR: classical model artifacts not found (train first):")
        for p in missing:
            print(f"  - {p}")
        return 1

    from app.services.preprocessing import clean_for_classical

    sample = "The professor explains lessons clearly and is very approachable."

    for artifact_path in artifact_paths:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = joblib.load(artifact_path)
        for w in caught:
            print(f"  (expected on old artifacts) {w.category.__name__}: {w.message}")

        if not hasattr(model, "predict_proba"):
            print(f"ERROR: {artifact_path.name} provides no predict_proba() — not a classifier pipeline.")
            return 1

        before = model.predict_proba([clean_for_classical(sample)])[0]

        joblib.dump(model, artifact_path)
        print(f"Re-pickled with current scikit-learn: {artifact_path}")

        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning => failure
            probe = joblib.load(artifact_path)

        import numpy as np

        after = probe.predict_proba([clean_for_classical(sample)])[0]
        if not np.allclose(before, after, atol=1e-6):
            print(f"ERROR: predictions differ after conversion for {artifact_path.name}!")
            print(f"  before: {before}")
            print(f"  after:  {after}")
            return 1
        print(f"Prediction check OK for {artifact_path.name}: {np.round(after, 4).tolist()}")

    print("\nDone — models are now version-safe. Restart the API and the")
    print("pickle/sklearn startup warnings will be gone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
