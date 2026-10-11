"""Synthetic inference-interface contracts; no model downloads or clinical rules."""

from __future__ import annotations

import importlib
import hashlib
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import torch
    from PIL import Image
except ImportError as exc:
    ML_IMPORT_ERROR = str(exc)
else:
    ML_IMPORT_ERROR = None


class InterfaceImportTests(unittest.TestCase):
    """The Flask boundary should remain importable without loading ML runtimes."""

    def test_import_is_lazy_and_unconfigured_prediction_is_explicit(self):
        result = subprocess.run([
            sys.executable, "-c",
            "import json,sys; import backend.ai.model_interface as m; "
            "print(json.dumps([name for name in ('torch','tensorflow','scin_ml') if name in sys.modules]))",
        ], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), [])
        interface = importlib.import_module("backend.ai.model_interface")
        previous = interface._active_model
        try:
            interface._active_model = None
            with self.assertRaises(interface.ModelNotLoadedError):
                interface.predict_case([])
        finally:
            interface._active_model = previous

    def test_triage_uses_explicit_structured_flags_and_only_top_diagnosis(self):
        """Prototype review flags must not infer speed, infection or positive booleans."""
        from backend.ai.triage import triage_flags

        ordinary = {"top_prediction": {"condition": "Eczema"},
                    "differential": [{"condition": "SCC/SCCIS", "confidence": .01}]}
        self.assertEqual(triage_flags(ordinary, None), [])
        spread = triage_flags(ordinary, {"spreading": True})
        self.assertEqual(spread, ["Spreading rash reported: clinician review required."])
        rapid = triage_flags(ordinary, {"spreading": True, "rapidly_spreading": 1})
        self.assertEqual(rapid, ["Rapidly spreading rash reported: clinician review required."])
        self.assertEqual(triage_flags(ordinary, {"fever": True}), [])
        self.assertEqual(triage_flags(ordinary, {"skin_infection_signs": 1}), [])
        self.assertEqual(triage_flags(ordinary, {"fever": True}, {"skin_infection_signs": 1}),
                         ["Fever with skin infection signs reported: clinician review required."])
        for value in ("true", "yes", "1", "false", "0", 1.0, None):
            with self.subTest(value=value):
                self.assertEqual(triage_flags(ordinary, {
                    "rapidly_spreading": value, "spreading": value, "fever": value,
                    "skin_infection_signs": value, "immunocompromised": value,
                }), [])
        self.assertEqual(triage_flags(ordinary, "fever, melanoma and rapidly spreading rash"), [])
        suspected = {"top_prediction": {"condition": "SCC/SCCIS", "confidence": .00001}}
        self.assertEqual(triage_flags(suspected, None),
                         ["Model suspicion of squamous cell carcinoma: clinician review required."])


@unittest.skipIf(ML_IMPORT_ERROR is not None, f"Optional ML dependencies absent: {ML_IMPORT_ERROR}")
class ModelInterfaceTests(unittest.TestCase):
    """Exercise trusted sidecars, structured metadata and safe model dispatch."""

    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.interface = importlib.import_module("backend.ai.model_interface")
        self.previous_active = self.interface._active_model
        self.interface._active_model = None
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.interface._active_model = self.previous_active
        self.temporary.cleanup()

    def config(self, **changes):
        """Declare a tiny model's actual transform, rather than infer its training."""
        configuration = {
            "target_classes": ["Red", "Green", "Blue"],
            "image": {"size": 16, "mean": [0., 0., 0.], "std": [1., 1., 1.],
                      "scale": 255., "resize": "pad"},
            "inputs": "image", "output": {"type": "softmax_logits"},
            "multi_image": "mean_probabilities", "model_version": "synthetic-test-v1",
        }
        configuration.update(changes)
        return configuration

    def save_script(self, module, configuration=None, *, embedded=False, arguments=None):
        """Serialize only an isolated TorchScript fixture and optional JSON contract."""
        path = self.directory / f"model-{len(list(self.directory.glob('*.pt')))}.pt"
        arguments = arguments or (torch.zeros(2, 3, 16, 16),)
        traced = torch.jit.trace(module.eval(), arguments, strict=False)
        extra = {"inference.json": json.dumps(configuration)} if embedded else None
        torch.jit.save(traced, str(path), _extra_files=extra or {})
        if configuration is not None and not embedded:
            Path(str(path) + ".json").write_text(json.dumps(configuration), encoding="utf-8")
        return path

    @staticmethod
    def mean_image_module():
        class ImageMeans(torch.nn.Module):
            def forward(self, images):
                return images.mean(dim=(2, 3))
        return ImageMeans()

    @staticmethod
    def scores(result):
        return {item["condition"]: item["confidence"] for item in result["differential"]}

    def test_torchscript_rgb_sources_and_serializable_ranked_output(self):
        path = self.save_script(self.mean_image_module(), self.config(), embedded=True)
        loaded = self.interface.load_model(path)
        self.assertIsNotNone(loaded.model)
        self.assertIn(str(loaded.device).split(":")[0], ("cpu", "cuda", "mps"))
        red = Image.new("RGB", (16, 16), (255, 0, 0))
        stream = io.BytesIO()
        red.save(stream, format="PNG")
        image_path = self.directory / "red.png"
        image_path.write_bytes(stream.getvalue())
        previous = None
        for image in (red, stream.getvalue(), image_path):
            result = self.interface.predict_case([image])
            self.assertEqual(result["top_prediction"]["condition"], "Red")
            self.assertAlmostEqual(result["top_prediction"]["confidence"],
                                   float(torch.softmax(torch.tensor([1., 0., 0.]), 0)[0]), places=6)
            self.assertEqual(len(result["differential"]), 3)
            self.assertEqual(result["model_version"], "synthetic-test-v1")
            for key in ("triage_flags", "warnings", "output_format"):
                self.assertIn(key, result)
            json.dumps(result, allow_nan=False)
            if previous is not None:
                self.assertEqual(self.scores(result), self.scores(previous))
            previous = result

    def test_multiple_images_average_probabilities_and_explicit_stack(self):
        red = Image.new("RGB", (16, 16), (255, 0, 0))
        green = Image.new("RGB", (16, 16), (0, 255, 0))
        path = self.save_script(self.mean_image_module(), self.config())
        self.interface.load_model(path)
        result = self.interface.predict_case([red, green])
        expected = torch.softmax(torch.tensor([[1., 0., 0.], [0., 1., 0.]]), dim=1).mean(dim=0)
        for index, name in enumerate(("Red", "Green", "Blue")):
            self.assertAlmostEqual(self.scores(result)[name], float(expected[index]), places=6)

        class StackImages(torch.nn.Module):
            def forward(self, images):
                return images.mean(dim=(0, 2, 3)).unsqueeze(0)

        path = self.save_script(StackImages(), self.config(multi_image="stack"))
        self.interface.load_model(path)
        stacked = self.interface.predict_case([red, green])
        expected = torch.softmax(torch.tensor([.5, .5, 0.]), dim=0)
        for index, name in enumerate(("Red", "Green", "Blue")):
            self.assertAlmostEqual(self.scores(stacked)[name], float(expected[index]), places=6)

    def test_sigmoid_outputs_remain_multilabel_and_auto_detects_activation(self):
        class SigmoidImages(torch.nn.Module):
            def forward(self, images):
                return torch.sigmoid(images.mean(dim=(2, 3)))

        path = self.save_script(SigmoidImages(), self.config(output={"type": "auto"}))
        self.interface.load_model(path)
        result = self.interface.predict_case([Image.new("RGB", (16, 16), (255, 0, 0))])
        scores = self.scores(result)
        self.assertAlmostEqual(scores["Red"], float(torch.sigmoid(torch.tensor(1.))), places=6)
        self.assertAlmostEqual(scores["Green"], .5, places=6)
        self.assertGreater(sum(scores.values()), 1.)
        path = self.save_script(self.mean_image_module(), self.config(output={"type": "sigmoid_logits"}))
        self.interface.load_model(path)
        explicit = self.interface.predict_case([Image.new("RGB", (16, 16), (255, 0, 0))])
        for name, score in scores.items():
            self.assertAlmostEqual(self.scores(explicit)[name], score, places=6)

    def test_metadata_transforms_unknown_categories_and_missing_defaults_warn(self):
        class MetadataOnly(torch.nn.Module):
            def forward(self, images, metadata):
                return metadata

        config = self.config(
            target_classes=["Age", "Itching", "Female", "Male"], inputs="image_metadata",
            metadata={"features": [
                {"name": "age", "kind": "numeric", "mean": 10., "std": 2., "default": 10.},
                {"name": "itching", "kind": "binary"},
                {"name": "sex", "kind": "categorical", "categories": ["female", "male"]},
            ]},
        )
        path = self.save_script(MetadataOnly(), config,
                                arguments=(torch.zeros(1, 3, 16, 16), torch.zeros(1, 4)))
        self.interface.load_model(path)
        image = Image.new("RGB", (16, 16))
        result = self.interface.predict_case([image], symptoms={"itching": 1},
                                             metadata={"age": 14., "sex": "unknown"})
        expected = torch.softmax(torch.tensor([2., 1., 0., 0.]), dim=0)
        for index, name in enumerate(("Age", "Itching", "Female", "Male")):
            self.assertAlmostEqual(self.scores(result)[name], float(expected[index]), places=6)
        self.assertTrue(result["warnings"])
        defaulted = self.interface.predict_case([image], symptoms={"itching": 1}, metadata={"sex": "female"})
        self.assertTrue(defaulted["warnings"])
        expected = torch.softmax(torch.tensor([0., 1., 1., 0.]), dim=0)
        self.assertAlmostEqual(self.scores(defaulted)["Age"], float(expected[0]), places=6)

    def test_invalid_outputs_and_class_mapping_fail_explicitly(self):
        image = Image.new("RGB", (16, 16))
        path = self.save_script(self.mean_image_module(), self.config(target_classes=["A", "B"]))
        with self.assertRaises((self.interface.ModelLoadError, self.interface.PredictionError)):
            self.interface.load_model(path)
            self.interface.predict_case([image])

        class Nonfinite(torch.nn.Module):
            def forward(self, images):
                return images.mean(dim=(2, 3)) * float("nan")

        path = self.save_script(Nonfinite(), self.config())
        with self.assertRaises((self.interface.ModelLoadError, self.interface.PredictionError)):
            self.interface.load_model(path)
            self.interface.predict_case([image])

    def test_failed_load_preserves_model_and_rejects_unsafe_pickle(self):
        path = self.save_script(self.mean_image_module(), self.config())
        self.interface.load_model(path)
        image = Image.new("RGB", (16, 16), (255, 0, 0))
        original = self.interface.predict_case([image])
        corrupt = self.directory / "corrupt.pt"
        corrupt.write_bytes(b"not a model")
        with self.assertRaises(self.interface.ModelLoadError):
            self.interface.load_model(corrupt)
        self.assertEqual(self.interface.predict_case([image]), original)
        unsupported = self.directory / "unconfigured-state.pt"
        torch.save({"weight": torch.zeros(2, 2)}, unsupported)
        with self.assertRaisesRegex(self.interface.ModelLoadError, "architecture"):
            self.interface.load_model(unsupported)
        self.assertEqual(self.interface.predict_case([image]), original)
        marker = self.directory / "unsafe-executed.txt"

        class UnsafeObject:
            def __reduce__(self):
                # Restricted loading must reject this callable without invoking it.
                return eval, (f"__import__('pathlib').Path({str(marker)!r}).write_text('unsafe')",)

        unsafe = self.directory / "unsafe.pt"
        torch.save({"model": UnsafeObject()}, unsafe)
        with self.assertRaises(self.interface.ModelLoadError):
            self.interface.load_model(unsafe)
        self.assertFalse(marker.exists())
        self.assertEqual(self.interface.predict_case([image]), original)

    def test_unconfigured_torchscript_defaults_are_visible(self):
        path = self.save_script(self.mean_image_module())
        self.interface.load_model(path)
        result = self.interface.predict_case([Image.new("RGB", (16, 16))])
        self.assertTrue(result["warnings"])
        self.assertTrue(all(item["condition"].startswith("class_") for item in result["differential"]))

    def test_scin_checkpoint_and_raw_state_dict_load_strictly_with_saved_encoder(self):
        """Saved SCIN feature order must survive architecture reconstruction."""
        try:
            import pandas as pd
            from scin_ml.data import CATEGORICAL_COLUMNS, MetadataEncoder
            from scin_ml.model import MultimodalDermatologyModel
        except ImportError:
            self.skipTest("Optional SCIN metadata dependencies absent")
        frame = pd.DataFrame({"flag_one": [0, 1], "flag_two": [1, 0],
                              **{name: ["known", "known"] for name in CATEGORICAL_COLUMNS}})
        encoder = MetadataEncoder().fit(frame)
        encoder_path = self.directory / "metadata_encoder.json"
        encoder.save(encoder_path)
        model = MultimodalDermatologyModel(encoder.output_dim, 41, pretrained=False).eval()
        classes = [f"condition-{index}" for index in range(41)]
        checkpoint = {
            "format_version": 1, "architecture": "mobilenet_v3_small_metadata_late_fusion",
            "metadata_dim": encoder.output_dim, "num_classes": 41,
            "target_classes": classes, "model_state_dict": model.state_dict(),
            "metadata_encoder_sha256": hashlib.sha256(encoder_path.read_bytes()).hexdigest(),
            "image_size": 224, "training_config": {},
            "image_normalization": {"mean": [.485, .456, .406], "std": [.229, .224, .225]},
        }
        checkpoint_path = self.directory / "scin-checkpoint.pt"
        torch.save(checkpoint, checkpoint_path)
        self.interface.load_model(checkpoint_path)
        image = Image.new("RGB", (20, 30), (150, 120, 100))
        result = self.interface.predict_case([image], metadata=frame.iloc[0].to_dict())
        self.assertEqual(len(result["differential"]), 41)
        self.assertEqual({item["condition"] for item in result["differential"]}, set(classes))
        with self.assertRaises(self.interface.PredictionError):
            self.interface.predict_case([image], metadata={})

        config = self.config(
            architecture="mobilenet_v3_small_metadata_late_fusion",
            model_kwargs={"metadata_dim": encoder.output_dim, "num_classes": 41},
            target_classes=classes, inputs="image_metadata",
            metadata={"encoder": "metadata_encoder.json"},
        )
        for name, payload in (("raw-state.pt", model.state_dict()),
                              ("wrapped-state.pt", {"state_dict": model.state_dict()})):
            path = self.directory / name
            torch.save(payload, path)
            Path(str(path) + ".json").write_text(json.dumps(config))
            self.interface.load_model(path)
            self.assertEqual(len(self.interface.predict_case([image], metadata=frame.iloc[0].to_dict())["differential"]), 41)

        config["multi_image"] = "mean_embeddings"
        Path(str(path) + ".json").write_text(json.dumps(config))
        self.interface.load_model(path)
        fused = self.interface.predict_case([image, image], metadata=frame.iloc[0].to_dict())
        self.assertEqual(len(fused["differential"]), 41)
        self.assertAlmostEqual(sum(self.scores(fused).values()), 1., places=6)

        invalid = self.directory / "wrong-architecture.pt"
        torch.save({"state_dict": {"unrelated.weight": torch.zeros(2, 2)}}, invalid)
        Path(str(invalid) + ".json").write_text(json.dumps(config))
        with self.assertRaises(self.interface.ModelLoadError):
            self.interface.load_model(invalid)
        mapping_path = self.directory / "class_mapping.json"
        mapping_path.write_text(json.dumps({"target_classes": list(reversed(classes))}))
        with self.assertRaisesRegex(self.interface.ModelLoadError, "Class mapping"):
            self.interface.load_model(checkpoint_path)
        mapping_path.unlink()
        encoder_path.write_bytes(encoder_path.read_bytes() + b" ")
        with self.assertRaises(self.interface.ModelLoadError):
            self.interface.load_model(checkpoint_path)

    def test_dictionary_inputs_outputs_and_weighted_score_semantics(self):
        class DictionaryImages(torch.nn.Module):
            def forward(self, values):
                return {"scores": values["image"].mean(dim=(2, 3))}

        config = self.config(inputs="dict", output={"type": "weighted_scores", "key": "scores"})
        path = self.save_script(DictionaryImages(), config,
                                arguments=({"image": torch.zeros(1, 3, 16, 16)},))
        self.interface.load_model(path)
        result = self.interface.predict_case([Image.new("RGB", (16, 16), (255, 128, 0))])
        expected = 255 / (255 + 128)
        self.assertAlmostEqual(result["top_prediction"]["confidence"], expected, places=6)
        self.assertAlmostEqual(sum(self.scores(result).values()), 1., places=6)
        self.assertEqual(result["output_format"], "weighted_scores")

    def test_huge_finite_weights_normalize_and_framework_errors_are_sanitized(self):
        """Finite weights must not overflow and third-party failures must hide data."""
        config = self.config(target_classes=["A", "B"], output={"type": "weighted_scores"})
        path = self.save_script(self.mean_image_module(), config)
        loaded = self.interface.load_model(path)
        image = Image.new("RGB", (16, 16))
        with patch.object(loaded.adapter, "predict_raw", return_value=np.array([[1e308, 1e308]])), \
                np.errstate(over="raise", invalid="raise"):
            result = self.interface.predict_case([image])
        self.assertEqual(self.scores(result), {"A": .5, "B": .5})
        marker = "SENSITIVE_PATIENT_MARKER"
        errors = ({"side_effect": ValueError(marker)},
                  {"return_value": np.array([[marker, "not-numeric"]], dtype=object)})
        for adapter_result in errors:
            with self.subTest(adapter_result=next(iter(adapter_result))), \
                    patch.object(loaded.adapter, "predict_raw", **adapter_result):
                with self.assertRaises(self.interface.PredictionError) as captured:
                    self.interface.predict_case([image])
                self.assertNotIn(marker, str(captured.exception))
                self.assertIn("Model execution failed", str(captured.exception))

    def test_optional_notebook_keras_architecture_loads_its_saved_companions(self):
        """Build the notebook's existing graph only; never execute training cells."""
        try:
            # TensorFlow's optional visualization imports must not write home caches.
            with patch.dict(os.environ, {"MPLCONFIGDIR": str(self.directory / "matplotlib"),
                                         "XDG_CACHE_HOME": str(self.directory / "cache")}):
                import pandas as pd
                import tensorflow as tf
                from tensorflow import keras
                from tensorflow.keras import layers
                from scin_ml.data import CATEGORICAL_COLUMNS, MetadataEncoder
        except ImportError:
            self.skipTest("Optional TensorFlow/SCIN dependencies absent")
        notebook_path = Path(__file__).resolve().parents[1] / "notebooks" / "SCIN_MODEL.IPYNB"
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        source = next(("".join(cell["source"]) for cell in notebook["cells"]
                       if cell["cell_type"] == "code" and "custom_model = keras.Model(" in "".join(cell["source"])), None)
        if source is None:
            self.skipTest("Notebook custom Keras architecture is not present")
        frame = pd.DataFrame({"flag_one": [0, 1], "flag_two": [1, 0],
                              **{name: ["known", "known"] for name in CATEGORICAL_COLUMNS}})
        encoder = MetadataEncoder().fit(frame)
        classes = [f"condition-{index}" for index in range(41)]
        namespace = {"keras": keras, "layers": layers, "custom_image_size": 224,
                     "custom_metadata": np.zeros((2, encoder.output_dim)), "custom_classes": classes}
        with tf.device("/CPU:0"), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, str(notebook_path), "exec"), namespace)
            model = namespace["custom_model"]
            path = self.directory / "SCIN_custom_model.keras"
            model.save(path)
        encoder.save(self.directory / "SCIN_custom_metadata_encoder.json")
        (self.directory / "SCIN_custom_classes.json").write_text(json.dumps({
            "target_classes": classes, "image_size": 224,
            "normalization": "RGB float32 /255, letterbox",
        }))
        loaded = self.interface.load_model(path)
        self.assertEqual(loaded.model.name, "hw3_scin_metadata")
        image = Image.new("RGB", (50, 70), (150, 130, 110))
        result = self.interface.predict_case([image], metadata=frame.iloc[0].to_dict())
        self.assertEqual(len(result["differential"]), 41)
        self.assertAlmostEqual(sum(self.scores(result).values()), 1., places=6)
        self.assertEqual({item["condition"] for item in result["differential"]}, set(classes))
        self.assertEqual(result["output_format"], "softmax")

        from PIL import ImageOps

        pixels = np.arange(224 * 221 * 3, dtype=np.uint32).reshape(224, 221, 3) % 256
        odd_width = Image.fromarray(pixels.astype(np.uint8))
        expected = np.asarray(ImageOps.pad(odd_width, (224, 224),
                              method=Image.Resampling.BILINEAR, color=(0, 0, 0)), dtype=np.float32) / 255.
        np.testing.assert_array_equal(loaded.image_pipeline(odd_width), expected.transpose(2, 0, 1))

        sidecar_path = Path(str(path) + ".json")
        sidecar_path.write_text(json.dumps({"target_classes": list(reversed(classes))}))
        with self.assertRaisesRegex(self.interface.ModelLoadError, "class order"):
            self.interface.load_model(path)
        self.assertIs(self.interface._active_model, loaded)

        saved_encoder = self.directory / "SCIN_custom_metadata_encoder.json"
        different_encoder = self.directory / "same-width-different-encoder.json"
        encoder_config = json.loads(saved_encoder.read_text())
        encoder_config["categories"][0][0] = "substituted-category"
        different_encoder.write_text(json.dumps(encoder_config))
        sidecar_path.write_text(json.dumps({"metadata": {"encoder": different_encoder.name}}))
        with self.assertRaisesRegex(self.interface.ModelLoadError, "different metadata encoder"):
            self.interface.load_model(path)
        self.assertIs(self.interface._active_model, loaded)
        sidecar_path.write_text(json.dumps({"image": {"mean": [.485, .456, .406]}}))
        with self.assertRaises(self.interface.ModelLoadError):
            self.interface.load_model(path)
        sidecar_path.unlink()


if __name__ == "__main__":
    unittest.main()
