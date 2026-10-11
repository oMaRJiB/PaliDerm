"""Two-phase soft-label training, honest evaluation and portable checkpoints.

The test split is deliberately absent from ``fit``: validation selects the
checkpoint, and the caller evaluates the held-out test set once afterward.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from .model import MultimodalDermatologyModel


@dataclass(frozen=True)
class TrainingConfig:
    """Explicit, serializable experiment settings; no clinical decision rules."""

    phase1_epochs: int = 5
    phase2_epochs: int = 15
    fine_tune_blocks: int = 3
    phase1_head_lr: float = 1e-3
    phase1_new_lr: float = 1e-4
    phase2_backbone_lr: float = 1e-5
    phase2_new_lr: float = 1e-4
    weight_decay: float = 1e-4
    scheduler_factor: float = 0.5
    scheduler_patience: int = 2
    early_stopping_patience: int = 5
    min_delta: float = 0.0
    seed: int = 42
    image_size: int = 224

    def __post_init__(self):
        """Reject invalid experiments before updating any weights or artifacts."""
        if self.phase1_epochs < 1 or self.phase2_epochs < 0:
            raise ValueError("phase1_epochs must be positive and phase2_epochs nonnegative.")
        if self.fine_tune_blocks < 1 or self.early_stopping_patience < 1:
            raise ValueError("Fine-tuning blocks and early-stopping patience must be positive.")
        if self.scheduler_patience < 0 or not 0 < self.scheduler_factor < 1:
            raise ValueError("Invalid ReduceLROnPlateau factor or patience.")
        rates = (self.phase1_head_lr, self.phase1_new_lr,
                 self.phase2_backbone_lr, self.phase2_new_lr)
        if any(not math.isfinite(rate) or rate <= 0 for rate in rates):
            raise ValueError("Learning rates must be finite positive values.")
        if self.weight_decay < 0 or self.min_delta < 0 or self.image_size < 1:
            raise ValueError("Invalid weight decay, minimum improvement or image size.")


@dataclass
class TrainingResult:
    """Summary of executed epochs and the globally best restored checkpoint."""

    history: list[dict[str, Any]] = field(default_factory=list)
    best_validation_loss: float = math.inf
    best_epoch: int = 0
    checkpoint_path: Path | None = None


def seed_everything(seed: int) -> None:
    """Seed Python, NumPy and Torch; exact device/platform equality is not promised."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def soft_label_cross_entropy(
    logits: torch.Tensor, targets: torch.Tensor, reduction: str = "mean"
) -> torch.Tensor:
    """Cross entropy against dermatologist-weighted probability distributions.

    Targets are validated, never hardened with argmax or silently renormalized.
    Raises ValueError for nonfinite/negative targets, incorrect sums or shapes.
    """
    if logits.ndim != 2 or targets.shape != logits.shape or logits.shape[0] == 0:
        raise ValueError("Logits and targets must have matching nonempty [batch, classes] shapes.")
    if not torch.is_floating_point(targets):
        raise ValueError("Soft targets must be floating-point probability distributions.")
    if not torch.isfinite(logits).all() or not torch.isfinite(targets).all():
        raise ValueError("Logits and soft targets must be finite.")
    if (targets < 0).any() or (targets > 1).any():
        raise ValueError("Soft target values must be within [0, 1].")
    sums = targets.sum(dim=1)
    if not torch.allclose(sums, torch.ones_like(sums), atol=1e-4, rtol=1e-4):
        raise ValueError("Every soft target distribution must sum to one.")
    losses = -(targets * F.log_softmax(logits, dim=1)).sum(dim=1)
    if reduction == "none":
        return losses
    if reduction == "sum":
        return losses.sum()
    if reduction == "mean":
        return losses.mean()
    raise ValueError("reduction must be 'none', 'sum' or 'mean'.")


def configure_optimizer(
    model: MultimodalDermatologyModel, phase: int, config: TrainingConfig
) -> torch.optim.AdamW:
    """Apply the requested frozen/fine-tuned backbone and discriminative rates."""
    if phase == 1:
        model.set_trainable_backbone_blocks(0)
        groups = [
            {"params": model.fusion_head.parameters(), "lr": config.phase1_head_lr,
             "name": "fusion_head"},
            {"params": list(model.image_projection.parameters()) +
                       list(model.metadata_branch.parameters()),
             "lr": config.phase1_new_lr, "name": "new_branches"},
        ]
    elif phase == 2:
        model.set_trainable_backbone_blocks(config.fine_tune_blocks)
        groups = [
            {"params": [p for p in model.features.parameters() if p.requires_grad],
             "lr": config.phase2_backbone_lr, "name": "cnn_last_blocks"},
            {"params": list(model.image_projection.parameters()) +
                       list(model.metadata_branch.parameters()) +
                       list(model.fusion_head.parameters()),
             "lr": config.phase2_new_lr, "name": "new_layers"},
        ]
    else:
        raise ValueError("Training phase must be 1 or 2.")
    return torch.optim.AdamW(groups, weight_decay=config.weight_decay)


def _batch_tensors(batch: dict, device: torch.device | str):
    """Move aligned image/metadata/soft-target tensors without changing labels."""
    return tuple(batch[key].to(device=device, dtype=torch.float32)
                 for key in ("image", "metadata", "target"))


def train_epoch(
    model: nn.Module, loader: Iterable, optimizer: torch.optim.Optimizer,
    device: torch.device | str = "cpu",
) -> dict[str, float | int]:
    """Execute one training epoch; fail on invalid targets or nonfinite loss."""
    model.train()
    total_loss = 0.0
    samples = 0
    for batch in loader:
        images, metadata, targets = _batch_tensors(batch, device)
        optimizer.zero_grad(set_to_none=True)
        loss = soft_label_cross_entropy(model(images, metadata), targets)
        loss.backward()
        optimizer.step()
        total_loss += float(loss.detach().cpu()) * len(targets)
        samples += len(targets)
    if not samples:
        raise ValueError("Training loader is empty.")
    return {"loss": total_loss / samples, "samples": samples}


@torch.inference_mode()
def evaluate(
    model: nn.Module, loader: Iterable, device: torch.device | str = "cpu",
    target_classes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Report soft-label loss plus explicitly argmax-reference ranking metrics.

    Accuracy and per-class precision/recall use the highest-weight dermatologist
    class as a reference only for reporting. Loss always uses the full target.
    Expected top-k mass additionally measures retained soft-label probability.
    Zero-support classes report None rather than implying measured performance.
    """
    model.eval()
    total_loss = 0.0
    samples = 0
    top1 = top3 = 0
    soft_top1 = soft_top3 = 0.0
    confusion: np.ndarray | None = None
    for batch in loader:
        images, metadata, targets = _batch_tensors(batch, device)
        logits = model(images, metadata)
        loss = soft_label_cross_entropy(logits, targets, reduction="sum")
        classes = logits.shape[1]
        if confusion is None:
            if target_classes is not None and len(target_classes) != classes:
                raise ValueError("Class mapping length does not match model outputs.")
            confusion = np.zeros((classes, classes), dtype=np.int64)
        elif confusion.shape[0] != classes:
            raise ValueError("Model class dimension changed during evaluation.")
        ranked = logits.topk(min(3, classes), dim=1).indices
        truth = targets.argmax(dim=1)
        prediction = ranked[:, 0]
        top1 += int((prediction == truth).sum().cpu())
        top3 += int((ranked == truth[:, None]).any(dim=1).sum().cpu())
        soft_top1 += float(targets.gather(1, prediction[:, None]).sum().cpu())
        soft_top3 += float(targets.gather(1, ranked).sum().cpu())
        truth_array = truth.cpu().numpy()
        prediction_array = prediction.cpu().numpy()
        np.add.at(confusion, (truth_array, prediction_array), 1)
        total_loss += float(loss.cpu())
        samples += len(targets)
    if samples == 0 or confusion is None:
        raise ValueError("Evaluation loader is empty.")
    per_class = []
    for index in range(len(confusion)):
        support = int(confusion[index].sum())
        predicted = int(confusion[:, index].sum())
        true_positive = int(confusion[index, index])
        precision = true_positive / predicted if predicted else None
        recall = true_positive / support if support else None
        # A represented class with no correct prediction has zero F1, including
        # classes never predicted; absent classes cannot be evaluated.
        f1 = (2 * true_positive / (support + predicted)) if support else None
        per_class.append({
            "class_index": index,
            "class_name": str(target_classes[index]) if target_classes is not None else str(index),
            "precision": precision, "recall": recall, "f1": f1,
            "support": support, "predicted_count": predicted,
        })
    supported = [item for item in per_class if item["support"] > 0]
    return {
        "loss": total_loss / samples, "samples": samples,
        "top1_accuracy": top1 / samples, "top3_accuracy": top3 / samples,
        "soft_top1_mass": soft_top1 / samples, "soft_top3_mass": soft_top3 / samples,
        "macro_precision": float(np.mean([item["precision"] or 0.0 for item in supported])),
        "macro_recall": float(np.mean([item["recall"] for item in supported])),
        "macro_f1": float(np.mean([item["f1"] for item in supported])),
        "per_class": per_class, "confusion_matrix": confusion.tolist(),
        "hard_metric_reference": "argmax of dermatologist-weighted soft targets; not training targets",
    }


def _write_json(path: Path, value: Any) -> None:
    """Atomically publish plain experiment metadata, never executable objects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_checkpoint(path: str | Path, payload: dict[str, Any]) -> None:
    """Atomically write tensor/state-dict artifacts compatible with weights_only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_checkpoint(
    path: str | Path, device: torch.device | str = "cpu",
) -> tuple[MultimodalDermatologyModel, dict[str, Any]]:
    """Load a trusted local state-dict bundle without downloading ImageNet weights.

    Torch's restricted loader rejects arbitrary pickle objects. This function
    validates the class order and model dimensions before strict weight loading.
    """
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or payload.get("format_version") != 1:
        raise ValueError("Unsupported SCIN checkpoint format.")
    if payload.get("architecture") != "mobilenet_v3_small_metadata_late_fusion":
        raise ValueError("Checkpoint architecture is not supported.")
    classes = payload.get("target_classes")
    if (not isinstance(classes, list) or
            not all(isinstance(name, str) and name.strip() for name in classes) or
            len(set(classes)) != len(classes)):
        raise ValueError("Checkpoint has no valid ordered class mapping.")
    num_classes = payload.get("num_classes")
    metadata_dim = payload.get("metadata_dim")
    if (type(num_classes) is not int or num_classes < 2 or
            len(classes) != num_classes):
        raise ValueError("Checkpoint class count and mapping disagree.")
    if type(metadata_dim) is not int or metadata_dim < 1:
        raise ValueError("Checkpoint metadata dimension must be a positive integer.")
    model = MultimodalDermatologyModel(
        metadata_dim=metadata_dim, num_classes=num_classes, pretrained=False,
    )
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.to(device).eval()
    return model, payload


def _checkpoint_payload(
    model: MultimodalDermatologyModel, optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.ReduceLROnPlateau,
    target_classes: list[str], config: TrainingConfig, epoch: int, phase: int,
    validation_loss: float, metadata_encoder_sha256: str | None = None,
) -> dict[str, Any]:
    """Use tensors/primitives only so restricted checkpoint loading stays possible."""
    return {
        "format_version": 1,
        "architecture": "mobilenet_v3_small_metadata_late_fusion",
        "metadata_dim": model.metadata_dim, "num_classes": model.num_classes,
        "target_classes": target_classes, "image_size": config.image_size,
        # Equal encoder dimensions do not imply equal feature/category order.
        # Binding its exact artifact prevents otherwise plausible wrong inputs.
        "metadata_encoder_sha256": metadata_encoder_sha256,
        "image_normalization": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
        "image_resize": "RGB; aspect-preserving resize; centered padding",
        "pretrained_initialization": model.pretrained_requested,
        "training_config": asdict(config),
        "model_state_dict": {key: value.detach().cpu().clone()
                             for key, value in model.state_dict().items()},
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "epoch": epoch, "phase": phase, "validation_loss": validation_loss,
        "torch_rng_state": torch.get_rng_state(),
        "torch_version": str(torch.__version__),
        "selection_metric": "validation soft-label cross entropy",
    }


def fit(
    model: MultimodalDermatologyModel, train_loader: Iterable, validation_loader: Iterable,
    output_dir: str | Path, target_classes: Sequence[str],
    config: TrainingConfig | None = None, device: torch.device | str = "cpu",
    *, metadata_encoder_path: str | Path | None = None,
) -> TrainingResult:
    """Train both requested phases and restore the globally best validation model.

    Phase two starts from the best phase-one weights. Each phase gets its own
    optimizer/scheduler and patience window because its trainable parameters
    differ; checkpoint selection remains global across the entire experiment.
    Test data must never be supplied as validation data.

    metadata_encoder_path binds the saved, training-fitted encoder's SHA-256 to
    every checkpoint. Production inference/export must verify that binding;
    None is reserved for isolated architecture/training tests without an encoder.
    """
    config = config or TrainingConfig()
    classes = [str(value) for value in target_classes]
    if len(classes) != model.num_classes:
        raise ValueError("target_classes must preserve the model's exact output count/order.")
    if config.fine_tune_blocks > len(model.features):
        raise ValueError("Requested fine-tuning blocks exceed the CNN feature blocks.")
    metadata_encoder_sha256 = None
    if metadata_encoder_path is not None:
        with Path(metadata_encoder_path).open("rb") as stream:
            metadata_encoder_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    output_dir = Path(output_dir)
    checkpoint_path = output_dir / "best_model.pt"
    if checkpoint_path.exists():
        raise FileExistsError("Choose a new output directory; an existing checkpoint will not be overwritten.")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "training_config.json", asdict(config))
    _write_json(output_dir / "class_mapping.json", {
        "target_classes": classes,
        "index_to_class": {str(index): value for index, value in enumerate(classes)},
    })
    seed_everything(config.seed)
    model.to(device)
    result = TrainingResult(checkpoint_path=checkpoint_path)
    global_epoch = 0
    for phase, epochs in ((1, config.phase1_epochs), (2, config.phase2_epochs)):
        if not epochs:
            continue
        if phase == 2:
            best_payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
            model.load_state_dict(best_payload["model_state_dict"], strict=True)
        optimizer = configure_optimizer(model, phase, config)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=config.scheduler_factor,
            patience=config.scheduler_patience,
        )
        phase_best = result.best_validation_loss
        epochs_without_improvement = 0
        for phase_epoch in range(1, epochs + 1):
            global_epoch += 1
            training = train_epoch(model, train_loader, optimizer, device)
            validation = evaluate(model, validation_loader, device, classes)
            validation_loss = validation["loss"]
            learning_rates = {group["name"]: group["lr"] for group in optimizer.param_groups}
            scheduler.step(validation_loss)
            record = {
                "epoch": global_epoch, "phase": phase, "phase_epoch": phase_epoch,
                "train_loss": training["loss"], "validation_loss": validation_loss,
                "validation_top1_accuracy": validation["top1_accuracy"],
                "validation_top3_accuracy": validation["top3_accuracy"],
                "validation_macro_f1": validation["macro_f1"],
                "learning_rates": learning_rates,
            }
            result.history.append(record)
            print(f"Phase {phase}, epoch {phase_epoch}/{epochs}: "
                  f"train_loss={training['loss']:.5f} val_loss={validation_loss:.5f} "
                  f"top1={validation['top1_accuracy']:.3f} top3={validation['top3_accuracy']:.3f}",
                  flush=True)
            if validation_loss < result.best_validation_loss:
                result.best_validation_loss = validation_loss
                result.best_epoch = global_epoch
                save_checkpoint(checkpoint_path, _checkpoint_payload(
                    model, optimizer, scheduler, classes, config,
                    global_epoch, phase, validation_loss, metadata_encoder_sha256,
                ))
                _write_json(output_dir / "best_validation_metrics.json", validation)
            if validation_loss < phase_best - config.min_delta:
                phase_best = validation_loss
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1
            _write_json(output_dir / "history.json", result.history)
            if epochs_without_improvement >= config.early_stopping_patience:
                print(f"Early stopping phase {phase} after {epochs_without_improvement} "
                      "epochs without validation-loss improvement.", flush=True)
                break
    best_payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model.load_state_dict(best_payload["model_state_dict"], strict=True)
    model.eval()
    return result
