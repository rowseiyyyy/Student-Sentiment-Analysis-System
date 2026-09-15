"""Regression tests for the Multilingual MiniLM ONNX input feed.

The Colab-exported graph declares ``int64`` inputs and, because it was traced
with ``token_type_ids``, requires that tensor to be fed. The sentencepiece
tokenizer of the exported checkpoint emits neither: it returns ``int32`` arrays
and no ``token_type_ids`` at all. Feeding the tokenizer output straight into
``session.run`` therefore failed with

    InvalidArgument: Unexpected input data type. Actual: (tensor(int32)),
    expected: (tensor(int64))

for every prediction, which silently downgraded live inference to the
XGBoost (TF-IDF) fallback. ``_build_onnx_feed`` is the fix: it feeds exactly
the tensors the graph declares, synthesizing zero ``token_type_ids`` and
casting each tensor to the declared element type.
"""
import numpy as np
import pytest

from app.services.minilm_service import _build_onnx_feed


class _InputSpec:
    """Minimal stand-in for ``onnxruntime.NodeArg``."""

    def __init__(self, name: str, type_: str) -> None:
        self.name = name
        self.type = type_


class _Session:
    """Minimal stand-in for ``onnxruntime.InferenceSession``."""

    def __init__(self, specs: list[_InputSpec]) -> None:
        self._specs = specs

    def get_inputs(self) -> list[_InputSpec]:
        return self._specs


def _tokenizer_output() -> dict:
    """What ``AutoTokenizer(return_tensors="np")`` yields for this checkpoint."""
    return {
        "input_ids": np.array([[101, 2054, 102]], dtype=np.int32),
        "attention_mask": np.array([[1, 1, 1]], dtype=np.int32),
    }


def test_feed_synthesizes_token_type_ids_and_casts_to_declared_dtypes():
    session = _Session(
        [
            _InputSpec("input_ids", "tensor(int64)"),
            _InputSpec("attention_mask", "tensor(int64)"),
            _InputSpec("token_type_ids", "tensor(int64)"),
        ]
    )

    feed = _build_onnx_feed(session, _tokenizer_output())

    assert set(feed) == {"input_ids", "attention_mask", "token_type_ids"}
    assert all(value.dtype == np.int64 for value in feed.values())
    assert np.array_equal(feed["token_type_ids"], np.zeros((1, 3), dtype=np.int64))


def test_feed_reuses_token_type_ids_when_the_tokenizer_provides_them():
    inputs = _tokenizer_output()
    inputs["token_type_ids"] = np.array([[0, 1, 0]], dtype=np.int32)
    session = _Session([_InputSpec("token_type_ids", "tensor(int64)")])

    feed = _build_onnx_feed(session, inputs)

    assert np.array_equal(feed["token_type_ids"], np.array([[0, 1, 0]], dtype=np.int64))


def test_feed_omits_inputs_the_graph_does_not_declare():
    session = _Session([_InputSpec("input_ids", "tensor(int64)")])

    feed = _build_onnx_feed(session, _tokenizer_output())

    assert set(feed) == {"input_ids"}


def test_feed_rejects_unknown_graph_inputs():
    session = _Session([_InputSpec("pixel_values", "tensor(float)")])

    with pytest.raises(ValueError, match="Unexpected ONNX model input 'pixel_values'"):
        _build_onnx_feed(session, _tokenizer_output())


# ---------------------------------------------------------------------------
# Memory guard
#
# The ONNX path needs ~570-640 MB RSS (app baseline + fast tokenizer + the
# 119 MB quantized session). On a 512 MB instance (Render free tier) loading it
# got the worker OOM-killed mid-request, which reaches the browser as
# "Unable to connect to the server. Please ensure the backend is running."
# Live inference therefore falls back to XGBoost (TF-IDF) when the host cannot
# hold the model.
# ---------------------------------------------------------------------------

def _service(monkeypatch, *, ready: bool, enabled: bool = True, host_mb=None, min_ram_mb: int = 900):
    from app.services import minilm_service as module

    monkeypatch.setattr(module.settings, "ENABLE_MINILM_INFERENCE", enabled, raising=False)
    monkeypatch.setattr(module.settings, "MINILM_MIN_RAM_MB", min_ram_mb, raising=False)
    monkeypatch.setattr(module, "_host_memory_limit_mb", lambda: host_mb, raising=False)
    service = module.MiniLMService()
    monkeypatch.setattr(service, "is_ready", lambda: ready, raising=False)
    return service


def test_live_inference_allowed_when_host_has_enough_memory(monkeypatch):
    assert _service(monkeypatch, ready=True, host_mb=1024).can_run_live_inference() is True


def test_live_inference_skipped_on_a_512mb_host(monkeypatch):
    # The free-tier case: artifacts are present, but the instance is too small.
    assert _service(monkeypatch, ready=True, host_mb=512).can_run_live_inference() is False


def test_live_inference_skipped_when_explicitly_disabled(monkeypatch):
    assert _service(monkeypatch, ready=True, enabled=False, host_mb=8192).can_run_live_inference() is False


def test_live_inference_skipped_when_artifacts_are_missing(monkeypatch):
    assert _service(monkeypatch, ready=False, host_mb=8192).can_run_live_inference() is False


def test_memory_guard_can_be_disabled_with_zero_budget(monkeypatch):
    # MINILM_MIN_RAM_MB=0 turns the guard off entirely (opt out on big hosts,
    # or when the operator knows the container has more RAM than reported).
    assert _service(monkeypatch, ready=True, host_mb=512, min_ram_mb=0).can_run_live_inference() is True


def test_unknown_host_memory_is_treated_as_unconstrained(monkeypatch):
    # Plain VMs / developer machines expose no cgroup limit (None) -> allowed.
    assert _service(monkeypatch, ready=True, host_mb=None).can_run_live_inference() is True


def test_host_memory_override_is_honoured(monkeypatch):
    from app.services import minilm_service as module

    monkeypatch.setattr(module.settings, "MINILM_HOST_RAM_MB", 512, raising=False)
    assert module._host_memory_limit_mb() == 512

    monkeypatch.setattr(module.settings, "MINILM_HOST_RAM_MB", 0, raising=False)
    assert module._host_memory_limit_mb() == 0  # 0 == unlimited, guard is skipped

    monkeypatch.setattr(module.settings, "MINILM_HOST_RAM_MB", None, raising=False)
    # No override -> falls back to detection, which is None on hosts without
    # cgroup / sysconf support (e.g. Windows developers).
    assert module._host_memory_limit_mb() in (None,) or isinstance(module._host_memory_limit_mb(), int)


# ---------------------------------------------------------------------------
# Lazy singletons
#
# Both the tokenizer and the ONNX session used to be rebuilt for every
# prediction: ~2 s and a fresh ~120 MB allocation per row, which made bulk
# imports (one pipeline call per row) unusable on a small instance.
# ---------------------------------------------------------------------------

def test_tokenizer_and_session_are_built_once(monkeypatch):
    from app.services import minilm_service as module

    built = {"tokenizer": 0, "session": 0}

    class _FakeTokenizer:
        @classmethod
        def from_file(cls, _path):
            built["tokenizer"] += 1
            return cls()

        def enable_truncation(self, max_length):
            self.max_length = max_length

    class _FakeSession:
        def __init__(self, *_args, **_kwargs):
            built["session"] += 1

    monkeypatch.setattr(module.settings, "ENABLE_MINILM_INFERENCE", True, raising=False)
    monkeypatch.setattr(module.settings, "MINILM_MIN_RAM_MB", 0, raising=False)
    service = module.MiniLMService()

    import onnxruntime
    import tokenizers

    monkeypatch.setattr(tokenizers, "Tokenizer", _FakeTokenizer, raising=False)
    monkeypatch.setattr(onnxruntime, "InferenceSession", _FakeSession, raising=False)

    assert service._load_tokenizer() is service._load_tokenizer()
    assert service._onnx_session() is service._onnx_session()
    assert built == {"tokenizer": 1, "session": 1}