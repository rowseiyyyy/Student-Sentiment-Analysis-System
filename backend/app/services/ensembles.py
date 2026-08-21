"""Approved ensemble definitions and weighted soft-voting helpers.

All four approved ensembles share one canonical registry and one label
ordering (``CLASS_ORDER``) so that training (weight selection), evaluation,
persistence and runtime inference all agree on how each ensemble is
assembled, combined and reported.

Approved models / ensembles
---------------------------
Single models:  XGBoost, DeBERTa, RoBERTa
Ensembles (weighted soft voting):
    * XGBoost + DeBERTa
    * DeBERTa + RoBERTa
    * RoBERTa + XGBoost
    * XGBoost + DeBERTa + RoBERTa

No ensemble weight value in this module is claimed to be optimal; weights
are selected during training against a validation split and persisted so
runtime inference uses the *trained* values rather than configuration
defaults.
"""
from __future__ import annotations

import numpy as np

from app.services.xgboost_service import CLASS_ORDER

# Canonical ordered mapping of ensemble name -> participating model keys.
ENSEMBLES: dict[str, list[str]] = {
    "XGBoost + DeBERTa": ["XGBoost", "DeBERTa"],
    "DeBERTa + RoBERTa": ["DeBERTa", "RoBERTa"],
    "RoBERTa + XGBoost": ["RoBERTa", "XGBoost"],
    "XGBoost + DeBERTa + RoBERTa": ["XGBoost", "DeBERTa", "RoBERTa"],
}

# Approved single-model approaches.
SINGLE_MODELS: tuple[str, ...] = ("XGBoost", "DeBERTa", "RoBERTa")

# Complete approved approach set (individual models + all four ensembles).
APPROVED_APPROACHES: tuple[str, ...] = SINGLE_MODELS + tuple(ENSEMBLES.keys())

# Resolution used while searching the weight simplex on the validation split.
GRID_STEPS = 21


def members_of(ensemble_name: str) -> list[str]:
    """Return the ordered participating model keys for an ensemble."""
    try:
        return list(ENSEMBLES[ensemble_name])
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown ensemble: {ensemble_name}") from exc


def normalize_weights(members: list[str], weights: dict[str, float]) -> dict[str, float]:
    """Return non-negative weights for every member, using equal weights for
    any member without an explicit value, then re-normalising to sum to one.

    The caller decides the weight source; this helper itself never falls back
    to configuration defaults.
    """
    if not members:
        raise ValueError("Cannot normalise weights for an empty member list.")
    if not weights:
        equal = 1.0 / len(members)
        return {member: equal for member in members}
    normalized = {member: max(float(weights.get(member, 0.0)), 0.0) for member in members}
    total = sum(normalized.values())
    if total <= 0:
        equal = 1.0 / len(members)
        return {member: equal for member in members}
    return {member: value / total for member, value in normalized.items()}


def fuse_probabilities(
    probs_by_member: dict[str, list[float] | np.ndarray],
    weights: dict[str, float],
    members: list[str] | None = None,
) -> np.ndarray:
    """Weighted soft-vote combination of per-member probability vectors.

    Returns a single length-3 vector aligned to ``CLASS_ORDER``.
    """
    members = members or list(probs_by_member.keys())
    fused = np.zeros(len(CLASS_ORDER), dtype=float)
    for member in members:
        fused += float(weights.get(member, 0.0)) * np.asarray(probs_by_member[member], dtype=float)
    return fused


def soft_vote(
    probs_by_member: dict[str, list[float] | np.ndarray],
    weights: dict[str, float],
    members: list[str] | None = None,
) -> tuple[str, float, list[float]]:
    """Combine per-member probability vectors and return
    ``(label, confidence, fused_probabilities)`` using ``CLASS_ORDER``."""
    fused = fuse_probabilities(probs_by_member, weights, members)
    index = int(np.argmax(fused))
    return CLASS_ORDER[index], float(fused[index]), [float(value) for value in fused]


def ensemble_prediction(
    ensemble_name: str,
    probability_vectors: dict[str, list[np.ndarray]],
    weights: dict[str, float],
) -> list[str]:
    """Return predicted labels for a full set of per-member probability
    vectors using the given (already selected) weights."""
    members = members_of(ensemble_name)
    if not probability_vectors:
        return []
    n = len(next(iter(probability_vectors.values())))
    members = [member for member in members if member in probability_vectors]
    labels: list[str] = []
    for index in range(n):
        fused = fuse_probabilities(
            {member: np.asarray(probability_vectors[member][index], dtype=float) for member in members},
            weights,
            members,
        )
        labels.append(CLASS_ORDER[int(np.argmax(fused))])
    return labels


def _candidate_weight_grid(members: list[str]) -> list[dict[str, float]]:
    """Enumerate candidate weight vectors on the probability simplex."""
    if len(members) == 2:
        return [
            {members[0]: float(w), members[1]: float(1.0 - w)}
            for w in np.linspace(0, 1, GRID_STEPS)
        ]

    candidates: list[dict[str, float]] = []

    def recurse(prefix: list[float], remaining: list[str]) -> None:
        if len(remaining) == 1:
            total = sum(prefix)
            if total <= 1.0 + 1e-9:
                candidates.append(dict(zip(members, prefix + [1.0 - total])))
            return
        for value in np.linspace(0, 1, GRID_STEPS):
            recurse(prefix + [float(value)], remaining[1:])

    recurse([], members)
    return candidates


def select_weights(
    ensemble_name: str,
    validation_predictions: dict[str, list[np.ndarray]],
    y_val: list[str],
) -> dict[str, float]:
    """Select the ensemble member weights maximising validation macro-F1.

    ``validation_predictions`` must map every member to an identical-length
    list of probability vectors aligned to ``CLASS_ORDER``.
    """
    from sklearn.metrics import f1_score

    members = [m for m in members_of(ensemble_name) if m in validation_predictions]
    if not members:
        return {}
    n = len(next(iter(validation_predictions.values())))
    best: dict[str, float] | None = None
    best_score = -1.0
    for weights in _candidate_weight_grid(members):
        preds: list[str] = []
        for index in range(n):
            fused = fuse_probabilities(
                {member: np.asarray(validation_predictions[member][index], dtype=float) for member in members},
                weights,
                members,
            )
            preds.append(CLASS_ORDER[int(np.argmax(fused))])
        score = f1_score(y_val, preds, average="macro", zero_division=0)
        if score > best_score:
            best_score = score
            best = dict(weights)
    return best or normalize_weights(members, {})

