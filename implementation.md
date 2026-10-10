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
