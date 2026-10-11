"""Aligned SCIN artifacts, train-only metadata encoding and primary-image loading.

This module consumes the existing cleaned artifact without selecting labels or
repeating EDA. Source images remain unchanged; resizing occurs only in memory.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageOps
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import OneHotEncoder
from torch.utils.data import Dataset
from torchvision.transforms import functional as TF

CATEGORICAL_COLUMNS = (
    "age_group", "sex_at_birth", "fitzpatrick_skin_type",
    "related_category", "condition_duration",
)
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True)
class SCINArtifacts:
    """Existing aligned data, with labels preserved as soft distributions."""

    metadata: pd.DataFrame
    images: pd.DataFrame
    labels: np.ndarray
    classes: tuple[str, ...]

    @property
    def case_ids(self) -> np.ndarray:
        """Return canonical group identifiers without changing source frames."""
        return self.images["case_id"].astype(str).to_numpy()

    @property
    def num_classes(self) -> int:
        """Return the unchanged target-class count."""
        return len(self.classes)


def validate_artifacts(artifacts: SCINArtifacts) -> None:
    """Reject ambiguous alignment or invalid targets, never silently repair Y.

    X frames must keep identical original row indices; ndarray Y follows that
    same row order as exported by the EDA notebook. That provenance cannot be
    reconstructed if an external tool has already reordered only the ndarray.
    """
    metadata, images, labels = artifacts.metadata, artifacts.images, artifacts.labels
    if not isinstance(metadata, pd.DataFrame) or not isinstance(images, pd.DataFrame):
        raise ValueError("X_metadata and X_images must be pandas DataFrames.")
    if not metadata.index.equals(images.index) or not metadata.index.is_unique:
        raise ValueError("Metadata/image indices are not uniquely aligned.")
    if not metadata.columns.is_unique or not images.columns.is_unique:
        raise ValueError("Artifact frames contain duplicate column names.")
    if not {"case_id", "image_1_path"}.issubset(images.columns):
        raise ValueError("X_images must contain case_id and image_1_path.")
    if images["case_id"].isna().any() or images["case_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Every sample needs a nonempty case_id for grouping.")
    if not set(CATEGORICAL_COLUMNS).issubset(metadata.columns):
        raise ValueError("Metadata lacks one or more required categorical features.")
    if not len(metadata) or labels.ndim != 2 or labels.shape != (len(metadata), len(artifacts.classes)):
        raise ValueError("Metadata, image rows, class mapping and Y have incompatible shapes.")
    if len(images) != len(metadata) or not artifacts.classes or len(set(artifacts.classes)) != len(artifacts.classes):
        raise ValueError("Image rows or target-class mapping are invalid.")
    if any(not isinstance(name, str) or not name for name in artifacts.classes):
        raise ValueError("Target-class names must be nonempty strings.")
    if not np.issubdtype(labels.dtype, np.number) or not np.isfinite(labels).all():
        raise ValueError("Y must contain finite numeric probabilities.")
    if (labels < 0).any() or (labels > 1).any() or not np.allclose(labels.sum(axis=1), 1, atol=1e-6):
        raise ValueError("Each unchanged soft-label Y row must sum to one.")


def load_cleaned_artifact(
    path: str | Path, *, expected_cases: int | None = None,
    expected_classes: int | None = None,
) -> SCINArtifacts:
    """Load a trusted local EDA pickle and validate aligned artifacts.

    Pickle can execute code: load only the repository's locally exported file.
    Optional expected sizes help a notebook reject an unintended dataset.
    """
    cleaned = pd.read_pickle(path)
    required = {"X_metadata", "X_images", "Y", "target_classes"}
    if not isinstance(cleaned, Mapping) or not required.issubset(cleaned):
        raise ValueError("Cleaned artifact lacks X_metadata, X_images, Y or target_classes.")
    artifacts = SCINArtifacts(
        cleaned["X_metadata"], cleaned["X_images"],
        np.asarray(cleaned["Y"]), tuple(cleaned["target_classes"]),
    )
    validate_artifacts(artifacts)
    if expected_cases is not None and len(artifacts.metadata) != expected_cases:
        raise ValueError(f"Expected {expected_cases} cases, found {len(artifacts.metadata)} rows.")
    if expected_classes is not None and artifacts.num_classes != expected_classes:
        raise ValueError(f"Expected {expected_classes} classes, found {artifacts.num_classes}.")
    return artifacts


def primary_image_eligibility(artifacts: SCINArtifacts) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Report primary-image availability without altering or relabeling the data.

    This only checks the exported reference, not whether bytes can be decoded.
    Using returned eligible rows must be an explicit, documented experiment
    choice; ImageStore.validate still verifies actual source availability.
    """
    validate_artifacts(artifacts)
    paths = artifacts.images["image_1_path"]
    available = paths.notna() & paths.astype(str).str.strip().ne("")
    exclusions = [
        {"position": int(position), "source_index": str(artifacts.images.index[position]),
         "case_id": str(artifacts.images.iloc[position]["case_id"]),
         "reason": "Missing image_1_path; no image_2/image_3 substitution."}
        for position in np.flatnonzero(~available.to_numpy())
    ]
    return np.flatnonzero(available.to_numpy()), exclusions


def grouped_split(case_ids: Sequence[Any], seed: int = 42) -> dict[str, np.ndarray]:
    """Create reproducible approximately 70/15/15 splits by whole case groups.

    Fractions are by unique case group, so repeated cases can change row ratios.
    No diagnosis-driven stratification or label selection is performed.
    """
    raw = np.asarray(case_ids)
    if raw.ndim != 1 or pd.isna(raw).any():
        raise ValueError("case_ids must be a one-dimensional nonmissing sequence.")
    groups = raw.astype(str)
    if np.any(np.char.strip(groups) == "") or len(np.unique(groups)) < 7:
        raise ValueError("At least seven nonempty case groups are needed for three splits.")
    positions = np.arange(len(groups), dtype=np.int64)
    train, held = next(GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=seed).split(positions, groups=groups))
    val_local, test_local = next(GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=seed + 1).split(held, groups=groups[held]))
    return {"train": np.sort(train), "val": np.sort(held[val_local]), "test": np.sort(held[test_local])}


def validate_split_alignment(artifacts: SCINArtifacts, splits: Mapping[str, Sequence[int]]) -> None:
    """Verify all rows occur exactly once and groups never cross split boundaries."""
    validate_artifacts(artifacts)
    if set(splits) != {"train", "val", "test"}:
        raise ValueError("Splits must contain exactly train, val and test.")
    groups: dict[str, set[str]] = {}
    combined = []
    for name, indices in splits.items():
        positions = np.asarray(indices)
        if positions.ndim != 1 or not np.issubdtype(positions.dtype, np.integer) or not len(positions):
            raise ValueError(f"{name} positions must be a nonempty integer vector.")
        if (positions < 0).any() or (positions >= len(artifacts.metadata)).any():
            raise ValueError(f"{name} contains out-of-range row positions.")
        groups[name] = set(artifacts.case_ids[positions])
        combined.extend(positions.tolist())
    if sorted(combined) != list(range(len(artifacts.metadata))):
        raise ValueError("Each source row must appear in exactly one split.")
    if groups["train"] & groups["val"] or groups["train"] & groups["test"] or groups["val"] & groups["test"]:
        raise ValueError("case_id leakage across splits.")


def save_split_manifest(artifacts: SCINArtifacts, splits: Mapping[str, Sequence[int]], path: str | Path) -> None:
    """Save row positions plus case/image identifiers for reproducible alignment."""
    validate_split_alignment(artifacts, splits)
    manifest = {
        name: [
            {"position": int(i), "source_index": str(artifacts.metadata.index[i]),
             "case_id": str(artifacts.images.iloc[i]["case_id"]),
             "image_1_path": str(artifacts.images.iloc[i]["image_1_path"])}
            for i in indices
        ] for name, indices in splits.items()
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


class MetadataEncoder:
    """Keep processed binary features and fit categorical vocabulary on train only.

    The portable JSON artifact records ordered columns/categories instead of
    executable pickle. Missing categories map to a sentinel; unseen categories
    become an all-zero category block via handle_unknown='ignore'. Missing binary
    values are rejected rather than guessing that unknown symptoms mean absent.
    """

    def __init__(self) -> None:
        self.binary_columns: list[str] = []
        self.encoder: OneHotEncoder | None = None

    @staticmethod
    def _categories(frame: pd.DataFrame) -> pd.DataFrame:
        """Provide a consistent string representation without changing the frame."""
        return frame.loc[:, list(CATEGORICAL_COLUMNS)].fillna("__MISSING__").astype(str)

    def _check_frame(self, frame: pd.DataFrame) -> None:
        """Fail on schema changes or invalid already-encoded binary inputs."""
        expected = set(self.binary_columns) | set(CATEGORICAL_COLUMNS)
        if not isinstance(frame, pd.DataFrame) or set(frame.columns) != expected or not frame.columns.is_unique:
            raise ValueError("Metadata must provide every saved feature column exactly once.")
        binary = frame.loc[:, self.binary_columns].to_numpy()
        if not np.isin(binary, [0, 1]).all():
            raise ValueError("Already-encoded binary features must contain only 0 or 1.")

    def fit(self, frame: pd.DataFrame) -> "MetadataEncoder":
        """Learn only training categories; caller must pass train rows, not all data."""
        if not isinstance(frame, pd.DataFrame) or not len(frame) or not set(CATEGORICAL_COLUMNS).issubset(frame.columns):
            raise ValueError("Fit needs nonempty training metadata with all five categorical columns.")
        self.binary_columns = [name for name in frame.columns if name not in CATEGORICAL_COLUMNS]
        self._check_frame(frame)
        self.encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32)
        self.encoder.fit(self._categories(frame))
        return self

    @property
    def output_dim(self) -> int:
        """Return network metadata width after fitting/loading."""
        if self.encoder is None:
            raise ValueError("Metadata encoder has not been fitted.")
        return len(self.binary_columns) + sum(len(values) for values in self.encoder.categories_)

    def transform(self, frame: pd.DataFrame | Mapping[str, Any]) -> np.ndarray:
        """Encode a frame or one inference metadata mapping in saved column order."""
        if self.encoder is None:
            raise ValueError("Metadata encoder has not been fitted.")
        if isinstance(frame, Mapping):
            frame = pd.DataFrame([frame])
        self._check_frame(frame)
        binary = frame.loc[:, self.binary_columns].to_numpy(dtype=np.float32)
        categorical = self.encoder.transform(self._categories(frame))
        return np.concatenate((binary, categorical), axis=1).astype(np.float32, copy=False)

    def save(self, path: str | Path) -> None:
        """Save non-executable train-fitted schema/categories for app inference."""
        if self.encoder is None:
            raise ValueError("Metadata encoder has not been fitted.")
        payload = {"format_version": 1, "binary_columns": self.binary_columns,
                   "categorical_columns": list(CATEGORICAL_COLUMNS),
                   "categories": [values.tolist() for values in self.encoder.categories_]}
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MetadataEncoder":
        """Reconstruct exactly the saved schema without fitting on inference data."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format_version") != 1 or payload.get("categorical_columns") != list(CATEGORICAL_COLUMNS):
            raise ValueError("Unsupported metadata encoder artifact.")
        categories = payload.get("categories")
        binary = payload.get("binary_columns")
        if not isinstance(binary, list) or any(not isinstance(x, str) for x in binary) or len(set(binary)) != len(binary) or set(binary) & set(CATEGORICAL_COLUMNS):
            raise ValueError("Invalid binary feature schema.")
        if not isinstance(categories, list) or len(categories) != len(CATEGORICAL_COLUMNS) or any(not values or any(not isinstance(x, str) for x in values) or len(set(values)) != len(values) for values in categories):
            raise ValueError("Invalid saved categorical vocabulary.")
        instance = cls()
        instance.binary_columns = binary
        instance.encoder = OneHotEncoder(categories=categories, handle_unknown="ignore", sparse_output=False, dtype=np.float32)
        # sklearn needs fitted internal bookkeeping. Explicit categories prevent
        # this synthetic row from learning any new value or accessing real data.
        example = pd.DataFrame([[values[0] for values in categories]], columns=CATEGORICAL_COLUMNS)
        instance.encoder.fit(example)
        return instance


class ImagePreprocessor:
    """Deterministic RGB letterbox transform shared by training and inference."""

    def __init__(self, size: int = 224) -> None:
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("Image size must be a positive integer.")
        self.size = size

    def __call__(self, source: Any) -> torch.Tensor:
        """Decode a PIL image, path, bytes or file-like object, then normalize.

        Raises Pillow/OSError for malformed inputs; no placeholder image is used.
        EXIF orientation is applied before resizing while originals stay intact.
        """
        if isinstance(source, Image.Image):
            image = ImageOps.exif_transpose(source).convert("RGB")
        else:
            if isinstance(source, (bytes, bytearray, memoryview)):
                source = io.BytesIO(bytes(source))
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        scale = min(self.size / image.width, self.size / image.height)
        dimensions = (max(1, min(self.size, round(image.width * scale))), max(1, min(self.size, round(image.height * scale))))
        image = image.resize(dimensions, Image.Resampling.BILINEAR)
        # A neutral constant pad preserves geometry without adding fake lesions.
        canvas = Image.new("RGB", (self.size, self.size), (0, 0, 0))
        canvas.paste(image, ((self.size - image.width) // 2, (self.size - image.height) // 2))
        return TF.normalize(TF.to_tensor(canvas), IMAGENET_MEAN, IMAGENET_STD)


class ImageStore:
    """Read original primary images from files or an existing local Arrow cache.

    Arrow is memory-mapped, not downloaded or copied. The small index binds
    case_id to its recorded image filename; row-position exports are deliberately
    not assumed to match because that can silently train against the wrong Y.
    """

    def __init__(self, image_root: str | Path | None = None, arrow_cache: str | Path | None = None) -> None:
        self.image_root = Path(image_root).expanduser().resolve() if image_root else None
        default = Path.home() / ".cache/huggingface/datasets/google___scin"
        self.arrow_cache = Path(arrow_cache).expanduser() if arrow_cache else default
        self._index: dict[str, tuple[int, int, str]] | None = None
        self._batches: list[Any] = []
        self._sources: list[Any] = []

    def _file(self, image_path: str) -> Path | None:
        """Resolve a source filename inside the explicit root, rejecting traversal."""
        if self.image_root is None:
            return None
        path = (self.image_root / image_path).resolve()
        if not path.is_relative_to(self.image_root):
            raise ValueError("Image path escapes the configured source directory.")
        return path if path.is_file() else None

    def _build_index(self) -> None:
        """Index Arrow IDs/paths without copying image payloads into Python."""
        if self._index is not None:
            return
        import pyarrow as pa
        import pyarrow.ipc as ipc
        paths = [self.arrow_cache] if self.arrow_cache.is_file() else sorted(self.arrow_cache.rglob("*.arrow"))
        if not paths:
            raise FileNotFoundError("No original image files/local SCIN Arrow cache found. Set image_root or arrow_cache; no download is attempted.")
        index: dict[str, tuple[int, int, str]] = {}
        try:
            for path in paths:
                source = pa.memory_map(str(path), "r")
                self._sources.append(source)
                try:
                    reader = ipc.open_stream(source)
                    batches = reader
                except pa.ArrowInvalid:
                    source.seek(0)
                    reader = ipc.open_file(source)
                    batches = (reader.get_batch(i) for i in range(reader.num_record_batches))
                for batch in batches:
                    if not {"case_id", "image_1_path"}.issubset(batch.schema.names):
                        raise ValueError(f"Arrow file lacks SCIN identifiers: {path.name}")
                    column = batch.column(batch.schema.get_field_index("image_1_path"))
                    if not pa.types.is_struct(column.type) or "path" not in [field.name for field in column.type]:
                        raise ValueError("SCIN Arrow image_1_path must be a bytes/path struct.")
                    ids = batch.column(batch.schema.get_field_index("case_id")).to_pylist()
                    filenames = column.field("path").to_pylist()
                    batch_id = len(self._batches)
                    self._batches.append(batch)
                    for row, (case_id, filename) in enumerate(zip(ids, filenames)):
                        key = str(case_id)
                        if key in index:
                            raise ValueError("Multiple local Arrow rows/versions contain the same case_id; select one cache version directory.")
                        index[key] = (batch_id, row, filename)
            self._index = index
        except Exception:
            self.close()
            raise

    def _entry(self, case_id: str, image_path: str) -> tuple[Any, int]:
        """Require both case identity and original filename to match cache data."""
        self._build_index()
        entry = self._index.get(str(case_id))
        if entry is None:
            raise FileNotFoundError(f"No cached primary image for case_id {case_id}.")
        batch_id, row, filename = entry
        if not filename or Path(filename).name != Path(image_path).name:
            raise ValueError(f"Primary-image filename mismatch for case_id {case_id}.")
        return self._batches[batch_id], row

    def read(self, case_id: str, image_path: str) -> bytes:
        """Return one primary original's bytes; fail on absent or mismatched data."""
        path = self._file(str(image_path))
        if path is not None:
            return path.read_bytes()
        batch, row = self._entry(str(case_id), str(image_path))
        value = batch.column(batch.schema.get_field_index("image_1_path"))[row].as_py()
        if value and value.get("bytes"):
            return value["bytes"]
        external = self._file(value.get("path", "")) if value else None
        if external is not None:
            return external.read_bytes()
        raise FileNotFoundError(f"Primary image has no embedded bytes/local file for case_id {case_id}.")

    def validate(self, artifacts: SCINArtifacts, indices: Sequence[int] | None = None) -> None:
        """Check primary references before training without decoding all images.

        Missing image_1 is a training-eligibility issue, not license to reclean
        or alter the original artifact. Callers must explicitly record any row
        excluded from the primary-image-only experiment, then pass those eligible
        positions here. With no positions, every original row is checked.
        """
        positions = range(len(artifacts.images)) if indices is None else indices
        case_ids = artifacts.case_ids
        for position in positions:
            case_id = case_ids[position]
            image_path = artifacts.images.iloc[position]["image_1_path"]
            if pd.isna(image_path) or not str(image_path).strip():
                raise FileNotFoundError(f"Primary image_1_path is missing for case_id {case_id}; record an explicit eligibility exclusion or supply the original image, never substitute image_2.")
            if self._file(str(image_path)) is not None:
                continue
            import pyarrow.compute as pc
            batch, row = self._entry(case_id, str(image_path))
            column = batch.column(batch.schema.get_field_index("image_1_path"))
            payload = column.field("bytes").slice(row, 1)
            length = pc.binary_length(payload)[0].as_py()
            if length is None or length == 0:
                raise FileNotFoundError(f"Primary image has no embedded bytes for case_id {case_id}.")

    def close(self) -> None:
        """Release memory maps; a subsequent read rebuilds the read-only index."""
        self._batches.clear()
        for source in self._sources:
            source.close()
        self._sources.clear()
        self._index = None

    def __getstate__(self) -> dict[str, Any]:
        """Let spawned DataLoader workers reopen maps instead of pickling 13GB."""
        state = self.__dict__.copy()
        state.update(_index=None, _batches=[], _sources=[])
        return state


class SCINDataset(Dataset):
    """One aligned primary image, encoded metadata and soft target per sample."""

    def __init__(
        self, artifacts: SCINArtifacts, indices: Sequence[int],
        encoded_metadata: np.ndarray, image_store: ImageStore,
        transform: ImagePreprocessor | None = None,
    ) -> None:
        validate_artifacts(artifacts)
        positions = np.asarray(indices)
        if positions.ndim != 1 or not np.issubdtype(positions.dtype, np.integer) or (positions < 0).any() or (positions >= len(artifacts.metadata)).any():
            raise ValueError("Dataset indices must be valid integer row positions.")
        selected_paths = artifacts.images.iloc[positions]["image_1_path"]
        if selected_paths.isna().any() or selected_paths.astype(str).str.strip().eq("").any():
            raise FileNotFoundError("Selected rows lack image_1_path; record an explicit primary-image eligibility exclusion before constructing the dataset.")
        encoded = np.asarray(encoded_metadata, dtype=np.float32)
        if encoded.ndim != 2 or len(encoded) != len(artifacts.metadata) or not np.isfinite(encoded).all():
            raise ValueError("Encoded metadata must align with all original artifact rows.")
        self.artifacts = artifacts
        self.indices = positions.astype(np.int64, copy=True)
        self.encoded_metadata = encoded
        self.image_store = image_store
        self.transform = transform or ImagePreprocessor()

    def __len__(self) -> int:
        """Return the selected row count."""
        return len(self.indices)

    def __getitem__(self, index: int) -> dict[str, Any]:
        """Load just image_1 and preserve one shared source position for all inputs."""
        position = int(self.indices[index])
        image_row = self.artifacts.images.iloc[position]
        case_id = str(image_row["case_id"])
        if pd.isna(image_row["image_1_path"]) or not str(image_row["image_1_path"]).strip():
            raise FileNotFoundError(f"Primary image_1_path is missing for case_id {case_id}.")
        raw = self.image_store.read(case_id, str(image_row["image_1_path"]))
        return {
            "image": self.transform(raw),
            "metadata": torch.from_numpy(self.encoded_metadata[position].copy()),
            "target": torch.tensor(self.artifacts.labels[position], dtype=torch.float32),
            "case_id": case_id,
        }
