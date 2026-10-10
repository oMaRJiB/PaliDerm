# Hacklanta teledermatology MVP — development instructions

## Goal and authority
Build a working, mobile-first patient-to-clinician teledermatology workflow for Omar's first Hacklanta submission. Omar is implementing the AI separately. Deliver the application, database integration, and a replaceable AI boundary; do not develop, train, download, or select an AI model on his behalf.

Place this file at the repository root as `AGENTS.md`. First inspect the repository, its existing instructions, dependencies, and code. Reuse an existing stack. If the repository is empty, use Python/Flask with server-rendered Jinja HTML, CSS and vanilla JavaScript, SQLite for metadata, and a private local uploads directory outside static assets. This reconciled plan selects the previously proposed Flask stack. Reuse a working existing stack rather than rewrite it; document that exception. Do not introduce React, Vite, FastAPI, new services or additional frameworks without a documented technical need. Document actual commands and dependency versions in the README.

The supplied `schema.sql` is the authoritative SQL model (SQLite user_version 2). Locate it by filename; the supplied attachment is `08-schema.sql`. The supplied `datamodel.sqlite3` is an older schema (user_version 0) and is NOT the runtime database. Preserve all source attachments. Initialize a separate development database from the SQL on first boot; do not rerun CREATE TABLE statements against an existing database. Check user_version and fail with an actionable message on mismatch. Never overwrite an existing database or invent a destructive migration.

The technical framework describes a long-term vision. Build the core workflow below first. Do not silently claim the full white paper has been implemented. Clinical decision support is the product; clinician diagnoses and treatment decisions remain separate from AI suggestions.

## Minimum working product
1. Patient intake: create patient and draft case, chief complaint, duration, symptom questionnaire, body location(s), multiple image uploads, and explicit case-submission consent with timestamp and version.
2. Submission: validate required data, freeze the submitted case payload, and show confirmation and status. Submission must work when the AI is unconfigured.
3. Patient case page: display their submitted information, status, and clinician-released message, diagnoses, treatment instructions, referral, and follow-up. Clearly distinguish provisional from confirmed diagnoses.
4. Clinician queue: show submitted/in-review/needs-information cases, assignment, age of submission, and explicitly labeled AI or clinician urgency when available. Unknown urgency is never shown as green. Support filters by status and reviewer.
5. Clinician case page: show questionnaire, images, AI state/history, ranked suggestions when available, quality warnings, and the clinician review form. A clinician can review without an AI run.
6. Clinician review: persist decision, triage, patient message, notes, optional diagnoses/treatments, referral and follow-up as one transaction. Preserve previous reviews. Needs-information is a real state with a message requesting clarification.
7. Demonstration: provide explicitly synthetic seed patients/cases and a reset/seed command targeting only a named demo database. Test the complete intake-to-review-to-patient-result path.

## SQL mapping and data invariants
- Patient -> many DermCase; Provider on DermCase is the assigned reviewer.
- Symptom is one questionnaire per case. Use upsert for draft edits. NULL means unanswered/unknown, and 0 means explicitly no; never coerce unknown flags to false.
- A case can have multiple Lesion rows. Each Lesion has a BodySite and multiple LesionImage rows. A lesion has no structured size/color/shape fields in this MVP; don't render forms that pretend these persist.
- Images live in private file storage; SQL stores URI, MIME, SHA-256 and quality. Generate storage identifiers server-side. Never store signed expiring URLs as permanent image identifiers.
- AIAnalysis is an attempt log. AICandidate rows belong to an attempt. Preserve successes even when a later attempt fails.
- ProviderReview is independent of AI and can reference no analysis. A referenced analysis MUST belong to the same case, as enforced by the composite FK.
- Diagnosis belongs to its ProviderReview and case, not directly to an AI candidate. At most one primary diagnosis per review; an inconclusive/needs-information/referral review may have no diagnosis.
- TreatmentPlan belongs to Diagnosis. Referrals belong to ProviderReview and do not require a diagnosis. If giving instructions with no diagnosis, use the review's patient_message rather than inventing a diagnosis just to satisfy a foreign key.
- Derive the current released result from the latest committed, authorized review; keep history. Choose an explicit latest ordering (reviewed_at, review_id). Show the latest successful AI analysis separately from the newest attempt and its status.
- Enable PRAGMA foreign_keys=ON on EVERY connection before transactions. Use parameterized statements, transactions, rollback on failures, and bounded SQLite busy_timeout. Never rely on the schema script's PRAGMA to configure future connections.

## Application validation that SQL does not enforce
- Before submission require a nonempty chief complaint, an existing questionnaire, at least one affected body site and one successfully stored image, and consent. Questionnaire answers may remain NULL if the patient explicitly chooses unknown. Do not claim an emergency case must finish an image upload to seek care.
- Validate dates as real calendar dates; date_of_birth must not be future, followup_date must parse, and event timestamps use UTC ISO 8601. Reject blank strings for required values; reject invalid noninteger durations and malformed booleans.
- Compute SHA-256 from the stored image bytes, never from a client-provided hash. If resizing, the stored image hash must identify the resized bytes actually analyzed. Validate MIME by decoding the file, not by trusting its extension/header. Enforce configurable file size/count/pixel limits, strip EXIF location metadata, and reject unsupported inputs with clear errors.
- Create case, questionnaire, lesion and image metadata consistently. Handle file cleanup on transaction failure. Serve private images through an authorized backend route; never accept arbitrary server paths or URLs from the client.
- Legal transitions: draft -> submitted; submitted -> in_review; in_review -> needs_information/reviewed; needs_information -> submitted after requested information is provided; reviewed -> closed. Permit reviewed -> in_review for an explicit revision that creates a new review. Reject other transitions. Set submitted_at once on initial submission; don't erase consent/history on resubmission.
- Publishing a review and updating case status is atomic. Enforce reviewer assignment/authorization in the service layer. A reviewed state requires an actual committed review; confirmed/modified reviews require at least one clinician diagnosis, with exactly one primary diagnosis when diagnoses are present.
- Enforce nonblank referral_reason when referral_required=1 and a destination when the workflow requires one. Don't accept a referral decision with referral_required=0.
- A closed/reviewed case cannot be silently edited by a patient. For needs-information updates, retain previous submitted content in a dedicated durable submission-revision store and record what changed (propose a non-destructive schema extension; AI snapshots alone are insufficient when AI is unconfigured); don't overwrite the previous clinical result. Document the limited audit coverage of this MVP.
- Handle double submission and retry safely: persist state transactionally, reuse a draft's identifier, disable duplicate UI actions, and return existing results on a repeated submission. Do not start duplicate AI jobs from a repeated request.

## AI integration boundary — Omar owns implementation
Define typed request/response models and one backend adapter interface, e.g. `analyze_case(input: AnalysisInput) -> AnalysisOutput`. Isolate this behind a module such as `backend/ai/adapter.py`; the frontend must not depend on a specific model, framework, API key, or vendor.

AnalysisInput includes contract_version, case_id, complaint, duration, available patient context (age/sex, only where relevant), symptom values preserving NULL, lesion IDs/body sites, image IDs with storage references/hash/MIME/quality, and source submission time. Construct it server-side. The JSON snapshot is the exact immutable input for that attempt and must reference the exact bytes used. Do not put image binary data in input_snapshot_json. Never log identifiable intake data or images.

AnalysisOutput includes model_name, model_version, prompt_version (use `not-applicable` for a nonprompted CNN), triage_level, summary, rationale, limitations, per-image quality results if supplied, and ordered candidates with diagnosis_name, rank, optional confidence, and rationale. Confidence is nullable and within [0,1]; do not fabricate probabilities or imply uncalibrated scores are validated probabilities. Validate all output before writing it.

Unconfigured adapter: report `AI integration pending` in the UI and return a clear service-unavailable response if analysis is explicitly requested. Do not create a fake completed run, assign a default diagnosis, or classify unknown cases as routine. Do not create an attempt merely because an unconfigured adapter exists.

Configured adapter: create a pending AIAnalysis, snapshot its input, transition to running, invoke outside the database transaction with timeout/error handling, then commit completed result + candidates + supplied image quality atomically. Failure writes status=failed, completed_at, and a sanitized error. Preserve all old results. Retries create new attempt rows. Handle interrupted running attempts on restart as failed/interrupted with an explicit recovery path.

Provide a developer-only deterministic fixture adapter for tests. If exposed for a demo, make it explicitly opt-in and visibly label every result `SIMULATED AI — not model inference`. Default remains unconfigured. Include a contract example and precise instructions showing where Omar plugs in inference. Avoid importing heavy ML libraries in application startup.

Model inference and clinical review must remain independent: no AI failure should prevent clinician review. Image quality poor, undetermined triage, or missing/low-confidence outputs must be visible for further review, not silently treated as green. Do not implement clinical thresholds or automated treatment rules without Omar supplying the intended policy.

## Feature vectors
Do not change the authoritative schema or add mandatory embeddings in this implementation. Preserve original usable images and clinician labels. Image embeddings are an optional derived cache, not ground truth, not an anonymization mechanism, and not a substitute for source images.

If Omar explicitly elects to add a cache after settling his encoder, use a separate ImageEmbedding table keyed to LesionImage with encoder name/version, preprocessing version, source content hash, dimension, dtype/encoding and vector bytes or artifact URI; uniqueness must identify the image, encoder, preprocessing and source hash. Require regeneration on encoder/preprocessing/source changes. Keep encoder cache independent from inference attempt history. No vector database or similarity-search service is needed merely to retrieve a known image's cached features.

Do not retrain automatically from uploads or AI guesses. Future training exports use quality-reviewed, clinician-labeled images and separate training permission; submission consent alone is not training permission. Retraining, training manifests, patient-level dataset splitting and independent model evaluation are deferred.

## Safety, access and scope
- Use only synthetic/demo data during development. Clearly label the application as a prototype and AI outputs as decision support. Do not claim clinical validation, production security, HIPAA compliance, or guaranteed response times.
- The current schema lacks structured emergency flags and medical history (medications, allergies, immunosuppression, prior treatment), training consent, authentication identities, comprehensive audit events, geography and notification delivery. Don't claim these persist or work. Flag any required schema addition as a small explicit migration proposal before implementing it.
- The white paper's emergency bypass is not implemented by six symptom booleans. Include prominent general emergency guidance and disclose that this prototype is not an emergency service. Do not invent emergency detection or clinical rules. If Omar requires automated emergency screening, agree its fields and policy first and add explicit structured persistence.
- Reuse existing authentication if present. Otherwise create an explicit local-only demo identity mechanism with separate patient/healthcare-worker/provider sessions and server-side ownership/role checks. A public deployment must not expose patient records through a role dropdown or arbitrary patient/provider ID. Document demo auth limitations and gate public deployment on appropriate authentication.
- Implement actual browser/backend error states, form validation and accessibility. Mobile layout, readable status, image previews and easy clinician review matter more than decorative complexity.
- Defer national health dashboards, automatic retraining, SMS, real offline queue/sync, resumable uploads, researcher exports and production integrations. An ordinary server-side draft is NOT offline support. Explain what is implemented versus deferred.

## Work order and completion
Follow the seven phases in the complete implementation plan below. Implement foundation, patient management, both submission paths, and clinical review first; then the AI/safety boundaries, integration testing, and local demonstration setup. Blocked requirements do not prevent independent work.

Use focused tests for consent/submission validation; NULL symptom handling; private image access; cross-case linkage; transactional review rollback; primary diagnosis rules; needs-information resubmission; AI unavailable/failure/retry history; and invalid adapter output. Perform one actual browser smoke test of the happy path if browser tooling is available. Do not report checks as passed unless run. Summarize implemented, tested and blocked/deferred features plus the exact AI integration seam. Track every AT-01 through AT-12 individually, including not-run and blocked results.

Preserve source files and unrelated changes. Don't broaden scope to chase sponsor prizes. Finish a reliable demonstrable workflow before adding optional features. If blocked, fix what can be fixed and report the specific unresolved dependency.

## Complete implementation plan — normative requirements

# Reconciled implementation decisions

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
