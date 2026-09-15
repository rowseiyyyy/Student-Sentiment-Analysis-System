"""Shared, standalone three-class transformer service support (Phase 2)."""
from __future__ import annotations

import gc
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from app.services.preprocessing import clean_for_transformer

CLASS_ORDER = ("Negative", "Neutral", "Positive")
LABEL_TO_ID = {label: index for index, label in enumerate(CLASS_ORDER)}


class TransformerSentimentService:
    checkpoint_name: str
    artifact_path: Path

    def __init__(
        self,
        checkpoint_name: str,
        artifact_path: Path,
        device: str = "cpu",
        quantized_filename: str | None = None,
    ) -> None:
        self.checkpoint_name = checkpoint_name
        self.artifact_path = artifact_path
        self.device = device
        # Filename (in artifact_path) of the quantized state_dict used for
        # inference; None means this service instance is training/full-precision.
        self.quantized_filename = quantized_filename
        self.model = self.tokenizer = None

    def _quantized_state_path(self) -> Path:
        """Absolute path of the quantized state_dict used for inference."""
        if not self.quantized_filename:
            raise RuntimeError("No quantized state_dict filename is configured for this service.")
        return self.artifact_path / self.quantized_filename

    def _build_quantized_model(self) -> tuple:
        """Build a fresh quantized model + tokenizer for a single prediction.

        The classification architecture is created from the model's own
        ``config.json`` (no full-size weights are ever loaded onto RAM), then
        dynamically quantized with the exact same ``qconfig_spec`` used when the
        quantized ``.pt`` was exported, and finally the quantized state_dict is
        loaded. Returns ``(tokenizer, model)``; the caller is responsible for
        deleting them (and GC) once inference is done.
        """
        import warnings

        import torch
        from transformers import (
            AutoConfig,
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        from app.utils.logger import logger

        has_saved = bool(
            self.artifact_path
            and self.artifact_path.exists()
            and (self.artifact_path / "config.json").exists()
        )
        source = str(self.artifact_path) if has_saved else self.checkpoint_name

        tokenizer = AutoTokenizer.from_pretrained(source)
        config = AutoConfig.from_pretrained(
            source,
            num_labels=len(CLASS_ORDER),
            id2label=dict(enumerate(CLASS_ORDER)),
            label2id=LABEL_TO_ID,
        )
        # Build architecture WITHOUT loading full-precision weights — the
        # RandomInit is harmless because load_state_dict overwrites everything.
        model = AutoModelForSequenceClassification.from_config(config)

        qconfig_spec = {
            torch.nn.Linear: torch.quantization.default_dynamic_qconfig,
            torch.nn.Embedding: torch.quantization.float_qparams_weight_only_qconfig,
        }
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # quantize_dynamic API deprecation noise
            model = torch.quantization.quantize_dynamic(  # type: ignore[no-untyped-call]
                model, qconfig_spec
            )

        state = torch.load(self._quantized_state_path(), map_location="cpu")
        missing, unexpected = model.load_state_dict(state, strict=False)
        if missing or unexpected:
            logger.warning(
                "Quantized state_dict mismatch for %s | missing=%s | unexpected=%s",
                self.__class__.__name__,
                missing,
                unexpected,
            )
        model.eval()
        return tokenizer, model

    def _load(self) -> None:
        if self.model is not None:
            return
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        has_saved_model = self.artifact_path.exists() and (self.artifact_path / "config.json").exists()
        source = str(self.artifact_path) if has_saved_model else self.checkpoint_name
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            source, num_labels=3, id2label=dict(enumerate(CLASS_ORDER)), label2id=LABEL_TO_ID,
            ignore_mismatched_sizes=True,
        )
        import torch
        self.model.to(torch.device(self.device if self.device == "cuda" and torch.cuda.is_available() else "cpu"))
        self.model.eval()

    def is_ready(self) -> bool:
        """A transformer is usable for inference when its quantized state_dict
        and config are on disk.

        Models are built per-prediction and unloaded afterwards, so readiness is
        a cheap file check rather than a check for a resident model. (The local
        dir may also contain a full-precision checkpoint from /ml/train, but that
        is not what inference uses.)
        """
        return bool(
            self.artifact_path
            and self.artifact_path.exists()
            and (self.artifact_path / "config.json").exists()
            and self._quantized_state_path().exists()
        )

    def reload(self) -> None:
        """Reload model and tokenizer after an artifact replacement."""
        self.model = None
        self.tokenizer = None
        self._load()

    @staticmethod
    def align_probabilities(raw: list[float] | np.ndarray, model_id2label: dict | None = None) -> list[float]:
        """Map any checkpoint order into the application order."""
        if not model_id2label:
            return [float(value) for value in raw]
        aligned = [0.0, 0.0, 0.0]
        for index, value in enumerate(raw):
            label = str(model_id2label.get(index, model_id2label.get(str(index), ""))).title()
            if label in LABEL_TO_ID:
                aligned[LABEL_TO_ID[label]] = float(value)
        total = sum(aligned)
        return [value / total for value in aligned] if total else aligned

    def save(self, training_config: dict | None = None) -> None:
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Cannot save an unloaded transformer model.")
        self.artifact_path.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(self.artifact_path)
        self.tokenizer.save_pretrained(self.artifact_path)
        (self.artifact_path / "asiatech_sentiment_config.json").write_text(json.dumps({"classes": CLASS_ORDER, "checkpoint": self.checkpoint_name, "training": training_config or {}}, indent=2), encoding="utf-8")

    def fine_tune(
        self,
        train_texts: list[str],
        train_labels: list[str],
        val_texts: list[str],
        val_labels: list[str],
        output_dir: str | Path,
        epochs: int = 3,
        learning_rate: float = 2e-5,
        batch_size: int = 8,
        max_length: int = 256,
        seed: int = 42,
    ) -> dict:
        from datasets import Dataset
        from transformers import Trainer, TrainingArguments

        if not set(train_labels).issubset(set(CLASS_ORDER)) or not set(val_labels).issubset(set(CLASS_ORDER)):
            raise ValueError("Transformer labels must be Negative, Neutral, or Positive.")

        self._load()
        label2id = {label: index for index, label in enumerate(CLASS_ORDER)}
        id2label = {index: label for label, index in label2id.items()}
        self.model.config.label2id = label2id
        self.model.config.id2label = id2label
        self.model.to(next(self.model.parameters()).device)

        def _encode(batch: dict) -> dict:
            tokens = self.tokenizer(batch["text"], truncation=True, padding="max_length", max_length=max_length)
            tokens["label"] = [label2id[label] for label in batch["label"]]
            return tokens

        # Apply the same cleaning used at inference time (see predict()) so
        # the model is trained and evaluated on the same text distribution
        # it will see in production, avoiding train/serve skew.
        train_texts_clean = [clean_for_transformer(text) for text in train_texts]
        val_texts_clean = [clean_for_transformer(text) for text in val_texts]

        train_dataset = Dataset.from_dict({"text": train_texts_clean, "label": train_labels}).map(_encode, batched=True)
        val_dataset = Dataset.from_dict({"text": val_texts_clean, "label": val_labels}).map(_encode, batched=True)

        train_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])
        val_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])

        args = TrainingArguments(
            output_dir=str(output_dir),
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            learning_rate=float(learning_rate),
            num_train_epochs=int(epochs),
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=1,
            load_best_model_at_end=True,
            metric_for_best_model="macro_f1",
            logging_steps=10,
            weight_decay=0.01,
            seed=int(seed),
            report_to=[],
            remove_unused_columns=False,
        )

        def _compute_metrics(eval_pred):
            logits, labels = eval_pred
            predictions = np.argmax(logits, axis=-1)
            y_true = [CLASS_ORDER[int(v)] for v in labels.tolist()]
            y_pred = [CLASS_ORDER[int(v)] for v in predictions.tolist()]
            return self.metrics(y_true, y_pred)

        trainer = Trainer(
            model=self.model,
            args=args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            tokenizer=self.tokenizer,
            compute_metrics=_compute_metrics,
        )
        trainer.train()
        self.model.eval()
        self.save({"checkpoint": self.checkpoint_name, "epochs": epochs, "learning_rate": learning_rate, "batch_size": batch_size, "max_length": max_length, "seed": seed})

        val_predictions = trainer.predict(val_dataset)
        logits = val_predictions.predictions
        y_pred = [CLASS_ORDER[int(np.argmax(logit))] for logit in logits]
        y_true = val_labels
        return self.metrics(y_true, y_pred)

    def predict(self, text: str) -> tuple[str, float, list[float]]:
        # Quantized inference is strictly load -> predict -> unload: build a
        # fresh model, run once, then delete + GC so RAM is freed between calls
        # (no persistent cache), as required for the constrained Render tier.
        tokenizer, model = self._build_quantized_model()
        try:
            import torch

            cleaned = clean_for_transformer(text)
            inputs = tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=256)
            with torch.no_grad():
                raw = torch.softmax(model(**inputs).logits[0], dim=-1).cpu().numpy()
            probabilities = self.align_probabilities(raw, model.config.id2label)
            index = int(np.argmax(probabilities))
            return CLASS_ORDER[index], probabilities[index], probabilities
        finally:
            del model, tokenizer
            gc.collect()

    @staticmethod
    def metrics(y_true: list[str], y_pred: list[str]) -> dict:
        """Compute common classification metrics (used only during training
        and evaluation — not at inference time). Imported lazily so the app
        can start without scikit-learn installed; it is only loaded when
        training/evaluation actually runs.
        """
        from sklearn import metrics

        accuracy = metrics.accuracy_score(y_true, y_pred)
        precision = metrics.precision_score(y_true, y_pred, average="weighted", zero_division=0)
        recall = metrics.recall_score(y_true, y_pred, average="weighted", zero_division=0)
        f1 = metrics.f1_score(y_true, y_pred, average="weighted", zero_division=0)
        f1_macro = metrics.f1_score(y_true, y_pred, average="macro", zero_division=0)
        confusion = metrics.confusion_matrix(y_true, y_pred, labels=list(CLASS_ORDER))
        report = metrics.classification_report(
            y_true, y_pred, labels=list(CLASS_ORDER), zero_division=0
        )

        return {
            "accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "macro_f1": float(f1_macro),
            "weighted_f1": float(f1),
            "labels": list(CLASS_ORDER),
            "confusion_matrix": confusion.tolist(),
            "classification_report": report,
        }