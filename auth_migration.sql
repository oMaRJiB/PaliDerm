-- Additive authentication extension for the supplied base schema v2.
-- Applied transactionally by backend.db; do not modify schema.sql.
CREATE TABLE Account (
    account_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE
      CHECK(length(username) BETWEEN 3 AND 64 AND username = lower(username)
            AND username NOT GLOB '*[^a-z0-9._-]*'),
    password_hash TEXT NOT NULL CHECK(length(trim(password_hash)) > 0),
    role TEXT NOT NULL CHECK(role IN ('patient','provider','worker')),
    patient_id INTEGER UNIQUE REFERENCES Patient(patient_id),
    provider_id INTEGER UNIQUE REFERENCES Provider(provider_id),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK((role = 'patient' AND patient_id IS NOT NULL AND provider_id IS NULL) OR
          (role = 'provider' AND provider_id IS NOT NULL AND patient_id IS NULL) OR
          (role = 'worker' AND patient_id IS NULL AND provider_id IS NULL))
);
