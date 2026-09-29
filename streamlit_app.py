"""Streamlit front-end for the mBERT Hybrid sentiment model.

Self-contained: it mirrors the inference contract proven in
``backend/app/services/mbert_service.py`` (word + char TF-IDF union with a
mean-pooled, StandardScaler-normalized ``bert-base-multilingual-cased``
embedding feeding a LinearSVC, label order 0=Negative / 1=Neutral /
2=Positive) without importing the backend package, so it can be deployed
standalone on Streamlit Community Cloud or any host.

Model resolution order:
1. ``MBERT_LOCAL_DIR`` env var (explicit path to the artifact folder)
2. ``backend/app/ml/mbert_hybrid`` next to this repo (local dev)
3. snapshot download of the hub repo (needs ``HF_TOKEN`` with read
   access) into a cache dir

Run locally:
    pip install -r requirements.txt
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import streamlit as st

MODEL_REPO = os.environ.get("MODEL_REPO", "rowseiy/mbert-sentiment")
DEFAULT_LOCAL_DIR = Path(__file__).resolve().parent / "backend" / "app" / "ml" / "mbert_hybrid"
MAX_INPUT_CHARS = 2000
MAX_SEQ_LENGTH = 96
CLASS_ORDER = ("Negative", "Neutral", "Positive")


def resolve_model_dir() -> Path:
    """Locate (or download) the artifact folder."""
    explicit = os.environ.get("MBERT_LOCAL_DIR")
    if explicit:
        path = Path(explicit)
        if (path / "model.joblib").is_file():
            return path
        raise FileNotFoundError(f"MBERT_LOCAL_DIR={explicit!r} has no model.joblib")

    if (DEFAULT_LOCAL_DIR / "model.joblib").is_file():
        return DEFAULT_LOCAL_DIR

    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download(
            MODEL_REPO,
            token=os.environ.get("HF_TOKEN") or None,
        )
    )


@lru_cache(maxsize=1)
def load_resources(model_dir: str):
    """Load the frozen encoder, tokenizer and hybrid head once per process.

    The fitted vectorizers/scaler/classifier are read straight out of
    ``model.joblib`` rather than rebuilt from hyperparameters — reconstructing
    a TfidfVectorizer would change its vocabulary and corrupt the scores.
    """
    import joblib
    import torch
    from transformers import AutoModel, AutoTokenizer

    root = Path(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(str(root))

    encoder = AutoModel.from_pretrained(str(root), dtype=torch.float32)
    encoder.eval()

    bundle = joblib.load(root / "model.joblib")
    word_vec, char_vec, scaler = bundle["vecs"]
    weight = float(bundle.get("w", 1.0))

    return tokenizer, encoder, word_vec, char_vec, scaler, bundle["clf"], weight


def clean_text(text: str) -> str:
    """Light cleaning consistent with the backend pipeline.

    ``app.services.preprocessing.clean_for_transformer`` collapses whitespace
    (incl. newlines) and strips zero-width characters — replicated here so the
    Streamlit scores match the production API byte-for-byte on the same input.
    """
    import re
    import unicodedata

    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("Cf"))
    return re.sub(r"\s+", " ", text).strip()


def predict(text: str) -> tuple[str, float, list[float]]:
    from scipy import sparse
    import torch

    tokenizer, encoder, word_vec, char_vec, scaler, clf, weight = load_resources(_MODEL_DIR)

    encoded = tokenizer(
        clean_text(text),
        return_tensors="pt",
        truncation=True,
        max_length=MAX_SEQ_LENGTH,
    )
    with torch.no_grad():
        hidden = encoder(**encoded).last_hidden_state
    mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
    embedding = ((hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9))
    embedding = embedding.squeeze(0).cpu().numpy().astype(np.float64)

    features = sparse.hstack(
        [
            # Sparse TF-IDF blocks plus a dense scaled embedding, combined with
            # scipy's sparse hstack (np.hstack would object-ify the CSR blocks).
            word_vec.transform([text]),
            char_vec.transform([text]),
            sparse.csr_matrix(scaler.transform(embedding.reshape(1, -1)) * weight),
        ],
        format="csr",
    )
    # LinearSVC yields decision margins, not probabilities; softmax them so the
    # UI shows a comparable 0-1 score.
    scores = np.asarray(clf.decision_function(features)[0], dtype=np.float64)
    probs = np.exp(scores - scores.max())
    probs = probs / probs.sum()
    idx = int(np.argmax(probs))
    return CLASS_ORDER[idx], float(probs[idx]), [float(p) for p in probs]


_MODEL_DIR = ""  # set by main() before first predict


def main() -> None:
    global _MODEL_DIR
    st.set_page_config(page_title="Student Sentiment", page_icon="🎓", layout="centered")
    st.title("🎓 Student Sentiment Analysis")
    st.caption("mBERT Hybrid (mBERT encoder + word/char TF-IDF) — Negative / Neutral / Positive")

    with st.spinner("Loading model…"):
        try:
            _MODEL_DIR = str(resolve_model_dir())
            load_resources(_MODEL_DIR)
        except Exception as exc:  # noqa: BLE001 - surface any load failure in the UI
            st.error(f"Failed to load model artifacts: {exc}")
            st.info(
                "If this is a private repo, set the ``HF_TOKEN`` environment "
                "variable (Streamlit: Settings → Secrets → ``HF_TOKEN = \"hf_…\"``) "
                "with read access to the model repo."
            )
            st.stop()
    st.success(f"Model loaded from `{_MODEL_DIR}`")

    text = st.text_area(
        "Feedback text",
        height=140,
        max_chars=MAX_INPUT_CHARS,
        placeholder="e.g. The professor is very helpful and explains topics clearly.",
    )

    if st.button("Analyze sentiment", type="primary", use_container_width=True):
        stripped = text.strip()
        if not stripped:
            st.warning("Please enter some text first — the input is empty.")
            st.stop()
        if len(stripped) > MAX_INPUT_CHARS:
            st.error(f"Input too long ({len(stripped)} > {MAX_INPUT_CHARS} characters).")
            st.stop()
        with st.spinner("Predicting…"):
            try:
                label, confidence, probs = predict(stripped)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Prediction failed: {exc}")
                st.stop()

        emoji = {"Positive": "😄", "Neutral": "😐", "Negative": "😞"}[label]
        st.markdown(
            f"### {emoji} {label} — confidence **{confidence:.1%}** "
            f"({len(stripped)} chars → ≤{MAX_SEQ_LENGTH} tokens)"
        )
        st.bar_chart(
            {"Probability": dict(zip(CLASS_ORDER, [round(p, 4) for p in probs]))}
        )

    st.divider()
    st.caption(f"Model repo: `{MODEL_REPO}` · truncation at {MAX_SEQ_LENGTH} tokens")


if __name__ == "__main__":
    main()

