# PaliDerm local prototype

A working patient-intake → private images → consent submission → clinician review → patient-result workflow. Synthetic data only. Plain Flask/Jinja forms; SQLite schema v2 is unchanged. AI is unconfigured by default and never blocks submission or review. This is not an emergency service, clinical validation, production authentication, HIPAA compliance, or a complete implementation of the long-term plan.

## Install, initialize and launch

Run from the repository root. Tested with Python 3.14.7; code requires Python 3.11+.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m flask --app app init-db
.venv/bin/python -m flask --app app seed-demo
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5000
```

Open http://127.0.0.1:5000/login. Only the first initialization creates `instance/demo.sqlite3` from `schema.sql`; startup verifies `user_version=2` and foreign keys. Subsequent launches preserve patients, cases, reviews and images. An existing version mismatch fails with a message to choose a fresh database path or an explicit reviewed migration; it never resets or imports the older source `../datamodel.sqlite3`.

`seed-demo` requires an empty database named exactly `demo.sqlite3`. It inserts fictional patients, clinicians and one submitted case with an image marked `SYNTHETIC DEMO - NOT SKIN`. Repeating seed preserves records and reports that the database is not empty. To deliberately reset and reseed **only the configured database named demo.sqlite3**, stop the server and run:

```sh
.venv/bin/python -m flask --app app reset-demo --confirm-demo
```

Reset transactionally clears demo clinical records; it never deletes a directory or any other database. Unreferenced image files are retained. Never point this command at a real database renamed `demo.sqlite3`.

## Demo identities and walkthrough

At `/login`, choose a seeded identity:

| Token | Identity | Access |
|---|---|---|
| `patient:1` | Synthetic Patient A | Own profile/cases/images and released outcomes |
| `patient:2` | مريض تجريبي Patient B | Separate ownership boundary |
| `provider:1` | Synthetic Clinician A | Submitted unassigned cases and own assignments |
| `provider:2` | Synthetic Clinician B | Separate assignment boundary |
| `worker-demo` | Healthcare worker | Pending-schema notice; no patient access or review privileges |

New profiles become new local patient identities and remain selectable after restart. The login selector intentionally lists fictional identities for anyone on the local machine. The signed session stores an identity token; the server resolves roles/ownership from its permitted demo records, never accepts role/provider IDs on intake/review forms, and rechecks authorization inside write transactions. This is demonstration access control, **not authentication against a malicious local user**. Requests from outside loopback or with an unexpected Host are rejected. Do not expose it publicly, proxy it externally, enable debug mode, or use real data. Production identity and access management must precede deployment.

1. Select Patient A or create a new fictional patient profile.
2. Create a draft with a nonblank complaint; enter duration or leave it unknown.
3. Save the questionnaire and affected body sites. Unknown is SQL NULL; No is 0. Saving a draft is server persistence, not offline support.
4. Select a saved body site and upload multiple JPEG/PNG images. Saved private images appear on the page. You can add more images to other sites.
5. Check the explicit submission consent and submit. The case becomes Pending Review; consent timestamp/version and initial submission time are preserved.
6. Switch to Clinician A, open the queue/case, and assign it to yourself.
7. Publish a review. You may provide a message without a diagnosis for an inconclusive, needs-information or referral decision. Confirmed/modified decisions require diagnoses; select exactly one populated diagnosis as primary. Up to three diagnoses and one optional treatment plan per diagnosis are supported by the simple form. Medication/dosage require treatment instructions; general advice without a diagnosis belongs in the patient message.
8. A referral requires a reason and destination. Record explicit urgent/emergency intent in the referral reason and patient instructions when documenting an escalation; red priority alone does not imply escalation. Follow-up is a real calendar date.
9. Switch back to the patient to see only released messages, clinician diagnoses/certainty, treatments, referral and follow-up. Private clinician notes and unconfirmed AI suggestions are not exposed to patients.

Reviews publish atomically with the case state; history remains stored. An explicit review revision reopens a reviewed case without erasing its previous result; a new review supersedes it using `(reviewed_at, review_id)` ordering. Closing a reviewed case prevents further revision. Needs-information requests are real committed reviews with a patient message; editing/resubmission remains disabled pending a durable revision migration, rather than overwriting submitted content.

## Configuration, storage and dependencies

`.env.example` documents optional environment variables without secrets. No dotenv dependency is used and `.env` is not automatically loaded. Set shell environment variables before invoking Flask. Relative paths resolve against the repository root.

| Variable | Default |
|---|---|
| `DATABASE` | `instance/demo.sqlite3` |
| `UPLOAD_DIR` | `instance/uploads` (private, outside static assets) |
| `APP_LOCALE` | `en` (`ar` prepares rtl with English fallback/incomplete notice) |
| `MAX_IMAGE_BYTES` | `8388608` (8 MiB; encoded input and stored PNG) |
| `MAX_IMAGE_COUNT` | `12` per case |
| `MAX_IMAGE_PIXELS` | `20000000` per image |
| `SECRET_KEY` | Generated once in private `instance/session.key` (mode 0600) |

Keep `instance/session.key` across restarts to retain sessions; it is ignored by Git. Keep both the database and private uploads when backing up. All connections use foreign keys and a 5000 ms busy timeout. Inputs are parameterized; writes use explicit transactions and rollback. POST forms require session CSRF tokens. Records/images use no-store responses. Native form validation is supplemented by server validation.

Pillow is required to decode and validate actual image content, enforce pixel limits, apply EXIF orientation and remove metadata. Supported single-frame JPEG/PNG inputs become lossless RGB PNGs without resizing; SQL hashes identify the stored PNG bytes, not the original upload. These usable normalized images remain the inference source. Upload rollback removes files written by that transaction. A process crash between file write and SQL commit can leave unreferenced files; orphan reconciliation, comprehensive auditing and production storage hardening are deferred. Images are retrieved only via authorized `/images/<image_id>`; no client path or remote URL is accepted.

Direct dependencies: Flask 3.1.2 and Pillow 12.0.0. Observed installed transitive versions: Werkzeug 3.1.9, Jinja2 3.1.6, MarkupSafe 3.0.4, click 8.5.0, itsdangerous 2.2.0, blinker 1.9.0. `pypdf 6.1.1` was used solely to inspect the supplied white paper and is not an application dependency. No frontend framework, AI model, ML runtime, extra service, or migration was introduced.

English UI strings live in `backend/i18n.py`. Arabic user-entered names, complaints, messages and notes are preserved exactly; HTML uses UTF-8 and automatic text direction. Arabic translation and full browser RTL verification remain pending. **Arabic interface support is not complete.**

## Tests and handoff

```sh
.venv/bin/python -m unittest discover -s tests -v
```

21 focused tests pass. A real HTTP test also passed through the running server, followed by a stop/start and successful persistence verification of exact Arabic text, released care and identical image bytes. To reproduce with the local server running:

```sh
.venv/bin/python tests/http_smoke.py create
# Stop the server with Ctrl-C; launch it again using the launch command above.
.venv/bin/python tests/http_smoke.py verify
```

The smoke script adds a fictional patient/case and writes identifiers/hashes to ignored `instance/http-smoke.json`; it does not reset anything. An actual browser smoke test could not run because Computer Use did not approve Safari access. Browser rendering, native file selection and JavaScript interactions are consequently unverified.

See [AI integration](docs/AI_INTEGRATION.md) for the exact typed adapter and configuration seam; [requirements](docs/REQUIREMENTS.md) for implemented/pending features, white-paper reconciliation and migration proposals; and [test results](docs/TEST_RESULTS.md) for individual AT-01 through AT-12 results. The schema-supported first-run prototype is functional; the full MVP remains incomplete. Nothing was deployed externally or pushed to GitHub.
