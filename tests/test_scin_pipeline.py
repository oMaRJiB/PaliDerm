"""Focused SCIN contracts; optional ML dependencies never affect Flask startup.

All optimization tests use generated images and random, non-pretrained weights.
The supplied cleaned artifact is read only to check its alignment and split.
"""

from __future__ import annotations

import io
import hashlib
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
    import pandas as pd
    import sklearn
    import torch
    import torchvision
    from PIL import Image
except ImportError as exc:
    ML_IMPORT_ERROR = str(exc)
else:
    ML_IMPORT_ERROR = None
    from scin_ml.data import (
        CATEGORICAL_COLUMNS,
        ImagePreprocessor,
        ImageStore,
        MetadataEncoder,
        SCINArtifacts,
        SCINDataset,
        grouped_split,
        load_cleaned_artifact,
        primary_image_eligibility,
        validate_split_alignment,
    )
    from scin_ml.model import MultimodalDermatologyModel
    from scin_ml.inference import SCINPredictor, export_for_app
    from scin_ml.pipeline import prepare_data
    from scin_ml.training import (
        TrainingConfig,
        configure_optimizer,
        evaluate,
        fit,
        load_checkpoint,
        soft_label_cross_entropy,
        train_epoch,
    )


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(ML_IMPORT_ERROR is not None, f"Optional ML dependencies absent: {ML_IMPORT_ERROR}")
class SCINPipelineTests(unittest.TestCase):
    """Protect soft labels, grouped alignment and reproducible inference transforms."""

    @classmethod
    def setUpClass(cls):
        """Keep small CPU tests quick without changing the caller's thread policy."""
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def artifacts(self, count=40, repeated_cases=False):
        """Build already-cleaned, aligned rows with deliberately non-one-hot targets."""
        index = pd.Index(np.arange(count) * 3 + 7)
        metadata = pd.DataFrame({
            "binary_one": np.arange(count) % 2,
            "binary_two": (np.arange(count) + 1) % 2,
            **{name: [f"known-{number % 2}" for number in range(count)]
               for name in CATEGORICAL_COLUMNS},
        }, index=index)
        images = pd.DataFrame({
            "case_id": [f"case-{number // 2 if repeated_cases else number}" for number in range(count)],
            "image_1_path": [f"image-{number}.png" for number in range(count)],
            "image_2_path": [None] * count,
            "image_3_path": [None] * count,
        }, index=index)
        labels = np.tile(np.array([0.6, 0.3, 0.1], dtype=np.float32), (count, 1))
        labels[1::2] = [0.1, 0.65, 0.25]
        return SCINArtifacts(metadata, images, labels, ("A", "B", "Other"))

    def test_existing_cleaned_labels_and_grouped_alignment_are_preserved(self):
        """Use the exact supplied label order/probabilities, never reclean them."""
        path = ROOT / "notebooks" / "SCIN_cleaned.pkl"
        if not path.is_file():
            self.skipTest("Supplied cleaned SCIN artifact is not present")
        source = pd.read_pickle(path)
        artifacts = load_cleaned_artifact(path, expected_cases=3061, expected_classes=41)
        self.assertEqual(artifacts.classes, tuple(source["target_classes"]))
        np.testing.assert_array_equal(artifacts.labels, source["Y"])
        self.assertTrue(artifacts.metadata.index.equals(source["X_metadata"].index))
        self.assertTrue(artifacts.images.index.equals(source["X_images"].index))
        self.assertGreater(np.count_nonzero((artifacts.labels > 0).sum(axis=1) > 1), 0)
        splits = grouped_split(artifacts.case_ids, seed=42)
        validate_split_alignment(artifacts, splits)
        for name, fraction in (("train", .7), ("val", .15), ("test", .15)):
            self.assertAlmostEqual(len(splits[name]) / 3061, fraction, delta=.01)
            positions = splits[name]
            np.testing.assert_array_equal(artifacts.labels[positions], source["Y"][positions])
            self.assertEqual(artifacts.images.iloc[positions].case_id.tolist(),
                             source["X_images"].iloc[positions].case_id.tolist())
        eligible, exclusions = primary_image_eligibility(artifacts)
        self.assertEqual(len(eligible), 3060)
        self.assertEqual(len(exclusions), 1)
        self.assertEqual(exclusions[0]["case_id"], "-1834609919572055750")
        self.assertTrue(pd.isna(artifacts.images.iloc[exclusions[0]["position"]].image_1_path))
        # A missing primary is explicit; the dataset never silently uses image_2.
        encoded = MetadataEncoder().fit(artifacts.metadata.iloc[splits["train"]]).transform(artifacts.metadata)
        with self.assertRaises(FileNotFoundError):
            SCINDataset(artifacts, np.array([exclusions[0]["position"]]), encoded, ImageStore())

    def test_repeated_case_ids_never_cross_splits_and_seed_is_reproducible(self):
        artifacts = self.artifacts(100, repeated_cases=True)
        splits = grouped_split(artifacts.case_ids, seed=19)
        validate_split_alignment(artifacts, splits)
        again = grouped_split(artifacts.case_ids, seed=19)
        seen = set()
        all_positions = []
        for name in ("train", "val", "test"):
            np.testing.assert_array_equal(splits[name], again[name])
            groups = set(artifacts.case_ids[splits[name]])
            self.assertFalse(seen.intersection(groups))
            seen.update(groups)
            all_positions.extend(splits[name])
        self.assertEqual(sorted(all_positions), list(range(100)))
        invalid = {name: positions.copy() for name, positions in splits.items()}
        invalid["val"] = np.append(invalid["val"], invalid["train"][0])
        with self.assertRaises(ValueError):
            validate_split_alignment(artifacts, invalid)

    def test_loading_rejects_misalignment_and_invalid_probability_targets(self):
        artifacts = self.artifacts()
        document = {"X_metadata": artifacts.metadata, "X_images": artifacts.images,
                    "Y": artifacts.labels, "target_classes": list(artifacts.classes)}
        path = self.directory / "cleaned.pkl"
        document["X_images"] = artifacts.images.iloc[::-1]
        path.write_bytes(pickle.dumps(document))
        with self.assertRaises(ValueError):
            load_cleaned_artifact(path)
        document["X_images"] = artifacts.images
        document["Y"] = artifacts.labels.copy()
        document["Y"][0] = [0.6, 0.3, 0.3]
        path.write_bytes(pickle.dumps(document))
        with self.assertRaises(ValueError):
            load_cleaned_artifact(path)

    def test_metadata_encoder_fits_training_only_unknown_safe_and_round_trips(self):
        artifacts = self.artifacts()
        train = artifacts.metadata.iloc[:20].copy()
        validation = artifacts.metadata.iloc[20:22].copy()
        for name in CATEGORICAL_COLUMNS:
            validation[name] = ["validation-only-category", None]
        original = artifacts.metadata.copy(deep=True)
        encoder = MetadataEncoder().fit(train)
        train_encoded = encoder.transform(train)
        validation_encoded = encoder.transform(validation)
        self.assertEqual(train_encoded.dtype, np.float32)
        self.assertEqual(validation_encoded.shape, (2, encoder.output_dim))
        self.assertTrue(np.isfinite(validation_encoded).all())
        np.testing.assert_array_equal(train_encoded[:, :2], train.iloc[:, :2].to_numpy())
        path = self.directory / "metadata_encoder.json"
        encoder.save(path)
        # A validation-only category must not expand or enter the learned vocabulary.
        self.assertNotIn("validation-only-category", path.read_text())
        restored = MetadataEncoder.load(path)
        np.testing.assert_array_equal(restored.transform(validation), validation_encoded)
        pd.testing.assert_frame_equal(artifacts.metadata, original)
        invalid = train.copy()
        invalid.loc[invalid.index[0], "binary_one"] = 2
        with self.assertRaises(ValueError):
            encoder.transform(invalid)

    def test_rgb_letterbox_normalization_preserves_geometry(self):
        transform = ImagePreprocessor(size=224)
        image = Image.new("RGB", (20, 40), (255, 0, 0))
        result = transform(image)
        self.assertEqual(tuple(result.shape), (3, 224, 224))
        self.assertEqual(result.dtype, torch.float32)
        mean = torch.tensor([.485, .456, .406])[:, None, None]
        std = torch.tensor([.229, .224, .225])[:, None, None]
        pixels = result * std + mean
        red = (pixels[0] > .99) & (pixels[1] < .01) & (pixels[2] < .01)
        self.assertTrue(red[:, 56:168].all())
        self.assertFalse(red[:, :55].any())
        self.assertFalse(red[:, 169:].any())
        grayscale = transform(Image.new("L", (40, 20), 128)) * std + mean
        torch.testing.assert_close(grayscale[0, 56:168], grayscale[1, 56:168])
        torch.testing.assert_close(grayscale[1, 56:168], grayscale[2, 56:168])
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        torch.testing.assert_close(transform(encoded.getvalue()), result)

    def test_dataset_indexes_metadata_images_soft_labels_together(self):
        artifacts = self.artifacts()
        for row in (3, 19):
            Image.new("RGB", (12, 20), (row, 0, 0)).save(
                self.directory / artifacts.images.iloc[row].image_1_path)
        metadata = MetadataEncoder().fit(artifacts.metadata).transform(artifacts.metadata)
        dataset = SCINDataset(artifacts, np.array([19, 3]), metadata,
                              ImageStore(image_root=self.directory))
        self.assertEqual(len(dataset), 2)
        for item_number, row in enumerate((19, 3)):
            item = dataset[item_number]
            self.assertEqual(item["case_id"], artifacts.case_ids[row])
            np.testing.assert_array_equal(item["metadata"].numpy(), metadata[row])
            np.testing.assert_array_equal(item["target"].numpy(), artifacts.labels[row])
            self.assertEqual(tuple(item["image"].shape), (3, 224, 224))

    def test_arrow_images_match_case_and_original_filename_not_row_position(self):
        """A local cache must bind image bytes to identity, including shuffled rows."""
        try:
            import pyarrow as pa
            import pyarrow.ipc as ipc
        except ImportError:
            self.skipTest("Optional Arrow cache dependency is absent")
        raw = []
        for color in ((255, 0, 0), (0, 255, 0)):
            stream = io.BytesIO()
            Image.new("RGB", (8, 12), color).save(stream, format="PNG")
            raw.append(stream.getvalue())
        table = pa.table({
            "case_id": ["case-second", "case-first"],
            "image_1_path": pa.array([
                {"path": "second-original.png", "bytes": raw[1]},
                {"path": "first-original.png", "bytes": raw[0]},
            ], type=pa.struct([("path", pa.string()), ("bytes", pa.binary())])),
        })
        path = self.directory / "source.arrow"
        with pa.OSFile(str(path), "wb") as sink, ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        original = path.read_bytes()
        store = ImageStore(arrow_cache=path)
        try:
            self.assertEqual(store.read("case-first", "first-original.png"), raw[0])
            self.assertEqual(store.read("case-second", "second-original.png"), raw[1])
            with self.assertRaises(ValueError):
                store.read("case-first", "second-original.png")
            with self.assertRaises(FileNotFoundError):
                store.read("missing-case", "first-original.png")
        finally:
            store.close()
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            ImageStore(image_root=self.directory).read("case-first", "../outside.png")

    def test_soft_cross_entropy_uses_entire_probability_target(self):
        logits = torch.tensor([[1., -.4, .3], [.2, .9, -1.]], requires_grad=True)
        targets = torch.tensor([[.6, .3, .1], [.1, .65, .25]])
        original = targets.clone()
        actual = soft_label_cross_entropy(logits, targets)
        expected = -(targets * torch.log_softmax(logits, dim=1)).sum(dim=1).mean()
        torch.testing.assert_close(actual, expected)
        hard_loss = torch.nn.functional.cross_entropy(logits, targets.argmax(dim=1))
        self.assertFalse(torch.isclose(actual, hard_loss))
        actual.backward()
        self.assertTrue(torch.isfinite(logits.grad).all())
        torch.testing.assert_close(targets, original)
        with self.assertRaises(ValueError):
            soft_label_cross_entropy(logits, torch.tensor([[1., 1., 1.], [.2, .3, .5]]))

    def test_exact_fusion_dimensions_freezing_and_discriminative_learning_rates(self):
        """Frozen CNN blocks must keep both weights and BatchNorm statistics fixed."""
        model = MultimodalDermatologyModel(metadata_dim=12, num_classes=41, pretrained=False)
        self.assertEqual((model.image_projection[0].in_features,
                          model.image_projection[0].out_features), (576, 128))
        self.assertEqual((model.metadata_branch[0].in_features,
                          model.metadata_branch[0].out_features), (12, 64))
        self.assertEqual((model.metadata_branch[3].in_features,
                          model.metadata_branch[3].out_features), (64, 32))
        self.assertEqual((model.fusion_head[0].in_features,
                          model.fusion_head[0].out_features), (160, 128))
        self.assertEqual(model.fusion_head[-1].out_features, 41)
        self.assertEqual(model.image_projection[2].p, .3)
        self.assertEqual(model.metadata_branch[2].p, .2)
        self.assertEqual(model.fusion_head[2].p, .3)
        self.assertFalse(any(isinstance(layer, torch.nn.Softmax) for layer in model.modules()))

        config = TrainingConfig()
        optimizer = configure_optimizer(model, phase=1, config=config)
        self.assertEqual({group["name"]: group["lr"] for group in optimizer.param_groups},
                         {"fusion_head": 1e-3, "new_branches": 1e-4})
        self.assertTrue(all(group["weight_decay"] == 1e-4 for group in optimizer.param_groups))
        self.assertFalse(any(parameter.requires_grad for parameter in model.features.parameters()))
        model.train()
        frozen_bn = [layer for layer in model.features.modules() if isinstance(layer, torch.nn.BatchNorm2d)]
        self.assertTrue(frozen_bn)
        self.assertTrue(all(not layer.training for layer in frozen_bn))
        original_statistics = [layer.running_mean.clone() for layer in frozen_bn]
        with torch.no_grad():
            logits = model(torch.rand(2, 3, 224, 224), torch.rand(2, 12))
        self.assertEqual(tuple(logits.shape), (2, 41))
        for layer, original in zip(frozen_bn, original_statistics):
            torch.testing.assert_close(layer.running_mean, original)

        optimizer = configure_optimizer(model, phase=2, config=config)
        self.assertEqual({group["name"]: group["lr"] for group in optimizer.param_groups},
                         {"cnn_last_blocks": 1e-5, "new_layers": 1e-4})
        cutoff = len(model.features) - config.fine_tune_blocks
        for index, block in enumerate(model.features):
            self.assertTrue(all(parameter.requires_grad == (index >= cutoff)
                                for parameter in block.parameters()))
            self.assertEqual(block.training, index >= cutoff)
        parameters = [parameter for group in optimizer.param_groups for parameter in group["params"]]
        self.assertEqual(len(parameters), len({id(parameter) for parameter in parameters}))

    def test_validation_reports_soft_loss_and_imbalance_metrics_separately(self):
        """Hard argmax metrics supplement, rather than replace, soft-label loss."""
        class FixedLogits(torch.nn.Module):
            def forward(self, images, metadata):
                return metadata

        logits = torch.tensor([[3., 1., 0., -1.], [3., 2., 1., -1.], [3., 2., 4., -5.]])
        targets = torch.tensor([[.6, .3, .1, 0.], [.2, .6, .1, .1], [.1, .1, .1, .7]])
        batch = {"image": torch.zeros(3, 3, 8, 8), "metadata": logits, "target": targets}
        metrics = evaluate(FixedLogits(), [batch], target_classes=["A", "B", "C", "Other"])
        self.assertAlmostEqual(metrics["loss"], soft_label_cross_entropy(logits, targets).item(), places=6)
        self.assertAlmostEqual(metrics["top1_accuracy"], 1 / 3)
        self.assertAlmostEqual(metrics["top3_accuracy"], 2 / 3)
        self.assertAlmostEqual(metrics["soft_top1_mass"], .3, places=6)
        self.assertIsNone(metrics["per_class"][2]["recall"])
        self.assertEqual(metrics["per_class"][1]["recall"], 0)
        self.assertIn("macro_f1", metrics)
        self.assertIn("argmax", metrics["hard_metric_reference"])
        with self.assertRaises(ValueError):
            evaluate(FixedLogits(), [])

    def test_training_epoch_updates_new_layers_using_soft_targets(self):
        """Exercise actual autograd/AdamW without downloading or fine-tuning a CNN."""
        class TinyFusion(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.projection = torch.nn.Linear(5, 3)

            def forward(self, images, metadata):
                return self.projection(torch.cat((images.mean((2, 3)), metadata), dim=1))

        model = TinyFusion()
        original = model.projection.weight.detach().clone()
        batch = {"image": torch.rand(4, 3, 8, 8), "metadata": torch.rand(4, 2),
                 "target": torch.tensor([[.6, .3, .1]] * 4)}
        original_targets = batch["target"].clone()
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=1e-4)
        metrics = train_epoch(model, [batch], optimizer, "cpu")
        self.assertEqual(metrics["samples"], 4)
        self.assertTrue(np.isfinite(metrics["loss"]))
        self.assertFalse(torch.equal(original, model.projection.weight))
        torch.testing.assert_close(batch["target"], original_targets)
        with self.assertRaises(ValueError):
            train_epoch(model, [], optimizer)

    def test_early_stopping_restores_best_checkpoint_and_loads_without_download(self):
        """A later worse epoch must not become the exported model's parameters."""
        model = MultimodalDermatologyModel(metadata_dim=4, num_classes=3, pretrained=False)
        config = TrainingConfig(phase1_epochs=10, phase2_epochs=0,
                                early_stopping_patience=2, scheduler_patience=1)
        epoch = 0

        def fake_train(current, loader, optimizer, device):
            nonlocal epoch
            epoch += 1
            with torch.no_grad():
                next(current.parameters()).fill_(epoch)
            return {"loss": .8, "samples": 2}

        losses = iter([.9, .5, .6, .7, .8])

        def fake_validation(current, loader, device, classes):
            return {"loss": next(losses), "top1_accuracy": .5,
                    "top3_accuracy": 1., "macro_f1": .4, "samples": 2}

        with patch("scin_ml.training.train_epoch", side_effect=fake_train), \
                patch("scin_ml.training.evaluate", side_effect=fake_validation), \
                patch("builtins.print"):
            result = fit(model, [], [], self.directory / "experiment",
                         ["A", "B", "Other"], config=config)
        self.assertEqual(len(result.history), 4)
        self.assertEqual(result.best_epoch, 2)
        self.assertEqual(result.best_validation_loss, .5)
        self.assertTrue(torch.all(next(model.parameters()) == 2))
        self.assertTrue(result.checkpoint_path.is_file())
        with patch("scin_ml.model.mobilenet_v3_small", wraps=torchvision.models.mobilenet_v3_small) as constructor:
            restored, payload = load_checkpoint(result.checkpoint_path)
        self.assertIsNone(constructor.call_args.kwargs["weights"])
        self.assertEqual(payload["epoch"], 2)
        self.assertEqual(payload["target_classes"], ["A", "B", "Other"])
        for name, original in model.state_dict().items():
            torch.testing.assert_close(restored.state_dict()[name], original)
        self.assertFalse(restored.training)
        for name in ("training_config.json", "class_mapping.json", "history.json"):
            self.assertTrue((result.checkpoint_path.parent / name).is_file())
        with self.assertRaises(FileExistsError):
            fit(model, [], [], result.checkpoint_path.parent, ["A", "B", "Other"], config=config)

    def test_fine_tuning_starts_from_best_phase_one_and_preserves_global_best(self):
        """Switching optimizers must not discard a better earlier-phase model."""
        model = MultimodalDermatologyModel(metadata_dim=4, num_classes=3, pretrained=False)
        config = TrainingConfig(phase1_epochs=3, phase2_epochs=2)
        seen_parameters = []
        losses = iter([.9, .5, .6, .8, .7])

        def fake_train(current, loader, optimizer, device):
            seen_parameters.append(float(next(current.parameters()).flatten()[0]))
            with torch.no_grad():
                next(current.parameters()).fill_(len(seen_parameters))
            return {"loss": .8, "samples": 2}

        def fake_validation(current, loader, device, classes):
            return {"loss": next(losses), "top1_accuracy": .5,
                    "top3_accuracy": 1., "macro_f1": .4}

        with patch("scin_ml.training.train_epoch", side_effect=fake_train), \
                patch("scin_ml.training.evaluate", side_effect=fake_validation), \
                patch("builtins.print"):
            result = fit(model, [], [], self.directory / "two-phases",
                         ["A", "B", "Other"], config=config)
        self.assertEqual([record["phase"] for record in result.history], [1, 1, 1, 2, 2])
        self.assertEqual(seen_parameters[3], 2)
        self.assertEqual(result.best_epoch, 2)
        self.assertEqual(result.best_validation_loss, .5)
        self.assertTrue(torch.all(next(model.parameters()) == 2))

    def test_missing_primary_requires_explicit_non_destructive_exclusion(self):
        """The primary-image limitation must remain visible in saved split reports."""
        artifacts = self.artifacts()
        artifacts.images.loc[artifacts.images.index[0], "image_1_path"] = None
        path = self.directory / "cleaned.pkl"
        path.write_bytes(pickle.dumps({
            "X_metadata": artifacts.metadata, "X_images": artifacts.images,
            "Y": artifacts.labels, "target_classes": list(artifacts.classes),
        }))
        original = path.read_bytes()
        output = self.directory / "prepared"
        with self.assertRaisesRegex(ValueError, "exclude_missing_primary"):
            prepare_data(path, output)
        self.assertFalse(output.exists())
        with patch("scin_ml.pipeline.ImageStore.validate") as validate_images:
            prepared = prepare_data(path, output, exclude_missing_primary=True)
        try:
            self.assertEqual(sum(map(len, prepared.splits.values())), 40)
            self.assertEqual(sum(map(len, prepared.usable_splits.values())), 39)
            self.assertEqual(len(validate_images.call_args.kwargs["indices"]), 39)
            self.assertEqual(len(prepared.report["excluded_missing_primary"]), 1)
            self.assertTrue(prepared.report["exclusion_explicitly_enabled"])
            self.assertEqual(path.read_bytes(), original)
            for name in ("split_manifest.json", "data_report.json", "metadata_encoder.json"):
                self.assertTrue((output / name).is_file())
        finally:
            prepared.image_store.close()

    def test_actual_two_phase_checkpoint_export_and_inference_round_trip(self):
        """Train two tiny synthetic batches, then use a standalone verified bundle."""
        artifacts = self.artifacts()
        encoder = MetadataEncoder().fit(artifacts.metadata)
        run = self.directory / "actual-training"
        run.mkdir()
        encoder_path = run / "metadata_encoder.json"
        encoder.save(encoder_path)
        model = MultimodalDermatologyModel(encoder.output_dim, 41, pretrained=False)
        classes = [f"diagnosis-{index:02}" for index in range(41)]
        targets = torch.zeros(2, 41)
        targets[:, [0, 1, 40]] = torch.tensor([.6, .3, .1])
        batch = {"image": torch.rand(2, 3, 224, 224),
                 "metadata": torch.from_numpy(encoder.transform(artifacts.metadata.iloc[:2])),
                 "target": targets}
        config = TrainingConfig(phase1_epochs=1, phase2_epochs=1, fine_tune_blocks=1)
        with patch("builtins.print"):
            result = fit(model, [batch], [batch], run, classes, config=config,
                         metadata_encoder_path=encoder_path)
        self.assertEqual(len(result.history), 2)
        self.assertTrue(np.isfinite(result.best_validation_loss))
        destination = self.directory / "app-model"
        self.assertEqual(export_for_app(run, destination), destination)
        predictor = SCINPredictor(destination)
        metadata = artifacts.metadata.iloc[0].to_dict()
        for name in CATEGORICAL_COLUMNS:
            metadata[name] = "unseen-at-inference"
        image = Image.new("RGB", (80, 40), (140, 110, 90))
        prediction = predictor.predict(image, metadata, top_k=3)
        ranked = prediction["probabilities"]
        self.assertEqual(len(ranked), 41)
        self.assertEqual(prediction["top_predictions"], ranked[:3])
        self.assertAlmostEqual(sum(item["probability"] for item in ranked), 1., places=6)
        self.assertEqual([item["rank"] for item in ranked], list(range(1, 42)))
        self.assertEqual({item["diagnosis_name"] for item in ranked}, set(classes))
        self.assertEqual([item["probability"] for item in ranked],
                         sorted((item["probability"] for item in ranked), reverse=True))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        self.assertEqual(predictor.predict(stream.getvalue(), metadata), prediction)
        with self.assertRaises(ValueError):
            predictor.predict(image, metadata, top_k=0)
        with self.assertRaises(ValueError):
            predictor.predict(image, {}, top_k=3)
        with self.assertRaises(FileExistsError):
            export_for_app(run, destination)

        mapping_path = destination / "class_mapping.json"
        original_mapping = mapping_path.read_bytes()
        mapping = json.loads(mapping_path.read_text())
        mapping["target_classes"] = list(reversed(classes))
        mapping_path.write_text(json.dumps(mapping))
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["class_mapping.json"] = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "class mapping"):
            SCINPredictor(destination)

        encoder_path = destination / "metadata_encoder.json"
        encoder_path.write_bytes(encoder_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            SCINPredictor(destination)

        # Even a same-width replacement encoder with a refreshed bundle checksum
        # must disagree with the encoder hash bound inside the trained checkpoint.
        mapping_path.write_bytes(original_mapping)
        manifest["files"]["class_mapping.json"] = hashlib.sha256(original_mapping).hexdigest()
        encoder_document = json.loads(encoder_path.read_text())
        encoder_document["categories"][0][0] = "substituted-vocabulary"
        encoder_path.write_text(json.dumps(encoder_document))
        manifest["files"]["metadata_encoder.json"] = hashlib.sha256(encoder_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "training-fitted metadata encoder"):
            SCINPredictor(destination)


if __name__ == "__main__":
    unittest.main()
