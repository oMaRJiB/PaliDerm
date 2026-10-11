# Reconciled implementation decisions

## PaliDerm English/Arabic delivery update — 2026-10-11

Brand the current app PaliDerm with black/white/green/red accents. Remove the word
prototype from visible app text while retaining the user's requested disclaimer,
AI clinician-review requirement and general emergency guidance. Preserve historical
technical documentation and the existing clinical/security limitations.

The complete centralized Arabic label catalog and browser English/Arabic selector
are authorized now. Locale is signed-session presentation state, preserved through
login/logout and app restarts, with CSRF and safe local redirects. RTL layout uses
logical CSS; dates format in the chosen interface language and device timezone.
Translate known model output labels/narratives for presentation without changing
stored English labels, probabilities, rules or encrypted clinical history. Patient
and clinician-authored free text is not automatically translated.

Names/complaints/notes support exact Arabic or English. The user confirmed Latin
usernames/emails and telephone 0–9 digits only; validate these server-side and in
native forms, keeping their direction LTR. Passwords may use either language. No
schema migration or model/notebook changes. Full visual Arabic/device/accessibility
verification remains distinct from catalog, HTTP, JavaScript and persistence tests.

## Minimal prototype triage and local reset — 2026-10-11

The user's latest request authorizes only the existing-model rule layer and demo reset; no notebook/model/training changes. The saved SCIN bridge calls deterministic triage_case after inference. Structured shortness of breath raises emergency; rapid worsening or fever with discharge raises urgent; only top-ranked Malignancy/Precancer raises model-based urgent. All other actual supported labels have routine mappings, never lowering symptom urgency. Missing/invalid inputs, unmapped labels, Other or top score below configurable AI_TRIAGE_DEMO_THRESHOLD=0.5 require manual review. Threshold and rules are illustrative/unvalidated, not treatment guidance or full AT-06 validation.

Persist triage and original narrative in the existing encrypted AIAnalysis.rationale envelope, preserving immutable inputs and legacy results, with no schema changes. Routine plus manual-review flag maps to undetermined, never green; clinician priority/review remains independent. New strings remain centralized; Arabic translations/full RTL verification are still pending. README contains exact rules/mappings and manual reset commands. Direct Flask and launcher select the same existing local encryption key unless explicitly overridden; no key generation/plaintext fallback. Authorized reset clears active demo records/accounts/generated images, rotates default sessions, seeds synthetic records and privately writes fresh test credentials. Preserve all notebooks/models/code, encryption key and original migration sources/backups. Worker/revision/history and other previously blocked requirements remain pending.

## Patient questionnaire update — 2026-10-11

Patients can now save the additional SCIN answers with drafts and submission.
The existing encrypted Symptom answer envelope stores nested `model_metadata`;
SQL remains v4, source schemas are unchanged, and old six-answer envelopes remain
compatible. Native checkbox tiles replace binary dropdowns. Group confirmation
makes unchecked choices explicit No; otherwise they remain unknown, preserving
previously recorded No answers. Sex at birth reuses the profile's canonical `sex`
field as explicitly requested; age group derives from DOB at submission. Duration
uses the given saved categories without inventing an exact day count. Clinician
analysis reuses these answers and accepts only missing supplemental values.
Older submitted cases remain frozen and clinician review remains independent of
model completeness. This supersedes earlier provider-only/separate-sex-entry
statements below; all other pending requirements and model limitations remain.

## Saved-model integration update — 2026-10-11

Omar has authorized inference using the existing `notebooks/SCIN_custom_model.keras`
bundle. This supersedes statements below that actual inference is awaiting a model.
The application now uses a lazy adapter selected by administrator `MODEL_PATH`;
an empty value retains the unconfigured boundary. The supplied model has 14 grouped
outputs and consumes 31 binary answers plus five categorical fields (68 encoded
features). Providers must supply missing answers explicitly, preserved with each
encrypted analysis snapshot; the submitted questionnaire is unchanged. No schema,
training code, notebooks or saved artifacts are changed for this integration.
Scores are not clinically calibrated; triage stays undetermined and image quality
unassessed. Automated safety screening, independent clinical model evaluation,
worker attribution/history/revisions and other pending requirements below remain
pending. See `docs/AI_INTEGRATION.md` and `docs/TEST_RESULTS.md` for the integration
contract and actual verification; full MVP completion is not claimed.

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

## First-run scope and locale architecture (2026-10-10)

For this delivery, the user's first-run scope overrides broader completion gates without deleting them. The acceptance target is a functioning local prototype using the unchanged schema v2: persistent patient profiles (existing fields only), draft intake, multiple private images, consent submission, authorized clinician review, care plans/referrals/follow-up and patient results. Use Flask/Jinja, native HTML controls, minimal CSS and no external deployment/push. Deferred schema-dependent work must stay visible and must not block independent development.

English is implemented first. Centralize all interface text in `backend/i18n.py`, including errors, labels, notices, status displays and actions. Preserve English identifiers and stored enums. `APP_LOCALE` prepares en/ltr and ar/rtl page attributes. Arabic locale currently falls back to English with a visible incomplete-translation notice. Store UTF-8 free text exactly as entered, including Arabic and surrounding whitespace after nonblank validation. Use `dir="auto"` for user content and ltr for phone/email/dates/technical identifiers. Exact Arabic text must survive saving, real application restart, retrieval and rendered display. Arabic translations and full browser RTL verification are required before claiming full Arabic interface support; neither is complete in this first run. Do not add translation services or large i18n dependencies.

See `docs/REQUIREMENTS.md` for white-paper reconciliation and unapplied migration proposals, and `docs/TEST_RESULTS.md` for individual acceptance results. Real AI screening and automated safety screening remain blocked on Omar's inference and clinical policy. Worker attribution/access, medical history and needs-information resubmission remain blocked on explicit additive migrations. All long-term requirements above remain pending where unsupported; this delivery is not completion of the entire plan.

## Second-pass update (2026-10-10)

The user authorized real password authentication and a focused backend refactor without redesign. Original schema.sql v2 is preserved; runtime v3 adds only Account through the documented additive migration in `docs/AUTH_MIGRATION.md`. Existing v2 databases are backed up and migrated explicitly; no clinical record/image is overwritten or removed. Public signup creates patient accounts only; existing-record/provider/worker accounts are provisioned separately through a local password-prompt CLI. Werkzeug scrypt hashes, Account-derived roles, patient ownership and CSRF replace normal demo identity selection. There are no default passwords.

CaseWorkflow groups case reads/writes, AuthService handles accounts/sessions, and ImageStorage handles private bytes/identifiers/hashes. Ordinary helpers remain functions; routes call services and templates handle presentation. See `docs/ARCHITECTURE.md` for the folder map and Tkinter comparison. Basic Home/My cases/New case/Clinician queue/Logout navigation is role-appropriate with unchanged minimal styling. Arabic readiness and unconfigured AI remain intact. Worker grants/submitting attribution, medical history, durable submission revisions, real inference, automated clinical safety and production security remain pending; authenticated worker identity alone does not complete worker-assisted submission. No deployment or push.

## Presentation scope update (2026-10-10)

The user's updated scope supersedes the earlier minimal-CSS restriction: keep Flask/Jinja and implement a restrained professional medical interface using system fonts, off-white/white surfaces, dark text, muted teal/navy accents, modest rounding and responsive spacing. Share `static/app.css` and `static/forms.js` through base.html. No frontend framework, design-system dependency, animations or decorative gradients. Preserve the existing CaseWorkflow/AuthService/ImageStorage/AI adapter separation and native-form fallback. Enhanced forms must preserve inputs after server errors, prevent repeated clicks, and navigate only after server confirmation. Keep translated UI text, logical CSS properties, labeled priorities, UTF-8/free-text directions and the pending Arabic translation/RTL status. No schema migration or inference change is part of this presentation pass. Original blocked requirements remain pending.

## Camera, intake and original-image update (2026-10-10)

The latest user instruction overrides the earlier metadata-stripping and custom image-pixel-limit requirements. Preserve newly uploaded JPEG/PNG bytes exactly, including EXIF/GPS, orientation and other metadata when present. Do not infer location or implement outbreak detection. Previous stripped metadata cannot be reconstructed. Remove MAX_IMAGE_PIXELS from application configuration and patient-facing pixel jargon; retain file-size/count validation, decode validation and Pillow's built-in decompression protection. No resizing is needed by the unconfigured application; future model preprocessing must preserve the original source and document the exact transform/bytes used.

After initial draft creation, show all intake sections together on one scrollable page, with atomic Save draft / Submit behavior covering questionnaire, body sites, new photos and consent. Provide native phone-camera capture, optional live camera with permission/error handling, and existing-file selection. Browser capture may provide no source EXIF/GPS; retain what actually exists without fabricating metadata. Hide internal case numbers from patient display labels; retain technical IDs for routes, ownership checks and clinician use. Use responsive layouts for wide desktops and narrow portrait phones. Preserve the schema, class boundaries, Arabic readiness and unconfigured AI; no deployment/push. Real browser/device and Arabic RTL checks remain distinct from software tests.

## Encrypted persistence and gender update (2026-10-10)

The latest user authorizes encryption/gender changes and a safe additive migration. Keep schema.sql v2 and auth_migration.sql v3 unchanged. Runtime v4 adds only encrypted symptom answers, encrypted duration, encrypted legacy gender archive and a key-check record, plus plaintext-write guards. Store patient PII, complaint/duration, structured symptoms/notes, clinician review notes/messages/referral/follow-up, diagnosis/treatment narratives, persisted analysis snapshots/narratives and original images using authenticated cryptography/Fernet encryption. IDs/statuses/operational enums/dates/account usernames/password hashes remain queryable metadata; this is field/file encryption, not whole-database or OS-memory encryption.

Require an environment-managed ENCRYPTION_KEY or explicitly selected ENCRYPTION_KEY_FILE; no startup key generation or plaintext fallback. Migration copies plaintext source DB into RAM, transforms/verifies fields/images and atomically publishes a separate encrypted destination. Preserve original source records/files for rollback and report that those originals/backups remain plaintext until separately secured/removed. Do not silently migrate existing DBs on startup. Use the documented run-local.sh/environment configuration for the encrypted dataset. Missing/wrong keys and corrupt ciphertext fail closed; decrypt image bytes in memory only after role/ownership authorization. No keys, patient text or image bytes in logs or tracked files.

Replace free-text gender with Female/Male/Unknown or Prefer not to say; keep API/schema name sex and canonical encrypted logical values female/male/unknown. One-hot order is female/male/unknown. Normalize safe legacy values; archive unrecognized originals encrypted rather than deleting them. Structured symptom encodings preserve NULL vs 0. No structured medical-history table is introduced: history within supported notes is encrypted; the existing schema gap remains explicit.

Keep existing typed AI signatures, unconfigured state and clinician independence. Only encryption-related persistence and documentation may change around that boundary; no model development/inference/training. Add focused security/migration/encoding tests and concise code documentation. Documentation-only edits must not alter working logic (AST comparison used); no unrelated formatting, restructuring or cosmetic work. Follow docs/ENCRYPTION.md and docs/TEST_RESULTS.md for actual migration and remaining limitations. No external deployment/push.
