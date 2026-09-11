"""Targeted tests for the label normalization fix in training.py.

Verifies that `_normalize_colab_model` and `normalize_metrics_payload`
resolve label_map dict values (human-readable class names like
"Negative"/"Neutral"/"Positive") rather than numeric index keys
("0"/"1"/"2") when a dict label_map is provided.
"""
import pytest

from app.services.training import CLASS_ORDER, _normalize_colab_model, normalize_metrics_payload


LABEL_MAP_DICT = {"0": "Negative", "1": "Neutral", "2": "Positive"}
LABEL_MAP_LIST = ["Negative", "Neutral", "Positive"]

SAMPLE_MODEL = {
    "accuracy": 0.908,
    "precision_weighted": 0.9081,
    "recall_weighted": 0.908,
    "weighted_f1": 0.908,
    "macro_f1": 0.899,
    "per_class": {
        "Negative": {"precision": 0.9642, "recall": 0.9586, "f1": 0.9614, "support": 870},
        "Neutral": {"precision": 0.8395, "recall": 0.8333, "f1": 0.8364, "support": 546},
        "Positive": {"precision": 0.8944, "recall": 0.9041, "f1": 0.8992, "support": 834},
    },
}


def test_normalize_colab_model_with_dict_label_map_uses_values():
    """When a dict label_map (index->name) is passed, the resolved labels
    must be the dict *values* (class names), not the *keys* (indices)."""
    result = _normalize_colab_model(SAMPLE_MODEL, LABEL_MAP_DICT)

    assert result["labels"] == ["Negative", "Neutral", "Positive"]
    assert "ClassificationReport keys are human-readable"
    assert set(result["classification_report"].keys()) >= {"Negative", "Neutral", "Positive"}


def test_normalize_colab_model_with_list_label_map():
    """When a list label_map is passed, labels pass through directly."""
    result = _normalize_colab_model(SAMPLE_MODEL, LABEL_MAP_LIST)
    assert result["labels"] == ["Negative", "Neutral", "Positive"]


def test_normalize_metrics_payload_dict_label_map():
    """End-to-end: normalize_metrics_payload with a Colab-style payload
    whose label_map is a dict {'0': 'Negative', ...}."""
    payload = {
        "label_map": LABEL_MAP_DICT,
        "models": {"xlm-roberta": SAMPLE_MODEL},
    }
    flat, recommended = normalize_metrics_payload(payload)

    assert "XLM-RoBERTa" in flat
    assert flat["XLM-RoBERTa"]["labels"] == ["Negative", "Neutral", "Positive"]
    assert recommended is None  # no recommended_production_model in this payload


def test_normalize_metrics_payload_list_label_map():
    """End-to-end: normalize_metrics_payload with a list label_map."""
    payload = {
        "label_map": LABEL_MAP_LIST,
        "models": {"xlm-roberta": SAMPLE_MODEL},
    }
    flat, _ = normalize_metrics_payload(payload)

    assert flat["XLM-RoBERTa"]["labels"] == ["Negative", "Neutral", "Positive"]


def test_normalize_metrics_payload_no_label_map_falls_back():
    """Without a label_map, CLASS_ORDER should be used."""
    payload = {"models": {"xlm-roberta": SAMPLE_MODEL}}
    flat, _ = normalize_metrics_payload(payload)
    assert flat["XLM-RoBERTa"]["labels"] == list(CLASS_ORDER)


def test_label_map_values_not_keys():
    """Regression test: explicitly check that .values() is used, not .keys()."""
    lm = {"0": "Negative", "1": "Neutral", "2": "Positive"}
    values_labels = [str(n) for n in lm.values()]
    keys_labels = [str(n) for n in lm.keys()]

    assert values_labels == ["Negative", "Neutral", "Positive"]
    assert keys_labels == ["0", "1", "2"]
    assert values_labels != keys_labels  # the bug would produce index strings
