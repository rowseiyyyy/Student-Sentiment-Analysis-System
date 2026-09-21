#!/usr/bin/env python
"""Fine-tune a Hugging Face transformer on the Asiatech student-feedback data.

Two prediction targets are supported via ``--target``:

* ``sentiment`` -- 3-class (Negative / Neutral / Positive)
* ``rating``    -- 5-class Likert rating (Rating column stores 1..5; it is
  converted to 0..4 for classification, i.e. ``Rating - 1``).

The script uses the Hugging Face ``Trainer`` API, tokenizes the ``Comment``
column (``max_length=128``), trains on ``train.csv`` / ``val.csv`` and
evaluates on ``test.csv``. It reports accuracy, a classification report, a
confusion matrix and (for ``rating``) a within-±1 accuracy. It also verifies
that no duplicate Comments leak between the train, validation and test sets.

Usage examples
--------------
    python finetune_transformer.py                              # MiniLM, 3-class
    python finetune_transformer.py --target rating              # MiniLM, 5-class
    python finetune_transformer.py --epochs 4
    python finetune_transformer.py --train a.csv --val b.csv --test c.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
    set_seed,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SENTIMENT_CLASSES = ["Negative", "Neutral", "Positive"]
SENTIMENT_LABEL2ID = {label: idx for idx, label in enumerate(SENTIMENT_CLASSES)}

RATING_MIN, RATING_MAX = 1, 5          # stored Likert scale (1..5)
RATING_OFFSET = 1                      # Rating - 1  -> 0..4 classification labels
RATING_CLASSES = [str(v) for v in range(RATING_MIN, RATING_MAX + 1)]  # "1".."5"

COMMENT_COL = "Comment"
SENTIMENT_COL = "Sentiment"
RATING_COL = "Rating"

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SUPPORTED_MODELS = {
    "minilm": DEFAULT_MODEL,
    "multilingual-minilm": DEFAULT_MODEL,
    "paraphrase-multilingual-minilm-l12-v2": DEFAULT_MODEL,
}

# Reference baselines reported by the user, as percentages.
BASELINE = {"sentiment": 95.7, "rating": 85.0}
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_csv(name: str, extra_dirs: list[Path], cli_value: str | None) -> Path:
    """Return the CSV path, preferring an explicit CLI value, then checking
    the working dir, the script dir and a few conventional data locations."""
    if cli_value:
        return Path(cli_value).expanduser()

    candidates = [Path.cwd(), Path(__file__).resolve().parent] + extra_dirs
    for base in candidates:
        candidate = base / name
        if candidate.exists():
            return candidate
    # Fall back to the working-dir name so an informative error is raised.
    return Path.cwd() / name


def _normalise_comments(series: pd.Series) -> pd.Series:
    """Strip whitespace for duplicate detection (case is preserved)."""
    return series.astype(str).str.strip()


def check_leak(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> None:
    """Ensure no duplicate Comments leak across train / validation / test.

    Raises a RuntimeError if a true duplication leak is found so the run stops
    before it can report inflated scores.
    """
    train_comments = set(_normalise_comments(train[COMMENT_COL]))
    val_comments = set(_normalise_comments(val[COMMENT_COL]))
    test_comments = set(_normalise_comments(test[COMMENT_COL]))

    overlaps = {
        "train_vs_test": len(train_comments & test_comments),
        "val_vs_test": len(val_comments & test_comments),
        "train_vs_val": len(train_comments & val_comments),
    }

    print("\n=== Duplicate-Comment Leak Check ===")
    for label, count in overlaps.items():
        status = "OK" if count == 0 else "LEAK"
        print(f"  {label:<16}: {count:<6} {status}")

    leaked = [k for k, v in overlaps.items() if v > 0]
    if leaked:
        raise RuntimeError(
            f"Duplicate Comment leakage detected across {', '.join(leaked)}. "
            "Fix the split before fine-tuning so reported metrics are valid."
        )

    print("  -> No duplicate-Comment leakage between train, val and test.\n")


def _labels_for(df: pd.DataFrame, target: str) -> tuple[np.ndarray, list[str], dict[str, int]]:
    """Map a dataframe to integer labels plus the class vocabulary."""
    if target == "sentiment":
        raw = df[SENTIMENT_COL].astype(str).str.strip()
        unknown = set(raw.unique()) - set(SENTIMENT_LABEL2ID)
        if unknown:
            raise ValueError(f"Unknown sentiment labels: {sorted(unknown)}")
        labels = raw.map(SENTIMENT_LABEL2ID).astype("int64").to_numpy()
        return labels, list(SENTIMENT_CLASSES), dict(SENTIMENT_LABEL2ID)
    # rating
    numeric = pd.to_numeric(df[RATING_COL], errors="coerce")
    bad = numeric.dropna()[~numeric.dropna().between(RATING_MIN, RATING_MAX)]
    if not bad.empty:
        raise ValueError(f"Rating values must be within [{RATING_MIN},{RATING_MAX}]: {bad.tolist()}")
    if numeric.isna().any():
        raise ValueError("Rating column contains non-numeric or missing values.")
    labels = (numeric.astype("int64") - RATING_OFFSET).to_numpy()  # 0..4
    label2id = {str(v): v - RATING_OFFSET for v in range(RATING_MIN, RATING_MAX + 1)}
    return labels, list(RATING_CLASSES), label2id


def _filter_valid(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Drop rows with a missing Comment or an invalid target label."""
    df = df.dropna(subset=[COMMENT_COL]).copy()
    df[COMMENT_COL] = df[COMMENT_COL].astype(str).str.strip()
    df = df[df[COMMENT_COL] != ""]
    if target == "sentiment":
        valid = df[SENTIMENT_COL].astype(str).str.strip().isin(SENTIMENT_LABEL2ID)
    else:
        valid = pd.to_numeric(df[RATING_COL], errors="coerce").between(RATING_MIN, RATING_MAX)
    return df[valid].reset_index(drop=True)


class TextDataset(torch.utils.data.Dataset):
    """Minimal torch Dataset built from tokenized encodings + integer labels."""

    def __init__(self, encodings: dict, labels: np.ndarray) -> None:
        self.encodings = encodings
        self.labels = labels

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item
def detect_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if getattr(getattr(torch, "backends", None), "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def run(args) -> dict:
    set_seed(args.seed)
    device = detect_device()
    n_classes = len(RATING_CLASSES) if args.target == "rating" else len(SENTIMENT_CLASSES)
    print("\n=== Environment ===")
    print(f"  Model        : {args.model}")
    print(f"  Target       : {args.target}  ({n_classes} classes)")
    print(f"  Device       : {device} (auto-detected)")
    print(f"  Seed         : {args.seed}")

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    extra_dirs = [
        Path(__file__).resolve().parent / "data",
        Path(__file__).resolve().parent / "backend" / "app" / "datasets",
    ]
    train_path = _resolve_csv("train.csv", extra_dirs, args.train)
    val_path = _resolve_csv("val.csv", extra_dirs, args.val)
    test_path = _resolve_csv("test.csv", extra_dirs, args.test)

    for path in (train_path, val_path, test_path):
        if not path.exists():
            raise FileNotFoundError(f"Required data file not found: {path}")

    train = pd.read_csv(train_path)
    val = pd.read_csv(val_path)
    test = pd.read_csv(test_path)

    for path, df in ((train_path, train), (val_path, val), (test_path, test)):
        for col in (COMMENT_COL, SENTIMENT_COL, RATING_COL):
            if col not in df.columns:
                raise ValueError(f"{path}: missing column '{col}' (found: {list(df.columns)})")

    train, val, test = (
        _filter_valid(train, args.target),
        _filter_valid(val, args.target),
        _filter_valid(test, args.target),
    )

    check_leak(train, val, test)
# ------------------------------------------------------------------
    # Labels + class vocabulary
    # ------------------------------------------------------------------
    train_labels, classes, label2id = _labels_for(train, args.target)
    val_labels, _, _ = _labels_for(val, args.target)
    test_labels, _, _ = _labels_for(test, args.target)
    id2label = {int(i): c for c, i in label2id.items()}

    print("=== Split sizes ===")
    for name, df in (("train", train), ("val", val), ("test", test)):
        counts = df[SENTIMENT_COL].astype(str).str.strip().value_counts()
        print(f"  {name:<6}: n={len(df)}  sentiment={dict(counts)}")
    print()

    # ------------------------------------------------------------------
    # Tokenize
    # ------------------------------------------------------------------
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    def _tokenize(df: pd.DataFrame) -> dict:
        return tokenizer(
            df[COMMENT_COL].tolist(),
            truncation=True,
            padding=False,
            max_length=args.max_length,
            return_token_type_ids=False,
        )

    train_ds = TextDataset(_tokenize(train), train_labels)
    val_ds = TextDataset(_tokenize(val), val_labels)
    test_ds = TextDataset(_tokenize(test), test_labels)
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer, padding="longest")

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(classes),
        id2label=id2label,
        label2id=label2id,
    )

    def _compute_metrics(eval_pred):
        logits, labels = eval_pred
        predictions = np.argmax(logits, axis=-1)
        metrics = {"accuracy": float(accuracy_score(labels, predictions))}
        if args.target == "rating":
            metrics["within_1"] = float(np.mean(np.abs(labels - predictions) <= 1))
        return metrics

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        num_train_epochs=args.epochs,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        greater_is_better=True,
        logging_steps=args.logging_steps,
        weight_decay=0.01,
        seed=args.seed,
        report_to=[],
        remove_unused_columns=False,
        no_cuda=(device == "cpu"),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=_compute_metrics,
    )

    # ------------------------------------------------------------------
    # Train + evaluate on test
    # ------------------------------------------------------------------
    print("\n=== Training ===")
    trainer.train()
    print("\n=== Evaluating on test.csv ===")
    test_pred = trainer.predict(test_ds)
    logits = test_pred.predictions
    if isinstance(logits, tuple):
        logits = logits[0]
    y_pred = np.argmax(logits, axis=-1)
    y_true = test_pred.label_ids if test_pred.label_ids is not None else test_labels

    accuracy = float(accuracy_score(y_true, y_pred))
    report_txt = classification_report(
        y_true, y_pred, labels=list(range(len(classes))),
        target_names=classes, digits=4, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(classes))))

    within_1 = None
    if args.target == "rating":
        within_1 = float(np.mean(np.abs(y_true - y_pred) <= 1))

    print(f"\nTest accuracy            : {accuracy:.4%}")
    if args.target == "rating":
        print(f"Test within-±1 accuracy  : {within_1:.4%}")

    print("\n=== Classification Report (test) ===")
    print(report_txt)

    print("=== Confusion Matrix (test) ===")
    print("Rows = true, Cols = predicted | labels:", classes)
    print(cm)

    # ------------------------------------------------------------------
    # Persist model + metrics + comparison
    # ------------------------------------------------------------------
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))

    metrics = {
        "target": args.target,
        "model": args.model,
        "device": device,
        "accuracy": accuracy,
        "within_plus_minus_1": within_1,
        "classification_report": report_txt,
        "confusion_matrix": cm.tolist(),
        "classes": classes,
        "split_sizes": {"train": len(train), "val": len(val), "test": len(test)},
        "hyperparameters": {
            "epochs": args.epochs, "learning_rate": args.learning_rate,
            "batch_size": args.batch_size, "max_length": args.max_length, "seed": args.seed,
        },
    }
    (args.output_dir / "test_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8")

    print("\n=== Comparison vs the recorded baseline ===")
    baseline = BASELINE[args.target]
    delta_pp = (accuracy * 100.0) - baseline
    print(f"  Transformer ({args.model}): {accuracy*100:.2f}% | Baseline: {baseline:.1f}% | Δ: {delta_pp:+.2f} pp")
    if args.target == "rating":
        print(f"  (rating within-±1 accuracy: {within_1:.2%})")
    print(f"\n  Model + tokenizer saved to: {args.output_dir.resolve()}")

    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fine-tune a Hugging Face transformer for 3-class sentiment or 5-class rating.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=("HF model name. Shortcuts: minilm, multilingual-minilm. "
                              "Default: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
    parser.add_argument("--target", choices=["sentiment", "rating"], default="sentiment",
                        help="Prediction target (default: sentiment)")
    parser.add_argument("--train", default=None, help="Path to train.csv (auto-discovered if omitted)")
    parser.add_argument("--val", default=None, help="Path to val.csv (auto-discovered if omitted)")
    parser.add_argument("--test", default=None, help="Path to test.csv (auto-discovered if omitted)")
    parser.add_argument("--max-length", type=int, default=128,
                        help="Tokenize Comment with this max length (default: 128)")
    parser.add_argument("--epochs", type=int, default=3, help="Number of epochs (default: 3)")
    parser.add_argument("--batch-size", type=int, default=16, help="Per-device train/eval batch size (default: 16)")
    parser.add_argument("--learning-rate", type=float, default=2e-5, help="Learning rate (default: 2e-5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--logging-steps", type=int, default=10, help="Log every N steps (default: 10)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to save the fine-tuned model (default: <cwd>/finetuned_<model>_<target>)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.model in SUPPORTED_MODELS:
        args.model = SUPPORTED_MODELS[args.model]

    if args.output_dir is None:
        model_tag = args.model.replace("/", "_")
        args.output_dir = Path.cwd() / f"finetuned_{model_tag}_{args.target}"

    try:
        run(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())