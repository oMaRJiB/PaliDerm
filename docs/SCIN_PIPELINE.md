# SCIN primary-image + metadata pipeline

The current user explicitly authorized this ML implementation. It consumes the
existing `notebooks/SCIN_cleaned.pkl` without repeating EDA, cleaning, label
selection, or modifying the existing encoder/image exports. Flask and its typed
AI adapter remain independent and unconfigured.

## Run

From the repository root, using the existing Python 3.14 environment:

```sh
.venv/bin/python -m pip install -r requirements-ml.txt
.venv/bin/python -m scin_ml --output-dir notebooks/scin_runs/my_run --exclude-missing-primary
```

Alternatively, select the existing `.venv` kernel and run
`notebooks/SCIN_MODEL.IPYNB` sequentially. Its original three cells are preserved;
the new cells cover setup, split/encoding, model, training, evaluation, app export,
and inference. New notebook runs choose a timestamped directory. Existing
checkpoint/output directories are preserved; choose a different directory for a
new experiment. Stop a foreground training command with Ctrl-C. Each completed
improving epoch saves its best checkpoint atomically. Interrupted runs are not
automatically resumed; their finished checkpoints remain loadable.

Defaults: seed 42, batch 32, 224px, five frozen-backbone epochs, fifteen final-block
fine-tuning epochs, validation-loss early stopping patience 5 per phase. Override
`--phase1-epochs`, `--phase2-epochs`, `--batch-size`, `--seed`, `--device`,
`--num-workers`, `--image-root`, or `--arrow-cache` explicitly. `auto` selects CUDA,
then Apple MPS, then CPU. Notebook workers default to zero for portability.
Official ImageNet weights are downloaded only if absent from `.cache/torch/hub`;
there is no random-weight fallback for training. Checkpoint inference downloads
nothing. Optional ML dependencies are separate from Flask dependencies.

## Existing artifacts and alignment

There are 3,061 labeled rows and 41 distinct output classes in the exact exported
order. `Y` contains soft dermatologist-weighted distributions. The loader checks
probability ranges/sums, matching metadata/image indexes and output shape. It
never hardens, reselects or renormalizes labels. ndarray-label order follows the
EDA export's provenance; an arbitrarily reordered external ndarray cannot be
independently realigned without case IDs attached to it.

Two group-shuffle splits produce 2,142/459/460 rows with seed 42. Full manifests
save positions, source indexes, case IDs and primary-image references. Whole
case groups cannot cross splits. Every batch uses one shared source position for
its image, metadata and target.

**One existing case lacks image_1:** `-1834609919572055750` (source index 270,
position 163). The default library behavior stops. The CLI flag/notebook setting
explicitly records its exclusion from image-based training/evaluation; the
original row stays in the unchanged artifact and complete split manifest. No
secondary image is substituted. Usable counts with seed 42 are 2,142/458/460.

The 31 encoded binary features stay unchanged. OneHotEncoder learns only from
usable training rows for age_group, sex_at_birth, fitzpatrick_skin_type,
related_category and condition_duration. Unknown categories safely yield zero
for that category block. Missing/invalid binary answers raise rather than
inventing negatives. This run's encoder has 68 outputs. Its JSON artifact records
column/category ordering and avoids executable encoder serialization.

The prior `notebooks/model_artifacts/` files remain untouched. Their numbered
images have no independent case/filename manifest, and their encoder was not
established as train-only, so the new pipeline does not assume they are suitable.
Original primary images are read by case ID **and** filename from the existing
local SCIN Arrow cache, or by original filename under an explicit image root.
Arrow memory maps avoid copying/downloading the full dataset. Missing or
mismatched images fail; no placeholder images or multi-image fusion are used.

Images are EXIF-oriented, converted to RGB, bilinearly resized with aspect ratio
preserved, centered on a black 224×224 pad and normalized using ImageNet mean/std.
Original image bytes are never overwritten. Training and inference share this
exact deterministic transform; no extra augmentations are introduced.

## Model, training and metrics

`scin_ml/model.py`: pretrained MobileNetV3-Small features + global average pool
(576); image projection 576→128/ReLU/Dropout 0.3; metadata input→64/ReLU/Dropout 0.2→32/ReLU;
fusion 160→128/ReLU/Dropout 0.3→41 logits. Softmax runs only for inference.

`scin_ml/training.py`: validated soft-label cross entropy
`-(Y * log_softmax(logits)).sum(-1).mean()`, equivalent to probability-target
CrossEntropyLoss. No BCE, one-hot replacement, invented class weights or extra
label smoothing. AdamW weight decay 1e-4. Phase 1 freezes every CNN block and its
BatchNorm running statistics; fusion-head LR 1e-3, image/metadata branches 1e-4.
Phase 2 restores the phase-one best and unfreezes final feature blocks 10–12:
CNN LR 1e-5; new layers 1e-4. ReduceLROnPlateau factor 0.5/patience 2. Each phase has
early-stopping patience 5; checkpoint selection remains global. The final model
restores the lowest validation-loss weights across both phases.

Primary metric is validation soft-label loss. Top-1/top-3 and per-class
precision/recall/F1 use the maximum-weight dermatologist class as a reporting
reference only. Macro metrics and expected soft-label mass retained in top-1/top-3
supplement accuracy. Absent-class recall/F1 are null; precision is null if a class
was never predicted. Read per-class support before interpreting rare-class
results. Test data is evaluated after checkpoint selection, not during training.
Softmax scores are uncalibrated; this run provides no clinical validation.

## Saved files and app access

Each run saves:

- `split_manifest.json`, `data_report.json`, `metadata_encoder.json`;
- `best_model.pt`, `training_config.json`, `class_mapping.json`, `history.json`;
- `best_validation_metrics.json`, `validation_metrics.json`, `test_metrics.json`;
- `app_model/`: best model plus encoder/classes/config and consistency manifest.

Checkpoints contain state dictionaries and primitives and use Torch's restricted
`weights_only=True` loader. The encoder hash is bound into the checkpoint;
bundle hashes catch accidental mismatches, not malicious tampering. Load only
locally trusted model artifacts. Artifact writes/export preserve existing runs.

```python
from scin_ml.inference import SCINPredictor

predictor = SCINPredictor("notebooks/scin_runs/my_run/app_model", device="cpu")
result = predictor.predict(image_bytes, complete_scin_metadata, top_k=3)
# result["probabilities"]: all 41 ranked diagnosis_name/probability/class_index/rank
# result["top_predictions"]: requested top predictions
```

`image_bytes` may be authorized decrypted bytes from the existing ImageStorage,
a PIL image, local path or file-like object. No plaintext cache is required.
`complete_scin_metadata` supplies all 31 saved binary features and five SCIN
categorical names; `metadata_encoder.json` defines that exact schema. Categories
must use SCIN's values, not the application's sex display labels. Missing binary
features are rejected rather than fabricated. The current app has a smaller
questionnaire and no established mapping for all SCIN features, so automatic
Flask integration is pending that explicit mapping. The typed adapter, clinical
review workflow and unavailable-AI behavior are unchanged.

## Modules and checks

- `data.py`: artifact checks, grouped splits, train-fitted encoder, image reader/transform/dataset.
- `pipeline.py`: setup, eligibility policy, manifests and aligned DataLoaders.
- `model.py`: exact late-fusion network and frozen-block behavior.
- `training.py`: optimization, train/validation/evaluation loops, checkpoint I/O.
- `inference.py`: verified standalone app export and ranked prediction.
- `__main__.py`: reproducible command-line experiment using the same modules.

Run `.venv/bin/python -m unittest tests.test_scin_pipeline -v` for focused ML
checks or `.venv/bin/python -m unittest discover -s tests -v` for app regressions.
ML checks use explicitly random test weights and synthetic images; real training
results are reported separately. They do not require a pretrained download.

Primary references: [torchvision MobileNetV3-Small](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.mobilenet_v3_small.html),
[probability-target cross entropy](https://docs.pytorch.org/docs/stable/generated/torch.nn.CrossEntropyLoss.html),
[ReduceLROnPlateau](https://docs.pytorch.org/docs/stable/generated/torch.optim.lr_scheduler.ReduceLROnPlateau.html).

## Actual local run — 2026-10-11

Command executed successfully with official pretrained ImageNet weights on Apple MPS:

```sh
.venv/bin/python -m scin_ml --artifact notebooks/SCIN_cleaned.pkl --output-dir notebooks/scin_runs/run_20261011_mps --exclude-missing-primary --device mps
```

All **20 epochs** completed (5 frozen + 15 fine-tuned); the lowest validation-loss
checkpoint was epoch **20**, restored before evaluation/export.

| Metric | Validation (458 cases) | Test (460 cases) |
|---|---:|---:|
| Soft-label cross entropy | 2.836584 | 2.854048 |
| Top-1 accuracy | 26.86% | 23.04% |
| Top-3 accuracy | 53.28% | 54.78% |
| Macro-F1 over supported classes | 0.026275 | 0.024093 |
| Expected soft-label top-3 mass | 0.492348 | 0.476619 |

Macro-F1 is low: the higher top-3 accuracy does not establish reliable performance
across the rare diagnoses. Full per-class precision/recall/F1/support and confusion
matrices are in `validation_metrics.json` and `test_metrics.json` beside the model.
No calibration or clinical-validation claim is made.

Saved application model:
`notebooks/scin_runs/run_20261011_mps/app_model/best_model.pt`.
Load its complete bundle with
`SCINPredictor("notebooks/scin_runs/run_20261011_mps/app_model")`.
Actual standalone CPU loading and prediction from an original SCIN image plus
metadata passed: 41 ranked finite scores summing to one, top-3 results, and exact
repeatability after loading a fresh model instance. No source cache is required
to load the model; only the verification sample reader used the cache.
`verification.json` records these results, and `environment.json` records the
installed versions (Torch 2.14.1, torchvision 0.29.1, NumPy 2.5.4, pandas 3.0.6,
scikit-learn 1.9.1, PyArrow 26.0.0, Pillow 12.3.0).

**65 tests PASS in 22.560 seconds**, including the 50 unchanged app regressions and
15 ML checks. `compileall`, `pip check` and `git diff --check` also passed. EDA and
cleaned pickle SHA-256 values remain unchanged, and the original three model
notebook cells remain unchanged. No original preprocessing exports were written.
One initial CPU probe was stopped before its first checkpoint to use the GPU;
its separate output directory is explicitly marked interrupted.
