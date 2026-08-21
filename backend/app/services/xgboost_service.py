"""Leakage-safe XGBoost text classifier for the Phase 1 baseline."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from app.core.config import settings
from app.services.preprocessing import clean_for_classical

CLASS_ORDER = ("Negative", "Neutral", "Positive")


class XGBoostService:
    def __init__(self) -> None:
        self.model: XGBClassifier | None = None
        self.vectorizer: TfidfVectorizer | None = None
        self._try_load()

    def _try_load(self) -> None:
        if Path(settings.XGB_MODEL_PATH).exists() and Path(settings.XGB_TFIDF_VECTORIZER_PATH).exists():
            self.model = joblib.load(settings.XGB_MODEL_PATH)
            self.vectorizer = joblib.load(settings.XGB_TFIDF_VECTORIZER_PATH)

    def is_ready(self) -> bool:
        return self.model is not None and self.vectorizer is not None

    def save(self) -> None:
        settings.ML_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, settings.XGB_MODEL_PATH)
        joblib.dump(self.vectorizer, settings.XGB_TFIDF_VECTORIZER_PATH)
        settings.XGB_LABEL_ENCODER_PATH.write_text(json.dumps({"classes": CLASS_ORDER}), encoding="utf-8")

    @staticmethod
    def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
        return {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
            "f1_score": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
            "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(CLASS_ORDER)).tolist(),
            "classification_report": classification_report(y_true, y_pred, labels=list(CLASS_ORDER), target_names=list(CLASS_ORDER), output_dict=True, zero_division=0),
            "labels": list(CLASS_ORDER),
        }

    def train(self, texts: list[str], labels: list[str]) -> dict:
        if set(labels) - set(CLASS_ORDER):
            raise ValueError("Labels must be Negative, Neutral, or Positive.")
        try:
            x_train_all, x_test, y_train_all, y_test = train_test_split(texts, labels, test_size=settings.TEST_SIZE, random_state=settings.RANDOM_STATE, stratify=labels)
            val_fraction = settings.TEST_SIZE / (1 - settings.TEST_SIZE)
            x_train, x_val, y_train, y_val = train_test_split(x_train_all, y_train_all, test_size=val_fraction, random_state=settings.RANDOM_STATE, stratify=y_train_all)
        except ValueError as exc:
            raise ValueError("Dataset cannot be stratified into train, validation, and test splits; add labeled rows to every sentiment class.") from exc
        return self.train_on_split(x_train, y_train, x_val, y_val, x_test, y_test)

    def train_on_split(
        self,
        train_texts: list[str],
        train_labels: list[str],
        val_texts: list[str] | None = None,
        val_labels: list[str] | None = None,
        test_texts: list[str] | None = None,
        test_labels: list[str] | None = None,
    ) -> dict:
        if set(train_labels) - set(CLASS_ORDER):
            raise ValueError("Labels must be Negative, Neutral, or Positive.")

        self.vectorizer = TfidfVectorizer(max_features=10_000, ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        x_train_vec = self.vectorizer.fit_transform([clean_for_classical(text) for text in train_texts])
        encode = {label: index for index, label in enumerate(CLASS_ORDER)}
        self.model = XGBClassifier(
            n_estimators=settings.XGB_N_ESTIMATORS,
            max_depth=settings.XGB_MAX_DEPTH,
            learning_rate=settings.XGB_LEARNING_RATE,
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            random_state=settings.RANDOM_STATE,
            n_jobs=1,
        )
        self.model.fit(x_train_vec, np.array([encode[label] for label in train_labels]))

        val_pred = None
        test_pred = None
        if val_texts is not None and val_labels is not None:
            x_val_vec = self.vectorizer.transform([clean_for_classical(text) for text in val_texts])
            val_pred = np.array([CLASS_ORDER[index] for index in self.model.predict(x_val_vec).astype(int)])
        if test_texts is not None and test_labels is not None:
            x_test_vec = self.vectorizer.transform([clean_for_classical(text) for text in test_texts])
            test_pred = np.array([CLASS_ORDER[index] for index in self.model.predict(x_test_vec).astype(int)])

        self.save()
        metrics = {}
        if test_texts is not None and test_labels is not None:
            metrics = self._metrics(np.array(test_labels), test_pred)
        if val_texts is not None and val_labels is not None:
            metrics["validation"] = self._metrics(np.array(val_labels), val_pred)

        stats = {"train": len(train_texts), "validation": len(val_texts) if val_texts is not None else 0, "test": len(test_texts) if test_texts is not None else 0}
        metrics["dataset_size"] = len(train_texts) + (len(val_texts) if val_texts is not None else 0) + (len(test_texts) if test_texts is not None else 0)
        metrics["split_sizes"] = stats
        metrics["hyperparameters"] = {"n_estimators": settings.XGB_N_ESTIMATORS, "max_depth": settings.XGB_MAX_DEPTH, "learning_rate": settings.XGB_LEARNING_RATE}
        return metrics

    def predict(self, text: str) -> tuple[str, float, list[float]]:
        if not self.is_ready():
            raise RuntimeError("XGBoost model is not available.")
        probabilities = self.model.predict_proba(self.vectorizer.transform([clean_for_classical(text)]))[0]
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(value) for value in probabilities]


xgboost_service = XGBoostService()
