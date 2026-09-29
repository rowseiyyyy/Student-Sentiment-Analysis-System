"""mBERT Hybrid — the only live production sentiment model.

Replaces the former Multilingual MiniLM ONNX service. The two models are
structurally different and so is this service:

* MiniLM was a fine-tuned ``BertForSequenceClassification`` exported to a
  119 MB INT8 ONNX graph and served through onnxruntime. One forward pass
  produced the logits directly.
* mBERT Hybrid is **not** an ONNX graph and has no classification head.
  ``config.json`` declares a bare ``BertModel`` (frozen, untrained encoder),
  and the classifier lives in a scikit-learn pickle. Inference is a
  three-stage feature union:

      text ──┬─► word TfidfVectorizer  (ngram 1-2, sublinear_tf)
             ├─► char TfidfVectorizer  (char_wb, ngram 2-5, min_df=2)
             └─► BertModel encoder     ──► 768-d embedding
                                              │
                     StandardScaler ───────────┤
                                              ▼
                          hstack ──► LinearSVC ──► label

Every component of that pipeline is read back out of ``model.joblib``
(``vecs`` / ``w`` / ``clf``), so this service does not re-declare the
vectorizer hyperparameters — it uses the fitted estimators themselves. That
matters: rebuilding a TfidfVectorizer from hyperparameters instead of loading
the fitted one would silently change the vocabulary and corrupt predictions.

The ``LinearSVC`` head has no ``predict_proba``, so confidences are derived
from the decision function via softmax (see ``predict``).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.transformer_service import CLASS_ORDER
from app.utils.logger import logger


def _host_memory_limit_mb() -> int | None:
    """Memory available to this process in MB, or ``None`` when unknown.

    Containers (Render, Docker, …) publish their limit through cgroup, not the
    host's physical RAM, so those files are checked first. ``MBERT_HOST_RAM_MB``
    overrides the detection when a platform exposes nothing usable, and hosts
    that expose neither are treated as unconstrained (developer machines).
    """
    override = settings.MBERT_HOST_RAM_MB
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



class MBertHybridService:
    """Frozen mBERT encoder + scikit-learn hybrid head, served from disk.

    The heavy artifacts (a 711 MB fp32 ``BertModel`` plus the vectorizers) are
    built once on first use and then held for the process lifetime; ``_lock``
    guards that lazy construction so concurrent first-requests cannot each
    allocate a second copy of the encoder.
    """

    name = "mBERT Hybrid"

    def __init__(self) -> None:
        self.artifact_path = Path(settings.MBERT_MODEL_PATH)
        self._encoder = None
        self._tokenizer = None
        self._clf = None
        self._word_vec = None
        self._char_vec = None
        self._scaler = None
        self._weight = float(settings.MBERT_EMBEDDING_WEIGHT)
        self._lock = threading.Lock()
        # Memoized memory-guard verdict: the host's limit cannot change while
        # the process runs, so the warning is logged once, not per request.
        self._memory_ok: bool | None = None

    # -- artifact readiness -------------------------------------------------
    def _required_files(self) -> tuple[Path, ...]:
        return (
            self.artifact_path / "config.json",
            self.artifact_path / settings.MBERT_SAFETENSORS_FILE,
            self.artifact_path / settings.MBERT_CLASSIFIER_FILE,
        )

    def is_ready(self) -> bool:
        """Whether the encoder + hybrid-head artifacts are on disk."""
        return all(path.exists() for path in self._required_files())

    def _memory_allows_inference(self) -> bool:
        """Whether this host has the RAM the encoder path needs."""
        if self._memory_ok is None:
            if not settings.ENABLE_MBERT_INFERENCE:
                logger.warning(
                    "mBERT Hybrid live inference disabled by ENABLE_MBERT_INFERENCE=false — "
                    "no live model remains, prediction requests will return 503."
                )
                self._memory_ok = False
            else:
                limit_mb = _host_memory_limit_mb()
                budget = settings.MBERT_MIN_RAM_MB
                # ``limit_mb`` of 0/None means "unlimited or unknown" -> allow.
                if budget and limit_mb and limit_mb < budget:
                    logger.warning(
                        f"mBERT Hybrid live inference skipped: this host has {limit_mb} MB "
                        f"but the encoder path needs ~{budget} MB (MBERT_MIN_RAM_MB). "
                        "mBERT Hybrid is the only live model, so prediction requests "
                        "will return 503 rather than risk being OOM-killed."
                    )
                    self._memory_ok = False
                else:
                    self._memory_ok = True
        return self._memory_ok

    def can_run_live_inference(self) -> bool:
        """Whether live inference should run in this process.

        Loading the fp32 encoder costs far more RAM than the retired INT8 ONNX
        path, so anything below ``MBERT_MIN_RAM_MB`` is refused up front rather
        than being OOM-killed mid-request. No fallback model exists by design.
        """
        return self._memory_allows_inference() and self.is_ready()

    # -- lazy artifact loading ---------------------------------------------
    def _load_hybrid_head(self) -> None:
        """Load the fitted vectorizers/scaler/classifier from ``model.joblib``.

        The fitted estimators are used directly — see the module docstring for
        why re-creating them from hyperparameters would be unsafe.
        """
        if self._clf is not None:
            return
        import joblib

        bundle = joblib.load(self.artifact_path / settings.MBERT_CLASSIFIER_FILE)
        self._word_vec, self._char_vec, self._scaler = bundle["vecs"]
        self._clf = bundle["clf"]
        # The training run persisted its own embedding weight; prefer it over
        # the configured default so inference can never drift from the artifact.
        self._weight = float(bundle.get("w", self._weight))

        if list(self._clf.classes_) != [0, 1, 2]:
            raise ValueError(
                f"Unexpected classifier classes {self._clf.classes_!r}; "
                "expected [0, 1, 2] to match Negative/Neutral/Positive."
            )

    def _load_encoder(self):
        """Build the frozen ``BertModel`` + tokenizer from the local artifact."""
        if self._encoder is None:
            with self._lock:
                if self._encoder is None:
                    import torch
                    from transformers import AutoModel, AutoTokenizer

                    source = str(self.artifact_path)
                    self._tokenizer = AutoTokenizer.from_pretrained(source)
                    # ``dtype=`` rather than the deprecated ``torch_dtype=``;
                    # the artifact's config already pins float32.
                    model = AutoModel.from_pretrained(source, dtype=torch.float32)
                    model.eval()
                    self._encoder = model
                    logger.info(f"mBERT Hybrid encoder loaded from {source}")
        return self._encoder

    def embed(self, text: str) -> np.ndarray:
        """Mean-pooled, attention-masked encoder embedding for one comment.

        Mean pooling (rather than the ``[CLS]`` vector) matches the Colab
        training script that paired this encoder with the StandardScaler; the
        scaler's ``mean_``/``scale_`` vectors are length 768, the encoder width.
        """
        import torch

        from app.services.preprocessing import clean_for_transformer

        encoder = self._load_encoder()
        encoded = self._tokenizer(
            clean_for_transformer(text),
            return_tensors="pt",
            truncation=True,
            max_length=settings.MBERT_MAX_SEQ_LENGTH,
        )
        with torch.no_grad():
            output = encoder(**encoded)
        hidden = output.last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        summed = (hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        return (summed / counts).squeeze(0).cpu().numpy().astype(np.float64)

    # -- inference ----------------------------------------------------------
    def predict(self, text: str) -> tuple[str, float, list[float]]:
        """Classify one comment; returns ``(label, confidence, probabilities)``.

        ``LinearSVC`` exposes decision margins rather than probabilities, so the
        scores are softmaxed to give the UI a comparable 0-1 confidence. These
        are decision-margin-derived scores, not calibrated posteriors.
        """
        from scipy import sparse

        self._load_hybrid_head()
        embedding = self.embed(text)
        # The two TF-IDF blocks are sparse CSR and the scaled embedding is
        # dense. They are combined with scipy's sparse hstack (NOT np.hstack,
        # which degrades a CSR block into an object array) and returned in CSR
        # form, which is what LinearSVC's accept_sparse="csr" path expects.
        features = sparse.hstack(
            [
                self._word_vec.transform([text]),
                self._char_vec.transform([text]),
                sparse.csr_matrix(
                    self._scaler.transform(embedding.reshape(1, -1)) * self._weight
                ),
            ],
            format="csr",
        )
        scores = np.asarray(self._clf.decision_function(features)[0], dtype=np.float64)

        probabilities = np.exp(scores - scores.max())
        probabilities = probabilities / probabilities.sum()
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(p) for p in probabilities]


mbert_service = MBertHybridService()
