-- Additive runtime-v4 encryption extension. Base v2/v3 schemas are preserved.
ALTER TABLE Patient ADD COLUMN legacy_sex_encrypted TEXT;
ALTER TABLE DermCase ADD COLUMN encrypted_duration TEXT;
ALTER TABLE Symptom ADD COLUMN encrypted_answers TEXT;
CREATE TABLE EncryptionConfig (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    key_check TEXT NOT NULL
);
