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