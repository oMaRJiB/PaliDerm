"""Export and load SCIN inference bundles without changing the Flask AI adapter.

Callers supply authorized, decrypted image bytes or a PIL image and the complete
SCIN metadata schema. This module never opens application databases or maps the
prototype's smaller questionnaire to invented SCIN answers.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import torch

from .data import IMAGENET_MEAN, IMAGENET_STD, ImagePreprocessor, MetadataEncoder
from .training import load_checkpoint

BUNDLE_FILES = ("best_model.pt", "metadata_encoder.json", "class_mapping.json", "training_config.json")


def _sha256(path: Path) -> str:
    """Hash one locally saved artifact for model/encoder consistency checking."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_for_app(run_dir: str | Path, destination: str | Path) -> Path:
    """Publish the restored best checkpoint plus encoder/classes as one directory.

    The directory is independently loadable, needs no training data/cache and
    never downloads pretrained weights. Existing destinations are preserved.
    Hashes detect accidental mismatched artifact files, not malicious tampering.
    """
    source, target = Path(run_dir), Path(destination)
    if target.exists():
        raise FileExistsError("Choose a new app-model destination; existing bundles are preserved.")
    for name in BUNDLE_FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".scin-bundle-", dir=target.parent))
    try:
        for name in BUNDLE_FILES:
            shutil.copy2(source / name, staging / name)
        manifest = {
            "format_version": 1,
            "architecture": "mobilenet_v3_small_metadata_late_fusion",
            "files": {name: _sha256(staging / name) for name in BUNDLE_FILES},
            "probability_notice": "Uncalibrated model softmax scores; not validated clinical probabilities.",
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
        )
        # Check dimensions/order before publishing a bundle for the application.
        SCINPredictor(staging)
        os.rename(staging, target)
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging)


class SCINPredictor:
    """Reusable inference object; load once outside a per-request Flask route."""

    def __init__(self, model_dir: str | Path, device: str | torch.device = "cpu") -> None:
        """Load a locally trusted exported bundle and verify all saved contracts."""
        directory = Path(model_dir)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format_version") != 1 or set(manifest.get("files", {})) != set(BUNDLE_FILES):
            raise ValueError("Unsupported or incomplete SCIN inference bundle.")
        for name in BUNDLE_FILES:
            if _sha256(directory / name) != manifest["files"][name]:
                raise ValueError(f"Inference artifact hash mismatch: {name}.")
        self.device = torch.device(device)
        self.model, checkpoint = load_checkpoint(directory / "best_model.pt", self.device)
        self.encoder = MetadataEncoder.load(directory / "metadata_encoder.json")
        if checkpoint.get("metadata_encoder_sha256") != _sha256(directory / "metadata_encoder.json"):
            raise ValueError("Checkpoint is not bound to this training-fitted metadata encoder.")
        self.target_classes = tuple(checkpoint["target_classes"])
        mapping = json.loads((directory / "class_mapping.json").read_text(encoding="utf-8"))
        config = json.loads((directory / "training_config.json").read_text(encoding="utf-8"))
        if mapping.get("target_classes") != list(self.target_classes):
            raise ValueError("Inference class mapping disagrees with checkpoint order.")
        if self.encoder.output_dim != checkpoint["metadata_dim"]:
            raise ValueError("Inference metadata encoder width disagrees with checkpoint.")
        if config != checkpoint["training_config"]:
            raise ValueError("Inference training configuration disagrees with checkpoint.")
        normalization = checkpoint.get("image_normalization", {})
        if normalization.get("mean") != list(IMAGENET_MEAN) or normalization.get("std") != list(IMAGENET_STD):
            raise ValueError("Inference image normalization disagrees with implemented transform.")
        self.preprocess = ImagePreprocessor(checkpoint["image_size"])

    @torch.inference_mode()
    def predict(self, image: Any, metadata: Mapping[str, Any], top_k: int = 3) -> dict[str, Any]:
        """Return every class ranked by softmax score and the requested top-k.

        Args:
            image: PIL image, bytes, file-like object or local image path.
            metadata: All saved binary and categorical SCIN feature names/values.
            top_k: Positive number of requested top predictions, capped at classes.

        Raises ValueError for invalid metadata/top_k; image decoding errors are
        surfaced to the caller. Predictions never become clinician diagnoses.
        """
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k must be a positive integer.")
        encoded = self.encoder.transform(metadata)
        inputs = self.preprocess(image).unsqueeze(0).to(self.device)
        metadata_tensor = torch.from_numpy(encoded).to(self.device)
        self.model.eval()
        probabilities = self.model(inputs, metadata_tensor).softmax(dim=1)[0].cpu()
        if not torch.isfinite(probabilities).all():
            raise ValueError("Model returned nonfinite probabilities.")
        ranked = [
            {"rank": rank, "class_index": index,
             "diagnosis_name": self.target_classes[index],
             "probability": float(probabilities[index])}
            for rank, index in enumerate(torch.argsort(probabilities, descending=True).tolist(), start=1)
        ]
        return {
            "probabilities": ranked, "top_predictions": ranked[:top_k],
            "probability_notice": "Uncalibrated model softmax scores; not validated clinical probabilities.",
        }
