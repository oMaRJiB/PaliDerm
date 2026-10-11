"""Experiment setup using the unchanged SCIN artifact and verified local images."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from .data import (
    SCINArtifacts, SCINDataset, ImagePreprocessor, ImageStore, MetadataEncoder,
    grouped_split, load_cleaned_artifact, primary_image_eligibility,
    save_split_manifest, validate_split_alignment,
)


@dataclass
class PreparedData:
    """Training-fitted inputs and loaders; full and usable splits stay explicit."""

    artifacts: SCINArtifacts
    splits: dict[str, np.ndarray]
    usable_splits: dict[str, np.ndarray]
    encoder: MetadataEncoder
    image_store: ImageStore
    loaders: dict[str, DataLoader]
    report: dict


def select_device(requested: str = "auto") -> torch.device:
    """Select an available accelerator or CPU, rejecting unavailable requests."""
    if requested == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    device = torch.device(requested)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable.")
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS was requested but is unavailable.")
    if device.type not in {"cpu", "cuda", "mps"}:
        raise ValueError("Supported devices are auto, cpu, cuda and mps.")
    return device


def prepare_data(
    artifact_path: str | Path, output_dir: str | Path, *, seed: int = 42,
    batch_size: int = 32, image_size: int = 224, num_workers: int = 0,
    image_root: str | Path | None = None, arrow_cache: str | Path | None = None,
    exclude_missing_primary: bool = False,
) -> PreparedData:
    """Split groups first, fit the train encoder, and verify primary references.

    Missing primary images require an explicit exclusion policy. Their original
    rows and split membership remain recorded; no secondary-image substitution
    or cleaned-artifact modification occurs. Validation/test never fit encoding.
    Existing experiment outputs are rejected instead of silently overwritten.
    """
    if batch_size < 1 or num_workers < 0:
        raise ValueError("batch_size must be positive and num_workers nonnegative.")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Choose an empty/new experiment output directory.")
    artifacts = load_cleaned_artifact(artifact_path)
    splits = grouped_split(artifacts.case_ids, seed)
    validate_split_alignment(artifacts, splits)
    eligible, excluded = primary_image_eligibility(artifacts)
    if excluded and not exclude_missing_primary:
        raise ValueError(
            f"{len(excluded)} case(s) lack image_1. Set exclude_missing_primary=True "
            "to record explicit training/evaluation exclusions; source data stays unchanged."
        )
    usable = {name: rows[np.isin(rows, eligible)] for name, rows in splits.items()}
    if any(not len(rows) for rows in usable.values()):
        raise ValueError("Each split requires at least one usable primary image.")
    encoder = MetadataEncoder().fit(artifacts.metadata.iloc[usable["train"]])
    encoded = encoder.transform(artifacts.metadata)
    store = ImageStore(image_root=image_root, arrow_cache=arrow_cache)
    try:
        store.validate(artifacts, indices=eligible)
        transform = ImagePreprocessor(image_size)
        generator = torch.Generator().manual_seed(seed)
        loaders = {
            name: DataLoader(
                SCINDataset(artifacts, rows, encoded, store, transform),
                batch_size=batch_size, shuffle=name == "train", num_workers=num_workers,
                generator=generator if name == "train" else None,
                # No dropped cases: soft distributions stay aligned even in a short final batch.
                drop_last=False,
            ) for name, rows in usable.items()
        }
        report = {
            "artifact_sha256": hashlib.sha256(Path(artifact_path).read_bytes()).hexdigest(),
            "total_labeled_rows": len(artifacts.metadata),
            "num_classes": artifacts.num_classes,
            "seed": seed, "primary_image_column": "image_1_path",
            "split_rows": {name: len(rows) for name, rows in splits.items()},
            "usable_split_rows": {name: len(rows) for name, rows in usable.items()},
            "excluded_missing_primary": excluded,
            "exclusion_explicitly_enabled": exclude_missing_primary,
            "metadata_dim": encoder.output_dim, "batch_size": batch_size,
            "num_workers": num_workers, "image_size": image_size,
            "image_source": "verified original filenames/local SCIN Arrow cache",
        }
        output.mkdir(parents=True, exist_ok=True)
        save_split_manifest(artifacts, splits, output / "split_manifest.json")
        encoder.save(output / "metadata_encoder.json")
        (output / "data_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        return PreparedData(artifacts, splits, usable, encoder, store, loaders, report)
    except Exception:
        store.close()
        raise
