-- Hacklanta teledermatology MVP: lean v2, fresh databases only.
-- Enable foreign_keys on EVERY application connection before transactions.
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;
BEGIN;

CREATE TABLE Patient (
    patient_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL CHECK(length(trim(first_name)) > 0),
    last_name TEXT NOT NULL CHECK(length(trim(last_name)) > 0),
    date_of_birth TEXT,
    sex TEXT,
    phone TEXT,
    email TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE Provider (
    provider_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    specialty TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE DermCase (
    case_id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES Patient(patient_id),
    provider_id INTEGER REFERENCES Provider(provider_id), -- assigned reviewer
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    submitted_at TEXT,
    chief_complaint TEXT NOT NULL CHECK(length(trim(chief_complaint)) > 0),
    duration_days INTEGER CHECK(duration_days >= 0),
    consent_at TEXT,
    consent_version TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
      CHECK(status IN ('draft','submitted','in_review','needs_information','reviewed','closed')),
    CHECK((consent_at IS NULL AND consent_version IS NULL) OR
          (consent_at IS NOT NULL AND consent_version IS NOT NULL AND length(trim(consent_version)) > 0)),
    CHECK(status = 'draft' OR
          (submitted_at IS NOT NULL AND consent_at IS NOT NULL AND consent_version IS NOT NULL))
);

-- One questionnaire per case. NULL means unknown/unanswered; 0 means no.
CREATE TABLE Symptom (
    symptom_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL UNIQUE REFERENCES DermCase(case_id),
    itching INTEGER CHECK(itching IN (0,1)),
    pain INTEGER CHECK(pain IN (0,1)),
    bleeding INTEGER CHECK(bleeding IN (0,1)),
    discharge INTEGER CHECK(discharge IN (0,1)),
    fever INTEGER CHECK(fever IN (0,1)),
    rapidly_worsening INTEGER CHECK(rapidly_worsening IN (0,1)),
    additional_notes TEXT
);

CREATE TABLE BodySite (
    body_site_id INTEGER PRIMARY KEY,
    site_name TEXT NOT NULL UNIQUE CHECK(length(trim(site_name)) > 0)
);

-- One affected area; patients need only select its body location.
CREATE TABLE Lesion (
    lesion_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES DermCase(case_id),
    body_site_id INTEGER NOT NULL REFERENCES BodySite(body_site_id)
);

CREATE TABLE LesionImage (
    image_id INTEGER PRIMARY KEY,
    lesion_id INTEGER NOT NULL REFERENCES Lesion(lesion_id),
    image_uri TEXT NOT NULL CHECK(length(trim(image_uri)) > 0),
    mime_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    image_quality TEXT NOT NULL DEFAULT 'unassessed'
      CHECK(image_quality IN ('unassessed','acceptable','poor'))
);

-- One row per AI attempt, including failed runs. Preserve prior successful runs.
CREATE TABLE AIAnalysis (
    analysis_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES DermCase(case_id),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_snapshot_json TEXT NOT NULL CHECK(json_valid(input_snapshot_json)),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK(status IN ('pending','running','completed','failed')),
    triage_level TEXT CHECK(triage_level IN ('red','amber','green','undetermined')),
    summary TEXT,
    rationale TEXT,
    limitations TEXT,
    error_message TEXT,
    UNIQUE(analysis_id, case_id),
    CHECK(status NOT IN ('completed','failed') OR completed_at IS NOT NULL),
    CHECK(status != 'completed' OR
          (triage_level IS NOT NULL AND summary IS NOT NULL)),
    CHECK(status != 'failed' OR error_message IS NOT NULL)
);

CREATE TABLE AICandidate (
    candidate_id INTEGER PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES AIAnalysis(analysis_id),
    rank INTEGER NOT NULL CHECK(rank >= 1),
    diagnosis_name TEXT NOT NULL CHECK(length(trim(diagnosis_name)) > 0),
    confidence REAL CHECK(confidence >= 0 AND confidence <= 1),
    rationale TEXT,
    UNIQUE(analysis_id, rank)
);

-- Provider decisions are separate from AI outputs, including triage overrides.
CREATE TABLE ProviderReview (
    review_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES DermCase(case_id),
    provider_id INTEGER NOT NULL REFERENCES Provider(provider_id),
    analysis_id INTEGER,
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decision TEXT NOT NULL CHECK(decision IN
      ('confirmed','modified','needs_information','referred','inconclusive')),
    triage_level TEXT NOT NULL CHECK(triage_level IN ('red','amber','green','undetermined')),
    clinical_notes TEXT,
    patient_message TEXT NOT NULL CHECK(length(trim(patient_message)) > 0),
    referral_required INTEGER NOT NULL DEFAULT 0 CHECK(referral_required IN (0,1)),
    referral_destination TEXT,
    referral_reason TEXT,
    followup_date TEXT,
    UNIQUE(review_id, case_id),
    FOREIGN KEY(analysis_id, case_id) REFERENCES AIAnalysis(analysis_id, case_id),
    CHECK(decision != 'referred' OR referral_required = 1),
    CHECK(referral_required = 0 OR length(trim(referral_reason)) > 0 AND referral_reason IS NOT NULL)
);

-- Clinician diagnoses only. No diagnosis is required for an inconclusive review.
CREATE TABLE Diagnosis (
    diagnosis_id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL,
    review_id INTEGER NOT NULL,
    diagnosis_name TEXT NOT NULL CHECK(length(trim(diagnosis_name)) > 0),
    certainty TEXT NOT NULL DEFAULT 'provisional' CHECK(certainty IN ('provisional','confirmed')),
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK(is_primary IN (0,1)),
    FOREIGN KEY(review_id, case_id) REFERENCES ProviderReview(review_id, case_id)
);
CREATE UNIQUE INDEX one_primary_diagnosis_per_review ON Diagnosis(review_id) WHERE is_primary = 1;

CREATE TABLE TreatmentPlan (
    treatment_id INTEGER PRIMARY KEY,
    diagnosis_id INTEGER NOT NULL REFERENCES Diagnosis(diagnosis_id),
    medication TEXT,
    dosage TEXT,
    instructions TEXT NOT NULL CHECK(length(trim(instructions)) > 0)
);

CREATE INDEX cases_by_patient ON DermCase(patient_id, created_at);
CREATE INDEX provider_queue ON DermCase(status, provider_id, submitted_at);
CREATE INDEX lesions_by_case ON Lesion(case_id);
CREATE INDEX images_by_lesion ON LesionImage(lesion_id);
CREATE INDEX analyses_by_case ON AIAnalysis(case_id, analysis_id);
CREATE INDEX reviews_by_case ON ProviderReview(case_id, review_id);
CREATE INDEX reviews_by_provider ON ProviderReview(provider_id);
CREATE INDEX diagnoses_by_case ON Diagnosis(case_id);
CREATE INDEX diagnoses_by_review ON Diagnosis(review_id);
CREATE INDEX treatments_by_diagnosis ON TreatmentPlan(diagnosis_id);

-- Deliberately small lookup vocabulary; append without changing the schema.
INSERT INTO BodySite(site_name) VALUES
 ('scalp'),('face'),('neck'),('chest'),('abdomen'),('back'),
 ('arm'),('hand'),('leg'),('foot'),('groin'),('other');
COMMIT;
