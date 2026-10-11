# PaliDerm branding and Arabic interface — 2026-10-11

This update supersedes earlier Arabic-translation-pending statements below;
historical checks and individual AT-01 through AT-12 results are preserved.
Visible app wording now uses PaliDerm without “prototype”. The synthetic-use,
clinical-validation and response-time disclaimer remains, together with emergency
guidance and required clinician review, in both languages. No model, notebook,
training artifact, database schema, clinical policy or dependency was changed.

- `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_localization test_presentation test_triage test_ai_runner test_workflow test_auth test_encryption test_intake test_local_model_adapter -q`:
  **100 tests PASS in 34.677s**. Eight localization tests cover complete matching
  348-key EN/AR catalogs and placeholders, CSRF/safe locale redirects, session and
  language retention, Arabic patient/clinician pages, technical-field validation,
  exact encrypted Arabic text after restart, unchanged stored English identifiers,
  and display-only translation of current/historical AI labels and narratives.
  Existing ownership, image, encryption, intake, triage, AI and review tests pass.
- `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=.cache/matplotlib TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 .venv/bin/python -B tests/live_smoke.py --with-model`:
  **PASS** with approved loopback access. Actual HTTP signup/login/intake, two
  images, consent, assignment, existing saved-model inference, Arabic RTL report
  and English switching, review/treatment/referral and patient release passed.
  An actual child-process restart preserved encrypted answers, predictions,
  triage, exact Arabic clinical text and identical image bytes. The disclaimer
  remains present and reports contain no visible “prototype” wording. Temporary
  synthetic test records only; normal demo records were untouched.
- `tests/forms_smoke.mjs` executed in the Node runtime: **PASS** for timestamp
  UTC parsing/device-timezone/DST behavior, named-action assignment, form error
  recovery/retry/duplicate prevention, navigation, close confirmation and image
  previews/removal. These use DOM doubles, not a real browser. Native HTML pattern
  checks accept Latin email/phone examples and reject Arabic email/phone digits.
- CSS checks passed; primary green/white contrast is **7.36:1**. Green, black,
  white and restrained red accents retain labeled clinical priority distinctions.
- The active server was restarted with preserved data/key on **127.0.0.1:5000**,
  background PID **9580**, debug off. A read-only HTTP login/language-switch check
  passed against that server. `git diff --check` passed. No deployment or push.

Only usernames/email addresses and phone digits require Latin/0–9 characters.
Names, passwords and authored clinical text support Unicode; user text is never
automatically translated or rewritten. Stored schema/API/enums/model labels remain
English; known generated labels/notices are translated only when displayed.
Language selection is available before and after login and works without JavaScript.

Remaining limitations: real browser/device Arabic RTL, keyboard, screen-reader and
camera visual/hardware verification are **NOT RUN** because Computer Use access
was unavailable. Complete Arabic support and clinical validation are not claimed.
Worker access/attribution, medical history, durable submission revisions and
production hardening remain pending as documented in earlier acceptance tracking.

Files changed: `AGENTS.md`, `implementation.md`, `README.md`,
`docs/TEST_RESULTS.md`, `app.py`, `backend/auth.py`, `backend/i18n.py`,
`backend/services.py`, `backend/validation.py`, `static/app.css`,
`static/forms.js`, `templates/base.html`, `templates/case.html`,
`templates/login.html`, `templates/macros.html`, `templates/register.html`,
`tests/http_smoke.py`, `tests/test_triage.py`, `tests/test_workflow.py`,
`tests/test_localization.py`.

# Minimal UI tidy-up and device-local times — 2026-10-11

Shared CSS now gives pages a restrained white surface, cleaner spacing, softer
form borders, clearer navigation/table rows and a small labeled AI priority panel.
Mobile layouts, native controls, keyboard focus and logical RTL-ready properties
remain intact. No new dependencies, model/schema/notebook changes or backend
workflow changes. Visual/native-device verification remains unavailable because
Computer Use permissions were not granted during the previous pass.

The shared timestamp macro emits UTC-labeled HTML time elements for case creation,
submission/consent, clinician reviews and AI history. Existing forms.js formats
only these timestamps using the browser's Intl timezone/locale and shows a brief
device-timezone notice. Original UTC is retained in datetime/title; no-JavaScript
and unsupported-formatting fallback remains UTC. DOB and follow-up dates are never
converted. All new interface labels stay in the translation catalog.

JavaScript DOM-double smoke **PASS** for timezone-less SQLite timestamps treated
as UTC, ISO offsets, summer/winter DST, previous-day conversion, invalid-time
preservation, timezone notice and unchanged datetime attributes. Existing
assignment, form recovery, retry, duplicates, redirect and image-preview checks
also pass. New HTTP presentation test covers shared timestamp markup, profile and
queue timestamps, missing-value fallback and unchanged database timestamp.

Files changed: `static/app.css`, `static/forms.js`, `backend/i18n.py`,
`templates/base.html`, `templates/macros.html`, `templates/case.html`,
`templates/profile.html`, `templates/queue.html`, `tests/forms_smoke.mjs`,
`tests/test_presentation.py`, `README.md`, `docs/TEST_RESULTS.md`.

Focused regression command (same suite as the previous pass) — **92 tests PASS
in 29.941s**. JavaScript smoke passed in the Node REPL. `git diff --check` passed.
No real browser/device visual verification or new model training was performed.
Server restarted on 127.0.0.1:5000, background PID **7163** at verification;
saved records/accounts and the encryption key were preserved.

# Assignment button and readable AI report verification — 2026-10-11

- Reproduced the JavaScript assignment regression before the fix using
  `tests/forms_smoke.mjs` in the Node REPL: the hidden `name="action"` control
  shadows `form.action`, so enhanced submission targets the input rather than
  the transition URL. Reading the HTML method/action attributes fixes assignment,
  revision and close without changing authorization or case transitions.
- Updated JavaScript smoke test **PASS**: named-action destination, confirmed
  redirect, server/network error recovery, retry, duplicate prevention, close
  cancellation and image preview/removal. Uses DOM doubles, not a real browser.
- `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_presentation test_triage test_ai_runner test_workflow test_auth test_encryption test_intake test_local_model_adapter -q`:
  **91 tests PASS in 30.297s**. Added enhanced assignment/ownership checks,
  readable percent boundaries, shortened legacy explanation display, expandable
  suggestions/details and unchanged stored candidate scores.
- `tests/live_smoke.py --with-model`, with the same environment/command recorded
  below: **PASS**. Actual HTTP assignment, existing saved-model inference,
  clinician review/treatment/referral, patient release and child-process restart
  preserve encrypted inputs/results/triage, Arabic text and image bytes. The
  first smoke run exposed an outdated assertion for the deliberately replaced
  technical summary; updated it to verify percentage labels and prototype notice,
  then reran successfully. Normal application data untouched by tests.
- Report shows three suggestions first, whole-percent AI match scores and a
  clear explanation that percentages are not diagnosis probabilities or severity.
  Full narratives/remaining suggestions/history stay expandable. Known historical
  triage explanations are shortened for presentation without rewriting records.
  Priority rules, thresholds, saved scores, AI inference and clinician authority
  are unchanged. No notebooks, model artifacts, schema or dependencies changed.
- Native Safari verification was unavailable because Computer Use permissions
  are not granted. Real browser clicks/mobile appearance/Arabic RTL are **NOT
  RUN**; JavaScript and HTTP checks above are separate from browser verification.

Files changed: `app.py`, `backend/i18n.py`, `static/forms.js`,
`templates/case.html`, `tests/forms_smoke.mjs`, `tests/test_presentation.py`,
`tests/test_ai_runner.py`, `tests/http_smoke.py`, `README.md`,
`docs/TEST_RESULTS.md`. Existing blocked long-term requirements remain pending.

Final wording rerun: `test_presentation test_triage` — **14 tests PASS in
3.601s**. `git diff --check` passed. Server restarted with existing data on
127.0.0.1:5000, debug off, background PID **5727** at verification.

# Local reset and minimal AI-assisted triage verification — 2026-10-11

This latest update supersedes earlier statements that records/accounts were
preserved during development and that no triage policy was configured. The user
explicitly requested a demo reset and illustrative prototype rules. No notebooks,
models, training artifacts, schema SQL or encryption key were changed in this run.

- `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_triage test_encryption test_auth test_workflow test_intake test_presentation test_ai_runner test_local_model_adapter -q`: **88 tests PASS in 28.310s**. The eight new tests cover emergency precedence, urgent symptom combinations, top-only model mapping, invalid/missing/uncertain/unknown output, explicit negative answers/free-text exclusion, actual 14-label mapping, encrypted triage/UI/ownership and guarded reset/default CLI key selection. Initial run found a test-only macOS `/var` versus `/private/var` path comparison; normalized the expected path and reran successfully.
- After strengthening reset session-secret rotation coverage, `test_triage` reran: **8 tests PASS in 1.109s**. Default session secret changes, encryption key is retained, repeated reset creates five accounts/one case/one image, unrelated upload files survive, password file is 0600 and foreign keys remain valid.
- `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=.cache/matplotlib TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 .venv/bin/python -B tests/live_smoke.py --with-model`: **PASS** with approved loopback access. Actual saved-model inference after patient questionnaire, clinician diagnosis/treatment/referral and patient release all work. An actual server-process restart preserves encrypted triage, 36 model answers, predictions, Arabic text and identical image bytes. Temporary synthetic test database only.
- Actual requested active demo reset executed successfully with `reset-demo --confirm-demo --purge-images --create-test-accounts`. Verified **2 patients, 2 providers, 1 submitted case, 1 image, 5 accounts, 0 AI attempts, 0 reviews**, no foreign-key violations, and successful password login for patient1, patient2, clinician1, clinician2 and worker1. Credentials are private/ignored in `instance/test-accounts.txt`; worker-assisted submission remains blocked.
- Direct `create_app()` with no key environment configuration now loads the same existing local key as the launcher; no regeneration or plaintext fallback. Missing/invalid/explicit key checks remain covered. Existing encryption key and source artifacts preserved; old migration backups are outside this reset and still need separate archival/removal.
- Restarted `./run-local.sh`, debug off, on **127.0.0.1:5000**, background PID **3032** at verification. `git diff --check` passed. No deployment/push. No real-device/browser visual/Arabic RTL checks were run for this narrowly scoped change.

Exact illustrative rules/mappings, the unvalidated 0.5 uncertainty flag, manual
reset/start/stop instructions and persistence format are in README and
docs/AI_INTEGRATION.md. Clinician assessment remains independent. AT-06 has
prototype rule checks passing; clinically validated emergency screening and the
remaining blocked long-term requirements are not claimed complete.

Files changed in this run: `.env.example`, `AGENTS.md`, `README.md`, `app.py`,
`backend/demo.py`, `backend/i18n.py`, `backend/services.py`,
`backend/ai/adapter.py`, `backend/ai/local_adapter.py`, `backend/ai/runner.py`,
`backend/ai/triage.py`, `templates/case.html`, `tests/test_triage.py`,
`tests/live_smoke.py`, `implementation.md`, `docs/AI_INTEGRATION.md`,
`docs/TEST_RESULTS.md`. Runtime demo data/password/session files are Git-ignored.

# Patient questionnaire verification — 2026-10-11

This update supersedes provider-only model-question collection below. Patients
can save the extra questions with draft intake and submission; clinicians reuse
those recorded answers and fill only missing values. No notebooks, saved models,
schema SQL, key files or pre-existing workspace clinical records were changed.

- `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_encryption test_auth test_workflow test_intake test_presentation test_ai_runner test_local_model_adapter -q` — **80 tests PASS in 29.820s**. Includes 10 added tests for native checkbox/range controls, profile age/sex mapping and age-band boundaries, nullable checkbox groups, existing No preservation, encrypted extra answers/restart/Arabic, old-record compatibility, malformed/duplicate/spoofed inputs, whole-intake rollback, ownership/CSRF/submitted freeze, saved patient answers feeding inference, and missing answers blocking only inference. Existing consent/camera/images/review/encryption/authorization tests still pass.
- After correcting the outdated submission notice, `test_presentation` reran: **3 tests PASS in 1.341s**. Submission now truthfully confirms clinician review without claiming model integration is pending.
- `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=.cache/matplotlib TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 .venv/bin/python -B tests/live_smoke.py --with-model` — **PASS** outside the sandbox after its initial loopback bind refusal. Actual HTTP signup/login → patient select-all checkbox groups/direct duration range → file + camera upload/consent → provider assignment → actual saved SCIN model without re-entering patient answers → review/treatment/referral → patient release. Actual child-process stop/restart preserved all 36 encrypted model answers, derived age/sex, successful predictions, Arabic text and identical source image bytes. The inference snapshot exactly matched the saved patient model mapping. Temporary synthetic database only; no normal demo records/accounts changed.
- Checkbox semantics: checked is Yes; explicitly confirming a group makes unanswered unchecked items No. Unconfirmed untouched choices remain NULL and prior No values persist. Provider controls for recorded answers are disabled/read-only; server validation also rejects attempts to change them. Incomplete model inputs do not block patient submission or manual clinician review.
- Server-derived age uses DOB at case submission. Missing DOB and ages outside 18–79 use AGE_UNKNOWN. Per Omar's instruction, the existing canonical encrypted profile `sex` field now supplies sex at birth and is labeled accordingly. No demographic guesses or extra frontend demographic answers are used. Duration uses saved ranges; explicitly selecting a range on a draft replaces exact-day duration with NULL rather than inventing days.
- No migration: the existing authenticated `Symptom.answers` envelope optionally adds nested `model_metadata`; its six original answer fields and older envelopes remain compatible. Runtime user_version remains **4**; source SQL and inference architecture/artifacts are unchanged. Submitted cases remain frozen; legacy missing answers can be completed by a clinician for an analysis attempt.
- Local app restarted with `./run-local.sh`, debug off, encrypted dataset/key and selected model retained; loopback listener PID at verification: **98453**. Modified Python sources parse and `git diff --check` passed. No deployment/push or new implementation folders/files.

Files modified in this pass: `backend/preprocessing.py`, `backend/services.py`,
`backend/ai/local_adapter.py`, `backend/i18n.py`, `app.py`, `templates/intake.html`,
`templates/macros.html`, `templates/case.html`, `templates/new_case.html`,
`static/app.css`, `tests/test_intake.py`, `tests/test_local_model_adapter.py`,
`tests/test_presentation.py`, `tests/http_smoke.py`, `tests/live_smoke.py`,
`README.md`, `AGENTS.md`, `implementation.md`, `docs/AI_INTEGRATION.md`,
`docs/MODEL_INTERFACE.md`, `docs/ARCHITECTURE.md`, `docs/ENCRYPTION.md`,
`docs/REQUIREMENTS.md`, and this report.

AT-01, AT-03, AT-04, AT-05 and AT-07 through AT-12 retain the qualified PASS
statuses in the table below; AT-02 worker attribution and AT-06 automated safety
remain BLOCKED. Structured history, durable submission revisions, full Arabic
translations/RTL, production security, independent model calibration and actual
browser/mobile/camera visual/hardware checks remain pending. HTTP and HTML checks
do not constitute those visual/hardware checks. Full MVP completion is not claimed.

---

# Saved SCIN model application integration — 2026-10-11

These results supersede earlier statements that real inference is unconfigured.
Omar's existing `SCIN_custom_model.keras` is selected; no notebooks, training
code or model/encoder/class artifacts were modified. Runtime remains SQLite v4;
no schema change or migration was needed for supplemental model-answer snapshots.

- Application command: `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_encryption test_auth test_workflow test_intake test_presentation test_ai_runner test_local_model_adapter -v` (equivalent combined loader executed): **70 tests PASS in 24.698s**. Includes 13 new local-adapter tests for lazy factory selection, explicitly disabled/missing bundles, all required answers, known-answer/none-flag contradictions, NULL preservation, labeled provider-only controls, authorization, authenticated image reading, encrypted snapshots/results, artifact-change rejection, invalid outputs, retries and independent manual review after failure.
- Standalone interface: `PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=.cache/matplotlib TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTEROP_THREADS=1 TF_NUM_INTRAOP_THREADS=1 .venv/bin/python -B -m unittest discover -s tests -p test_model_interface.py -v` — **13 tests PASS in 13.198s**. **83 automated tests passed in total.** Existing PyTorch Python-3.14/TorchScript and Keras/NumPy deprecation warnings remain; no test failure or skip occurred. Unrelated EDA/training-artifact tests were outside this application pass.
- **Actual saved-model inference PASS:** isolated encrypted Flask test client, two synthetic PNGs, all 31 binary and five categorical answers explicitly supplied, 68 encoded features, 14 finite ranked outputs summing to 0.99999993. First load plus inference took **2.281s on CPU**. Original unknown itching remained NULL while the supplemental explicit answer was recorded separately. No clinician Diagnosis was generated, priority remained undetermined and images remained unassessed. Clinician review/patient release and fresh-app encrypted-result/image/Arabic retrieval passed. SHA-256 of all three supplied model artifacts was identical before/after.
- **Actual HTTP model workflow and child-process restart PASS:** ran the existing isolated `tests/live_smoke.py` harness with an in-memory hook after clinician assignment to submit the real 36-field model form. Actual `.keras` inference completed with 14 encrypted candidates, followed by diagnosis/treatment/referral/follow-up, patient release and stop/restart of the Flask subprocess. Successful AI history, all candidates, exact Arabic text and image bytes survived. Workspace demo records/accounts were untouched. The sandbox could not bind the test server; approved execution outside the sandbox passed.
- **Startup PASS:** default application selected SCINModelAdapter and 14 classes without importing TensorFlow, Keras, Torch or NumPy. `pip check` reported no broken installed requirements. Actual environment: Python 3.14.7, SQLite 3.53.4, Flask 3.1.2, Werkzeug 3.1.9, Pillow 12.3.0, cryptography 50.0.2, TensorFlow **2.22.0rc0** (release candidate), Keras 3.15.1 and NumPy 2.5.4. No dependencies or models were downloaded/installed.
- Restarted the loopback server with `./run-local.sh`, debug off, selected model enabled, existing encrypted dataset/key retained. Background PID at verification: **92389**. Approved real HTTP GET `/login` and `/patients/new` both returned **200**. `git diff --check` passed. No deployment or push.
- Browser inventory returned no connected browser surface. Actual visual/mobile/keyboard/camera and complete Arabic RTL verification remain **NOT RUN**; labeled native controls/rendered HTML assertions and HTTP workflows are separate software checks.

| ID | Current result | Qualification |
|---|---|---|
| AT-01 | PASS for supported account/profile fields | Structured medical history remains pending. |
| AT-02 | BLOCKED | Worker grants and submitting-user attribution still absent. |
| AT-03 | PASS | Encrypted intake, multiple images/camera fields and consent. |
| AT-04 | PASS for supported roles | Authorized decrypted cases/results/images. |
| AT-05 | PASS for selected-model integration | Actual 14-group model outputs persisted as unconfirmed suggestions; no clinical accuracy/calibration claim. |
| AT-06 | PARTIAL / prototype checks PASS | User-authorized illustrative rules and encrypted results implemented; clinical validation/full emergency-screening requirements remain pending. |
| AT-07 | PASS | Independent atomic clinician review, including after AI failure. |
| AT-08 | PASS | Clinician diagnosis/treatment/follow-up persistence. |
| AT-09 | PASS for clinician documentation | Referral saved; no automatic escalation. |
| AT-10 | PASS | Actual HTTP process restart preserves encrypted AI/clinical/image/Arabic data. |
| AT-11 | PASS for local controls | Role/ownership/assignment/CSRF/private storage; production hardening pending. |
| AT-12 | PASS for implemented boundary | Missing answers, unavailable model, invalid output/failure/timeout/retry/history and manual review. |

Remaining limitations: missing binary answers intentionally block inference, never
manual review; multiple-image probability averaging is not independently validated;
scores are uncalibrated and grouped, with no image-quality or clinical-priority
classifier. A current bundle fingerprint cannot prove historical training-encoder
provenance absent from the original export. Production hardening, structured history,
worker attribution, durable submission revisions, automated safety screening and
full Arabic/browser checks remain pending. Full MVP completion is not claimed.

Files changed for this integration: `app.py`, `backend/ai/adapter.py`,
`backend/ai/runner.py`, new `backend/ai/local_adapter.py`, `backend/i18n.py`,
`templates/case.html`, `run-local.sh`, `.env.example`, new
`requirements-inference.txt`, `tests/test_workflow.py`, new
`tests/test_local_model_adapter.py`, `README.md`, `AGENTS.md`, `implementation.md`,
`docs/AI_INTEGRATION.md`, `docs/MODEL_INTERFACE.md`, `docs/REQUIREMENTS.md` and this
report. Earlier encryption/migration edits and pre-existing notebook/artifact
working-tree changes were preserved.

---

# Encryption startup/migration corrections — 2026-10-11

- Application regression command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest discover -s tests -p test_encryption.py -v` for the focused suite; the combined `test_encryption`, `test_auth`, `test_workflow`, `test_intake`, `test_presentation` and `test_ai_runner` suites ran together: **57 tests PASS in 28.082 seconds**, including seven new regression tests. Model-training tests were outside this backend-only pass.
- New checks cover direct startup selecting encrypted paths while preserving legacy sources, missing-copy refusal/no automatic key, wrong keys/explicit plaintext paths rejected, duplicate image rows preserved with one encrypted object, conflicting image metadata rollback, invalid image identifiers returning controlled CLI errors, existing destination guidance/no overwrite, and failed fresh initialization safely retrying without copy migration.
- `ENCRYPTION_KEY_FILE=instance/encryption.key PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m flask --app app init-db` **PASS**: direct CLI verified the existing encrypted v4 database. Its saved key matches, SQLite quick check is `ok`, and foreign-key check has no violations. No workspace migration, key replacement or password reset was performed.
- `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/live_smoke.py` **PASS**: actual HTTP signup/login/logout, two-image intake/consent, clinician review with diagnosis/treatment/referral, patient outcome and child-process restart preserving Arabic text and exact decrypted images. The initial sandboxed attempt could not start the loopback server; the approved rerun outside the sandbox passed. Only isolated temporary synthetic records were used.
- `git diff --check` **PASS**. No Jupyter notebooks or ML artifacts were edited. Existing schema versions and AI adapter behavior are unchanged. Broader deferred requirements and the AT-01 through AT-12 status table below remain applicable.
- Restarted the existing local background server with `./run-local.sh`, debug off, using the existing encrypted dataset/key. Current PID at verification: **85448**. Actual HTTP `/login` and `/patients/new` both returned **200**; loopback checks required approved execution outside the sandbox. No external deployment or push.

# Encryption/gender verification — 2026-10-10

These results supersede previous runtime/security statements below. Source schema.sql v2 and auth_migration.sql v3 are unchanged; active runtime requires encrypted v4. No AI development or deployment/push occurred.

## Actual checks

- Final command: `.venv/bin/python -m unittest discover -s tests -v` — **50 tests PASS in 19.760 seconds**. Original 40 regression tests remain, with expected storage-version/encrypted-field checks adapted; 10 new encryption/gender/migration/security tests pass.
- Coverage: canonical gender choices/one-hot and malformed types; safe legacy F/M/unmapped archive; fixed symptom-vector order and None vs No; required/invalid/wrong keys; private-path checks; encrypted SQL fields/files and raw-database plaintext scans; no plaintext cache; authenticated source hashes/MIME/metadata; ciphertext corruption/context swap rejection; unauthorized access denied before image decryption; SQL guards against plaintext writes; sanitized errors/no clinical logging; patient service data excludes private clinician notes/AI history; malformed Unicode CSRF returns 400; camera/file intake, rollback, legal transitions, reviews and account controls.
- Copy migration tests PASS: sources byte-for-byte preserved; accounts/hashes retained; unknown schema extensions rejected; missing/corrupt images abort without publishing target; staging cleanup; encrypted legacy gender archival; key verification and migrated credential login/image retrieval.
- `PYTHONPATH=. .venv/bin/python tests/live_smoke.py` — **PASS:** real loopback encrypted signup/login/logout → unified intake with file + camera multipart fields → consent → queue/assignment → diagnosis/treatment/referral/follow-up → patient outcome. **PASS after actual child-process restart:** Arabic text, released care and identical decrypted image bytes persist. Temporary synthetic dataset only.
- Existing optional-adapter fixture tests PASS (success/failure/retry/timeout/output-validation/history). Input signatures/contract version unchanged; decrypted symptom/gender/image-reader compatibility PASS. Unconfigured analysis still returns 503 without creating an attempt; manual submission/review remain independent. No real model/inference is introduced or claimed.
- Code documentation: 98 missing production docstrings inserted in a documentation-only batch with AST equivalence after removing docstrings; remaining inner transaction helper documented separately. Final audit finds no undocumented production classes/functions. `git diff --check` PASS. No unrelated code formatting/restructuring was performed for documentation.

## Actual workspace migration and server

Migrated the existing synthetic v3 source to `instance/encrypted/demo.sqlite3` + `instance/encrypted/uploads`: **4 patients, 4 cases, 3 questionnaires, 1 review, 1 diagnosis, 1 treatment and 4 referenced images** verified. **All 7 accounts retained**, with existing password hashes/links unchanged. Source database SHA-256 before/after is identical. Source attachments and older backups preserved. Generated the Fernet key once into `instance/encryption.key` (0600); never displayed/logged/committed it. Key, active data and the existing synthetic credential file are Git-ignored. **All 6 documented test-account login/logout checks PASS**, including authorized patient pages and provider queues. The seventh existing account is retained without resetting its password.

Started the updated app with `./run-local.sh` at 127.0.0.1:5000, debug off, in a tool-managed process (PID 57955 at handoff). After the final restart, HTTP GET `/login` and `/patients/new` returned 200 with the password field and standardized gender choices verified. The script exports the encrypted DB/upload/key-file configuration. Old plaintext DB/uploads are never used by that launcher. The signing secret remains separate. Future starts use the same script/key; never regenerate an existing key. See README/ENCRYPTION.md for migration/fresh-init commands.

## Remaining issues / manual steps

- Original v3 DB/uploads and old backups remain **plaintext rollback material**. Securely archive/remove them after validation; this run preserves source data and performs no destructive removal. Back up the encryption key separately from the encrypted dataset. Existing plaintext synthetic test-password file remains by the user's prior explicit request, restricted to 0600; patient display names were removed.
- Field/file encryption leaves IDs, relationships/body-site references, statuses, operational times/enums and account usernames/hash metadata queryable. It is not whole-file/OS memory/swap encryption or authenticated relational structure. Key rotation, production secrets/authentication/session-revocation/throttling/MFA/recovery/audit remain pending.
- No structured MedicalHistory table exists. History entered in supported notes is encrypted; a new structured-history extension requires agreed fields and mapping. Unknown extensions block migration rather than silently remaining plaintext.
- Physical browser/camera/mobile and complete Arabic translation/RTL checks remain unverified. Existing browser logic tests from the previous pass are distinct from hardware verification; this pass changes no CSS/camera JavaScript.
- Real AI, automated safety policy, worker grants/submission attribution and durable submission revisions remain the previously documented gaps. AI development was explicitly excluded.

## Current acceptance tracking

| ID | Current result | Qualification |
|---|---|---|
| AT-01 | PASS for supported profile/account fields | Gender canonical/one-hot; PII encrypted. Structured history still pending. |
| AT-02 | BLOCKED | Worker access grants and submitting-user attribution absent. |
| AT-03 | PASS | Encrypted questionnaire/camera/file intake/consent, transaction rollback. |
| AT-04 | PASS for supported roles | Authorized decrypted case/result/image retrieval. |
| AT-05 | BLOCKED / real inference NOT RUN | Existing contract software checks pass; no AI development. |
| AT-06 | BLOCKED / clinical policy absent | General guidance only. |
| AT-07 | PASS | Encrypted independent provider review, assignment, rollback/history. |
| AT-08 | PASS | Encrypted clinician diagnoses/treatments/follow-up. |
| AT-09 | PASS for clinician documentation | Encrypted referral instructions; no automated escalation. |
| AT-10 | PASS | Copy migration/source preservation and actual encrypted process-restart workflow. |
| AT-11 | PASS for local controls | Credential roles/ownership/CSRF/private data boundaries; production hardening pending. |
| AT-12 | PASS for implemented boundary | Strict key/cipher failures, review rollback, existing unavailable/fixture AI checks. |

## Files changed in this encryption/documentation pass

- Functional/new backend: `app.py`, `backend/security.py`, `backend/preprocessing.py`, `backend/migrate_encryption.py`, `backend/db.py`, `backend/services.py`, `backend/auth.py`, `backend/images.py`, `backend/ai/runner.py`, `backend/i18n.py`.
- Documentation-only backend: `backend/validation.py`, `backend/ai/adapter.py`, `backend/safety.py`, `backend/demo.py`.
- Gender presentation: `templates/register.html`, `templates/macros.html`.
- Setup/migration: `encryption_migration.sql`, `requirements.txt`, `.env.example`, `run-local.sh`.
- Tests: `tests/test_encryption.py`, `tests/test_workflow.py`, `tests/test_auth.py`, `tests/test_ai_runner.py`, `tests/test_intake.py`, `tests/live_smoke.py`.
- Documentation: `README.md`, `AGENTS.md`, `implementation.md`, `docs/ENCRYPTION.md`, `docs/ARCHITECTURE.md`, `docs/AI_INTEGRATION.md`, `docs/REQUIREMENTS.md`, `docs/TEST_RESULTS.md`.
- Private ignored runtime changes: new `instance/encryption.key`, new encrypted dataset/report directory, updated test-credential file database path/removal of display names, and restricted source file permissions. No secret is in tracked source.

---

# Camera and scrollable-intake verification — 2026-10-10

Current results supersede prior metadata-stripping/pixel-cap requirements and presentation status below; historical results and individual AT-01 through AT-12 tracking are preserved.

- **40 Python tests PASS in 15.632s** (`.venv/bin/python -m unittest discover -s tests -v`). Includes 36 previous tests, with the obsolete custom-pixel-cap assertion updated to acceptance, plus 4 new intake tests.
- New coverage: all sections/camera/consent visible before saving; draft without photos; combined file+camera submission; NULL vs No and zero duration; retry creates no extra images/consent; clinician review/patient outcome; invalid consent, file or photo-site rolls back symptoms, lesions, images and files; cross-patient denial; original JPEG bytes, EXIF orientation/manufacturer/GPS and PNG text survive save, fresh app startup and authorized retrieval. Stored hashes/MIME checked. A deliberately tiny obsolete MAX_IMAGE_PIXELS config no longer rejects the photos.
- **Real loopback HTTP workflow and actual process restart PASS** (`PYTHONPATH=. .venv/bin/python tests/live_smoke.py`). The script now sends one existing-file field plus one camera field to the single-page intake endpoint with questionnaire/sites/consent, then exercises queue, review, care/referral/follow-up and patient retrieval. Arabic text and identical stored image bytes survive restart. Only temporary synthetic records used; normal demo accounts/records unchanged.
- **forms_smoke.mjs PASS** through available Node runtime: error/network recovery, retry, double-click prevention, server-confirmed navigation, close cancellation, preview/removal. **camera_smoke.mjs PASS:** optional live opening, rear-camera preference, capture to pending FileList, permission-error recovery and track cleanup on capture/submit/page exit. These use DOM/API doubles; no physical camera or browser rendering is claimed.
- Responsive CSS: wide screens use up to 86rem content, paired fields and fluid grids; portrait phones use stacked fields/actions, wrapping touch-sized navigation, bounded video and contained queue scrolling. **Physical phone/widescreen browser rendering, camera permission UI, EXIF orientation display and full RTL NOT RUN.** Browser access was unavailable/not approved in the preceding pass; no unsupported claim of hardware/mobile verification.
- **Schema unchanged; git diff --check PASS.** Original PNG references remain valid; new sources retain JPEG/PNG extensions and exact metadata. App-level pixel configuration/UI removed; Pillow's built-in decompression protection and file-size/count validation retained. No model, geolocation/outbreak logic, migration, deployment or push.

The user's normal non-debug server remains in their terminal and needs Ctrl-C/relaunch to load changes. Metadata removed by older versions is unrecoverable; browser-generated captures may have no EXIF/GPS to preserve. Previously blocked worker/history/revision/AI/safety/Arabic/production requirements remain pending.

---

# Presentation-pass verification — 2026-10-10

This section supersedes earlier presentation/browser status where applicable; historical reports and individual AT-01 through AT-12 tracking remain below.

- Existing regression suite: **33 tests passed in 13.276s** before the enhanced-response contract.
- After the final response contract: **36 tests passed in 14.454s** (33 existing + 3 focused presentation tests). Two new static-response test resources produced ResourceWarnings; those test responses were subsequently changed to context managers and the 3 presentation tests rerun without warnings.
- New tests verify enhanced submission failures leave the draft unchanged and permit retry; success returns a destination only after the write, preserves its flash notice until the GET, and retains no-store headers. Also checks enhanced requests cannot bypass CSRF or ownership, shared assets/navigation/skip link, translated browser messages and exact zero-duration display.
- Real loopback HTTP workflow **PASS**, rerun after the response change: signup/login/logout → draft/questionnaire → two images → consent → clinician queue/assignment → diagnosis/treatment/referral/follow-up → patient result. Actual child-process restart **PASS** for exact Arabic text, saved care and identical image bytes. Isolated temporary database only; existing demo records and credentials untouched.
- `tests/forms_smoke.mjs` **PASS** through the available Node runtime: actual forms.js executed with lightweight DOM doubles for server-error recovery, network-error recovery, retry, repeated-click prevention, confirmed redirect navigation, close cancellation, two previews and removal from the pending file selection. JavaScript syntax parsing **PASS**. This is a logic test, not a browser test.
- Mobile behavior: responsive CSS implemented (640px breakpoint, wrapping navigation, logical dimensions, stacked detail rows, fluid image grids and contained horizontally scrollable queue). **Actual phone/laptop rendering and keyboard/screen-reader interactions NOT RUN.** Browser inventory had no connected browser; Chrome was unavailable; Computer Use did not approve Safari access. File picker, real browser FileList/DataTransfer, preview decoding and full RTL visual behavior remain unverified.
- No schema change: supplied schema.sql SHA-256 remains `c3315779f36410940f8f0a0a52cb2ee7671f6bd1a8611d9ff15332f6964158cc`; auth_migration.sql is unchanged by this pass. AI adapter/services/auth/storage behavior preserved. `git diff --check` PASS.

Native forms/links still work without JavaScript (also exercised by the HTTP workflow). Enhanced forms require a restart of an already-running non-debug Flask process to load the new JSON redirect hook. The current port 5000 listener is PID 12026 in the user's terminal, `ttys005`; it was left running in that terminal. Ctrl-C and relaunch the documented Flask command to load changes. No external deployment or push.

Remaining limitations: real browser/mobile/accessibility and full Arabic translations/RTL verification; worker grants/submission attribution, medical history, durable submission revisions, actual AI inference, automated safety policy and production hardening. Full MVP/Arabic support is not claimed.

---

# Current second-pass verification — 2026-10-10

The results in this section supersede the historical first-run report below. The supplied base schema remains v2; runtime authentication extension is v3. Existing clinical records/images were preserved. No deployment or push occurred.

Executed before refactoring: **21 existing tests passed in 0.861 seconds**.

Executed after CaseWorkflow/AuthService/ImageStorage refactoring and password authentication:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

**33 tests passed in 13.874 seconds, with no failures.** This includes the original 21 tests adapted to log in with real hashed-password accounts, and 12 additional account/migration tests.

Additional tests verify patient-only signup with scrypt hashes, login/logout, case-insensitive duplicate signup without orphan profiles, wrong password/unknown user errors, removal/ineffectiveness of the demo selector, rejection of role/existing-record injection, username/password validation, login/signup/logout CSRF and rotation, cross-patient denial and role navigation, separate CLI provisioning/link constraints, deactivated-account denial, additive migration/backups/idempotence, failed-migration rollback and SQL account role/entity constraints. Existing workflow, consent/NULL, private-image, cross-case FK, review atomicity/history, AI-unavailable/failure/retry and Arabic readiness tests still pass.

Executed a real loopback HTTP test in an isolated temporary database:

```sh
PYTHONPATH=. .venv/bin/python tests/live_smoke.py
```

**PASS:** actual patient signup/login/logout → draft/questionnaire/sites → two uploaded private images → consent submission → separately provisioned clinician login → queue/assignment → diagnosis/treatment/referral/follow-up → patient outcome. **PASS after an actual child-process stop/restart:** signed patient login session, exact Arabic text, released care and identical image bytes persist. The test creates/deletes only its temporary synthetic database and does not change the normal demo database. Passwords are held in memory; the private temporary session-cookie file is removed with the test directory. No real inference ran.

Applied the explicitly authorized migration to `instance/demo.sqlite3` while the old server was stopped. Backup: `instance/demo.before-auth-v3-20261010T184159Z-ebf1b720.sqlite3`. Compared **every original table and row** to the SQLite backup: exact match. Verified **every stored image** against its existing SHA-256: match. Runtime user_version is 3; foreign-key check returns no violations. Migration creates no accounts/default passwords; existing records require deliberate local provisioning.

Python source parsing, centralized literal interface/error catalog checks, and `git diff --check` passed. app.py has **zero SQL execute calls**; routes dispatch to services. The final running server's `/login` response was fetched over HTTP and confirmed to contain a password field with no identity dropdown. The normal server was restarted on 127.0.0.1:5000, debug off, in a tool-managed process without an interactive terminal; PID at handoff is 10373 (changes on restart).

Native-browser rendering/file-picker/JavaScript interactions and full Arabic translations/RTL remain **NOT RUN / pending**. The earlier Safari Computer Use action was not approved; this pass used HTTP/HTML checks and does not claim a browser smoke test.

| ID | Current result | Qualification |
|---|---|---|
| AT-01 | PASS for supported profile fields | Signup persists Patient+Account atomically; medical history/district remain pending. |
| AT-02 | BLOCKED / NOT RUN | Worker accounts now persist, but patient grants/submitting-worker attribution are still absent. No worker submission is exposed. |
| AT-03 | PASS | Original intake/images/consent/state tests plus credential-based real HTTP workflow. |
| AT-04 | PASS for supported roles | Authenticated ownership/assignment/private-image/patient-result retrieval checked. Worker case access still blocked. |
| AT-05 | BLOCKED / real inference NOT RUN | Typed adapter and fixture software tests remain intact; Omar's actual inference pending. |
| AT-06 | BLOCKED / policy NOT RUN | General guidance only; agreed inputs/persistence/clinical policy pending. |
| AT-07 | PASS for supported review | Independent no-AI review, transactional rollback, assignment and review history still pass. |
| AT-08 | PASS | Diagnosis/certainty/primary/treatment/medication/dosage/follow-up remain tested. |
| AT-09 | PASS for clinician documentation | Referral/explicit escalation intent persist; no automatic screening/escalation claimed. |
| AT-10 | PASS | Migration preserves every prior row/image; credentials, Arabic text and outcome survive real process restart. |
| AT-11 | PASS for local password authentication | Real accounts, hash checks, role/entity lookup, CSRF, ownership and privilege-injection tests. Production hardening remains out of scope. |
| AT-12 | PASS for implemented boundary | Unconfigured/fixture AI failures and review/image rollback remain tested. |

Remaining limitations: worker access/attribution, medical history, durable submission revisions, real AI, automated safety policy, Arabic translation/full RTL/browser verification, and production authentication/hosting features. Password reset/recovery, email verification/MFA, login throttling and durable server-side session revocation are not implemented. Loopback-only operation remains. Full MVP completion is not claimed.

---

## Historical first-run report (v2, prior to authentication migration)

# Actual verification results — 2026-10-10

Local environment: macOS, Python 3.14.7, Flask 3.1.2, Pillow 12.0.0, SQLite runtime from Python. Schema remains user_version 2; no migration applied. All data/images are fictional/geometric. These are functional software checks, not clinical validation.

## Focused automated tests

Executed:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Final run: **21 tests passed in 0.909 seconds; no failures or resource warnings.**

| Test | Result |
|---|---|
| Configured fixture success → failure → retry preserves old success, candidates, source-quality snapshot; repeated stale request creates no extra run | PASS |
| Invalid configured output commits failed attempt only, no candidates/quality changes | PASS |
| Timeout discards late output; interrupted recovery; manual review remains possible | PASS |
| Unconfigured AI returns 503, creates no attempt and does not block review | PASS |
| Patient ownership, private images, clinician assignment, worker-denied records/actions | PASS |
| End-to-end patient intake → two images → consent → clinician diagnosis/treatment → patient result; exact Arabic text and images through fresh app/DB connections | PASS |
| Foreign keys on connections, cross-case review/analysis and diagnosis/review linkage, unique primary diagnosis | PASS |
| CSRF, loopback/Host gate, invalid demo identity | PASS |
| AI output contract rejects invalid text/triage/rank/confidence/image ownership | PASS |
| Legal transitions, explicit review revision, history, closure, stale/repeated review rejection | PASS |
| en/ar page attributes, pending Arabic notice, dir=auto rendering | PASS (scaffolding only) |
| Needs-information review/message persisted without destructive patient edits | PASS (resubmission intentionally blocked) |
| Providers cannot read/claim patient drafts | PASS |
| Referral/explicit escalation documentation without diagnosis; correct lifecycle | PASS |
| Diagnosis requirements, exactly one primary, referral validation and real follow-up date | PASS |
| Forced SQL failure during treatment insert rolls back review, diagnoses, treatment and status | PASS |
| Image decode validation, multi-file rollback cleanup, limits, stored hash/MIME and absence of EXIF | PASS |
| Consent/completeness validation, NULL vs 0, double-submit safety and submitted-content freeze | PASS |
| Invalid/future dates, blank names, malformed durations/booleans/sites and questionnaire upsert | PASS |
| Existing wrong-version database rejected without overwriting records | PASS |
| Seed/reset named-demo guard, duplicate seed preserves data, explicit reset flag | PASS |

## Running-server verification

Executed `flask --app app init-db` and `seed-demo`, then launched the actual Flask development server on **127.0.0.1:5000**, debug off. Executed:

```sh
.venv/bin/python tests/http_smoke.py create
```

**PASS:** real HTTP registration, exact Arabic name/complaint/notes, draft, two image uploads, consent submission, clinician queue/assignment, clinician diagnosis/treatment/referral/follow-up, patient result with private clinician notes excluded. Created synthetic case 2 (patient 3) in the demo database; seed case 1 remains available for review.

Stopped the server process, launched a fresh process against the same database/upload directory, then executed:

```sh
.venv/bin/python tests/http_smoke.py verify
```

**PASS:** identical stored image SHA-256, exact Arabic text, clinician result, provisional certainty, treatments, referral and access persisted. Repeated the read-only verification against the final application process after AI runner integration; **PASS**. The final server is left running locally. No external deployment or GitHub push occurred.

`git diff --check` passed. `schema.sql` is unchanged (SHA-256 `c3315779f36410940f8f0a0a52cb2ee7671f6bd1a8611d9ff15332f6964158cc`); original PDF remains unchanged/preserved. Root instruction documents were appended as requested.

**Actual browser happy path: NOT RUN / BLOCKED.** Browser inventory returned no connected browser surfaces. Native Safari access was not approved by Computer Use. No browser-rendering, file-picker, JavaScript double-click or full RTL visual-verification result is claimed. HTTP checks and HTML assertions are distinct from a browser smoke test. The denied Safari action was opening/controlling Safari for this local smoke test; no more detailed reason was returned.

## Individual acceptance tracking

| ID | First-run result | Evidence / full-plan qualification |
|---|---|---|
| AT-01 Patient registration | PASS for existing fields; full requirement PARTIAL | Profile test + running-server registration/retrieval. Medical history/geographic district pending schema. |
| AT-02 Worker submission | BLOCKED / NOT RUN | No User, worker grants or submitting-user attribution in v2; worker identity intentionally cannot submit/access records. |
| AT-03 Patient submission | PASS | Complaint/duration, NULL-preserving questionnaire, multiple sites/images, consent, submission persistence and idempotence tested. |
| AT-04 Case retrieval | PASS for supported roles | Own-patient/provider retrieval, image access, patient outcome and clinician-note privacy tested; worker path pending. |
| AT-05 AI screening | BLOCKED / real inference NOT RUN | No Omar inference supplied. Typed contract + simulated attempt lifecycle/failure/retry tests pass; these do not satisfy real screening acceptance. |
| AT-06 Safety screening | BLOCKED / automated policy NOT RUN | General emergency guidance + independent protocol only. No agreed input fields/clinical policy or structured assessment store; no invented rules. |
| AT-07 Clinical review | PASS for schema-supported review | Independent no-AI review; forced database-failure rollback, assignment checks, stale request rejection and preserved revision history tested. Missing medical history separately pending. |
| AT-08 Treatment documentation | PASS | Clinician-authorized provisional diagnosis, treatment instructions, medication/dosage and follow-up stored/retrieved; primary-diagnosis rules tested. |
| AT-09 Referral/escalation | PASS for clinician documentation; automated detection BLOCKED | Referral without diagnosis, required reason/destination, explicit escalation intent and red clinician priority persist; lifecycle reviewed and clinical decision referred remain separate. No automatic escalation or structured emergency flag claimed. |
| AT-10 Persistence | PASS | Fresh app/connection tests plus real server process restart and identical private image hash; exact Arabic text retained. |
| AT-11 Authorization | PASS for local demo mechanism | Cross-patient/provider/worker denials, private images, CSRF, Host/loopback checks. Production authentication/worker access design not implemented. |
| AT-12 Failure handling | PASS for implemented boundary | Unconfigured AI and simulated configured failures/timeouts/invalid outputs preserve manual review; clinical write rollback and upload cleanup tested. Real model-specific failures pending actual inference. |

The **schema-supported local prototype is functional**. Full MVP completion is not claimed: AT-02, real AT-05 and AT-06 remain blocked, together with durable medical history/identity/revision requirements. Complete Arabic translations/RTL verification and the actual browser smoke test remain pending.
