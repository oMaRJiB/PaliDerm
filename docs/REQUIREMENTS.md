# First-run requirements and pending work

The user's first-run delivery overrides broader completion gates. Root `AGENTS.md` and reconciled `implementation.md` are preserved and extended; `schema.sql` remains the unchanged authoritative v2 schema. No migration has been applied. No prior code/stack existed to reuse. No source attachment was changed or deleted.

## Delivered schema-supported slice

- Patient profile creation/retrieval using first/last name, real nonfuture DOB, optional sex/phone/email. Arabic and surrounding whitespace preserved. No medical-history/geography form pretending to save unsupported fields.
- Patient-owned drafts with complaint, nonnegative integer/unknown duration, upserted questionnaire preserving NULL/0/1, and multiple affected body sites.
- Multiple decoded/validated private images with server IDs, stored-byte hashes, stripped metadata, size/count/pixel limits and authorized retrieval. File cleanup on transactional failure.
- Explicit consent version/time, validated idempotent submission, immutable submitted intake through application write restrictions, queue/status tracking, unknown priority explicitly Indeterminate.
- Clinician assignment/authorization, independent manual review, optional clinician diagnoses/certainty/treatments, referral/follow-up, patient release, review history, explicit review revision and closure. One primary diagnosis when diagnoses exist. Review inserts and lifecycle update are atomic.
- Queue status/reviewer filters and submission age; clinician priority and latest successful AI priority displayed separately. Provider phone access supports external communication only.
- Local-only patient/provider demo sessions and a separate worker identity with a blocked-work notice. Server-side role/ownership checks, CSRF, loopback/Host gating. No public deployment or production authentication claim.
- Typed AI adapter, honest unconfigured 503 with no attempt row, server-built immutable attempt snapshots, optional configured runner with timeout, output validation, sanitized failures, retries/history and restart recovery. Developer deterministic fixtures live only under tests and are explicitly simulated. No model/vendor selected or inference supplied.
- General emergency guidance visible before uploads. Independent safety protocol defined; no automatic medical rules invented or activated.
- English catalog with en/ar locale plumbing, UTF-8, `dir=auto` free text and ltr technical/contact values. Exact Arabic storage/retrieval and actual process-restart checks passed.

## Pending or limited

| Requirement | Status / dependency |
|---|---|
| Actual AI screening / AT-05 | Blocked on Omar's adapter/model. Contract fixtures are software tests, not screening. |
| Automated warning signs / AT-06 | Blocked on agreed structured inputs, persistence and Omar-supplied clinical policy. General emergency notice is not detection. |
| Worker-assisted submission and durable submitting identity / AT-02 | Blocked on User, worker access grants and case attribution extension. Worker has no patient access now. |
| Medical history / full UC-01, UC-07, UC-12 | Blocked on history extension. Current profile stores only existing Patient columns. |
| Needs-information resubmission | Blocked on durable submission revisions; current needs-information review/message works, intake stays protected. |
| Persistent identity/authentication / public hosting | Local synthetic identity selector only. Appropriate real authentication and access/audit design are prerequisites. |
| Profile/history updates / UC-12 | P1 pending; profile immutability also protects current submitted patient context. |
| Arabic translated UI and full RTL validation | Pending. Arabic free-text persistence and locale/page scaffolding work; this does not constitute complete Arabic UI support. |
| Actual browser happy-path test | Not run: no connected browser surface and native Safari access was not approved by Computer Use. HTTP workflow and rendered HTML assertions passed. |
| Comprehensive audit / durable full submission snapshots | v2 has clinical attempt/review history only. First-run intake is protected by application restrictions; arbitrary SQL edits are outside that protection. No identity/audit events or complete immutable submission revision store. |
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

## Minimal additive migration proposals — NOT APPLIED

These are proposals for a future reviewed v2→v3 migration, not runtime SQL and not authorization to alter the supplied schema. Preserve/backup original sources and live DB first; implement transactional migration with tests and a version bump only after fields/constraints are agreed. Never retrofit invented actor/history values into existing cases.

Proposed order:

1. `AppUser(user_id PK, role CHECK patient/worker/provider, patient_id FK nullable, provider_id FK nullable, external_subject UNIQUE, created_at)`; require correct role/entity pairing, unique patient/provider mappings. Authentication provider/credentials must be decided before public use; do not store plaintext passwords.
2. `WorkerPatientAccess(worker_user_id FK AppUser, patient_id FK Patient, granted_at, revoked_at, PRIMARY KEY(worker_user_id,patient_id))`; service-layer/trigger validation requires worker role and authorized grant administration. No automatic all-patient worker access.
3. `CaseSubmitter(case_id PK FK DermCase, submitted_user_id FK AppUser, submitted_at)`; immutable first-submission attribution separate from assigned Provider. Existing cases have explicitly unknown legacy attribution; never infer the actor from reviewer or patient.
4. `MedicalHistory(history_id PK, patient_id FK, recorded_by FK AppUser, recorded_at, conditions TEXT, allergies TEXT, medications TEXT, immunosuppression INTEGER NULL CHECK IN(0,1), prior_treatment TEXT)`; append versions, unknown distinct from No, latest ordering `(recorded_at,history_id)`. Agree clinical history fields before implementation.
5. `SubmissionRevision(revision_id PK, case_id FK, revision_no, submitted_user_id FK AppUser, submitted_at, consent_at, consent_version, snapshot_json CHECK json_valid, change_summary TEXT NOT NULL nonblank, UNIQUE(case_id,revision_no))`; immutable full server-built intake/profile/history reference and image IDs/hashes snapshot, no image binaries. Record the initial submission too. Needs-information resubmission atomically inserts a new revision and updates supported current-case fields/status; preserve old released reviews and original submitted_at/consent. Add optional `analysis_source_revision` and review revision linkage only with compatible composite case FKs.
6. Safety fields/storage are intentionally not specified as clinical questions yet. After Omar agrees inputs and policy, propose typed `SafetyAnswer`/`SafetyAssessment` with case+submission-revision FKs, policy/version, nullable explicit answers, assessment time, priority and guidance. Do not use free-text parsing, six existing symptom flags, or AI snapshots as a substitute for approved structured screening persistence.

Migration tests must cover ownership/worker grants, actor attribution, unchanged v2 records, immutable revision history, rollback, version mismatch and restart. Current audit coverage remains limited until these additions and a separate comprehensive audit design are implemented.
