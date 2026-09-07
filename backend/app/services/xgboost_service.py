"""Leakage-safe XGBoost (TF-DF) text classifier."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from app.core.config import settings
from app.services.preprocessing import clean_for_classical

CLASS_ORDER = ("Negative", "Neutral", "Positive")


class XGBoostService:
    def __init__(self) -> None:
        self.model = None
        self.vectorizer: TfidfVectorizer | None = None
        self.load_error: str | None = None
        self._model_format: str | None = None
        self._try_load()

    def _try_load(self) -> None:
        if not Path(settings.XGB_MODEL_PATH).exists():
            return
        if not Path(settings.XGB_TFIDF_VECTORIZER_PATH).exists():
            return
        try:
            self.vectorizer = joblib.load(settings.XGB_TFIDF_VECTORIZER_PATH)
            model_path = Path(settings.XGB_MODEL_PATH)
            if model_path.is_file():
                try:
                    self.model = joblib.load(model_path)
                    if not hasattr(self.model, "predict_proba"):
                        raise TypeError("Joblib XGBoost artifact does not provide predict_proba().")
                    self._model_format = "joblib"
                except Exception:
                    import xgboost

                    self.model = xgboost.Booster()
                    self.model.load_model(model_path)
                    self._model_format = "native_xgboost"
            else:
                import tensorflow as tf
                import tensorflow_decision_forests as tfdf
                self.model = tf.keras.models.load_model(str(model_path))
                self._model_format = "tfdf"
        except Exception as exc:  # noqa: BLE001
            self.model = None
            self.load_error = str(exc)

    def is_ready(self) -> bool:
        return self.model is not None and self.vectorizer is not None

    def save(self) -> None:
        settings.ML_DIR.mkdir(parents=True, exist_ok=True)
        if self.model is None:
            raise RuntimeError("Cannot save an unloaded TF-DF model.")
        if self._model_format == "joblib":
            joblib.dump(self.model, settings.XGB_MODEL_PATH)
        elif self._model_format == "native_xgboost":
            self.model.save_model(settings.XGB_MODEL_PATH)
        else:
            self.model.save(str(settings.XGB_MODEL_PATH))
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

        try:
            import tensorflow as tf
            import tensorflow_decision_forests as tfdf
        except Exception:  # noqa: BLE001
            # Local dev/test environments commonly do not have TensorFlow or
            # TF-DF installed. Fall back to a native scikit-learn classifier so
            # model training remains usable under the app's Colab-first workflow.
            self.model = LogisticRegression(
                max_iter=2000,
                solver="lbfgs",
                random_state=settings.RANDOM_STATE,
            )
            self.model.fit(x_train_vec, train_labels)
            self._model_format = "joblib"
        else:
            # TF-DF consumes dense numeric tensors/DataFrames, unlike native
            # XGBoost's sparse matrix support, so the TF-IDF matrix is densified.
            features = x_train_vec.toarray().astype(np.float32)
            train_frame = {f"tfidf_{index}": features[:, index] for index in range(features.shape[1])}
            train_frame["label"] = np.array([encode[label] for label in train_labels], dtype=np.int32)
            train_dataset = tfdf.keras.pd_dataframe_to_tf_dataset(
                __import__("pandas").DataFrame(train_frame), label="label", task=tfdf.keras.Task.CLASSIFICATION
            )
            self.model = tfdf.keras.GradientBoostedTreesModel(
                task=tfdf.keras.Task.CLASSIFICATION,
                num_trees=settings.XGB_N_ESTIMATORS,
                max_depth=settings.XGB_MAX_DEPTH,
                shrinkage=settings.XGB_LEARNING_RATE,
                random_seed=settings.RANDOM_STATE,
            )
            self.model.fit(train_dataset)
            self._model_format = "tfdf"

        val_pred = None
        test_pred = None
        if val_texts is not None and val_labels is not None:
            x_val_vec = self.vectorizer.transform([clean_for_classical(text) for text in val_texts])
            val_pred = np.array([CLASS_ORDER[index] for index in np.argmax(self._predict_proba(x_val_vec), axis=1)])
        if test_texts is not None and test_labels is not None:
            x_test_vec = self.vectorizer.transform([clean_for_classical(text) for text in test_texts])
            test_pred = np.array([CLASS_ORDER[index] for index in np.argmax(self._predict_proba(x_test_vec), axis=1)])

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
        probabilities = self._predict_proba(self.vectorizer.transform([clean_for_classical(text)]))[0]
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], float(probabilities[index]), [float(value) for value in probabilities]

    def _predict_proba(self, matrix) -> np.ndarray:
        if self._model_format == "joblib":
            probabilities = np.asarray(self.model.predict_proba(matrix))
            classes = getattr(self.model, "classes_", None)
            if classes is not None:
                aligned = np.zeros((probabilities.shape[0], len(CLASS_ORDER)), dtype=float)
                for source_index, source_label in enumerate(classes):
                    if isinstance(source_label, (int, np.integer)):
                        target_index = int(source_label)
                    else:
                        normalized = str(source_label).strip().capitalize()
                        target_index = CLASS_ORDER.index(normalized) if normalized in CLASS_ORDER else -1
                    if 0 <= target_index < len(CLASS_ORDER):
                        aligned[:, target_index] = probabilities[:, source_index]
                probabilities = aligned
            return probabilities.reshape((-1, len(CLASS_ORDER)))

        if self._model_format == "native_xgboost":
            import xgboost

            probabilities = np.asarray(self.model.predict(xgboost.DMatrix(matrix)))
            if probabilities.ndim == 1:
                probabilities = np.column_stack((1 - probabilities, probabilities))
            return probabilities.reshape((probabilities.shape[0], -1))

        import tensorflow as tf
        import tensorflow_decision_forests as tfdf
        dense = matrix.toarray().astype(np.float32)
        frame = {f"tfidf_{index}": dense[:, index] for index in range(dense.shape[1])}
        dataset = tf.data.Dataset.from_tensor_slices(frame).batch(32)
        predictions = self.model.predict(dataset, verbose=0)
        if isinstance(predictions, dict):
            predictions = next(iter(predictions.values()))
        probabilities = np.asarray(predictions)
        if probabilities.ndim == 1:
            probabilities = np.column_stack((1.0 - probabilities, probabilities))
        return probabilities.reshape((-1, len(CLASS_ORDER)))


xgboost_service = XGBoostService()
