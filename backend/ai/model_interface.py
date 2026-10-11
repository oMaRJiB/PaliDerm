"""Model-agnostic case inference; the application calls load_model/predict_case.

Models and preprocessing files are administrator-provided local artifacts, never
patient uploads. Framework imports are lazy so Flask's unconfigured AI boundary
stays lightweight. No database, training, UI or clinical-decision code lives here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import zipfile
from pathlib import Path
from typing import Any, Mapping


class ModelLoadError(ValueError):
    """A saved model is unsafe, incomplete, unsupported or inconsistent."""


class PredictionError(ValueError):
    """A case or model output violates the saved inference contract."""


class ModelNotLoadedError(RuntimeError):
    """load_model must succeed before a module-level prediction is possible."""


def _json(path: Path) -> dict:
    """Read a UTF-8 configuration object, without executing configuration code."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ModelLoadError("Invalid model configuration JSON.") from None
    if not isinstance(result, dict):
        raise ModelLoadError("Model configuration must be a JSON object.")
    return result


def _hash(path: Path) -> str:
    """Identify exact model/encoder bytes, including models without a version tag."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(directory: Path, name: str) -> Path:
    """Keep referenced artifacts inside their administrator-selected bundle."""
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ModelLoadError("A referenced model artifact is missing or outside its bundle.")
    return path


def _merge(base: dict, updates: Mapping) -> dict:
    """Merge nested configuration while retaining ordered feature/class lists."""
    result = copy.deepcopy(base)
    for key, value in updates.items():
        result[key] = _merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, Mapping) else copy.deepcopy(value)
    return result


def _sidecar(path: Path) -> dict:
    """Prefer a file-specific sidecar over the directory-wide inference config."""
    for candidate in (path.with_name(path.name + ".json"), path.parent / "inference_config.json"):
        if candidate.is_file():
            return _json(candidate)
    return {}


def _checkpoint_config(payload: Mapping) -> dict:
    """Read common saved checkpoint fields; architecture handling stays in adapters."""
    config = {key: payload[key] for key in ("architecture", "target_classes", "model_version", "metadata_dim", "num_classes", "model_kwargs") if key in payload}
    if "image_size" in payload:
        config["image"] = {"size": payload["image_size"]}
    if "image_normalization" in payload:
        config.setdefault("image", {}).update(payload["image_normalization"])
    embedded = payload.get("inference_config", payload.get("config", {}))
    if not isinstance(embedded, Mapping):
        raise ModelLoadError("Checkpoint inference configuration must be a mapping.")
    return _merge(config, embedded)


class TorchAdapter:
    """Execute TorchScript or a registered state-dict architecture in eval mode.

    New architectures subclass this adapter and implement build_model(config).
    Input conventions and artifact settings remain internal to the adapter.
    """

    def __init__(self, path, payload, config, device, scripted_model=None):
        import torch

        self.config = copy.deepcopy(config)
        self.device = torch.device(device)
        if scripted_model is None:
            self.model = self.build_model(self.config)
            state = next((payload[key] for key in ("model_state_dict", "state_dict", "model") if isinstance(payload.get(key), Mapping)), payload)
            if not state or not all(isinstance(key, str) and torch.is_tensor(value) for key, value in state.items()):
                raise ModelLoadError("Checkpoint has no tensor state dictionary.")
            if all(key.startswith("module.") for key in state):
                state = {key[7:]: value for key, value in state.items()}
            try:
                self.model.load_state_dict(state, strict=True)
            except (ValueError, RuntimeError):
                raise ModelLoadError("Weights do not match the declared architecture/configuration.") from None
        else:
            self.model = scripted_model
        self.model.to(self.device).eval()
        if "inputs" not in self.config:
            if scripted_model is not None:
                arguments = list(self.model.forward.schema.arguments)[1:]
                if len(arguments) == 1:
                    self.config["inputs"] = "dict" if "Dict" in str(arguments[0].type) else "image"
                elif len(arguments) == 2:
                    self.config["inputs"] = "image_metadata"
                else:
                    raise ModelLoadError("Declare a supported input convention or register an adapter.")
            else:
                self.config["inputs"] = "image"
        self.activation = None
        if scripted_model is not None:
            # Inspect the returned operation, not intermediate CNN sigmoid gates.
            try:
                operation = list(self.model.inlined_graph.outputs())[0].node().kind()
                self.activation = {"aten::softmax": "softmax", "aten::sigmoid": "sigmoid"}.get(operation)
            except (AttributeError, RuntimeError, IndexError):
                pass

    def build_model(self, config):
        """Require a known architecture instead of guessing topology from weights."""
        raise ModelLoadError("Register an adapter for this state-dict architecture, or export TorchScript.")

    def predict_raw(self, images, metadata, mode):
        """Return batch outputs; stacked-image models own their aggregation."""
        import torch

        if mode == "mean_embeddings":
            raise PredictionError("This adapter does not support mean_embeddings; use mean_probabilities or a compatible adapter.")
        image_tensor = torch.as_tensor(images, dtype=torch.float32, device=self.device)
        meta_tensor = None
        if metadata is not None:
            meta_tensor = torch.as_tensor(metadata, dtype=torch.float32, device=self.device)
            if mode == "mean_probabilities":
                meta_tensor = meta_tensor.expand(len(images), -1)
        with torch.inference_mode():
            inputs = self.config["inputs"]
            if inputs == "image":
                return self.model(image_tensor)
            if inputs == "image_metadata":
                if meta_tensor is None:
                    raise PredictionError("This model requires its saved metadata encoder or ordered feature configuration.")
                return self.model(image_tensor, meta_tensor)
            if inputs == "dict":
                values = {"image": image_tensor}
                if meta_tensor is not None:
                    values["metadata"] = meta_tensor
                return self.model(values)
            raise PredictionError("Unknown model input convention; register a model-specific adapter.")


class MobileNetAdapter(TorchAdapter):
    """Reconstruct the existing SCIN MobileNet without pretrained downloads."""

    def __init__(self, path, payload, config, device, scripted_model=None):
        config = copy.deepcopy(config)
        config.setdefault("inputs", "image_metadata")
        config.setdefault("output", {"type": "softmax_logits"})
        config["image"] = _merge({"size": 224, "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225], "scale": 255, "resize": "pad"}, config.get("image", {}))
        config.setdefault("metadata", {})
        if "encoder" not in config["metadata"] and (path.parent / "metadata_encoder.json").is_file():
            config["metadata"]["encoder"] = "metadata_encoder.json"
        expected_hash = payload.get("metadata_encoder_sha256")
        if expected_hash:
            encoder_name = config["metadata"].get("encoder")
            if not encoder_name or _hash(_artifact(path.parent, encoder_name)) != expected_hash:
                raise ModelLoadError("Checkpoint and training-fitted metadata encoder do not match.")
        super().__init__(path, payload, config, device, scripted_model)

    def build_model(self, config):
        """Architecture dimensions come from saved metadata, never patient inputs."""
        from scin_ml.model import MultimodalDermatologyModel

        kwargs = config.get("model_kwargs", {})
        metadata_dim = config.get("metadata_dim", kwargs.get("metadata_dim"))
        num_classes = config.get("num_classes", kwargs.get("num_classes", len(config.get("target_classes", []))))
        if type(metadata_dim) is not int or metadata_dim < 1 or type(num_classes) is not int or num_classes < 2:
            raise ModelLoadError("MobileNet weights require metadata_dim and num_classes in checkpoint/config.")
        config["metadata_dim"] = metadata_dim
        config["num_classes"] = num_classes
        return MultimodalDermatologyModel(metadata_dim, num_classes, pretrained=False)

    def predict_raw(self, images, metadata, mode):
        """Optionally average projected image embeddings before metadata fusion."""
        if mode != "mean_embeddings":
            return super().predict_raw(images, metadata, mode)
        import torch

        if metadata is None:
            raise PredictionError("This model requires the training-fitted metadata encoder.")
        with torch.inference_mode():
            image_tensor = torch.as_tensor(images, dtype=torch.float32, device=self.device)
            meta_tensor = torch.as_tensor(metadata, dtype=torch.float32, device=self.device)
            features = self.model.avgpool(self.model.features(image_tensor)).flatten(1)
            image_embedding = self.model.image_projection(features).mean(dim=0, keepdim=True)
            metadata_embedding = self.model.metadata_branch(meta_tensor)
            return self.model.fusion_head(torch.cat((image_embedding, metadata_embedding), dim=1))


class CNNAdapter:
    """Load self-contained Keras image or image/metadata CNNs, including HW3 SCIN."""

    def __init__(self, path, config):
        import tensorflow as tf
        from tensorflow import keras

        self.config = copy.deepcopy(config)
        self.device = "/GPU:0" if tf.test.is_built_with_cuda() and tf.config.list_physical_devices("GPU") else "/CPU:0"
        with tf.device(self.device):
            try:
                self.model = keras.models.load_model(path, compile=False, safe_mode=True)
            except Exception:
                raise ModelLoadError("Keras model could not be safely loaded; use a .keras export with supported layers.") from None
        image_inputs = [item for item in self.model.inputs if len(item.shape) == 4 and item.shape[-1] == 3]
        metadata_inputs = [item for item in self.model.inputs if len(item.shape) == 2]
        if len(image_inputs) != 1 or len(metadata_inputs) > 1 or len(self.model.inputs) != 1 + len(metadata_inputs):
            raise ModelLoadError("Register an adapter for this Keras input signature.")
        self.image_name = image_inputs[0].name.split(":")[0]
        self.metadata_name = metadata_inputs[0].name.split(":")[0] if metadata_inputs else None
        self.config["inputs"] = "image_metadata" if self.metadata_name else "image"
        if self.metadata_name:
            self.config["metadata_dim"] = int(metadata_inputs[0].shape[-1])
        self.config["num_classes"] = int(self.model.output_shape[-1])
        height, width = image_inputs[0].shape[1:3]
        self.config.setdefault("image", {})
        if height and width:
            saved_size = self.config["image"].get("size", [int(height), int(width)])
            if ([saved_size, saved_size] if type(saved_size) is int else list(saved_size)) != [height, width]:
                raise ModelLoadError("Image size configuration disagrees with Keras input shape.")
            self.config["image"]["size"] = saved_size
        # The notebook export has these exact companions and known /255 scaling.
        if self.model.name == "hw3_scin_metadata":
            prefix = path.stem.removesuffix("_model")
            classes_path = path.parent / f"{prefix}_classes.json"
            if classes_path.is_file():
                saved = _json(classes_path)
                if saved.get("normalization") != "RGB float32 /255, letterbox":
                    raise ModelLoadError("Unsupported custom CNN preprocessing contract.")
                if self.config.get("target_classes", saved["target_classes"]) != saved["target_classes"]:
                    raise ModelLoadError("Custom CNN sidecar class order disagrees with its saved classes.")
                self.config.setdefault("target_classes", saved["target_classes"])
                if saved.get("image_size") not in (height, [height, width]):
                    raise ModelLoadError("Custom CNN class/config artifact disagrees with image shape.")
            # Pillow's centering rounds odd padding differently from the
            # MobileNet manual pad. Match the notebook's exact training bytes.
            training_image = {"mean": [0, 0, 0], "std": [1, 1, 1], "scale": 255, "resize": "pillow_pad"}
            for key, value in training_image.items():
                if key in self.config["image"] and self.config["image"][key] != value:
                    raise ModelLoadError("Custom CNN sidecar disagrees with saved training image preprocessing.")
            self.config["image"] = _merge(training_image, self.config["image"])
            self.config.setdefault("metadata", {})
            encoder = path.parent / f"{prefix}_metadata_encoder.json"
            if encoder.is_file():
                self.config["metadata"].setdefault("encoder", encoder.name)
                configured_encoder = _artifact(path.parent, self.config["metadata"]["encoder"])
                if _hash(configured_encoder) != _hash(encoder):
                    raise ModelLoadError("Custom CNN sidecar substitutes a different metadata encoder.")
        activation = getattr(self.model.layers[-1], "activation", None)
        self.activation = getattr(activation, "__name__", None)

    def predict_raw(self, images, metadata, mode):
        """Keras uses NHWC and training=False; its architecture stays encapsulated."""
        import numpy as np
        import tensorflow as tf

        if mode != "mean_probabilities":
            raise PredictionError("This Keras adapter supports mean_probabilities; other fusion requires a model-specific adapter.")
        values = {self.image_name: np.transpose(images, (0, 2, 3, 1))}
        if self.metadata_name:
            if metadata is None:
                raise PredictionError("This model requires its saved metadata encoder or feature configuration.")
            values[self.metadata_name] = np.repeat(metadata, len(images), axis=0)
        with tf.device(self.device):
            return self.model(values if len(self.model.inputs) > 1 else values[self.image_name], training=False)


_adapter_classes = {"mobilenet_v3_small_metadata_late_fusion": MobileNetAdapter}
_active_model = None
_active_lock = threading.RLock()


def register_adapter(architecture: str, adapter_class: type[TorchAdapter]) -> None:
    """Model authors register future state-dict architectures; app calls stay fixed."""
    if not isinstance(architecture, str) or not architecture.strip() or not issubclass(adapter_class, TorchAdapter):
        raise ValueError("Register a named TorchAdapter subclass.")
    _adapter_classes[architecture] = adapter_class


def _probabilities(output, config, activation):
    """Validate and activate outputs, preserving independent multi-label scores.

    Logits do not reveal the training objective. Ambiguous auto mode uses a
    disclosed softmax fallback; multi-label logits should declare sigmoid_logits.
    """
    import numpy as np

    if isinstance(output, Mapping):
        key = config.get("key")
        if key is None:
            key = next((name for name in ("logits", "probabilities", "output") if name in output), None)
        if key not in output:
            raise PredictionError("Configure output.key for dictionary model outputs.")
        output = output[key]
    if isinstance(output, (tuple, list)):
        index = config.get("index")
        if type(index) is not int or not 0 <= index < len(output):
            raise PredictionError("Configure output.index for tuple model outputs.")
        output = output[index]
    if hasattr(output, "detach"):
        output = output.detach().cpu().numpy()
    values = np.asarray(output, dtype=np.float64)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or not values.size or not np.isfinite(values).all():
        raise PredictionError("Model output must be a finite, nonempty [batch, classes] array.")
    mode = config.get("type", "auto")
    notices = []
    detected = None
    if mode == "auto":
        if activation in ("softmax", "sigmoid"):
            mode, detected = "probabilities", activation
        elif np.all((values >= 0) & (values <= 1)):
            mode = "probabilities"
            notices.append("Output semantics inferred from values in [0,1]; declare output.type to remove ambiguity.")
        else:
            mode = "sigmoid_logits" if config.get("multi_label") is True else "softmax_logits"
            notices.append("Logit objective was not saved; using configured multi_label or softmax fallback. Declare output.type for reliability.")
    if mode == "softmax_logits":
        values = np.exp(values - values.max(axis=1, keepdims=True))
        values /= values.sum(axis=1, keepdims=True)
        detected = "softmax"
    elif mode == "sigmoid_logits":
        # Stable sigmoid avoids overflow for confidently negative logits.
        values = np.exp(-np.logaddexp(0, -values))
        detected = "sigmoid"
    elif mode == "weighted_scores":
        maxima = values.max(axis=1, keepdims=True)
        if (values < 0).any() or (maxima <= 0).any():
            raise PredictionError("Weighted scores must be nonnegative with positive row sums.")
        # Scaling first prevents finite large weights from overflowing their sum.
        values /= maxima
        values /= values.sum(axis=1, keepdims=True)
        detected = "weighted_scores"
    elif mode == "probabilities":
        if (values < 0).any() or (values > 1).any():
            raise PredictionError("Declared probabilities must be within [0,1].")
        if detected == "softmax" and not np.allclose(values.sum(axis=1), 1, atol=1e-5):
            raise PredictionError("Softmax output does not sum to one.")
    else:
        raise PredictionError("Unsupported output.type in inference configuration.")
    return values, notices, detected or "probabilities"


class LoadedModel:
    """One loaded contract; requests are serialized per model instance."""

    def __init__(self, adapter, path: Path, trust_pickle=False):
        from .preprocessing import ImagePipeline, MetadataPipeline

        self.adapter, self.model, self.device = adapter, adapter.model, adapter.device
        self.config = adapter.config
        self.warnings = []
        if self.config.get("multi_image", "mean_probabilities") not in ("mean_probabilities", "mean_embeddings", "stack"):
            raise ModelLoadError("Unsupported multi_image configuration.")
        output_config = self.config.get("output", {})
        if not isinstance(output_config, Mapping) or output_config.get("type", "auto") not in ("auto", "softmax_logits", "sigmoid_logits", "probabilities", "weighted_scores"):
            raise ModelLoadError("Unsupported output configuration.")
        if self.config.get("inputs") not in ("image", "image_metadata", "dict"):
            raise ModelLoadError("Unsupported input convention.")
        image_config = self.config.get("image", {})
        if not all(key in image_config for key in ("size", "mean", "std")):
            self.warnings.append("Training image statistics were not fully saved; using 224px/ImageNet defaults for missing settings.")
        self.image_pipeline = ImagePipeline(image_config)
        self.metadata_pipeline = MetadataPipeline(self.config.get("metadata", {}), path.parent, trust_pickle=trust_pickle)
        expected_dim = self.config.get("metadata_dim")
        if expected_dim is not None and self.metadata_pipeline.output_dim != expected_dim:
            raise ModelLoadError("Saved metadata encoder/features are missing or have the wrong dimension; provide the training artifact.")
        self.classes = self.config.get("target_classes")
        if (path.parent / "class_mapping.json").is_file():
            saved_classes = _json(path.parent / "class_mapping.json").get("target_classes")
            if self.classes is not None and saved_classes != self.classes:
                raise ModelLoadError("Class mapping artifact disagrees with checkpoint order.")
            self.classes = saved_classes
        if self.classes is not None and (not isinstance(self.classes, list) or not self.classes or any(not isinstance(c, str) or not c.strip() for c in self.classes) or len(set(self.classes)) != len(self.classes)):
            raise ModelLoadError("Provide unique, nonempty target_classes in exact training order.")
        if self.classes is not None and self.config.get("num_classes", len(self.classes)) != len(self.classes):
            raise ModelLoadError("Class mapping and model class count disagree.")
        self.model_version = str(self.config.get("model_version") or "sha256:" + _hash(path)[:16])
        self._lock = threading.RLock()

    def predict_case(self, images, symptoms=None, metadata=None) -> dict[str, Any]:
        """Accept raw case inputs; return ranked scores and separate review flags.

        Image paths are local backend paths, not arbitrary URLs. For encrypted
        storage pass authorized decrypted bytes; no plaintext file is written.
        Free text is retained as context, never converted to invented features.
        """
        import numpy as np
        from .triage import triage_flags

        sources = list(images) if isinstance(images, (list, tuple)) else [images]
        if not sources or any(source is None for source in sources):
            raise PredictionError("Provide at least one dermatology image.")
        notices = list(self.warnings)
        try:
            batch = np.stack([self.image_pipeline(source) for source in sources])
            encoded, metadata_notices = self.metadata_pipeline.transform(symptoms, metadata)
            notices.extend(metadata_notices)
        except (ValueError, TypeError) as error:
            # These preprocessing helpers deliberately report field names only.
            raise PredictionError(str(error)) from None
        try:
            mode = self.config.get("multi_image", "mean_probabilities")
            if mode not in ("mean_probabilities", "mean_embeddings", "stack"):
                raise PredictionError("multi_image must be mean_probabilities, mean_embeddings or stack.")
            with self._lock:
                raw = self.adapter.predict_raw(batch, encoded, mode)
                scores, output_notices, output_format = _probabilities(raw, self.config.get("output", {}), self.adapter.activation)
            expected_rows = len(batch) if mode == "mean_probabilities" else 1
            if len(scores) != expected_rows:
                raise PredictionError("Model output batch disagrees with multi_image mode.")
            scores = scores.mean(axis=0)
            classes = self.classes or [f"class_{i}" for i in range(len(scores))]
            if len(classes) != len(scores):
                raise PredictionError("Model output dimension disagrees with saved class mapping.")
            if self.classes is None:
                notices.append("Class mapping unavailable; class_N labels are technical placeholders, not diagnoses.")
            notices.extend(output_notices)
            if isinstance(symptoms, str) or isinstance(symptoms, Mapping) and isinstance(symptoms.get("description"), str):
                notices.append("Free-text symptoms are not embedded by this model adapter; only configured structured features are encoded.")
            ranked = [{"condition": classes[int(i)], "confidence": float(scores[i])} for i in np.argsort(-scores, kind="stable")]
            result = {"top_prediction": ranked[0], "differential": ranked,
                      "model_version": self.model_version, "output_format": output_format,
                      "warnings": list(dict.fromkeys(notices)),
                      "probability_notice": "Uncalibrated model scores; not validated clinical probabilities."}
            result["triage_flags"] = triage_flags(result, symptoms, metadata)
            return result
        except PredictionError:
            raise
        except Exception:
            # Never expose framework tracebacks, image bytes or intake values.
            raise PredictionError("Model execution failed; check its saved input/preprocessing contract.") from None


def load_model(model_path, *, trust_pickle=False) -> LoadedModel:
    """Load a local model once and atomically install it for predict_case.

    Supports restricted PyTorch state/checkpoint dictionaries, TorchScript and
    native Keras .keras exports. Raw state dictionaries require a registered
    architecture plus config. Pickled preprocessing is opt-in trusted code; the
    loader never retries a failed weights_only load with unsafe deserialization.
    A failed load leaves the previous active model usable.
    """
    global _active_model

    path = Path(model_path).expanduser().resolve()
    if path.is_dir():
        path = path / "best_model.pt"
    if not path.is_file():
        raise ModelLoadError("Model file does not exist.")
    try:
        sidecar = _sidecar(path)
        manifest_path = path.parent / "manifest.json"
        if manifest_path.is_file():
            manifest = _json(manifest_path)
            for name, digest in manifest.get("files", {}).items():
                if _hash(_artifact(path.parent, name)) != digest:
                    raise ModelLoadError("Inference bundle artifact hash mismatch.")
        if path.suffix.lower() == ".keras":
            adapter = CNNAdapter(path, sidecar)
        else:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            scripted = False
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    scripted = any(name.endswith("/constants.pkl") or name == "constants.pkl" for name in archive.namelist())
            if scripted:
                extra = {"inference.json": ""}
                model = torch.jit.load(str(path), map_location="cpu", _extra_files=extra)
                embedded = json.loads(extra["inference.json"]) if extra["inference.json"] else {}
                adapter = TorchAdapter(path, {}, _merge(embedded, sidecar), device, scripted_model=model)
            else:
                try:
                    payload = torch.load(path, map_location="cpu", weights_only=True)
                except Exception:
                    raise ModelLoadError("Not a supported safe checkpoint. Export a state_dict with architecture/config or TorchScript; unsafe pickle loading is disabled.") from None
                if not isinstance(payload, Mapping):
                    raise ModelLoadError("Expected a checkpoint/state dictionary or TorchScript model.")
                config = _checkpoint_config(payload)
                # Sidecars may supply absent details and input aliases, but must
                # not silently replace the training contract already saved.
                for key in ("architecture", "target_classes", "metadata_dim", "num_classes"):
                    if key in config and key in sidecar and config[key] != sidecar[key]:
                        raise ModelLoadError("Sidecar disagrees with saved checkpoint configuration.")
                for key in ("size", "mean", "std"):
                    if key in config.get("image", {}) and key in sidecar.get("image", {}) and config["image"][key] != sidecar["image"][key]:
                        raise ModelLoadError("Sidecar disagrees with saved training image preprocessing.")
                config = _merge(config, sidecar)
                adapter_class = _adapter_classes.get(config.get("architecture"))
                if adapter_class is None:
                    raise ModelLoadError("Weights alone do not define an architecture. Add architecture/model_kwargs to a sidecar and register its adapter, or export TorchScript.")
                adapter = adapter_class(path, payload, config, device)
        loaded = LoadedModel(adapter, path, trust_pickle=trust_pickle)
    except ModelLoadError:
        raise
    except (ValueError, TypeError) as error:
        raise ModelLoadError(str(error)) from None
    except Exception:
        raise ModelLoadError("Model could not be loaded; check framework dependencies and saved inference artifacts.") from None
    with _active_lock:
        _active_model = loaded
    return loaded


def predict_case(images, symptoms=None, metadata=None) -> dict[str, Any]:
    """Predict through the most recently loaded model; no model details escape."""
    with _active_lock:
        loaded = _active_model
    if loaded is None:
        raise ModelNotLoadedError("Call load_model(model_path) before predict_case.")
    return loaded.predict_case(images, symptoms, metadata)
