from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.transformer_service import (
    CLASS_ORDER,
    TransformerSentimentService,
)


_ONNX_INPUT_DTYPES: dict[str, type] = {
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


def _build_onnx_feed(session, inputs) -> dict:
    """Build the input feed the exported ONNX graph actually declares.

    Two mismatches between the HF tokenizer output and the traced graph are
    handled here, both of which otherwise made every prediction fail with an
    ``InvalidArgument`` error (and silently fall back to XGBoost):

    * the export traced ``token_type_ids`` as a *required* input while the
      sentencepiece tokenizer used by this checkpoint does not emit it — it is
      synthesized as all-zeros, the correct value for a single un-paired
      sequence;
    * the graph declares ``int64`` inputs while ``return_tensors="np"`` yields
      ``int32`` — each tensor is cast to the declared element type.
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
        expected_dtype = _ONNX_INPUT_DTYPES.get(spec.type)
        if expected_dtype is not None:
            value = np.asarray(value, dtype=expected_dtype)
        feed[name] = value
    return feed


class MiniLMService(TransformerSentimentService):
    """Multilingual MiniLM served from an INT8-quantized ONNX artifact.

    The private hub repo (``rowseiy/minilm-sentiment``) carries the tokenizer
    files + ``config.json`` and the quantized ``model.onnx`` (exported with
    ``onnxruntime.quantization.quantize_dynamic`` in Colab). Live inference
    runs through ONNX Runtime instead of the PyTorch dynamic-quant path used
    by the other transformers — a much smaller runtime footprint for the
    free-tier RAM budget. Fine-tuning still uses the inherited PyTorch
    ``Trainer`` path with the base checkpoint.
    """

    def __init__(self) -> None:
        super().__init__(
            settings.MINILM_MODEL_NAME,
            settings.MINILM_MODEL_PATH,
            settings.TRANSFORMER_DEVICE,
            None,  # no PyTorch quantized state_dict — ONNX is served instead
        )

    # -- artifact readiness -------------------------------------------------
    def _onnx_path(self) -> Path:
        return self.artifact_path / settings.MINILM_ONNX_FILE

    def is_ready(self) -> bool:
        return (
            self.artifact_path.exists()
            and (self.artifact_path / "config.json").exists()
            and self._onnx_path().exists()
        )

    # -- ONNX inference -----------------------------------------------------
    def _load_tokenizer(self):
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(str(self.artifact_path))

    def _onnx_session(self):
        import onnxruntime as ort

        return ort.InferenceSession(
            str(self._onnx_path()),
            providers=["CPUExecutionProvider"],
        )

    def predict(self, text: str) -> tuple[str, float, list[float]]:
        """ONNX Runtime inference. Logits index order follows the fine-tuned
        model's label ids (0=Negative, 1=Neutral, 2=Positive) == CLASS_ORDER."""
        from app.services.preprocessing import clean_for_transformer

        tokenizer = self._load_tokenizer()
        session = self._onnx_session()
        inputs = tokenizer(
            clean_for_transformer(text),
            return_tensors="np",
            truncation=True,
            max_length=settings.MINILM_MAX_SEQ_LENGTH,
        )
        feed = _build_onnx_feed(session, inputs)
        logits = session.run(None, feed)[0][0]
        probabilities = np.exp(logits - logits.max())
        probabilities = probabilities / probabilities.sum()
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(p) for p in probabilities]


minilm_service = MiniLMService()