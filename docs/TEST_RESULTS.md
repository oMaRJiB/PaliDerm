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
