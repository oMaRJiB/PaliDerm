"""Model-independent image and tabular inference transforms.

These utilities consume an explicit saved preprocessing contract. They do not
train encoders, infer symptoms from prose, or guess mappings between the app's
questionnaire and another dataset's fields. No Torch/model imports are needed.
"""

from __future__ import annotations

import io
import json
import math
import pickle
from numbers import Real
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageOps


def _number(value: Any, field: str, *, binary: bool = False) -> float:
    """Normalize finite numeric scalars without including their values in errors."""
    if (isinstance(value, (bool, np.bool_)) and not binary) or not isinstance(value, (Real, str, np.bool_)):
        raise ValueError(f"Invalid numeric metadata field: {field}.")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"Invalid numeric metadata field: {field}.") from None
    if not math.isfinite(result) or (binary and result not in (0.0, 1.0)):
        raise ValueError(f"Invalid {'binary' if binary else 'numeric'} metadata field: {field}.")
    return result


def _missing(value: Any) -> bool:
    """Treat absent/blank inputs as missing; NaN is invalid, never silently filled."""
    return value is None or (isinstance(value, str) and not value.strip())


def _names(value: Any, description: str) -> list[str]:
    """Validate a unique, explicitly ordered list of field names."""
    if (not isinstance(value, list) or
            any(not isinstance(name, str) or not name.strip() for name in value) or
            len(set(value)) != len(value)):
        raise ValueError(f"Invalid {description}.")
    return value


def _category(value: Any, field: str) -> str:
    """Match saved string vocabularies while rejecting nonfinite/compound inputs."""
    if not isinstance(value, (str, Real, bool, np.bool_)):
        raise ValueError(f"Invalid categorical metadata field: {field}.")
    if isinstance(value, Real) and not math.isfinite(float(value)):
        raise ValueError(f"Invalid categorical metadata field: {field}.")
    return str(value)


class ImagePipeline:
    """Decode RGB images, resize/pad in memory and return float32 CHW arrays.

    Config keys: size (integer or [height, width]), resize (pad/pillow_pad/stretch), scale
    (positive divisor, default 255), and three-channel mean/std. Defaults use
    224-square input, centered black padding and ImageNet normalization. Originals
    and EXIF metadata are never modified; EXIF orientation is applied to the copy.
    """

    def __init__(self, config: Mapping[str, Any] | None = None):
        if config is not None and not isinstance(config, Mapping):
            raise ValueError("Image preprocessing config must be a mapping.")
        config = dict(config or {})
        size = config.get("size", 224)
        dimensions = [size, size] if type(size) is int else size
        if (not isinstance(dimensions, (list, tuple)) or len(dimensions) != 2 or
                any(type(item) is not int or item < 1 for item in dimensions)):
            raise ValueError("Image size must be positive height/width integers.")
        self.height, self.width = dimensions
        self.resize = config.get("resize", "pad")
        if not isinstance(self.resize, str) or self.resize not in {"pad", "pillow_pad", "stretch"}:
            raise ValueError("Image resize must be pad, pillow_pad or stretch.")
        self.scale = _number(config.get("scale", 255.0), "image scale")
        if self.scale <= 0:
            raise ValueError("Image scale must be positive.")
        vectors = []
        for name, default in (("mean", [0.485, 0.456, 0.406]), ("std", [0.229, 0.224, 0.225])):
            values = config.get(name, default)
            if not isinstance(values, (list, tuple)) or len(values) != 3:
                raise ValueError(f"Image {name} must have three finite channels.")
            vectors.append(np.asarray([_number(value, f"image {name}") for value in values], dtype=np.float32))
        self.mean, self.std = (vector[:, None, None] for vector in vectors)
        if not np.isfinite(self.mean).all() or not np.isfinite(self.std).all() or np.any(self.std <= 0):
            raise ValueError("Image mean/std must be finite with positive standard deviations.")

    def __call__(self, source: Any) -> np.ndarray:
        """Accept a PIL image, local path, encoded bytes or readable image stream.

        Raises ValueError for decoding or transform errors; messages deliberately
        omit file paths and input content because callers may log failures.
        """
        try:
            if isinstance(source, Image.Image):
                image = ImageOps.exif_transpose(source).convert("RGB")
            else:
                if isinstance(source, (bytes, bytearray, memoryview)):
                    source = io.BytesIO(bytes(source))
                with Image.open(source) as opened:
                    image = ImageOps.exif_transpose(opened).convert("RGB")
            if image.width < 1 or image.height < 1:
                raise ValueError("Image dimensions must be positive.")
            if self.resize == "stretch":
                image = image.resize((self.width, self.height), Image.Resampling.BILINEAR)
            elif self.resize == "pillow_pad":
                # Some saved models used Pillow's own contain/pad rounding.
                # Keep it distinct from the original SCIN manual letterbox.
                image = ImageOps.pad(image, (self.width, self.height),
                                     method=Image.Resampling.BILINEAR, color=(0, 0, 0))
            else:
                scale = min(self.width / image.width, self.height / image.height)
                dimensions = (max(1, min(self.width, round(image.width * scale))),
                              max(1, min(self.height, round(image.height * scale))))
                resized = image.resize(dimensions, Image.Resampling.BILINEAR)
                image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
                image.paste(resized, ((self.width - resized.width) // 2,
                                     (self.height - resized.height) // 2))
            values = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)
            values = (values / self.scale - self.mean) / self.std
            if not np.isfinite(values).all():
                raise ValueError("Nonfinite image transform.")
            return np.ascontiguousarray(values, dtype=np.float32)
        except (OSError, ValueError, TypeError, SyntaxError, Image.DecompressionBombError):
            raise ValueError("Unable to decode or preprocess dermatology image.") from None


class MetadataPipeline:
    """Apply saved ordered metadata encoding without training or implicit NLP.

    Config accepts an encoder JSON/pickle path relative to base_dir, or features
    descriptors with name/kind and optional categories/mean/std/default. Aliases
    map expected names to raw names; defaults name explicit imputation values.
    SCIN JSON binary fields are mandatory unless a configured default exists.
    Generic numeric/binary missing values become zero with warnings; categorical
    unknowns become zero blocks. Pickles require explicit trust and are never a
    fallback for JSON/configuration failures.
    """

    def __init__(self, config: Mapping[str, Any] | None, base_dir: Path, trust_pickle: bool = False):
        if config is not None and not isinstance(config, Mapping):
            raise ValueError("Metadata preprocessing config must be a mapping.")
        self.config = dict(config or {})
        self.aliases = self.config.get("aliases", {})
        self.defaults = self.config.get("defaults", {})
        if (not isinstance(self.aliases, dict) or
                any(not isinstance(k, str) or not k.strip() or
                    not isinstance(v, str) or not v.strip() for k, v in self.aliases.items()) or
                not isinstance(self.defaults, dict) or
                any(not isinstance(name, str) or not name.strip() for name in self.defaults)):
            raise ValueError("Invalid metadata aliases or defaults.")
        self.output_dim: int | None = None
        self.features: list[dict[str, Any]] = []
        self.saved_schema = False
        self.transformer = None
        self.feature_names: list[str] = []
        encoder = self.config.get("encoder")
        if encoder is not None:
            if not isinstance(encoder, str) or not encoder.strip():
                raise ValueError("Metadata encoder must name a local artifact.")
            base = Path(base_dir).resolve()
            path = (base / encoder).resolve()
            if not path.is_relative_to(base):
                raise ValueError("Metadata encoder must remain inside the model directory.")
            if path.suffix.lower() in {".pkl", ".pickle"}:
                self._load_pickle(path, trust_pickle)
                return
            if path.suffix.lower() != ".json":
                raise ValueError("Metadata encoder must be JSON or an explicitly trusted pickle.")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                raise ValueError("Unable to load metadata encoder JSON.") from None
            if not isinstance(payload, dict):
                raise ValueError("Invalid metadata encoder JSON contract.")
            if "binary_columns" in payload:
                self._load_saved_schema(payload)
                return
            descriptors = payload.get("features")
            if descriptors is None:
                raise ValueError("Metadata encoder JSON has no supported feature contract.")
        else:
            descriptors = self.config.get("features")
        if descriptors is not None:
            self._load_features(descriptors)

    def _load_saved_schema(self, payload: dict[str, Any]) -> None:
        """Rebuild SCIN one-hot order directly, without importing training code."""
        if payload.get("format_version", 1) != 1:
            raise ValueError("Unsupported metadata encoder JSON version.")
        binary = _names(payload.get("binary_columns"), "saved binary columns")
        categorical = _names(payload.get("categorical_columns"), "saved categorical columns")
        categories = payload.get("categories")
        if (set(binary) & set(categorical) or not isinstance(categories, list) or
                len(categories) != len(categorical)):
            raise ValueError("Invalid saved metadata category schema.")
        self.saved_schema = True
        self._load_features(
            [{"name": name, "kind": "binary"} for name in binary] +
            [{"name": name, "kind": "categorical", "categories": values}
             for name, values in zip(categorical, categories)]
        )

    def _load_features(self, descriptors: Any) -> None:
        """Validate descriptors once; preserve their explicitly declared ordering."""
        if not isinstance(descriptors, list) or not descriptors:
            raise ValueError("Metadata features must be a nonempty descriptor list.")
        names = []
        features = []
        width = 0
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                raise ValueError("Invalid metadata feature descriptor.")
            feature = dict(descriptor)
            name, kind = feature.get("name"), feature.get("kind")
            if (not isinstance(name, str) or not name.strip() or not isinstance(kind, str) or
                    kind not in {"numeric", "binary", "categorical"}):
                raise ValueError("Invalid metadata feature name or kind.")
            names.append(name)
            if kind == "categorical":
                categories = feature.get("categories")
                if (not isinstance(categories, list) or not categories or
                        any(not isinstance(item, str) for item in categories) or
                        len(set(categories)) != len(categories)):
                    raise ValueError(f"Invalid category vocabulary for field: {name}.")
                width += len(categories)
            else:
                width += 1
                if kind == "numeric":
                    feature["mean"] = _number(feature.get("mean", 0.0), name)
                    feature["std"] = _number(feature.get("std", 1.0), name)
                    if feature["std"] <= 0:
                        raise ValueError(f"Invalid standard deviation for field: {name}.")
            features.append(feature)
        _names(names, "metadata feature order")
        self.features = features
        self.output_dim = width

    def _load_pickle(self, path: Path, trusted: bool) -> None:
        """Load executable sklearn artifacts only after an explicit trust decision."""
        if trusted is not True:
            raise ValueError("Pickle metadata encoders require explicit trust_pickle=True.")
        try:
            with path.open("rb") as stream:
                transformer = pickle.load(stream)
            if not callable(getattr(transformer, "transform", None)):
                raise ValueError("Not a transformer.")
            saved_names = getattr(transformer, "feature_names_in_", None)
            saved_names = list(saved_names) if saved_names is not None else None
            configured_names = self.config.get("feature_names")
            if saved_names is not None and configured_names is not None and saved_names != configured_names:
                raise ValueError("Input order mismatch.")
            self.feature_names = _names(saved_names if saved_names is not None else configured_names,
                                        "trusted encoder feature order")
            if not self.feature_names:
                raise ValueError("No feature order.")
            self.transformer = transformer
            output_names = getattr(transformer, "get_feature_names_out", None)
            if callable(output_names):
                try:
                    self.output_dim = len(output_names(self.feature_names))
                except (ValueError, TypeError, AttributeError):
                    self.output_dim = None
        except Exception:
            # Sklearn/pickle exceptions can embed input content or filesystem paths.
            raise ValueError("Unable to load trusted metadata encoder or feature order.") from None

    def _merge(self, symptoms: Any, metadata: Any, warnings: list[str]) -> dict[str, Any]:
        """Merge structured sources, rejecting ambiguity instead of picking a winner."""
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ValueError("Patient metadata must be a field mapping.")
        merged = dict(metadata)
        if symptoms is None:
            symptoms = {}
        if isinstance(symptoms, str):
            if symptoms.strip():
                warnings.append("Free-text symptoms were not encoded; structured feature values are required.")
            symptoms = {}
        if not isinstance(symptoms, Mapping):
            raise ValueError("Symptoms must be text or a structured field mapping.")
        if any(not isinstance(name, str) or not name.strip() for name in (*merged, *symptoms)):
            raise ValueError("Metadata field names must be nonempty strings.")
        for name, value in symptoms.items():
            if name in merged and not _missing(merged[name]) and not _missing(value):
                try:
                    same = bool(merged[name] == value)
                except (ValueError, TypeError):
                    same = False
                if not same:
                    raise ValueError(f"Conflicting structured metadata field: {name}.")
            if name not in merged or _missing(merged[name]):
                merged[name] = value
        return merged

    def _resolve(self, feature: dict[str, Any], raw: dict[str, Any], warnings: list[str]) -> Any:
        """Apply explicit aliases/defaults while recording every imputed field."""
        name = feature["name"]
        alias = self.aliases.get(name, name)
        value = raw.get(alias)
        direct = raw.get(name)
        if alias != name and not _missing(value) and not _missing(direct):
            try:
                same = bool(value == direct)
            except (ValueError, TypeError):
                same = False
            if not same:
                raise ValueError(f"Conflicting aliased metadata field: {name}.")
        if _missing(value) and not _missing(direct):
            value = direct
        if _missing(value) and (name in self.defaults or "default" in feature):
            value = self.defaults[name] if name in self.defaults else feature["default"]
            if not _missing(value):
                warnings.append(f"Used configured default for metadata field: {name}.")
        return value

    def transform(self, symptoms: Any = None, metadata: Any = None) -> tuple[np.ndarray | None, list[str]]:
        """Return one ordered float32 row and nonidentifying preprocessing warnings.

        Raises ValueError for malformed/conflicting values or missing mandatory
        saved fields. Encoder output is never silently resized or renormalized.
        """
        warnings: list[str] = []
        raw = self._merge(symptoms, metadata, warnings)
        if self.transformer is not None:
            return self._transform_pickle(raw, warnings), warnings
        if not self.features:
            warnings.append("No metadata encoder is configured; metadata was not encoded.")
            return None, warnings
        result = []
        for feature in self.features:
            name, kind = feature["name"], feature["kind"]
            value = self._resolve(feature, raw, warnings)
            if _missing(value):
                if self.saved_schema and kind == "binary":
                    raise ValueError(f"Required saved binary metadata field is missing: {name}.")
                warnings.append(f"Missing metadata field: {name}.")
                if kind == "categorical":
                    # SCIN's saved encoder used this explicit missing sentinel.
                    value = "__MISSING__" if self.saved_schema else None
                else:
                    value = 0.0
            if kind == "categorical":
                category = _category(value, name) if value is not None else None
                if category is not None and category not in feature["categories"]:
                    warnings.append(f"Unknown category for metadata field: {name}.")
                result.extend(float(category == item) for item in feature["categories"])
            else:
                number = _number(value, name, binary=kind == "binary")
                result.append((number - feature["mean"]) / feature["std"] if kind == "numeric" else number)
        encoded = np.asarray([result], dtype=np.float32)
        if encoded.shape != (1, self.output_dim) or not np.isfinite(encoded).all():
            raise ValueError("Metadata encoder produced invalid dimensions or nonfinite values.")
        return encoded, warnings

    def _transform_pickle(self, raw: dict[str, Any], warnings: list[str]) -> np.ndarray:
        """Apply a trusted sklearn transform to exactly its saved input order."""
        values = []
        for name in self.feature_names:
            value = self._resolve({"name": name}, raw, warnings)
            if _missing(value):
                raise ValueError(f"Required trusted-encoder metadata field is missing: {name}.")
            # The transform owns categorical semantics, but compound/nonfinite
            # inputs are rejected here before third-party error messages arise.
            _category(value, name)
            values.append(value)
        try:
            import pandas as pd

            frame = pd.DataFrame([values], columns=self.feature_names)
            transformed = self.transformer.transform(frame)
            if callable(getattr(transformed, "toarray", None)):
                transformed = transformed.toarray()
            encoded = np.asarray(transformed, dtype=np.float32)
        except Exception:
            raise ValueError("Trusted metadata encoder could not transform the supplied fields.") from None
        if (encoded.ndim != 2 or encoded.shape[0] != 1 or encoded.shape[1] < 1 or
                not np.isfinite(encoded).all() or
                (self.output_dim is not None and encoded.shape[1] != self.output_dim)):
            raise ValueError("Trusted metadata encoder produced invalid dimensions or nonfinite values.")
        self.output_dim = encoded.shape[1]
        return encoded
