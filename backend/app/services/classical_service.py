"""Classical (TF-IDF + scikit-learn) text classifiers for the approved
research model set: SVM, Naive Bayes and Logistic Regression.

These are the offline research models. They share one implementation
(``ClassicalTextService``) parameterised by an scikit-learn estimator, and
each persists its own fitted TF-IDF vectorizer alongside the model so that
inference-time preprocessing always matches training-time preprocessing
(leakage-safe: vectorizer is fitted on train split only).

Multilingual MiniLM remains the ONLY live production model — the classical
services are never imported at app startup, only lazily by the training
pipeline.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from app.core.config import settings
from app.services.ensembles import CLASS_ORDER
from app.services.preprocessing import clean_for_classical


class ClassicalTextService:
    """A leakage-safe TF-IDF + scikit-learn text classifier."""

    def __init__(self, estimator_factory, model_path, vectorizer_path, hyperparams: dict):
        self._estimator_factory = estimator_factory
        self.model = None
        self.vectorizer = None
        self.load_error: str | None = None
        # Settings paths may be monkeypatched to str in tests — accept both.
        self.model_path = Path(model_path)
        self.vectorizer_path = Path(vectorizer_path) if vectorizer_path is not None else None
        self.hyperparams = hyperparams
        self._try_load()

    def _service_paths(self) -> tuple[Path, Path | None]:
        """Resolve the current settings paths for this singleton.

        The singletons are constructed at import time, but tests redirect
        settings paths per-test — always read the live settings values.
        """
        if self._estimator_factory is _svm:
            return Path(settings.SVM_MODEL_PATH), Path(settings.SVM_VECTORIZER_PATH)
        if self._estimator_factory is _naive_bayes:
            return Path(settings.NAIVE_BAYES_MODEL_PATH), Path(settings.NAIVE_BAYES_VECTORIZER_PATH)
        return Path(settings.LOGREG_MODEL_PATH), Path(settings.LOGREG_VECTORIZER_PATH)

    def _try_load(self) -> None:
        model_path, vectorizer_path = self._service_paths()
        self.model_path = model_path
        self.vectorizer_path = vectorizer_path
        self.model = None
        self.vectorizer = None
        if not model_path.exists():
            return
        try:
            self.model = joblib.load(model_path)
            if not hasattr(self.model, "predict_proba"):
                raise TypeError("Loaded classifier does not provide predict_proba().")
            if vectorizer_path is not None and vectorizer_path.exists():
                try:
                    self.vectorizer = joblib.load(vectorizer_path)
                except Exception:
                    self.vectorizer = None
        except Exception as exc:  # noqa: BLE001
            self.model = None
            self.load_error = str(exc)

    def is_ready(self) -> bool:
        return self.model is not None

    def save(self) -> None:
        settings.ML_DIR.mkdir(parents=True, exist_ok=True)
        if self.model is None:
            raise RuntimeError("Cannot save an unloaded classical model.")
        model_path, vectorizer_path = self._service_paths()
        self.model_path = model_path
        self.vectorizer_path = vectorizer_path
        joblib.dump(self.model, model_path)
        if self.vectorizer is not None and vectorizer_path is not None:
            joblib.dump(self.vectorizer, vectorizer_path)

    @staticmethod
    def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
        )

        return {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
            "f1_score": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
            "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            "labels": list(CLASS_ORDER),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(CLASS_ORDER)).tolist(),
            "classification_report": classification_report(
                y_true, y_pred, labels=list(CLASS_ORDER), target_names=list(CLASS_ORDER),
                output_dict=True, zero_division=0,
            ),
        }
    def train_on_split(
        self,
        train_texts: list[str],
        train_labels: list[str],
        val_texts: list[str] | None = None,
        val_labels: list[str] | None = None,
        test_texts: list[str] | None = None,
        test_labels: list[str] | None = None,
    ) -> dict:
        """Fit the TF-IDF vectorizer on the train split only, train the
        classifier, and evaluate on the untouched validation / test splits."""
        import time as _time

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.pipeline import Pipeline

        start = _time.perf_counter()
        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
            ("clf", self._estimator_factory()),
        ])
        pipeline.fit([clean_for_classical(t) for t in train_texts], train_labels)
        self.model = pipeline
        self.vectorizer = pipeline.named_steps["tfidf"]
        train_seconds = _time.perf_counter() - start

        val_pred = np.array(pipeline.predict([clean_for_classical(t) for t in val_texts])) \
            if val_texts is not None and val_labels is not None else None
        test_pred = np.array(pipeline.predict([clean_for_classical(t) for t in test_texts])) \
            if test_texts is not None and test_labels is not None else None
        infer_n = max(len(test_texts or val_texts or train_texts), 1)
        inference_ms = (_time.perf_counter() - start) * 1000 / infer_n

        self.save()
        metrics: dict = {}
        if test_pred is not None:
            metrics = self._metrics(np.array(test_labels), test_pred)
        if val_pred is not None:
            metrics["validation"] = self._metrics(np.array(val_labels), val_pred)
        metrics["training_time_seconds"] = float(train_seconds)
        metrics["inference_time_ms"] = float(inference_ms)
        stats = {
            "train": len(train_texts),
            "validation": len(val_texts) if val_texts is not None else 0,
            "test": len(test_texts) if test_texts is not None else 0,
        }
        metrics["dataset_size"] = sum(stats.values())
        metrics["split_sizes"] = stats
        metrics["hyperparameters"] = dict(self.hyperparams)
        return metrics

    def predict(self, text: str) -> tuple[str, float, list[float]]:
        if not self.is_ready():
            raise RuntimeError(f"{type(self).__name__} model is not available.")
        probabilities = np.asarray(self.model.predict_proba([clean_for_classical(text)]), dtype=float)[0]
        classes = [str(c).strip().capitalize() for c in self.model.classes_]
        aligned = np.zeros(len(CLASS_ORDER), dtype=float)
        for source_index, source_label in enumerate(classes):
            if source_label in CLASS_ORDER:
                aligned[CLASS_ORDER.index(source_label)] = probabilities[source_index]
        total = aligned.sum()
        if total <= 0:
            aligned = np.full(len(CLASS_ORDER), 1 / len(CLASS_ORDER))
        index = int(np.argmax(aligned))
        return CLASS_ORDER[index], float(aligned[index]), [float(value) for value in aligned]


def _svm():
    from sklearn.svm import SVC

    return SVC(kernel="linear", C=settings.SVM_C, probability=True, random_state=settings.RANDOM_STATE)


def _naive_bayes():
    from sklearn.naive_bayes import MultinomialNB

    return MultinomialNB(alpha=settings.NAIVE_BAYES_ALPHA)


def _logistic_regression():
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(
        C=settings.LOGREG_C, max_iter=settings.LOGREG_MAX_ITER, random_state=settings.RANDOM_STATE
    )


svm_service = ClassicalTextService(
    _svm,
    settings.SVM_MODEL_PATH,
    settings.SVM_VECTORIZER_PATH,
    {"kernel": "linear", "C": settings.SVM_C, "vectorizer": "tfidf (1-2 ngrams, sublinear)"},
)

naive_bayes_service = ClassicalTextService(
    _naive_bayes,
    settings.NAIVE_BAYES_MODEL_PATH,
    settings.NAIVE_BAYES_VECTORIZER_PATH,
    {"alpha": settings.NAIVE_BAYES_ALPHA, "vectorizer": "tfidf (1-2 ngrams, sublinear)"},
)

logistic_regression_service = ClassicalTextService(
    _logistic_regression,
    settings.LOGREG_MODEL_PATH,
    settings.LOGREG_VECTORIZER_PATH,
    {"C": settings.LOGREG_C, "max_iter": settings.LOGREG_MAX_ITER, "vectorizer": "tfidf (1-2 ngrams, sublinear)"},
)
