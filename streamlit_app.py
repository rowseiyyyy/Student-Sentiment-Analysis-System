"""Streamlit front-end for the Multilingual MiniLM sentiment model.

Self-contained: it reuses the same ONNX inference contract proven in
``backend/app/services/minilm_service.py`` (required int64 ``token_type_ids``,
dtype-cast inputs, label order 0=Negative / 1=Neutral / 2=Positive) without
importing the backend package, so it can be deployed standalone on
Streamlit Community Cloud or any host.

Model resolution order:
1. ``MINILM_LOCAL_DIR`` env var (explicit path to the artifact folder)
2. ``backend/app/ml/minilm_sentiment`` next to this repo (local dev)
3. snapshot download of the private hub repo (needs ``HF_TOKEN`` with read
   access) into a cache dir

Run locally:
    pip install -r requirements-streamlit.txt
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import streamlit as st

MODEL_REPO = os.environ.get("MODEL_REPO", "rowseiyyyy/minilm-sentiment")
DEFAULT_LOCAL_DIR = Path(__file__).resolve().parent / "backend" / "app" / "ml" / "minilm_sentiment"
MAX_INPUT_CHARS = 2000
MAX_SEQ_LENGTH = 128
CLASS_ORDER = ("Negative", "Neutral", "Positive")

_ONNX_INPUT_DTYPES = {
    "tensor(float)": np.float32,
    "tensor(float16)": np.float16,
    "tensor(double)": np.float64,
    "tensor(int64)": np.int64,
    "tensor(int32)": np.int32,
    "tensor(int16)": np.int16,
    "tensor(int8)": np.int8,
    "tensor(uint8)": np.uint8,
    "tensor(bool)": np.bool_,
}


def resolve_model_dir() -> Path:
    """Locate (or download) the ONNX artifact folder."""
    explicit = os.environ.get("MINILM_LOCAL_DIR")
    if explicit:
        path = Path(explicit)
        if (path / "model.onnx").is_file():
            return path
        raise FileNotFoundError(f"MINILM_LOCAL_DIR={explicit!r} has no model.onnx")

    if (DEFAULT_LOCAL_DIR / "model.onnx").is_file():
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
    """Load the raw ``tokenizers`` tokenizer + ONNX session once per process.

    ``tokenizers.Tokenizer`` is used instead of ``AutoTokenizer`` (same as the
    backend): byte-identical ids for this checkpoint, and far lighter on RAM —
    which matters on free-tier Streamlit containers (~690 MB, and the session
    alone holds ~119 MB of INT8 weights).
    """
    import onnxruntime as ort
    import tokenizers

    root = Path(model_dir)
    tokenizer = tokenizers.Tokenizer.from_file(str(root / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_SEQ_LENGTH)

    session = ort.InferenceSession(
        str(root / "model.onnx"),
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def build_feed(session, inputs: dict) -> dict:
    """Mirror of ``minilm_service._build_onnx_feed``.

    * synthesizes the ``token_type_ids`` the traced graph requires but the
      sentencepiece tokenizer does not emit;
    * casts each tensor to the graph's declared element type (int64 vs int32).
    """
    feed: dict = {}
    for spec in session.get_inputs():
        name = spec.name
        if name in inputs:
            value = inputs[name]
        elif name == "token_type_ids":
            value = np.zeros_like(inputs["input_ids"])
        else:
            raise ValueError(f"Unexpected ONNX model input {name!r}.")
        dtype = _ONNX_INPUT_DTYPES.get(spec.type)
        if dtype is not None:
            value = np.asarray(value, dtype=dtype)
        feed[name] = value
    return feed
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
    tokenizer, session = load_resources(_MODEL_DIR)
    encoding = tokenizer.encode(clean_text(text))
    inputs = {
        "input_ids": np.array([encoding.ids], dtype=np.int64),
        "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
        "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
    }
    logits = session.run(None, build_feed(session, inputs))[0][0]
    probs = np.exp(logits - logits.max())
    probs = probs / probs.sum()
    idx = int(np.argmax(probs))
    return CLASS_ORDER[idx], float(probs[idx]), [float(p) for p in probs]


_MODEL_DIR = ""  # set by main() before first predict


def main() -> None:
    global _MODEL_DIR
    st.set_page_config(page_title="Student Sentiment", page_icon="🎓", layout="centered")
    st.title("🎓 Student Sentiment Analysis")
    st.caption("Multilingual MiniLM (INT8 ONNX) — Negative / Neutral / Positive")

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

