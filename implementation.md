# Implementation plan and delivery status

## Requirements and current status

Updated 2026-10-11. This section supersedes historical first-run defaults in the
original plan below; it does not remove unmet requirements. [README.md](README.md)
is the single guide for commands, architecture, authentication/encryption and AI
contracts. [AGENTS.md](AGENTS.md) governs development. The eight generated guides
were consolidated here and into README; their historical versions remain in Git.

The working local app uses Flask/Jinja, vanilla JS and SQLite runtime v4: unchanged
source schema v2 plus additive Account v3 and authenticated encryption v4. It has
patient signup/login, private encrypted profiles/intake/images, consent, patient
case tracking, provider queue/assignment, transactional reviews/diagnoses/treatments/
referrals/follow-up and clinician-released outcomes. Patient select-all questions
preserve unknown versus No and feed the selected 14-output custom Keras model.
Inference is explicitly requested by clinicians and never blocks manual review.
The separate optional PyTorch experiment has 41 outputs; its artifacts are not
interchangeable with the 14-output application model.

Current presentation is PaliDerm, restrained flag accents, English/Arabic labels
and browser locale switching. Keep the disclaimer and emergency/clinician notices.
Names/clinical text/passwords support Unicode; only technical usernames/emails and
phone digits require Latin/0–9. Stored enums and model identifiers stay English.
Arabic translation/catalog, RTL markup, saved Arabic text and software persistence
checks pass; real-device RTL/accessibility/camera verification remains unperformed.

| Requirement / acceptance ID | Current status | Limits / evidence |
|---|---|---|
| AT-01 Patient registration | PASS for supported fields; full scope PARTIAL | Atomic Patient+Account; standardized sex/one-hot; encrypted PII. Structured history/district absent. |
| AT-02 Worker submission | BLOCKED / NOT RUN | Worker accounts exist; patient grants and durable submitting-user attribution do not. |
| AT-03 Patient submission | PASS | Structured NULL/No-preserving answers, images/camera multipart, consent, rollback/idempotence and freeze. |
| AT-04 Retrieval | PASS for supported roles | Patient ownership/provider authorization; private image decryption and released outcomes. Worker access blocked. |
| AT-05 AI screening | PASS for saved-model software integration | Actual 14-group unconfirmed scores stored; independent clinical evaluation/calibration pending. |
| AT-06 Safety screening | PARTIAL; limited rule tests PASS | Authorized illustrative post-inference rules; independent immediate pre-upload/AI-unavailable warning screening and clinical validation pending. |
| AT-07 Clinical review | PASS | Authorized assignment; atomic review/status/history; works after AI failure. |
| AT-08 Treatment documentation | PASS | Clinician diagnosis/certainty/primary rules, treatment/medication/dosage and follow-up persist. |
| AT-09 Referral/escalation | PASS for clinician documentation | Required destination/reason and explicit escalation intent; no automatic escalation. |
| AT-10 Persistence | PASS | Actual HTTP process restart; encrypted answers/predictions/triage/care, exact Arabic text and image bytes. |
| AT-11 Authorization | PASS for local controls | Scrypt/roles/ownership/assignment/CSRF/private storage/loopback; production hardening pending. |
| AT-12 Failure handling | PASS for implemented boundary | Unconfigured 503/no attempt; missing answers, failures/invalid output/timeouts/retry/history and manual review; SQL/file rollback. |

Other pending requirements: P1 profile/history editing; durable needs-information
submission revisions (request/message works, patient edits/resubmission blocked);
training consent, comprehensive audit, key rotation, production login throttling,
MFA/recovery/verification/session revocation, deployment/security design, robust
job cancellation/multiple workers, offline/sync, notifications/SMS, national data,
researcher exports, retraining, location recommendations and resumable uploads.
The synchronous one-thread local runner cannot kill a stuck inference thread;
restart is its recovery. No full-MVP, clinical validation, HIPAA compliance or
complete Arabic-support claim is made. The first-run local acceptance target does
not erase blocked full-plan requirements.

## Verification record

These are actual prior results retained from the consolidated reports, not tests
rerun by this documentation cleanup. All clinical inputs/images were synthetic.

- Latest application regression (2026-10-11): **100 tests PASS in 34.677s**.
  Reproduce with the focused command in [README](README.md#tests-and-handoff).
  Includes encryption/copy migration/integrity, auth/CSRF/ownership, questionnaire,
  image validation/rollback, clinician transactions, AI failure/retry/uncertainty,
  348-key EN/AR catalog parity, locale safety/session retention, technical-field
  validation and exact encrypted Arabic text through restart.
- Actual `tests/live_smoke.py --with-model`: **PASS**. HTTP signup/login → patient
  answers → two images/consent → queue/assignment → actual saved Keras inference →
  Arabic/English report → clinician diagnosis/treatment/referral → patient result.
  Actual child-process restart preserved exact Arabic text, care, answers, scores,
  triage and identical images. Temporary database only. Normal-server read-only
  English/Arabic login/disclaimer check also passed after its previous restart.
- `tests/forms_smoke.mjs` and `tests/camera_smoke.mjs`: **PASS** using DOM/API
  doubles, not hardware. Includes local timezone/DST/UTC fallback, named-action
  assignment, errors/retry/repeated clicks, redirects, previews/removal and camera
  permission/track cleanup. Primary green/white contrast check: **7.36:1**.
- Earlier standalone inference pass: **78 tests PASS** (65 existing + 13 interface
  checks). CPU MobileNet bundle inference matched its original predictor's 41
  scores. Keras synthetic export/reload, TorchScript/restricted checkpoints,
  configuration mismatch/unsafe pickle/nonfinite inputs and multi-image handling
  passed; CUDA inference was not exercised.
- Optional PyTorch run: 20 epochs on Apple MPS, best epoch 20; actual validation/
  test metrics and bundle paths are retained in [README](README.md#scin-multimodal-model-pipeline).
  Its original **65 tests PASS in 22.560s** included 15 ML checks; compileall,
  pip check and original-source preservation checks passed at that time.
- Browser/mobile/keyboard/screen-reader/physical-camera/full Arabic RTL visual
  checks: **NOT RUN**, Computer Use access unavailable. HTTP/HTML/DOM checks do
  not establish these. No external deployment/push or clinical evaluation ran.
- Documentation consolidation: original Markdown provenance checked against Git,
  all repository MD/TXT names audited, live scin_ml imports found, generated guides
  merged; **23 local links/anchors PASS**, balanced fences, all 12 acceptance
  statuses retained and `git diff --check` PASS. The only Python diff is one
  startup-error documentation pointer (verified by exact comparison and AST).
  Reran `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest
  test_encryption -q`: **17 tests PASS in 3.806s**. scin_ml, notebooks/models,
  dependency files and private demo credentials remain untouched.

## White-paper reconciliation

Read `AI TELEDERMATOLOGY & SKIN INTELLIGENCE PLATFORM.pdf`, Sections 1.2 and 1.3 (pages 5–20). UJ-01 patient consultation and UJ-03 manual clinician management are delivered within existing schema fields; UJ-02 remains blocked on worker identity/history/access attribution. AI-unavailable manual review is explicitly supported by these journeys.

- UC-01 requires history and geographic district; v2 has neither. They are absent from first-run forms. Existing-field profile creation works.
- UC-02 worker patient search/selection and the actor linkage in UC-03 require authorization grants and durable actor identities; blocked instead of substituting provider assignment for submission attribution.
- UC-04 case history/status and UC-07/08 manual assessment/treatment are implemented except missing structured history. Care plans map through clinician Diagnosis; no automatic confirmation or medication decisions.
- UC-05 now has saved-model inference and UC-06 has the limited user-authorized post-inference rules; clinical validation and independent emergency screening remain pending. The paper's descriptive clinical warning examples and response-time targets are not a supplied, validated executable policy. No six-symptom emergency detector or response-time guarantee was invented.
- UC-09 permits an unspecified referral destination. This first-run workflow follows the reconciled requirement to require a destination; use a named service/care setting when an exact facility is unknown. No directory/facility search was introduced.
- UC-10 supports provider-recorded urgent/emergency intent in referral reason/patient instructions and clinician red priority, with outcome `referred` and lifecycle `reviewed`. There is no structured automatic emergency screening/escalation flag; priority alone is never used to infer that outcome.
- UC-11 is explicitly P2, and UC-12 is P1. Neither delays this first-run slice.
- White-paper conceptual statuses (including Referred/Escalated) are not SQL enum values. Persist only v2 statuses; show clinician decision/referral and priority separately. No missing referenced Section 1.2/1.3: both were available and inspected.

## Pending schema extensions

Applied migrations are Account v3 and encryption v4; source schema.sql remains
v2. The proposals below are **NOT APPLIED**. Assign an explicit future version
(at least v5), agree fields/constraints, back up records, encrypt sensitive new
values, test rollback/integrity/restart and preserve unknown legacy attribution.
Do not silently retrofit submitting identities, history or consent into old cases.

1. Authentication identity is now `Account(account_id, username, password_hash, role, patient_id, provider_id, active, created_at)`, implemented in v3 with role/entity CHECKs and unique links. Do not create a duplicate AppUser table. Any future external identity integration requires a separate explicit proposal; no plaintext passwords.
2. `WorkerPatientAccess(worker_account_id FK Account, patient_id FK Patient, granted_at, revoked_at, PRIMARY KEY(worker_account_id,patient_id))`; service-layer/trigger validation requires worker role and authorized grant administration. No automatic all-patient worker access.
3. `CaseSubmitter(case_id PK FK DermCase, submitted_account_id FK Account, submitted_at)`; immutable first-submission attribution separate from assigned Provider. Existing cases have explicitly unknown legacy attribution; never infer the actor from reviewer or patient.
4. `MedicalHistory(history_id PK, patient_id FK, recorded_by FK Account, recorded_at, conditions TEXT, allergies TEXT, medications TEXT, immunosuppression INTEGER NULL CHECK IN(0,1), prior_treatment TEXT)`; append versions, unknown distinct from No, latest ordering `(recorded_at,history_id)`. Agree clinical history fields before implementation.
5. `SubmissionRevision(revision_id PK, case_id FK, revision_no, submitted_account_id FK Account, submitted_at, consent_at, consent_version, snapshot_json CHECK json_valid, change_summary TEXT NOT NULL nonblank, UNIQUE(case_id,revision_no))`; immutable full server-built intake/profile/history reference and image IDs/hashes snapshot, no image binaries. Record the initial submission too. Needs-information resubmission atomically inserts a new revision and updates supported current-case fields/status; preserve old released reviews and original submitted_at/consent. Add optional `analysis_source_revision` and review revision linkage only with compatible composite case FKs.
6. Safety fields/storage are intentionally not specified as clinical questions yet. After Omar agrees inputs and policy, propose typed `SafetyAnswer`/`SafetyAssessment` with case+submission-revision FKs, policy/version, nullable explicit answers, assessment time, priority and guidance. The current limited post-inference rules do not substitute for approved independent structured screening and revision persistence. Do not use free-text parsing.

Migration tests must cover ownership/worker grants, actor attribution, unchanged v2 records, immutable revision history, rollback, version mismatch and restart. Current audit coverage remains limited until these additions and a separate comprehensive audit design are implemented.

## Original reconciled requirements and seven-phase plan

The original plan below remains the full-MVP requirement source. References to
pending inference, v2-only runtime, demo identity selection or first-run styling
are historical planning defaults superseded by the current status above and
AGENTS.md. The original phases and acceptance criteria are retained in full.

This document preserves every requirement of the supplied `implementaton.md` (renamed `implementation.md`). The following decisions resolve conflicts with the SQL v2 schema and Omar's instruction to integrate AI himself. They govern the plan below; blocked P0 requirements remain required for the full MVP, not silently demoted.

- **Stack:** For an empty repository select Flask, Jinja HTML/CSS/vanilla JavaScript, SQLite, private local image storage, server-side-authorized sessions, Git/GitHub, and local deployment. Reuse an existing working stack and document the reason. No model/vendor is selected: Omar supplies inference.
- **AI ownership:** Implement a typed replaceable adapter and honest unconfigured state now. Actual AI screening (AT-05) remains blocked until Omar supplies inference. Fixture-based contract tests do not count as real model screening or full MVP completion.
- **Safety:** General emergency guidance is implementable now. Automated predefined warning-sign screening (AT-06) remains blocked on an explicit input set and Omar-supplied clinical policy. Build its independent integration boundary; it must run without AI and, when configured, show immediate guidance before uploads or routine review. Do not invent medical rules or claim general guidance passes AT-06.
- **Schema extensions:** Preserve supplied schema.sql v2 and old datamodel.sqlite3. Propose a minimal additive migration for account identities/roles, worker-to-patient access, submitting-user attribution, patient medical history, durable submission revisions, and any approved safety fields. Document proposed tables/columns, constraints and migration order before applying; do not silently rewrite the source schema or destructively migrate. Proceed with schema-supported features while proposals are unresolved. Requirements dependent on unapplied extensions must be reported blocked. Increment user_version only through an explicit migration, and check the resulting version on every startup.
- **Roles and attribution:** Both patient self-submission and worker-assisted submission are P0. A worker selects only an authorized patient, records the actual submitting identity separately from patient and assigned reviewer, and cannot publish provider decisions. Provider access to patient telephone numbers supports external communication. Contact/history forms must persist their values; do not substitute session-only storage or unstructured symptom notes for medical history. Updating profiles and histories is P1 after P0.
- **Logical entities:** User and MedicalHistory require explicit extensions. DermCase maps to DermCase; CaseImage maps through Lesion to LesionImage; AIScreening maps to AIAnalysis/AICandidate; ClinicalReview maps to ProviderReview; CarePlan maps to Diagnosis/TreatmentPlan plus ProviderReview referral/follow-up/patient_message. TreatmentPlan belongs to Diagnosis and indirectly to its review. Referrals and general instructions need no diagnosis. Do not create duplicate tables merely to match logical names.
- **Statuses:** Persist only SQL v2 values: draft, submitted, in_review, needs_information, reviewed, closed. Submitted is the submission confirmation; Pending Review is the queue label for submitted cases; In Review maps to in_review; Additional Information Required maps to needs_information; Completed maps to reviewed/closed after a committed review. Referred is a clinical outcome from referral_required and review decision, not an invented SQL status. Escalated is a provider-recorded red-priority referral outcome with destination/reason and explicit emergency/specialist intent in the review, not inferred solely from red priority or AI. Show lifecycle status, clinical outcome, and red/amber/green/undetermined priority separately. Indeterminate is the UI label for undetermined. No automatic confirmed diagnosis or prescription.
- **Scope:** Exclude payments, appointments, conversational messaging, automatic prescriptions, automatic clinical decisions, and app-managed custom model training. A clinician-released patient message or needs-information request is part of the review workflow, not a chat service. Defer location recommendations, offline collection/sync, national analytics/integration, training, SMS, researcher exports, resumable uploads and production integrations. Embeddings remain optional pending Omar's encoder decision.
- **Completion:** Follow all seven development phases below and test AT-01 through AT-12. Demonstrable core completion and full MVP completion are distinct. Full completion requires every mandatory acceptance test passing with actual functionality; blocked AI/safety/history/worker-attribution requirements must remain visible in a requirements status table. Unimplemented or simulated functionality and exceptions must be documented. Missing referenced Sections 1.2/1.3 must be reported and must not be invented; use the supplied framework if available and document uncovered use cases.

# 7. MVP IMPLEMENTATION PLAN

This section defines the implementation scope, technical architecture, development requirements, and acceptance criteria for the AI Teledermatology & Skin Intelligence Platform's Minimum Viable Product (MVP).

The MVP shall demonstrate an end-to-end workflow supporting patient registration, dermatology case submission, AI-assisted screening, clinical review, and documentation of treatment or referral outcomes.

The implementation shall follow the user journeys and use cases defined in Sections 1.2 and 1.3. Functionality outside the defined scope shall not be introduced unless required to support an existing requirement.

The MVP is a proof of concept and is not intended for clinical deployment.

## 7.1. MVP Scope & Feature Prioritization

### Core Functionality (P0)

The system shall support:

1. Patient profile creation with contact information and relevant medical history.
2. Patient-initiated and healthcare-worker-assisted case submissions.
3. Uploading skin photographs and recording symptoms, affected body area, and symptom duration.
4. Persistent storage and retrieval of patient records and dermatology cases.
5. Preliminary AI-assisted screening and identification of potential safety concerns.
6. Clinical review of patient information, images, and AI findings.
7. Documentation of clinician-authorized diagnoses, treatment plans, and prescriptions.
8. Documentation of in-person referrals, specialist consultations, or emergency escalation.
9. Case status tracking and access to clinician-approved outcomes.
10. Role-based access restrictions for patients, healthcare workers, and providers.

### Secondary Functionality (P1)

- Updating existing patient profiles and medical histories.

### Future Development (P2)

- Location-based healthcare facility recommendations.
- Offline data collection and synchronization.
- National health data integration and population-level analytics.

### Excluded Functionality

The MVP shall not include payment processing, appointment scheduling, in-application messaging, automated prescriptions, custom AI model training, or automatic clinical decision-making.

Providers shall access patient telephone numbers for external communication. No messaging service integration is required.

## 7.2. Technology Stack

The system shall use technologies selected for compatibility, maintainability, and implementation efficiency.

| Component | Technology |
|---|---|
| Backend | Python, Flask (selected for an empty repository) |
| Frontend | Jinja HTML, CSS, vanilla JavaScript (selected) |
| Database | SQLite (selected) |
| AI Screening | Omar-supplied model behind a typed adapter (pending) |
| Image Storage | Local private storage for prototype |
| Authentication | Session-based, role-restricted access |
| Version Control | Git/GitHub |
| Deployment | Local initially; hosting TBD |

Pending integrations must be supplied before their dependent behavior can be reported complete; independent work continues. AI-assisted development shall not introduce additional frameworks, services, or dependencies without a documented technical need.

## 7.3. System Implementation Architecture

The system shall follow a modular client-server architecture consisting of:

- **Presentation Layer:** Patient, healthcare-worker, and provider interfaces.
- **Application Layer:** Validation, authorization, case management, and workflow coordination.
- **Data Layer:** Relational records and image references.
- **AI Screening Component:** Preliminary analysis of submitted clinical information and images.
- **Safety & Triage Component:** Identification of predefined warning signs and preliminary case prioritization.
- **Clinical Review Component:** Provider assessment, diagnosis, treatment, referral, and escalation documentation.

### Core Workflow

Patient/Worker Submission → Validation → Data Storage → Safety Screening → AI Assessment → Provider Review → Clinical Outcome → Status Update

Safety checks shall operate independently of AI availability. Potential emergency warning signs shall trigger immediate safety guidance without waiting for AI processing or routine clinical review.

### Case Statuses

The system shall support the following statuses:

- Submitted
- Pending Review
- In Review
- Additional Information Required
- Completed
- Referred
- Escalated

Case status shall remain separate from clinical priority (Red, Amber, Green, or Indeterminate).

AI-generated findings shall never automatically become confirmed diagnoses or prescriptions.

## 7.4. Database Implementation

The relational data model shall support the following logical entities:

| Entity | Purpose |
|---|---|
| User | Account identity and role |
| Patient | Demographics and contact details |
| MedicalHistory | Allergies, medications, and relevant conditions |
| DermCase | Consultation and symptom records |
| CaseImage | Submitted photograph references |
| AIScreening | Preliminary AI findings and uncertainty |
| ClinicalReview | Provider-authored clinical assessment |
| CarePlan | Treatment, prescription, referral, and follow-up information |

### Required Relationships

- One patient may have multiple cases.
- Each case belongs to one patient and records its submitting user.
- Each case may contain multiple images.
- AI screening records belong to individual cases.
- Clinical reviews belong to cases and identify the reviewing provider.
- Care plans belong to the relevant clinical review.
- Medical history belongs to the corresponding patient.

Primary keys, foreign keys, required-field validation, and appropriate authorization shall maintain data integrity.

All records shall persist beyond individual application sessions. Medical images shall be stored separately from structured database records, with their references maintained in the database.

## 7.5. Development Phases & Dependencies

Development shall follow the order below. Each phase must satisfy its completion criteria before dependent features are introduced.

| Phase | Implementation | Completion Criteria |
|---|---|---|
| 1. Foundation | Project structure, dependencies, database | Application launches and retrieves stored data |
| 2. Patient Management | Patient registration, medical history, patient selection | Patient records can be created and retrieved |
| 3. Case Submission | Symptoms, photographs, validation, persistent storage | Both submission methods function |
| 4. Clinical Review | Provider dashboard, assessments, care plans, referrals | Submitted cases can be reviewed and updated |
| 5. AI & Safety | Warning-sign rules, AI integration, uncertainty handling | Screening functions without compromising manual review |
| 6. Integration Testing | End-to-end workflows, error handling, access restrictions | Core acceptance tests pass |
| 7. Deployment | Application setup, demonstration data, documentation | System launches and operates reliably |

### Implementation Rules

1. Implement requirements according to their assigned priority and dependencies.
2. Complete and test core functionality before adding secondary features.
3. Maintain separation between AI-generated and clinician-authored information.
4. Preserve existing functional behavior when modifying the application.
5. Handle invalid inputs, unavailable services, and database errors explicitly.
6. Do not substitute mocked functionality for working implementation without clearly identifying it.
7. Document any deviation from the approved requirements.

## 7.6. Testing & Acceptance Criteria

The system shall be tested against the use cases defined in Section 1.3.

| Test ID | Requirement | Expected Result |
|---|---|---|
| AT-01 | Patient registration | Valid patient profile created and stored |
| AT-02 | Healthcare-worker submission | Case correctly linked to patient and submitting worker |
| AT-03 | Patient case submission | Symptoms and images stored successfully |
| AT-04 | Case retrieval | Authorized users retrieve correct case information |
| AT-05 | AI screening | Preliminary findings stored and identified as unconfirmed |
| AT-06 | Safety screening | Defined warning signs trigger appropriate guidance |
| AT-07 | Clinical review | Provider assessment stored independently of AI findings |
| AT-08 | Treatment documentation | Clinician-authorized care plan saved |
| AT-09 | Referral/escalation | Appropriate outcome recorded and case status updated |
| AT-10 | Persistence | Records remain available after application restart |
| AT-11 | Authorization | Unauthorized access to protected records is denied |
| AT-12 | Failure handling | AI failures do not prevent submission or manual review |

### Definition of Done

The MVP is complete when an authorized patient or healthcare worker can submit a dermatology case, the system persists and processes the submission, a provider can review it, and an appropriate clinical outcome can be documented and retrieved.

All mandatory acceptance tests must pass. Unimplemented components, simulated functionality, and known limitations must be explicitly documented.

The prototype shall use fictional patient records and demonstration imagery. AI screening outputs are not clinically validated and shall not be presented as independent medical diagnoses or treatment decisions.
