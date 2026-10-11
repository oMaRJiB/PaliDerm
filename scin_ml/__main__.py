"""Run the same explicit SCIN experiment as the notebook, without EDA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from .inference import export_for_app
from .model import MultimodalDermatologyModel
from .pipeline import prepare_data, select_device
from .training import TrainingConfig, evaluate, fit, seed_everything


def main() -> None:
    """Train, evaluate held-out data once, and export an inference directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=Path("notebooks/SCIN_cleaned.pkl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase1-epochs", type=int, default=5)
    parser.add_argument("--phase2-epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "mps", "cuda"))
    parser.add_argument("--image-root", type=Path)
    parser.add_argument("--arrow-cache", type=Path)
    parser.add_argument("--exclude-missing-primary", action="store_true")
    parser.add_argument("--torch-cache", type=Path, default=Path(".cache/torch/hub"))
    args = parser.parse_args()
    torch.hub.set_dir(str(args.torch_cache.resolve()))
    config = TrainingConfig(
        phase1_epochs=args.phase1_epochs, phase2_epochs=args.phase2_epochs, seed=args.seed,
    )
    device = select_device(args.device)
    print(f"Device: {device}", flush=True)
    prepared = prepare_data(
        args.artifact, args.output_dir, seed=config.seed, batch_size=args.batch_size,
        image_size=config.image_size, num_workers=args.num_workers,
        image_root=args.image_root, arrow_cache=args.arrow_cache,
        exclude_missing_primary=args.exclude_missing_primary,
    )
    try:
        print(json.dumps(prepared.report, indent=2), flush=True)
        seed_everything(config.seed)
        model = MultimodalDermatologyModel(prepared.encoder.output_dim, prepared.artifacts.num_classes)
        result = fit(
            model, prepared.loaders["train"], prepared.loaders["val"], args.output_dir,
            prepared.artifacts.classes, config, device,
            metadata_encoder_path=args.output_dir / "metadata_encoder.json",
        )
        # Checkpoint selection is complete before the held-out test loader is used.
        validation = evaluate(model, prepared.loaders["val"], device, prepared.artifacts.classes)
        test = evaluate(model, prepared.loaders["test"], device, prepared.artifacts.classes)
        for name, metrics in (("validation", validation), ("test", test)):
            (args.output_dir / f"{name}_metrics.json").write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
        bundle = export_for_app(args.output_dir, args.output_dir / "app_model")
        print(json.dumps({
            "best_validation_loss": result.best_validation_loss,
            "best_epoch": result.best_epoch,
            "epochs_executed": len(result.history),
            "validation_top1": validation["top1_accuracy"],
            "validation_top3": validation["top3_accuracy"],
            "validation_macro_f1": validation["macro_f1"],
            "test_loss": test["loss"], "test_top1": test["top1_accuracy"],
            "test_top3": test["top3_accuracy"], "test_macro_f1": test["macro_f1"],
            "checkpoint": str(result.checkpoint_path), "app_bundle": str(bundle),
        }, indent=2), flush=True)
    finally:
        prepared.image_store.close()


if __name__ == "__main__":
    main()
