import os
import threading
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.transformer_service import (
    CLASS_ORDER,
    TransformerSentimentService,
)
from app.utils.logger import logger


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


def _host_memory_limit_mb() -> int | None:
    """Memory available to this process in MB, or ``None`` when unknown.

    Containers (Render, Docker, …) publish their limit through cgroup, not the
    host's physical RAM, so those files are checked first. ``MINILM_HOST_RAM_MB``
    overrides the detection when a platform exposes nothing usable, and hosts
    that expose neither are treated as unconstrained (developer machines).
    """
    override = settings.MINILM_HOST_RAM_MB
    if override is not None and override >= 0:
        return int(override)

    for path in (
        "/sys/fs/cgroup/memory.max",                     # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",   # cgroup v1
    ):
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not raw or raw == "max":
            continue
        try:
            limit = int(raw)
        except ValueError:
            continue
        # cgroup v1 uses a huge sentinel value when the limit is unlimited.
        if 0 < limit < (1 << 62):
            return int(limit // (1024 * 1024))
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):  # Windows / restricted hosts
        return None
    return int(pages * page_size // (1024 * 1024))


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
        # Built once on first use and then reused (see ``_onnx_session`` /
        # ``_load_tokenizer``); ``_lock`` guards that lazy construction so
        # concurrent requests cannot each allocate a second 119 MB session.
        self._session = None
        self._lock = threading.Lock()
        # Memoized memory-guard verdict (see ``can_run_live_inference``); the
        # host's limit cannot change while the process runs, so the warning is
        # logged once instead of on every prediction.
        self._memory_ok: bool | None = None

    # -- artifact readiness -------------------------------------------------
    def _onnx_path(self) -> Path:
        return self.artifact_path / settings.MINILM_ONNX_FILE

    def is_ready(self) -> bool:
        """Whether the quantized artifacts are on disk (hub/upload managed)."""
        return (
            self.artifact_path.exists()
            and (self.artifact_path / "config.json").exists()
            and self._onnx_path().exists()
        )

    def _memory_allows_inference(self) -> bool:
        """Whether this host has the RAM the ONNX path needs (~570-640 MB)."""
        if self._memory_ok is None:
            if not settings.ENABLE_MINILM_INFERENCE:
                logger.warning(
                    "MiniLM live inference disabled by ENABLE_MINILM_INFERENCE=false — "
                    "no live model remains, prediction requests will return 503."
                )
                self._memory_ok = False
            else:
                limit_mb = _host_memory_limit_mb()
                budget = settings.MINILM_MIN_RAM_MB
                # ``limit_mb`` of 0/None means "unlimited or unknown" -> allow.
                if budget and limit_mb and limit_mb < budget:
                    logger.warning(
                        f"MiniLM live inference skipped: this host has {limit_mb} MB "
                        f"but the ONNX path needs ~{budget} MB (MINILM_MIN_RAM_MB). "
                        "MiniLM is the only live model, so prediction requests "
                        "will return 503 rather than risk being OOM-killed."
                    )
                    self._memory_ok = False
                else:
                    self._memory_ok = True
        return self._memory_ok

    def can_run_live_inference(self) -> bool:
        """Whether live MiniLM inference should run in this process.

        Artifact readiness is necessary but not sufficient: the ONNX path needs
        ~570-640 MB RSS, which exceeds a 512 MB instance's limit — the worker
        would be OOM-killed mid-request and the browser would report "Unable to
        connect to the server". Anything below ``settings.MINILM_MIN_RAM_MB``
        therefore falls back to the light XGBoost (TF-IDF) model.
        """
        return self._memory_allows_inference() and self.is_ready()

    # -- ONNX inference -----------------------------------------------------
    def _load_tokenizer(self):
        """Fast (Rust) tokenizer, read straight from the repo's ``tokenizer.json``.

        Loading the same file through ``transformers.AutoTokenizer`` costs an
        extra ~140 MB (importing ``transformers`` at all) plus ~60 MB more for
        the Python tokenizer object. On the 512 MB free-tier instance that was
        enough to push a prediction over the limit, get the worker killed and
        drop the in-flight request. ``tokenizers`` returns byte-identical
        ``ids`` / ``attention_mask`` / ``type_ids`` for this checkpoint
        (verified against ``AutoTokenizer``, including 128-token truncation).

        Parsed once and then reused — re-reading the 17 MB file for every
        prediction was half of the per-row cost of bulk imports.
        """
        if self.tokenizer is None:
            with self._lock:
                if self.tokenizer is None:
                    import tokenizers

                    tokenizer = tokenizers.Tokenizer.from_file(
                        str(self.artifact_path / "tokenizer.json")
                    )
                    tokenizer.enable_truncation(max_length=settings.MINILM_MAX_SEQ_LENGTH)
                    self.tokenizer = tokenizer
        return self.tokenizer

    def _onnx_session(self):
        """Return the shared ONNX Runtime session, created on first use.

        The session (and its ~119 MB of INT8 weights) used to be rebuilt and
        dropped for *every* prediction. Bulk imports score one row at a time —
        ``import_service.process_imported_evaluations`` calls
        ``run_prediction_pipeline`` per row — so on Render's 512 MB free tier
        that meant ~2 s and a fresh ~120 MB allocation per row: a few hundred
        rows ran for many minutes and left the instance thrashing until the
        request was dropped mid-flight, which the browser reports as
        "Unable to connect to the server. Please ensure the backend is running."
        Building it once keeps the same peak footprint without paying for it on
        every prediction.
        """
        if self._session is None:
            with self._lock:
                if self._session is None:
                    import onnxruntime as ort

                    self._session = ort.InferenceSession(
                        str(self._onnx_path()),
                        providers=["CPUExecutionProvider"],
                    )
        return self._session

    def predict(self, text: str) -> tuple[str, float, list[float]]:
        """ONNX Runtime inference. Logits index order follows the fine-tuned
        model's label ids (0=Negative, 1=Neutral, 2=Positive) == CLASS_ORDER."""
        from app.services.preprocessing import clean_for_transformer

        tokenizer = self._load_tokenizer()
        session = self._onnx_session()
        # ``tokenizers`` truncates at MINILM_MAX_SEQ_LENGTH (enabled at load) and
        # the vocabulary's post-processor adds the special tokens, so the ids
        # match AutoTokenizer(..., truncation=True, max_length=...) exactly.
        encoding = tokenizer.encode(clean_for_transformer(text))
        inputs = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
        }
        feed = _build_onnx_feed(session, inputs)
        logits = session.run(None, feed)[0][0]
        probabilities = np.exp(logits - logits.max())
        probabilities = probabilities / probabilities.sum()
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(p) for p in probabilities]


minilm_service = MiniLMService()