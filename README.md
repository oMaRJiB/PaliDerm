# PaliDerm local prototype

A working patient-intake → private images → consent submission → clinician review → patient-result workflow. Synthetic data only. Plain Flask/Jinja forms with password login and patient signup. The supplied base schema v2 is unchanged; runtime v4 adds authenticated field/file encryption after the additive authentication migration. AI is unconfigured by default and never blocks submission or review. This is not an emergency service, clinical validation, production security, HIPAA compliance, or a complete implementation of the long-term plan.

## Install, initialize and launch

The current workspace has already been migrated to `instance/encrypted/demo.sqlite3` and `instance/encrypted/uploads`. Its private key is in `instance/encryption.key` (0600, Git-ignored); existing account passwords are unchanged. **Do not regenerate that key or rerun migration into the existing destination.** Start from the repository root with:

```sh
./run-local.sh
```

The script supplies database/upload/key-file paths through environment variables; the application never generates a replacement encryption key or falls back to plaintext. Missing/invalid/wrong keys fail before serving records. An encryption key is distinct from the session-signing secret. Tested with Python 3.14.7; code requires Python 3.11+.

For a **fresh installation only**, create the virtual environment, install dependencies and generate a new key without displaying it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p instance
.venv/bin/python -c 'import os; from cryptography.fernet import Fernet; fd=os.open("instance/encryption.key",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,Fernet.generate_key()+b"\n"); os.close(fd)'
```

The key command refuses to overwrite an existing file. Before any direct Flask CLI command, select the encrypted environment in that terminal:

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

This copies data in memory, applies the additive v4 extension, encrypts clinical values and images, verifies every decoded clinical field/image hash and foreign keys, rebuilds SQLite pages, then publishes the destination directory. Sources are never overwritten. Original plaintext sources/backups remain for rollback and need secure archival/removal after verification; they are never used by the encrypted launcher. Unknown source schema extensions are refused rather than silently leaving their data plaintext. See [encryption/migration details](docs/ENCRYPTION.md); [the original authentication migration](docs/AUTH_MIGRATION.md) remains documented separately.

Open http://127.0.0.1:5000/login. Startup checks runtime `user_version=4` and the matching environment key. An existing plaintext database is refused with migration instructions. Source attachments and the base schema are preserved. Back up encrypted DB/uploads and the encryption key separately; key loss makes encrypted data unreadable.

`seed-demo` requires an empty database named exactly `demo.sqlite3`. It inserts fictional patients, clinicians and one submitted case with an image marked `SYNTHETIC DEMO - NOT SKIN`. Repeating seed preserves records and reports that the database is not empty. To deliberately reset and reseed **only the configured database named demo.sqlite3**, stop the server and run:

```sh
.venv/bin/python -m flask --app app reset-demo --confirm-demo
```

Reset transactionally clears demo accounts and clinical records; it never deletes a directory or any other database. Unreferenced image files are retained. Never point this command at a real database renamed `demo.sqlite3`.

## Accounts and walkthrough

The user-switching dropdown is removed. `/login` accepts a username/password; `/patients/new` signs up a **new patient account and profile only**. There are no default passwords, public provider/worker signup, or web links to claim existing patient IDs. After signup, the new patient is logged in. Usernames are ASCII identifiers; names, complaints and notes remain exact UTF-8/Arabic. Passwords are salted scrypt hashes using Werkzeug, never plaintext SQL/session data.

Existing synthetic records are preserved: Patient 1 is Synthetic Patient A, Patient 2 is مريض تجريبي Patient B, and Providers 1/2 are Synthetic Clinicians A/B. To access them, provision accounts in a terminal while the server is stopped; each command prompts for your chosen password twice without echoing it:

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
3. The draft page shows all intake sections together. Answer the questionnaire and select affected body sites; Unknown is SQL NULL and No is 0.
4. Choose the body site for the new photos, then use existing files, the native phone camera, or the live camera. Selections have previews and removal before upload. Save draft persists all changes/photos without submitting; repeat to add photographs for another affected site. Saving is server persistence, not offline support.
5. Check explicit consent and use Submit case to save the entire intake and submit in one transaction. No prior questionnaire/photo save is required. Invalid data or photographs roll back that action. The case becomes Pending Review; consent/version and initial submission time are preserved. Patient labels use complaint and creation time rather than internal case numbers.
6. Log out, log in with a separately provisioned clinician account, open the queue/case, and assign it to yourself.
7. Publish a review. You may provide a message without a diagnosis for an inconclusive, needs-information or referral decision. Confirmed/modified decisions require diagnoses; select exactly one populated diagnosis as primary. Up to three diagnoses and one optional treatment plan per diagnosis are supported by the simple form. Medication/dosage require treatment instructions; general advice without a diagnosis belongs in the patient message.
8. A referral requires a reason and destination. Record explicit urgent/emergency intent in the referral reason and patient instructions when documenting an escalation; red priority alone does not imply escalation. Follow-up is a real calendar date.
9. Log out and log back in as the patient to see only released messages, clinician diagnoses/certainty, treatments, referral and follow-up. Private clinician notes and unconfirmed AI suggestions are not exposed to patients.

Reviews publish atomically with the case state; history remains stored. An explicit review revision reopens a reviewed case without erasing its previous result; a new review supersedes it using `(reviewed_at, review_id)` ordering. Closing a reviewed case prevents further revision. Needs-information requests are real committed reviews with a patient message; editing/resubmission remains disabled pending a durable revision migration, rather than overwriting submitted content.

## Configuration, storage and dependencies

`.env.example` documents optional environment variables without secrets. No dotenv dependency is used and `.env` is not automatically loaded. Set shell environment variables before invoking Flask. Relative paths resolve against the repository root.

| Variable | Default |
|---|---|
| `DATABASE` | launcher selects `instance/encrypted/demo.sqlite3`; direct Flask requires this environment setting for migrated data |
| `UPLOAD_DIR` | launcher selects `instance/encrypted/uploads` (private, outside static assets) |
| `ENCRYPTION_KEY_FILE` | launcher selects private `instance/encryption.key`; alternatively supply `ENCRYPTION_KEY`, never both |
| `SESSION_COOKIE_SECURE` | `0` for local HTTP; set `1` with HTTPS |
| `APP_LOCALE` | `en` (`ar` prepares rtl with English fallback/incomplete notice) |
| `MAX_IMAGE_BYTES` | `8388608` (8 MiB per original image) |
| `MAX_IMAGE_COUNT` | `12` per case |
| `SECRET_KEY` | Generated once in private `instance/session.key` (mode 0600) |

Keep `instance/session.key` across restarts to retain sessions; it is ignored by Git. Keep both the database and private uploads when backing up. All connections use foreign keys and a 5000 ms busy timeout. Inputs are parameterized; writes use explicit transactions and rollback. POST forms require session CSRF tokens. Records/images use no-store responses. Native form validation is supplemented by server validation.

Pillow decodes actual image content to validate single-frame JPEG/PNG files. Newly uploaded originals are encrypted with Fernet; authorized decryption returns the exact original bytes with their correct MIME and source SHA-256; EXIF/GPS, orientation, ICC and PNG text are retained if present. The earlier EXIF stripping behavior has been superseded at the user's request. Existing normalized images remain readable; previously discarded metadata cannot be recovered. Images captured through a browser canvas generally have no camera EXIF/GPS, and no geolocation is fabricated or collected separately. Outbreak detection is not implemented.

There is no application MAX_IMAGE_PIXELS setting or patient-facing pixel limit. File-size/count limits and the decoder's built-in decompression protections remain. There is no current inference/preprocessing that requires resizing. Future model-specific downscaling belongs in the adapter's documented preprocessing, with originals retained and source/transform/hash provenance explicit. Private images are served only through authorized `/images/<image_id>` routes; no arbitrary client path/URL is accepted. Upload and combined-intake rollback remove new files. Crash-time orphan reconciliation and comprehensive auditing remain deferred.

Direct dependencies: Flask 3.1.2, Pillow 12.0.0, cryptography 50.0.2 and Werkzeug 3.1.9 (already supplied by Flask, explicitly pinned for password hashing). Observed transitive versions: Jinja2 3.1.6, MarkupSafe 3.0.4, click 8.5.0, itsdangerous 2.2.0, blinker 1.9.0. `pypdf 6.1.1` was used solely to inspect the supplied white paper and is not an application dependency. No frontend framework, AI model, ML runtime, extra service, or destructive migration was introduced. Only the documented additive Account and v4 encryption extensions were applied; schema.sql is unchanged.

English UI strings live in `backend/i18n.py`. Arabic user-entered names, complaints, messages and notes are preserved exactly; HTML uses UTF-8 and automatic text direction. Arabic translation and full browser RTL verification remain pending. **Arabic interface support is not complete.**

## Tests and handoff

```sh
.venv/bin/python -m unittest discover -s tests -v
```

50 focused tests passed after the encryption/gender update (including the previous 40 tests). The real HTTP workflow also passed using password signup/login/logout, followed by an actual child-process restart and verification of exact Arabic text, released care and identical image bytes. Reproduce this isolated test (temporary database, synthetic accounts, loopback port 5001):

```sh
PYTHONPATH=. .venv/bin/python tests/live_smoke.py
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

At this encryption-pass handoff, the server is PID **57955**, running in a Codex-managed background process without an interactive terminal. It uses only the encrypted dataset. To take over in your own terminal:

```sh
lsof -nP -iTCP:5000 -sTCP:LISTEN
# Verify the Python process is this app, then replace PID with its numeric PID:
kill -TERM <PID>
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

Signup uses Female, Male, or Unknown / Prefer not to say. The existing field name `sex` is retained for compatibility; logical values female/male/unknown are encrypted at rest. `backend/preprocessing.py:gender_one_hot` derives [1,0,0], [0,1,0] or [0,0,1]. Legacy unrecognized free text becomes unknown while its exact original is archived encrypted. `symptom_answers` validates browser values and `symptom_vector` preserves None in the documented fixed order. No model or clinical thresholds are added.

Fernet encrypts patient demographics/contact, complaint/duration, structured symptoms/notes, released/private review text/referral/follow-up, diagnosis/treatment text, stored analysis snapshots/narratives and image originals. IDs, relationships, operational dates/status/priority/certainty/quality and account usernames/password hashes remain queryable metadata. This does not encrypt the entire SQLite file or OS memory/swap. Structured medical-history storage is absent; history written in existing notes is encrypted. Patient service results now exclude private clinician notes and unconfirmed analysis history, in addition to existing template restrictions. Authentication retains scrypt, database-owned roles/ownership, session rotation/HttpOnly/SameSite, CSRF, loopback checks and no-store responses. Production throttling, MFA/recovery, comprehensive audit and key-rotation tooling remain pending.

The previously requested plaintext synthetic test-password file remains Git-ignored and 0600; patient display names were removed from it and its database path updated. All six documented test logins were rechecked after migration, and all seven database accounts were preserved. Never put actual encryption keys or passwords into tracked files/command arguments/logs.

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
bundle. Flask's AI adapter is unchanged; complete SCIN metadata mapping is still
required before connecting this model to app intake. See
[SCIN pipeline, commands and inference interface](docs/SCIN_PIPELINE.md).
