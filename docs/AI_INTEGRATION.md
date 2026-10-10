# Omar's inference integration seam

Default behavior is **AI integration pending**. Submission does not request AI. Explicit clinician POST `/cases/<case_id>/analyze` returns 503 while unconfigured and creates no attempt. The frontend has no model/vendor/key/framework coupling. No trained model, vendor, probabilities or clinical policy has been selected for you.

## Exact interface

`backend/ai/adapter.py` defines frozen dataclasses and a Protocol:

```python
class Adapter(Protocol):
    model_name: str
    model_version: str
    prompt_version: str
    def analyze_case(self, input: AnalysisInput) -> AnalysisOutput: ...
```

- `AnalysisInput(contract_version, case_id, complaint, duration_days, age, sex, symptoms, lesions, submitted_at)`.
- `LesionInput(lesion_id, body_site, images: tuple[ImageInput, ...])`.
- `ImageInput(image_id, storage_reference, sha256, mime_type, quality)`.
- `AnalysisOutput(model_name, model_version, prompt_version, triage_level, summary, rationale, limitations, candidates=(), image_quality={})`.
- `Candidate(diagnosis_name, rank, confidence=None, rationale=None)`.

Use `not-applicable` for a nonprompted CNN's prompt version. Adapter metadata is required before starting an attempt and must match its output. Confidence is nullable, finite and within [0,1]; candidate ranks must be consecutive in order from 1. Do not invent confidence, call uncalibrated scores validated probabilities, or automate clinician treatment decisions. Triage uses only red/amber/green/undetermined. Missing/uncertain results should be visibly disclosed; no application clinical confidence threshold exists. Output quality keys must identify images in that exact input and use unassessed/acceptable/poor.

`backend/services.py:build_analysis_input(case_id, identity)` constructs the request from authorized server-side records, preserving NULL symptoms. It verifies image hashes against stored bytes. Names/contact/DOB are not included; age and sex are available context. `storage_reference` is a permanent server-generated filename relative to the configured private upload root, never a client path, URL or image binary. Pass this private root into your adapter constructor; the worker has no Flask request/application context. Respect the immutable input and exact bytes; never log intake or images.

## Plug in inference without changing the frontend

Create your own implementation module and a local entry point, for example `local_inference.py`:

```python
from pathlib import Path
from app import create_app
from your_module import OmarAdapter  # your code; no vendor is chosen here

app = create_app()
app.config['AI_ADAPTER'] = OmarAdapter(
    upload_root=Path(app.config['UPLOAD_DIR'])
)
app.config['AI_TIMEOUT_SECONDS'] = 30
```

Then launch a **single** local process:

```sh
.venv/bin/python -m flask --app local_inference:app run --host 127.0.0.1 --port 5000
```

In your `analyze_case`, resolve only the server-provided storage references under the private root, verify/consume the specified bytes, run your inference and return the declared dataclasses. Put heavy ML imports/loading in your implementation, preferably lazily, not in this application's default startup. Keep any preprocessing/model versions explicit. Return nullable confidence if unavailable. Do not train from uploads or clinician-independent guesses. Submission consent is not training consent.

The module-level `adapter` object in `adapter.py` documents the unconfigured default; the live injected instance is `app.config['AI_ADAPTER']`. Use that configuration seam, rather than changing frontend calls.

## Attempt orchestration and limits

`backend/ai/runner.py:run_analysis(case_id, identity, adapter, analysis_base, timeout)` performs:

1. Authorization, submitted-case access, configured adapter/metadata check.
2. Server-built input, exact `dataclasses.asdict` UTF-8 JSON snapshot, pending attempt commit, then running-state commit.
3. Invoke outside all SQLite transactions with a configured timeout.
4. Validate the entire output, then atomically commit completed result, candidates and supplied image quality. Do not write any clinician Diagnosis or TreatmentPlan from AI.
5. On invalid output/exception/timeout, store failed/completed_at and a sanitized code. Older successful results remain visible separately from newest attempt status. Clinical review remains independent.

The form carries `analysis_base` (newest attempt ID, 0 if none). Reposting a stale request returns existing history without another attempt. An intentional retry uses the latest form and creates a new row. Repeated **case submissions** never schedule AI. Current runner is synchronous from the clinician's perspective and intentionally supports one bounded daemon inference worker per local process. Python cannot forcibly stop a stuck thread; a timed-out worker retains the single slot until it actually exits. Further requests receive an explicit busy error, avoiding unbounded stuck workers. Restart is the recovery for a permanently stuck adapter. A late result is discarded after timeout. Production job scheduling/cancellation and multiple workers are not implemented.

Startup changes interrupted pending/running attempts to failed with `error_message=interrupted` and a UTC completion time. The clinician explicitly retries. Run one process without Flask debug/reloader: concurrent application factories/processes could misidentify another process's live attempt as interrupted. This is a local demonstration runner, not a distributed job system.

`tests/fixtures.py:FixtureAdapter` is deterministic, developer-only, and never imported or selectable by default in the app. Every output/model name is marked **SIMULATED AI — not model inference**. Contract, failure/retry, invalid output, quality rollback, timeout and interrupted-history tests are software tests only; AT-05 remains blocked on actual inference.

## Contract example

This is illustrative JSON, not an actual inference result or a usable hash/storage identifier. Real snapshots are always built on the server and have the real source hash. No image bytes belong in JSON.

```json
{
  "contract_version": "1.0",
  "case_id": 1,
  "complaint": "Synthetic complaint only",
  "duration_days": null,
  "age": 36,
  "sex": null,
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
      "sha256": "<64 hexadecimal characters hashing exact stored PNG bytes>",
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
