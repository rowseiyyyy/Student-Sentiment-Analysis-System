"""Shared, standalone three-class transformer service support (Phase 2)."""
from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score

from app.services.preprocessing import clean_for_transformer

CLASS_ORDER = ("Negative", "Neutral", "Positive")
LABEL_TO_ID = {label: index for index, label in enumerate(CLASS_ORDER)}


class TransformerSentimentService:
    checkpoint_name: str
    artifact_path: Path

    def __init__(self, checkpoint_name: str, artifact_path: Path, device: str = "cpu") -> None:
        self.checkpoint_name, self.artifact_path, self.device = checkpoint_name, artifact_path, device
        self.model = self.tokenizer = None

    def _load(self) -> None:
        if self.model is not None:
            return
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        source = str(self.artifact_path) if self.artifact_path.exists() else self.checkpoint_name
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            source, num_labels=3, id2label=dict(enumerate(CLASS_ORDER)), label2id=LABEL_TO_ID,
            ignore_mismatched_sizes=True,
        )
        import torch
        self.model.to(torch.device(self.device if self.device == "cuda" and torch.cuda.is_available() else "cpu"))
        self.model.eval()

    def is_ready(self) -> bool:
        return self.model is not None or self.artifact_path.exists()

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

        train_dataset = Dataset.from_dict({"text": train_texts, "label": train_labels}).map(_encode, batched=True)
        val_dataset = Dataset.from_dict({"text": val_texts, "label": val_labels}).map(_encode, batched=True)
        train_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])
        val_dataset.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])

        args = TrainingArguments(
            output_dir=str(output_dir),
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            learning_rate=float(learning_rate),
            num_train_epochs=int(epochs),
            evaluation_strategy="epoch",
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
        self._load()
        import torch
        cleaned = clean_for_transformer(text)
        inputs = self.tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=256)
        inputs = {key: value.to(next(self.model.parameters()).device) for key, value in inputs.items()}
        with torch.no_grad():
            raw = torch.softmax(self.model(**inputs).logits[0], dim=-1).cpu().numpy()
        probabilities = self.align_probabilities(raw, self.model.config.id2label)
        index = int(np.argmax(probabilities))
        return CLASS_ORDER[index], probabilities[index], probabilities

    @staticmethod
    def metrics(y_true: list[str], y_pred: list[str]) -> dict:
        return {"accuracy": float(accuracy_score(y_true, y_pred)), "precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)), "recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)), "f1_score": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)), "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), "labels": list(CLASS_ORDER), "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(CLASS_ORDER)).tolist(), "classification_report": classification_report(y_true, y_pred, labels=list(CLASS_ORDER), target_names=list(CLASS_ORDER), output_dict=True, zero_division=0)}
