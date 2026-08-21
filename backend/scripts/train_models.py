#!/usr/bin/env python
"""
Standalone CLI training script.

Usage:
    python scripts/train_models.py --dataset app/datasets/feedback.csv
    python scripts/train_models.py --dataset app/datasets/feedback.csv --n-estimators 400 --skip-bert

This performs the same "research mode" pipeline as ``POST /ml/train``:
trains SVM + Naive Bayes + Random Forest on an identical split,
evaluates BERT on the same held-out data, records everything to the
database (TrainingHistory) and to app/ml/comparison_results.json, and
promotes the best model (highest weighted F1) to production.
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.services.training import run_full_training  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Train SVM/Naive Bayes/Random Forest and evaluate BERT.")
    parser.add_argument("--dataset", required=True, help="Path to a labeled CSV (id, category, comment, sentiment).")
    parser.add_argument("--n-estimators", type=int, default=300, help="Random Forest tree count.")
    parser.add_argument("--max-depth", type=int, default=None, help="Random Forest max tree depth.")
    parser.add_argument("--min-samples-split", type=int, default=2, help="Random Forest min samples to split a node.")
    parser.add_argument("--skip-bert", action="store_true", help="Skip BERT evaluation (faster, classical models only).")
    args = parser.parse_args()

    csv_path = Path(args.dataset)
    if not csv_path.exists():
        print(f"Dataset not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print(f"Training on dataset: {csv_path}")
        summary = run_full_training(
            db,
            csv_path,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            min_samples_split=args.min_samples_split,
            evaluate_bert=not args.skip_bert,
        )

        print("\n=== Model Comparison ===")
        print(f"{'Algorithm':<15}{'Accuracy':<10}{'Weighted F1':<14}{'Train (s)':<12}{'Infer (ms)':<12}")
        for algo, metrics in summary["results"].items():
            print(
                f"{algo:<15}"
                f"{metrics['accuracy']:<10.4f}"
                f"{metrics['weighted_f1']:<14.4f}"
                f"{metrics['training_time_seconds']:<12.2f}"
                f"{metrics['inference_time_ms']:<12.2f}"
            )
        print(f"\nBest performing model (promoted to production): {summary['best_model']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
