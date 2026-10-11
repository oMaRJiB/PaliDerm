# PaliDerm local prototype

A working patient-intake → private images → consent submission → clinician review → patient-result workflow. Synthetic data only. Plain Flask/Jinja forms with password login and patient signup. The supplied base schema v2 is unchanged; runtime v4 adds authenticated field/file encryption after the additive authentication migration. The user-selected local SCIN model is available for explicit clinician requests; unavailable AI never blocks submission or review. This is not an emergency service, clinical validation, production security, HIPAA compliance, or a complete implementation of the long-term plan.

## Install, initialize and launch

The current workspace uses `instance/encrypted/demo.sqlite3` and `instance/encrypted/uploads`. Its existing private key is in `instance/encryption.key` (0600, Git-ignored). The authorized demo reset generated fresh account passwords in `instance/test-accounts.txt`. **Do not regenerate the encryption key or rerun migration into the existing destination.** Start from the repository root with:

```sh
./run-local.sh
```

The script supplies database/upload/key-file paths and selects `notebooks/SCIN_custom_model.keras` through `MODEL_PATH`; the application never generates a replacement encryption key or falls back to plaintext. Direct Flask startup now defaults to the same encrypted database/upload paths and model. Explicit settings still take precedence: replace old plaintext paths in your terminal rather than rerunning migration. Missing/invalid/wrong keys fail before serving records. An encryption key is distinct from the session-signing secret. `SECRET_KEY` takes a secret value, never the encryption-key filename. Tested with Python 3.14.7; code requires Python 3.11+.

For a **fresh installation only**, create the virtual environment, install dependencies and generate a new key without displaying it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p instance
.venv/bin/python -c 'import os; from cryptography.fernet import Fernet; fd=os.open("instance/encryption.key",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,Fernet.generate_key()+b"\n"); os.close(fd)'
```

The key command refuses to overwrite an existing file. Optionally select the defaults explicitly before direct Flask CLI commands (the existing local key is now selected automatically when neither key source is configured):

```sh
export ENCRYPTION_KEY_FILE=instance/encryption.key
export DATABASE=instance/encrypted/demo.sqlite3
export UPLOAD_DIR=instance/encrypted/uploads
```

For a new empty database, initialize and optionally seed synthetic records:

```sh
.venv/bin/python -m flask --app app init-db
.venv/bin/python -m flask --app app seed-demo
./run-local.sh
```

For an **existing plaintext v2/v3 database**, stop the old server and migrate into an unused destination instead of initializing or seeding:

```sh
.venv/bin/python -m backend.migrate_encryption --source-db instance/demo.sqlite3 --source-uploads instance/uploads --destination instance/encrypted
./run-local.sh
```

This copies data in memory, applies the additive v4 extension, encrypts clinical values and images, verifies every decoded clinical field/image hash and foreign keys, rebuilds SQLite pages, then publishes the destination directory. Sources are never overwritten. Multiple SQL image rows may share one source file; migration preserves every row and encrypts each distinct file once, rejecting conflicting hashes or MIME metadata. Original plaintext sources/backups remain for rollback and need secure archival/removal after verification; they are never used by the encrypted launcher. Unknown source schema extensions are refused rather than silently leaving their data plaintext. See [encryption/migration details](docs/ENCRYPTION.md); [the original authentication migration](docs/AUTH_MIGRATION.md) remains documented separately.

Open http://127.0.0.1:5000/login. Startup checks runtime `user_version=4` and the matching environment key. An existing plaintext database is refused with migration instructions. Source attachments and the base schema are preserved. Back up encrypted DB/uploads and the encryption key separately; key loss makes encrypted data unreadable.

`seed-demo` requires an empty database named exactly `demo.sqlite3`. It inserts fictional patients, clinicians and one submitted case with an image marked `SYNTHETIC DEMO - NOT SKIN`. Repeating seed preserves records and reports that the database is not empty. To deliberately reset and reseed **only the configured database named demo.sqlite3**, stop the server and run:

```sh
.venv/bin/python -m flask --app app reset-demo --confirm-demo
```

Reset transactionally clears demo accounts and clinical records; it never deletes a directory or any other database. Without `--purge-images`, unreferenced image files are retained. Never point this command at a real database renamed `demo.sqlite3`.

### Full local demo reset (including test logins and images)

1. Stop Flask with Ctrl-C in its terminal. If it is running in the background, run `lsof -nP -iTCP:5000 -sTCP:LISTEN`, verify this app's PID, then `kill -TERM <PID>` using that actual number.
2. From the repository root, run:

```sh
.venv/bin/python -m flask --app app reset-demo --confirm-demo --purge-images --create-test-accounts
./run-local.sh
```

This deletes the configured demo's cases, reviews, AI attempts, accounts and old generated images, then seeds two patients, two clinicians, one submitted synthetic case/image and five logins. Each login receives a fresh random password. Open `instance/test-accounts.txt` in your editor for patient1, patient2, clinician1, clinician2 and worker1 usernames/plaintext passwords (local demo only, mode 0600, Git-ignored). Previously issued passwords stop working. Worker-assisted submission is still unavailable. Do not run `provision-account` again for these usernames.

The default file-managed session secret rotates to invalidate existing browser sessions; log in again after restart. If you explicitly set `SECRET_KEY`, change that environment secret yourself before restarting. Encryption key, code, notebooks, models, source attachments and legacy migration backups stay intact. Reset does **not** erase old plaintext migration sources/backups; see `docs/ENCRYPTION.md` for that separate archive/removal concern. Purging is allowed only for the demo database's dedicated sibling `uploads` directory and removes generated image filenames, preserving unrelated files.

Direct Flask CLI commands now select the same existing `instance/encryption.key` as the launcher when no key source is specified. You do not need to export it again on this installation. Explicit environment/configuration values take precedence; a missing/wrong key still fails closed, and no new encryption key is generated. `.env` is not automatically loaded.

### Minimal AI-assisted triage

Event timestamps display in the browser/device's local timezone and date format,
including a timezone label. Hovering a timestamp shows its original UTC value.
Without JavaScript or supported date formatting, the explicitly labeled UTC value
remains visible. Storage, sorting and audit timestamps remain UTC. Birthdays and
follow-up dates are calendar dates and are never shifted to another timezone.

The clinician report uses short explanations and shows its top three suggestions
first. Match scores appear as whole percentages, with “Less than 1%” and “Over
99%” for extreme values; saved scores are unchanged. A visible explanation says
these scores describe AI matches, not the chance of a condition or its severity.
Other suggestions, previous analyses and full report details use native
expandable sections. Previously saved prototype triage wording is shortened for
display without rewriting encrypted history or changing its priority.

After successful SCIN inference, `backend/ai/triage.py:triage_case` evaluates structured answers only. Its editable `SYMPTOM_RULES` are: shortness of breath → emergency; rapid worsening → urgent; fever **and** discharge → urgent. Emergency always wins. Required answers are those four fields; NULL/malformed answers require manual review. No extra intake fields or free-text matching are added.

`CONDITION_PRIORITIES` contains the saved model's actual 14 labels. Only the **top-ranked** prediction may raise priority: `Malignancy/Precancer` → urgent. All remaining supported labels map to routine: Acne/Follicular, Bacterial Infection, Benign Lesion, Dermatitis/Eczema, Fungal Infection, Hair/Nail Disorder, Inflammatory/Autoimmune, Other, Parasite/Bite, Pigment Disorder, Trauma/Wound, Vascular/Purpura, Viral Infection. These mappings never reduce symptom priority. `Other` also requires manual review.

`AI_TRIAGE_DEMO_THRESHOLD=0.5` is an **unvalidated demo uncertainty threshold**, not a severity threshold. A lower top score, missing/invalid output, any unmapped label or missing required symptom answer sets `needs_manual_review`. Routine with this flag displays **“Priority undetermined — manual review needed”**. Urgent/emergency remain raised even when review is required. The separate clinician form remains authoritative; these illustrative rules are not validated medical guidance or treatment advice.

The clinician case page labels results **“AI-assisted triage — prototype; clinician review required.”** Level/reasons/manual-review/method persist in the existing encrypted AI rationale envelope, atomically with predictions; no schema migration. Existing queue enums are emergency→red, urgent→amber, routine→green, or routine+manual→undetermined. Old attempts retain their original results; retry inference to obtain triage under this policy. Patients still receive clinician-released outcomes only. Unavailable AI continues to allow submission and manual clinical review.

## Accounts and walkthrough

The user-switching dropdown is removed. `/login` accepts a username/password; `/patients/new` signs up a **new patient account and profile only**. There are no default passwords, public provider/worker signup, or web links to claim existing patient IDs. After signup, the new patient is logged in. Usernames are ASCII identifiers; names, complaints and notes remain exact UTF-8/Arabic. Passwords are salted scrypt hashes using Werkzeug, never plaintext SQL/session data.

The reset seeds Patient 1 Synthetic Patient A, Patient 2 مريض تجريبي Patient B, and Providers 1/2 Synthetic Clinicians A/B. With `--create-test-accounts`, their login credentials already exist in `instance/test-accounts.txt`; do not provision the same usernames again. For a fresh `seed-demo` without accounts, provision them while the server is stopped; each command prompts for your chosen password twice without echoing it:

```sh
.venv/bin/python -m flask --app app provision-account --username patient1 --role patient --patient-id 1
.venv/bin/python -m flask --app app provision-account --username clinician1 --role provider --provider-id 1
# Optional separate records/worker account:
.venv/bin/python -m flask --app app provision-account --username patient2 --role patient --patient-id 2
.venv/bin/python -m flask --app app provision-account --username clinician2 --role provider --provider-id 2
.venv/bin/python -m flask --app app provision-account --username worker1 --role worker
```

Use 12–256 character passwords and unique 3–64 character usernames (letters/digits/dot/underscore/hyphen). The operator explicitly selects the role/entity link; this command is not exposed through HTTP. Existing records without accounts stay preserved but cannot be selected at login. Worker accounts can log in, but patient access/submission remains blocked pending access-grant/attribution extensions. Never enter passwords into a command line or commit them. Public signup cannot change or acquire a provider role.

Navigation is ordinary role-appropriate links/buttons: Home for everyone, My cases/New case for patients, Clinician queue for providers, and a CSRF-protected POST Logout for authenticated users. Every protected backend request still checks role/ownership; hiding a link is not authorization.

The signed session stores Account ID only. The server reloads active status, role and patient/provider linkage on each request. Login/signup rotate the session/CSRF token; logout clears the session. Unknown usernames and wrong passwords get the same error. Loopback/Host restrictions remain. This is actual local password authentication, with production features still missing (reset/recovery, verification/MFA, throttling, durable session revocation and comprehensive audit). Do not expose it publicly or use real data.

1. Log in with a provisioned patient account or sign up a new fictional patient.
2. Create a draft with a nonblank complaint; enter duration or leave it unknown.
3. The draft page shows all intake sections together, including additional skin/model questions. Select all applicable checkbox choices and confirm each group only after considering every item; unchecked answers then mean No. Unconfirmed unanswered choices stay unknown and saved No values are preserved. Select duration directly from the offered ranges. Age group derives from birthday at submission; sex at birth reuses the profile's canonical sex field. Select affected body sites for the photos too.
4. Choose the body site for the new photos, then use existing files, the native phone camera, or the live camera. Selections have previews and removal before upload. Save draft persists all changes/photos without submitting; repeat to add photographs for another affected site. Saving is server persistence, not offline support.
5. Check explicit consent and use Submit case to save the entire intake and submit in one transaction. No prior questionnaire/photo save is required. Invalid data or photographs roll back that action. The case becomes Pending Review; consent/version and initial submission time are preserved. Patient labels use complaint and creation time rather than internal case numbers.
6. Log out, log in with a separately provisioned clinician account, open the queue/case, and assign it to yourself.
7. Optionally request AI analysis using the saved patient answers; the clinician completes only missing inputs. Recorded answers and profile-derived categories are read-only there. Missing binary answers or contradictory choices prevent inference. You can publish a review without requesting AI or after an AI failure. You may provide a message without a diagnosis for an inconclusive, needs-information or referral decision. Confirmed/modified decisions require diagnoses; select exactly one populated diagnosis as primary. Up to three diagnoses and one optional treatment plan per diagnosis are supported by the simple form. Medication/dosage require treatment instructions; general advice without a diagnosis belongs in the patient message.
8. A referral requires a reason and destination. Record explicit urgent/emergency intent in the referral reason and patient instructions when documenting an escalation; red priority alone does not imply escalation. Follow-up is a real calendar date.
9. Log out and log back in as the patient to see only released messages, clinician diagnoses/certainty, treatments, referral and follow-up. Private clinician notes and unconfirmed AI suggestions are not exposed to patients.

Reviews publish atomically with the case state; history remains stored. An explicit review revision reopens a reviewed case without erasing its previous result; a new review supersedes it using `(reviewed_at, review_id)` ordering. Closing a reviewed case prevents further revision. Needs-information requests are real committed reviews with a patient message; editing/resubmission remains disabled pending a durable revision migration, rather than overwriting submitted content.

## Configuration, storage and dependencies

`.env.example` documents optional environment variables without secrets. No dotenv dependency is used and `.env` is not automatically loaded. Set shell environment variables before invoking Flask. Relative paths resolve against the repository root.

| Variable | Default |
|---|---|
| `DATABASE` | defaults to `instance/encrypted/demo.sqlite3` for both Flask and the launcher |
| `UPLOAD_DIR` | defaults to `instance/encrypted/uploads` (private, outside static assets) |
| `ENCRYPTION_KEY_FILE` | launcher selects private `instance/encryption.key`; alternatively supply `ENCRYPTION_KEY`, never both |
| `SESSION_COOKIE_SECURE` | `0` for local HTTP; set `1` with HTTPS |
| `APP_LOCALE` | `en` (`ar` prepares rtl with English fallback/incomplete notice) |
| `MODEL_PATH` | `notebooks/SCIN_custom_model.keras`; explicitly empty disables inference |
| `AI_TIMEOUT_SECONDS` | `60`, including the first request's lazy model load |
| `MAX_IMAGE_BYTES` | `8388608` (8 MiB per original image) |
| `MAX_IMAGE_COUNT` | `12` per case |
| `SECRET_KEY` | Generated once in private `instance/session.key` (mode 0600) |

Keep `instance/session.key` across restarts to retain sessions; it is ignored by Git. Keep both the database and private uploads when backing up. All connections use foreign keys and a 5000 ms busy timeout. Inputs are parameterized; writes use explicit transactions and rollback. POST forms require session CSRF tokens. Records/images use no-store responses. Native form validation is supplemented by server validation.

Pillow decodes actual image content to validate single-frame JPEG/PNG files. Newly uploaded originals are encrypted with Fernet; authorized decryption returns the exact original bytes with their correct MIME and source SHA-256; EXIF/GPS, orientation, ICC and PNG text are retained if present. The earlier EXIF stripping behavior has been superseded at the user's request. Existing normalized images remain readable; previously discarded metadata cannot be recovered. Images captured through a browser canvas generally have no camera EXIF/GPS, and no geolocation is fabricated or collected separately. Outbreak detection is not implemented.

There is no application MAX_IMAGE_PIXELS setting or patient-facing pixel limit. File-size/count limits and the decoder's built-in decompression protections remain. Local inference applies the saved model's RGB/resize/padding/normalization contract in memory while retaining original source bytes and hashes. Private images are served only through authorized `/images/<image_id>` routes; no arbitrary client path/URL is accepted. Upload and combined-intake rollback remove new files. Crash-time orphan reconciliation and comprehensive auditing remain deferred.

Core dependencies: Flask 3.1.2, Pillow 12.0.0, cryptography 50.0.2 and Werkzeug 3.1.9 (already supplied by Flask, explicitly pinned for password hashing). Observed transitive versions: Jinja2 3.1.6, MarkupSafe 3.0.4, click 8.5.0, itsdangerous 2.2.0, blinker 1.9.0. `pypdf 6.1.1` was used solely to inspect the supplied white paper and is not an application dependency. Saved-model inference has separate optional runtime dependencies documented below; it does not import TensorFlow/Keras during ordinary Flask startup. No frontend framework, extra service or destructive migration was introduced. Only the documented additive Account and v4 encryption extensions were applied; schema.sql is unchanged.

English UI strings live in `backend/i18n.py`. Arabic user-entered names, complaints, messages and notes are preserved exactly; HTML uses UTF-8 and automatic text direction. Arabic translation and full browser RTL verification remain pending. **Arabic interface support is not complete.**

## Tests and handoff

```sh
PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest test_encryption test_auth test_workflow test_intake test_presentation test_ai_runner test_local_model_adapter -v
```

80 application tests passed after the patient-questionnaire update. The real HTTP workflow also passed with patient checkbox answers, the actual saved Keras model, encrypted scores and a child-process restart, preserving exact Arabic text, released care and identical image bytes. These are software checks with synthetic inputs, not clinical validation. Reproduce the isolated HTTP test (temporary database, synthetic accounts, loopback port 5001):

```sh
PYTHONPATH=. .venv/bin/python tests/live_smoke.py
# Also verify the existing saved model using patient-supplied answers:
PYTHONPATH=. .venv/bin/python tests/live_smoke.py --with-model
```

To exercise the normally running server instead, use a separately provisioned clinician account. The script prompts for its password, signs up a new synthetic patient, and saves a private patient session cookie (mode 0600) for restart verification; no password is written to disk:

```sh
.venv/bin/python tests/http_smoke.py create --provider-username clinician1
# Stop/restart the server, then:
.venv/bin/python tests/http_smoke.py verify
```

The script adds fictional records and writes ignored `instance/http-smoke.json` and `instance/http-smoke.cookies`; it does not reset anything. Treat the cookie file as a session credential. An actual browser smoke test remains unverified: the earlier Computer Use attempt did not approve Safari access. HTTP checks are not visual/browser interaction checks.

## Starting and stopping the local server

Run the foreground server from this repository in an ordinary terminal:

```sh
./run-local.sh
```

That terminal stays occupied and shows request logs. Stop it with **Ctrl-C in that same terminal**; close/reopen a browser tab without stopping the server. Ctrl-C stops Flask; it does not delete SQLite or uploads. Relaunch with the same command to keep saved data. Do not use debug/reloader or multiple server processes with the local AI runner.

At the 2026-10-11 UI/local-time verification, the restarted server is PID **7163**, running in a Codex-managed background process without an interactive terminal. It uses the encrypted dataset and selected SCIN model. To take over in your own terminal:

```sh
lsof -nP -iTCP:5000 -sTCP:LISTEN
# Verify the Python process is this app. Use its current numeric PID here:
kill -TERM 7163
./run-local.sh
```

In your terminal, **Ctrl-C** stops the foreground server; running `./run-local.sh` restarts it with persisted encrypted records/images. PID values change on restart. No installed service, nohup, external hosting or deployment was configured.

See [architecture and Tkinter comparison](docs/ARCHITECTURE.md) for the folder map and route → service → database → template flow. See [AI integration](docs/AI_INTEGRATION.md) for the exact typed adapter and configuration seam; [requirements](docs/REQUIREMENTS.md) for implemented/pending features, white-paper reconciliation and migration proposals; and [test results](docs/TEST_RESULTS.md) for individual AT-01 through AT-12 results. The local schema-supported workflow and password authentication are functional; the full MVP remains incomplete. Nothing was deployed externally or pushed to GitHub.

## Presentation and browser behavior

The existing backend classes remain in their original folders; see `docs/ARCHITECTURE.md` for responsibilities and the Tkinter comparison. Shared `static/app.css` supplies responsive medical styling and accessible focus states. `static/forms.js` adds pre-upload previews/removal, body-site selection, submission states, inline server errors and close confirmation. `static/camera.js` handles optional live capture, permissions and camera track cleanup. Forms remain usable without JavaScript. No new application dependency or schema change was introduced.

For this workspace, already-provisioned synthetic account credentials are in the Git-ignored `instance/test-accounts.txt` (mode 0600); these are local test credentials, not built-in application defaults. Do not rerun provisioning for those usernames. The database stores hashes only. Resetting the demo removes accounts as well as cases.

Optional JavaScript logic smoke test, if Node.js is installed: `node tests/forms_smoke.mjs`. It uses lightweight DOM doubles and does not replace a real browser/mobile/assistive-technology check. Full Arabic translations and browser RTL verification remain pending. Restart an already-running Flask process after changing Python or cached templates; the normal non-debug server does not reload application code automatically.

Native phone capture uses `capture="environment"` alongside a separate existing-file selector; [browser support varies](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture). The live-camera button is shown only where getUserMedia and file assignment are available. Live capture needs a secure browser context (localhost qualifies); camera permission denial leaves file/native capture available. The app remains loopback-only: responsive phone layout does not change hosting/access policy. Camera hardware and physical-phone visual checks remain unverified in this environment.

Run optional camera lifecycle logic checks with `node tests/camera_smoke.mjs`; as with forms_smoke.mjs these use API doubles, not real hardware. Metadata-preservation and single-page intake tests are in `tests/test_intake.py`. After code changes, restart your foreground Flask server with Ctrl-C and the launch command above.

## Gender, preprocessing and encryption boundaries

Signup uses Female, Male, or Unknown / Prefer not to say. The existing field name `sex` is retained for compatibility; logical values female/male/unknown are encrypted at rest. `backend/preprocessing.py:gender_one_hot` derives [1,0,0], [0,1,0] or [0,0,1]. Legacy unrecognized free text becomes unknown while its exact original is archived encrypted. `symptom_answers` validates browser values and `symptom_vector` preserves None in the documented fixed order. These helpers do not select a clinical threshold or supply missing saved-model features.

Fernet encrypts patient demographics/contact, complaint/duration, structured symptoms/notes, released/private review text/referral/follow-up, diagnosis/treatment text, stored analysis snapshots/narratives and image originals. IDs, relationships, operational dates/status/priority/certainty/quality and account usernames/password hashes remain queryable metadata. This does not encrypt the entire SQLite file or OS memory/swap. Structured medical-history storage is absent; history written in existing notes is encrypted. Patient service results now exclude private clinician notes and unconfirmed analysis history, in addition to existing template restrictions. Authentication retains scrypt, database-owned roles/ownership, session rotation/HttpOnly/SameSite, CSRF, loopback checks and no-store responses. Production throttling, MFA/recovery, comprehensive audit and key-rotation tooling remain pending.

The plaintext synthetic test-password file remains Git-ignored and 0600. The subsequent authorized demo reset replaced older accounts with five freshly generated logins, all verified. Never put actual encryption keys or passwords into tracked files/command arguments/logs.

## Supplied local model in the clinician workflow

`MODEL_PATH` selects the user-supplied saved model. The default is
`notebooks/SCIN_custom_model.keras`, with its required adjacent companions
`SCIN_custom_metadata_encoder.json` and `SCIN_custom_classes.json`. This custom
model has **14 grouped-condition outputs**, separate from the 41-output PyTorch
experiment described below. No training or notebook/artifact modification is
part of this application integration.

For the saved Keras model, install the tested inference runtime if missing:

```sh
.venv/bin/python -m pip install -r requirements-inference.txt
MODEL_PATH=notebooks/SCIN_custom_model.keras ./run-local.sh
# To use the complete manual workflow with inference disabled:
MODEL_PATH='' ./run-local.sh
```

TensorFlow/Keras load lazily on the first authorized analysis request, not when
Flask starts. The 60-second timeout includes that cold start. Missing artifacts,
runtime errors or unavailable AI leave manual review available. `.env` is not
autoloaded: export variables in the shell or prefix the launch command. Restart
after changing model artifacts; model/version provenance binds the selected
weights, encoder, class mapping and input policy. Another saved model needs its
compatible architecture and companion configuration; changing the filename
cannot reconstruct arbitrary weights.

The current environment already has TensorFlow 2.22.0rc0, Keras 3.15.1 and NumPy
2.5.4; no installation was needed during integration. The TensorFlow pin is the
release-candidate build tested with this Python 3.14 environment. Keep inference
dependencies separate from optional notebook/training dependencies.

The selected encoder requires **31 binary inputs and five categorical fields**,
producing 68 metadata values. Patients answer the questions in their draft; the
existing encrypted Symptom envelope stores `model_metadata` alongside the six
original answers. Sex at birth reuses the canonical profile `sex` value as Omar
requested; age group derives from birthday at submission. Missing DOB or ages
outside 18–79 use the trained unknown category. Duration is selected directly
without inventing exact days; an explicitly selected range replaces the numeric
duration on an edited draft. Body locations and skin type are explicitly answered.
Clinicians can supply missing answers without changing recorded patient choices;
the exact inference input remains in its encrypted analysis-attempt snapshot
(`contract_version=1.1`). No SQL migration is needed. Older submitted cases stay
frozen, with missing answers completed by clinicians. Manual submission/review
works even with incomplete model answers; unknown binary values block inference.

Authorized source images are authenticated/decrypted in memory, processed using
the saved contract, and their per-image probabilities are averaged. All 14 ranked
groups remain unconfirmed, uncalibrated decision-support scores. Clinical priority
stays **undetermined**; image quality is not automatically assessed. Complaints
and free-text notes are not embedded. AI never publishes diagnoses or treatments
and is never requested automatically on submission. See
[typed application bridge](docs/AI_INTEGRATION.md) and
[saved-model contracts](docs/MODEL_INTERFACE.md).

## SCIN multimodal model pipeline

The explicitly requested optional PyTorch pipeline lives in `scin_ml/` and
`notebooks/SCIN_MODEL.IPYNB`; it preserves the cleaned artifact, EDA and prior
preprocessing exports. Install/run from the repository root:

```sh
.venv/bin/python -m pip install -r requirements-ml.txt
.venv/bin/python -m scin_ml --output-dir notebooks/scin_runs/my_run --exclude-missing-primary
```

One original case has no primary image; the explicit flag records its exclusion
without changing the source. Outputs include the best model, train-only encoder,
class/config JSON, evaluation reports and an independently loadable `app_model/`
bundle. This optional 41-output experiment is distinct from the supplied custom
Keras model selected by the application. Each model needs its own complete saved
metadata/class contract; inputs are not interchangeable merely because their
encoded widths match. See
[SCIN pipeline, commands and inference interface](docs/SCIN_PIPELINE.md).
