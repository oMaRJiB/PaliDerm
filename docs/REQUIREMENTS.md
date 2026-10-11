# Saved-model integration update — 2026-10-11

Patient questionnaire update: patients can save additional model answers with
their own drafts/intake. Native checkbox groups preserve NULL versus explicit No;
duration uses the trained ranges, age derives from DOB at submission, and profile
sex is reused as sex at birth per Omar's instruction. Extras persist in the existing
encrypted Symptom envelope without a migration. Submitted cases stay frozen;
clinicians reuse known answers and fill only missing values. Prior provider-only
or separately asked demographic descriptions are superseded by this update.

Omar selected `SCIN_custom_model.keras`. The app now runs that saved model through
the existing typed inference boundary; no model training, notebook/artifact edits
or database migration were performed. All missing model answers are explicitly
required and saved in encrypted attempt snapshots. Actual synthetic HTTP inference
and process-restart persistence passed. Scores remain unconfirmed/uncalibrated,
clinical triage is undetermined, and automated safety screening remains blocked.
The following historical status text is updated only where this integration
changes delivery; full MVP completion is not claimed.

# Current encryption/gender update

Runtime v4 is now required; supplied schema.sql v2 and the v3 Account extension remain preserved. Patient gender choices and deterministic one-hot/symptom helpers are implemented. Sensitive clinical fields and original images use authenticated Fernet encryption, with strict key configuration, authorized in-memory decryption, plaintext-write guards and explicit copy-only migration. See ENCRYPTION.md for exact protected fields and plaintext operational metadata.

The local synthetic dataset was migrated into instance/encrypted, all seven accounts preserved, and all six documented credentials verified. Original source DB/uploads/backups remain plaintext rollback material and require separate secure archival/removal. Structured MedicalHistory remains unsupported; history within existing notes is encrypted. Existing role/ownership/CSRF/scrypt/session controls remain; private clinician notes/unconfirmed analysis data are also excluded from patient service results. No AI development was performed. Historical requirement/status text below remains subject to this update.

---

# First-run requirements and pending work

The user's first-run delivery overrides broader completion gates. Root `AGENTS.md` and reconciled `implementation.md` are preserved and extended; `schema.sql` remains the unchanged authoritative v2 schema. The user-authorized second pass adds Account via the explicit v2→v3 migration; all clinical base tables and attachments remain unchanged. See AUTH_MIGRATION.md. No prior code/stack existed to reuse. No source attachment was changed or deleted.

## Delivered schema-supported slice

- Patient profile creation/retrieval using first/last name, real nonfuture DOB, optional sex/phone/email. Arabic and surrounding whitespace preserved. No medical-history/geography form pretending to save unsupported fields.
- Patient-owned drafts with complaint, nonnegative integer/unknown duration, upserted questionnaire preserving NULL/0/1, and multiple affected body sites.
- Multiple decoded/validated private images with server IDs, stored-byte hashes, original metadata preservation, file-size/count limits and built-in decoder protection and authorized retrieval. File cleanup on transactional failure.
- Explicit consent version/time, validated idempotent submission, immutable submitted intake through application write restrictions, queue/status tracking, unknown priority explicitly Indeterminate.
- Clinician assignment/authorization, independent manual review, optional clinician diagnoses/certainty/treatments, referral/follow-up, patient release, review history, explicit review revision and closure. One primary diagnosis when diagnoses exist. Review inserts and lifecycle update are atomic.
- Queue status/reviewer filters and submission age; clinician priority and latest successful AI priority displayed separately. Provider phone access supports external communication only.
- Local-only password-based patient/provider/worker accounts with patient-only public signup, separately provisioned privileged/existing-record accounts and a blocked-work notice for worker submissions. Server-side role/ownership checks, CSRF, loopback/Host gating. No public deployment or production security claim.
- Typed AI adapter, selected local saved-SCIN inference, encrypted immutable attempt snapshots and supplemental model answers, timeout, output validation, sanitized failures, retries/history and restart recovery. Explicitly empty MODEL_PATH retains honest unconfigured 503 with no attempt row. Developer deterministic fixtures live only under tests and are explicitly simulated.
- General emergency guidance visible before uploads. Independent safety protocol defined; no automatic medical rules invented or activated.
- English catalog with en/ar locale plumbing, UTF-8, `dir=auto` free text and ltr technical/contact values. Exact Arabic storage/retrieval and actual process-restart checks passed.

## Pending or limited

| Requirement | Status / dependency |
|---|---|
| Actual AI screening / AT-05 | PASS for saved-model software integration: actual 14-group outputs stored as unconfirmed suggestions. Independent clinical evaluation/calibration and safety policy remain pending. |
| Automated warning signs / AT-06 | Blocked on agreed structured inputs, persistence and Omar-supplied clinical policy. General emergency notice is not detection. |
| Worker-assisted submission and durable submitting identity / AT-02 | Account identity is implemented; blocked on worker access grants and case attribution extension. Worker has no patient access now. |
| Medical history / full UC-01, UC-07, UC-12 | Blocked on history extension. Current profile stores only existing Patient columns. |
| Needs-information resubmission | Blocked on durable submission revisions; current needs-information review/message works, intake stays protected. |
| Persistent identity/authentication / public hosting | Password authentication and Account identity implemented; production hardening, recovery/MFA, throttling, durable session revocation and access/audit design remain prerequisites. |
| Profile/history updates / UC-12 | P1 pending; profile immutability also protects current submitted patient context. |
| Arabic translated UI and full RTL validation | Pending. Arabic free-text persistence and locale/page scaffolding work; this does not constitute complete Arabic UI support. |
| Actual browser happy-path test | Not run: no connected browser surface and native Safari access was not approved by Computer Use. HTTP workflow and rendered HTML assertions passed. |
| Comprehensive audit / durable full submission snapshots | The clinical base has attempt/review history and runtime v3 adds accounts only. First-run intake is protected by application restrictions; arbitrary SQL edits are outside that protection. No identity/audit events or complete immutable submission revision store. |
| Robust inference process cancellation | Local bounded worker timeout exists; Python cannot forcibly stop a stuck thread. One slot stays occupied until it exits. Restart is the recovery for a permanently stuck adapter. |
| Clinical policy/validation, training consent | Not supplied or implemented. Submission consent is not training permission. |
| Offline/sync, notifications/SMS, national analytics, researcher/training exports, retraining, location recommendations, resumable uploads, production integrations | Deferred as specified. No embeddings, training, automated prescriptions, payments, appointments or chat. |

## White-paper reconciliation

Read `AI TELEDERMATOLOGY & SKIN INTELLIGENCE PLATFORM.pdf`, Sections 1.2 and 1.3 (pages 5–20). UJ-01 patient consultation and UJ-03 manual clinician management are delivered within existing schema fields; UJ-02 remains blocked on worker identity/history/access attribution. AI-unavailable manual review is explicitly supported by these journeys.

- UC-01 requires history and geographic district; v2 has neither. They are absent from first-run forms. Existing-field profile creation works.
- UC-02 worker patient search/selection and the actor linkage in UC-03 require authorization grants and durable actor identities; blocked instead of substituting provider assignment for submission attribution.
- UC-04 case history/status and UC-07/08 manual assessment/treatment are implemented except missing history and AI inference. Care plans map through clinician Diagnosis; no automatic confirmation or medication decisions.
- UC-05 real screening and UC-06 warning rules remain blocked. The paper's descriptive clinical warning examples and response-time targets are not a supplied, validated executable policy. No six-symptom emergency detector or response-time guarantee was invented.
- UC-09 permits an unspecified referral destination. This first-run workflow follows the reconciled requirement to require a destination; use a named service/care setting when an exact facility is unknown. No directory/facility search was introduced.
- UC-10 supports provider-recorded urgent/emergency intent in referral reason/patient instructions and clinician red priority, with outcome `referred` and lifecycle `reviewed`. There is no structured automatic emergency screening/escalation flag; priority alone is never used to infer that outcome.
- UC-11 is explicitly P2, and UC-12 is P1. Neither delays this first-run slice.
- White-paper conceptual statuses (including Referred/Escalated) are not SQL enum values. Persist only v2 statuses; show clinician decision/referral and priority separately. No missing referenced Section 1.2/1.3: both were available and inspected.

## Remaining additive migration proposals — NOT APPLIED

The original v2→v3 identity proposal below is superseded by the applied Account extension described in AUTH_MIGRATION.md. The remaining clinical/access/history proposals are unapplied; a future explicit version must be assigned (at least v4), without changing the supplied base schema. Preserve/backup original sources and live DB first; implement transactional migration with tests and a version bump only after fields/constraints are agreed. Never retrofit invented actor/history values into existing cases.

Proposed order:

1. Authentication identity is now `Account(account_id, username, password_hash, role, patient_id, provider_id, active, created_at)`, implemented in v3 with role/entity CHECKs and unique links. Do not create a duplicate AppUser table. Any future external identity integration requires a separate explicit proposal; no plaintext passwords.
2. `WorkerPatientAccess(worker_account_id FK Account, patient_id FK Patient, granted_at, revoked_at, PRIMARY KEY(worker_account_id,patient_id))`; service-layer/trigger validation requires worker role and authorized grant administration. No automatic all-patient worker access.
3. `CaseSubmitter(case_id PK FK DermCase, submitted_account_id FK Account, submitted_at)`; immutable first-submission attribution separate from assigned Provider. Existing cases have explicitly unknown legacy attribution; never infer the actor from reviewer or patient.
4. `MedicalHistory(history_id PK, patient_id FK, recorded_by FK Account, recorded_at, conditions TEXT, allergies TEXT, medications TEXT, immunosuppression INTEGER NULL CHECK IN(0,1), prior_treatment TEXT)`; append versions, unknown distinct from No, latest ordering `(recorded_at,history_id)`. Agree clinical history fields before implementation.
5. `SubmissionRevision(revision_id PK, case_id FK, revision_no, submitted_account_id FK Account, submitted_at, consent_at, consent_version, snapshot_json CHECK json_valid, change_summary TEXT NOT NULL nonblank, UNIQUE(case_id,revision_no))`; immutable full server-built intake/profile/history reference and image IDs/hashes snapshot, no image binaries. Record the initial submission too. Needs-information resubmission atomically inserts a new revision and updates supported current-case fields/status; preserve old released reviews and original submitted_at/consent. Add optional `analysis_source_revision` and review revision linkage only with compatible composite case FKs.
6. Safety fields/storage are intentionally not specified as clinical questions yet. After Omar agrees inputs and policy, propose typed `SafetyAnswer`/`SafetyAssessment` with case+submission-revision FKs, policy/version, nullable explicit answers, assessment time, priority and guidance. Do not use free-text parsing, six existing symptom flags, or AI snapshots as a substitute for approved structured screening persistence.

Migration tests must cover ownership/worker grants, actor attribution, unchanged v2 records, immutable revision history, rollback, version mismatch and restart. Current audit coverage remains limited until these additions and a separate comprehensive audit design are implemented.

## Camera/intake scope update

User-approved override: new original images retain metadata, the custom MAX_IMAGE_PIXELS configuration is removed, and patients no longer see case numbers. Draft intake now shows every section together and supports atomic save/submission with native or live camera capture. Responsive narrow/wide layouts are implemented; physical device testing remains pending. No metadata extraction, GPS collection, geography migration, outbreak detection, model preprocessing or external hosting was added. Older stripped metadata cannot be restored. Previously blocked requirements remain blocked.
