import sys
sys.path.insert(0, ".")

import main  # noqa: F401 - boots the app

loaded = sorted(
    m
    for m in sys.modules
    if (
        "pandas" in m
        or "sklearn" in m
        or "joblib" in m
        or "xgboost" in m
        or "torch" in m
        or "tensorflow" in m
        or "transformers" in m
        or "nltk" in m
        or "spacy" in m
        or "sentencepiece" in m
        or "datasets" in m
    )
)

print("Heavy ML modules loaded at startup (" + str(len(loaded)) + "):")
if loaded:
    print("\n".join("  " + m for m in loaded))
else:
    print("  (none)")
