# Omar's inference integration seam

The user-selected `notebooks/SCIN_custom_model.keras` is connected through `backend/ai/local_adapter.py:SCINModelAdapter`. `MODEL_PATH` selects the local saved model; explicitly setting it to an empty string restores **AI integration pending**. Submission never requests AI. Explicit clinician POST `/cases/<case_id>/analyze` returns 503 while unconfigured and creates no attempt. Model/runtime failures remain independent of manual review. No model is trained, downloaded or modified by this integration, and no clinical decision policy is invented.

## Exact interface

`backend/ai/adapter.py` defines frozen dataclasses and a Protocol:

```python
class Adapter(Protocol):
    model_name: str
    model_version: str
    prompt_version: str
    def analyze_case(self, input: AnalysisInput) -> AnalysisOutput: ...
```

- `AnalysisInput(contract_version, case_id, complaint, duration_days, age, sex, symptoms, lesions, submitted_at, model_metadata={})`.
- `LesionInput(lesion_id, body_site, images: tuple[ImageInput, ...])`.
- `ImageInput(image_id, storage_reference, sha256, mime_type, quality)`.
- `AnalysisOutput(model_name, model_version, prompt_version, triage_level, summary, rationale, limitations, candidates=(), image_quality={})`.
- `Candidate(diagnosis_name, rank, confidence=None, rationale=None)`.

Use `not-applicable` for a nonprompted CNN's prompt version. Adapter metadata is required before starting an attempt and must match its output. Confidence is nullable, finite and within [0,1]; candidate ranks must be consecutive in order from 1. Do not invent confidence, call uncalibrated scores validated probabilities, or automate clinician treatment decisions. SQL priority uses red/amber/green/undetermined. The optional `assisted_triage` dictionary carries emergency/urgent/routine, reasons, manual-review flag and method; validation requires consistency with SQL priority. The local adapter uses the user-authorized illustrative policy described in README; its configurable 0.5 score threshold flags uncertainty only and is unvalidated. Output quality keys must identify images in that exact input and use unassessed/acceptable/poor.

`backend/services.py:CaseWorkflow(identity).build_analysis_input(case_id)` constructs the request from authorized server-side records, preserving NULL symptoms. It verifies image hashes against stored bytes. Names/contact/DOB are not included; age and sex are available context. `storage_reference` is a permanent server-generated filename relative to the configured private upload root, never a client path, URL or image binary. Pass a configured ImageStorage reader into your adapter constructor; the worker has no Flask request/application context. Respect the immutable input and exact bytes; never log intake or images.

`model_metadata` is a backward-compatible optional field for existing v1.0 callers. The local adapter validates provider-supplied supplemental answers and returns a replaced request with `contract_version='1.1'`. Its complete `model_metadata` mapping is included in that attempt's encrypted immutable input snapshot; submitted symptoms and demographics remain unchanged. This uses existing AIAnalysis JSON storage and requires no schema migration.

## Run the selected saved model

Keep these three existing files together:

- `notebooks/SCIN_custom_model.keras`.
- `notebooks/SCIN_custom_metadata_encoder.json`.
- `notebooks/SCIN_custom_classes.json`.

The selected model produces 14 grouped-condition scores. Its encoder requires 31 binary answers and five categorical fields (`age_group`, `sex_at_birth`, `fitzpatrick_skin_type`, `related_category`, `condition_duration`), yielding 68 encoded inputs. Patients can now save the answers with draft intake and submission. Sex at birth maps the existing canonical profile sex per Omar's explicit instruction; age group derives from birthday at the case submission date, using AGE_UNKNOWN when DOB is missing or the age is outside the trained 18–79 range. Duration uses the offered saved categories directly. No body location, skin type or unreported symptom is guessed.

Checkboxes encode checked=Yes. Explicit group confirmation makes unchecked=No;
without confirmation, unanswered choices remain NULL and prior No values remain
No. `Symptom.encrypted_answers` keeps the six original values and a nested
`model_metadata` mapping, using its existing authenticated encryption. Older
six-answer records need no rewrite or SQL migration. Submitted cases remain
frozen. The clinician form reuses recorded answers as read-only controls and asks
only for missing model inputs. Supplemental answers cannot contradict recorded
patient answers; missing binary values still block inference but never manual
submission/review. Each attempt keeps its exact complete encrypted input snapshot.

Install the tested optional runtime when missing, then launch from the repository root:

```sh
.venv/bin/python -m pip install -r requirements-inference.txt
MODEL_PATH=notebooks/SCIN_custom_model.keras ./run-local.sh
# Disable inference while keeping patient submission and clinical review:
MODEL_PATH='' ./run-local.sh
```

`.env` is not autoloaded. `run-local.sh` selects the saved model and `AI_TIMEOUT_SECONDS=60`; shell environment settings take precedence. TensorFlow/Keras and model weights load lazily on the first explicit authorized request. Missing companion artifacts leave an unavailable notice; execution failures produce sanitized failed attempts. The adapter fingerprints weights, encoder, classes, optional contracts and input policy for model-version provenance. Changing any selected file requires a restart rather than silently replacing a running model.

The optional dependency file pins the already-installed TensorFlow 2.22.0rc0,
Keras 3.15.1 and NumPy 2.5.4; TensorFlow is a release candidate in this tested
Python 3.14 environment. No dependency installation or model download occurred.

The image reader authenticates/decrypts originals in memory. `model_interface` applies saved preprocessing and averages probabilities across the case's images. The bridge returns all 14 groups as ranked, unconfirmed `Candidate` scores, then calls `triage_case` with those scores and structured answers. The separate policy never changes model tensors, scores or clinician decisions. Scores are uncalibrated; free-text complaints/notes are not embedded and image quality is not classified. Patients continue to see only clinician-released outcomes.

The optional triage output persists inside a versioned `paliderm-triage-v1` JSON envelope in the existing encrypted AIAnalysis.rationale field, alongside the original narrative. CaseWorkflow unwraps it for presentation. Legacy narrative strings remain supported, and immutable input snapshots are unchanged. Completed prior attempts are not retroactively reclassified. The model bundle version includes the triage policy version and configured uncertainty threshold. See README for exact editable rules/mappings and the manual-review display convention. This is prototype prioritization, not validated emergency screening or automated treatment.

## Keep the replaceable adapter seam

Create your own implementation module and a local entry point, for example `local_inference.py`:

```python
from backend.images import ImageStorage
from app import create_app
from your_module import OmarAdapter  # your code; no vendor is chosen here

app = create_app({'MODEL_PATH': ''})
app.config['AI_ADAPTER'] = OmarAdapter(
    image_reader=ImageStorage(app.config, app.extensions['cipher'])
)
app.config['AI_TIMEOUT_SECONDS'] = 60
```

Then launch a **single** local process:

```sh
.venv/bin/python -m flask --app local_inference:app run --host 127.0.0.1 --port 5000
```

In your `analyze_case`, use `self.image_reader.read_original(image.storage_reference, image.sha256)` to obtain authenticated decrypted source bytes in memory, run your inference and return the declared dataclasses. Put heavy ML imports/loading in your implementation, preferably lazily, not in this application's default startup. Keep any preprocessing/model versions explicit. Return nullable confidence if unavailable. Do not train from uploads or clinician-independent guesses. Submission consent is not training consent.

The module-level `adapter` object in `adapter.py` documents the unconfigured default; the live injected instance is `app.config['AI_ADAPTER']`. Use that configuration seam, rather than changing frontend calls.

## Attempt orchestration and limits

`backend/ai/runner.py:run_analysis(case_id, identity, adapter, analysis_base, timeout, *, supplemental=None)` performs:

1. Authorization, submitted-case access, configured adapter/metadata check.
2. Server-built input and optional adapter `prepare_input` validation of supplemental provider answers, before creating an attempt. Then the exact `dataclasses.asdict` UTF-8 JSON snapshot is stored inside an encrypted JSON envelope, followed by pending and running-state commits.
3. Invoke outside all SQLite transactions with a configured timeout.
4. Validate the entire output, then atomically commit completed result, candidates and supplied image quality. Do not write any clinician Diagnosis or TreatmentPlan from AI.
5. On invalid output/exception/timeout, store failed/completed_at and a sanitized code. Older successful results remain visible separately from newest attempt status. Clinical review remains independent.

The form carries `analysis_base` (newest attempt ID, 0 if none). Reposting a stale request returns existing history without another attempt. An intentional retry uses the latest form and creates a new row. Repeated **case submissions** never schedule AI. Current runner is synchronous from the clinician's perspective and intentionally supports one bounded daemon inference worker per local process. Python cannot forcibly stop a stuck thread; a timed-out worker retains the single slot until it actually exits. Further requests receive an explicit busy error, avoiding unbounded stuck workers. Restart is the recovery for a permanently stuck adapter. A late result is discarded after timeout. Production job scheduling/cancellation and multiple workers are not implemented.

Startup changes interrupted pending/running attempts to failed with `error_message=interrupted` and a UTC completion time. The clinician explicitly retries. Run one process without Flask debug/reloader: concurrent application factories/processes could misidentify another process's live attempt as interrupted. This is a local demonstration runner, not a distributed job system.

`tests/fixtures.py:FixtureAdapter` is deterministic, developer-only, and never imported or selectable by default in the app. Every output/model name is marked **SIMULATED AI — not model inference**. Fixture-based contract, failure/retry, invalid output, quality rollback, timeout and interrupted-history checks do not establish real inference or clinical validation. Actual checks and remaining acceptance requirements are tracked separately in `docs/TEST_RESULTS.md`.

## Contract example

This illustrates the backward-compatible base v1.0 input, not an actual inference result or a usable hash/storage identifier. The configured local model's v1.1 input additionally contains every provider-supplied model field under `model_metadata`. Real snapshots are always built on the server and have the real source hash. No image bytes belong in JSON.

```json
{
  "contract_version": "1.0",
  "case_id": 1,
  "complaint": "Synthetic complaint only",
  "duration_days": null,
  "age": 36,
  "sex": "unknown",
  "symptoms": {
    "itching": null,
    "pain": 0,
    "bleeding": null,
    "discharge": null,
    "fever": null,
    "rapidly_worsening": null,
    "additional_notes": "ملاحظات تجريبية"
  },
  "lesions": [{
    "lesion_id": 1,
    "body_site": "arm",
    "images": [{
      "image_id": 1,
      "storage_reference": "<server-generated UUID>.png",
      "sha256": "<64 hexadecimal characters hashing exact decrypted original bytes>",
      "mime_type": "image/png",
      "quality": "unassessed"
    }]
  }],
  "submitted_at": "2026-10-10T18:00:00.000000Z"
}
```

Example Python output shape, with all content supplied by your adapter:

```python
AnalysisOutput(
    model_name=self.model_name,
    model_version=self.model_version,
    prompt_version=self.prompt_version,
    triage_level='undetermined',
    summary=adapter_summary,
    rationale=adapter_rationale,
    limitations=adapter_limitations,
    candidates=(),  # or ordered Candidate values, with nullable confidence
    image_quality={},
)
```

General emergency guidance is independent of this module. `backend/safety.py` defines a separate policy protocol, but automatic screening is intentionally unconfigured pending agreed fields, clinical policy and structured persistence. Do not implement screening rules from descriptive white-paper examples without that agreement.

## Original source-image handling update

New sources are now exact JPEG/PNG originals with metadata retained at the user's request, while older normalized PNGs remain supported. Resolve the server-provided reference and use its supplied MIME/hash; do not assume every source is PNG. No app-level pixel cap/downscaling is applied. If inference needs orientation normalization/resizing, retain the original, version/document your preprocessing and preserve source/transform provenance; do not change the snapshot's hash to describe different bytes. Source metadata is not automatically extracted into AnalysisInput or clinical/epidemiology fields. Browser live captures may lack EXIF/GPS.

## Encrypted source compatibility

The Adapter and AnalysisOutput contracts are preserved; AnalysisInput adds only the optional `model_metadata` field described above. Storage references point to encrypted private files, and their SHA-256 values identify exact decrypted original bytes. Do not open these files directly with Pillow/a model. Inject an ImageStorage reader initialized with the startup-verified cipher; `read_original(reference, expected_hash)` authenticates/decrypts into memory without a plaintext temporary file. A standalone worker can construct Cipher.from_config from its own environment and pass it to ImageStorage. The local bridge already uses this reader, after the runner's role/ownership checks.

`sex` remains female/male/unknown in the encrypted profile, now labeled sex at birth per Omar's request. `SCINQuestionnaire` maps it to FEMALE/MALE/OTHER_OR_UNSPECIFIED for this saved model. Existing `gender_one_hot(input.sex)` and `symptom_vector(input.symptoms)` helpers retain their interfaces and do not impute unknown binary symptoms. Old snapshots remain historically exact inside encrypted storage. Patient and supplemental answers and analysis narratives use authenticated encrypted persistence; timeout/retry/history behavior remains intact.
