from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.transformer_service import (
    CLASS_ORDER,
    TransformerSentimentService,
)


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
        feed = {name: inputs[name] for name in (
            "input_ids", "attention_mask",
            *(["token_type_ids"] if "token_type_ids" in inputs else []),
        )}
        logits = session.run(None, feed)[0][0]
        probabilities = np.exp(logits - logits.max())
        probabilities = probabilities / probabilities.sum()
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(p) for p in probabilities]


minilm_service = MiniLMService()