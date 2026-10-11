# Encryption and gender migration (runtime v4)

Patient questionnaire extension (2026-10-11): `Symptom.encrypted_answers` now
optionally contains `model_metadata` alongside the six original nullable answers.
The mapping holds the additional SCIN binary/category responses, including selected
duration ranges and server-derived profile categories. It uses the same authenticated
`Symptom.answers` encryption context. Old envelopes without this key remain valid;
no SQL migration, key change, plaintext fallback or record rewrite is required.
Submitted answers remain frozen. Each inference attempt also retains its exact
complete model inputs in the independently encrypted analysis snapshot.

The supplied schema.sql v2 and auth_migration.sql v3 remain unchanged. The user authorized authenticated encryption and an additive migration. v4 adds Patient.legacy_sex_encrypted, DermCase.encrypted_duration, Symptom.encrypted_answers and one EncryptionConfig key-check record. Existing symptom integer columns become NULL placeholders because their original CHECK constraints prohibit ciphertext. The encrypted answers preserve exact 0/1/NULL semantics. No clinical table is dropped or rebuilt.

Fernet protects patient name/contact/DOB/gender; case complaint/duration; structured symptoms and notes; clinician notes/messages/referral/follow-up; diagnosis/treatment text; AI attempt snapshots and narrative results (storage compatibility only, no inference development); and original image bytes. IDs, relationships, statuses, triage/certainty/quality enums, operational timestamps, account usernames and salted password hashes remain queryable metadata. This is field/file encryption, not encryption of the entire SQLite file. There is no structured MedicalHistory table: any history entered in existing free-text notes is protected; adding structured history remains pending agreed fields/schema.

The key must come from ENCRYPTION_KEY or explicitly configured ENCRYPTION_KEY_FILE. No generated startup default or plaintext fallback exists. A missing/invalid/wrong key stops startup; corrupt tokens fail closed without logging content. Use a distinct session signing secret. Losing the encryption key loses access to the data. Back up the key separately from encrypted records; key rotation tooling is pending.

Migration is copy-only: stop the server, select an unused destination directory, then run `python -m backend.migrate_encryption --source-db ... --source-uploads ... --destination ...` with the key environment configured. Source files are never overwritten. Migration verifies source image SHA-256, encrypts a clean target database/images, verifies round trips and foreign keys, then atomically publishes the destination directory. Source pages are transformed and VACUUMed in RAM before the target is written, avoiding stale plaintext SQLite pages. SQL triggers reject accidental plaintext writes to protected fields. Existing target paths are refused. Failure removes only newly created migration staging artifacts. The source v3 database/uploads and older backups remain plaintext, deliberately preserved for rollback; archive them securely and remove them separately once migration is validated. Do not continue running the old plaintext app.

Gender remains the existing API/database field `sex`; logical stored values become female/male/unknown, encrypted at rest. Known legacy F/M and case variants are normalized. Unrecognized legacy values map to unknown and their exact originals are archived encrypted. The one-hot helper returns female [1,0,0], male [0,1,0], unknown [0,0,1]; the vector is derived rather than redundantly stored. Symptom vector order and NULL preservation are documented in backend/preprocessing.py. No clinical rules/model are introduced.

Images are decrypted into memory only after service authorization, then returned through no-store backend endpoints. Raw storage references now identify encrypted files; future adapters must use the documented ImageStorage.read_original helper with the configured cipher, never open ciphertext as an image. The typed adapter interface and source plaintext SHA-256/MIME remain unchanged. No plaintext temporary image/cache is created. Camera capture and metadata retention apply to the decrypted original bytes.

See the README for exact key-generation, migration and launch commands. Fernet behavior follows the [cryptography documentation](https://cryptography.io/en/stable/fernet/).

## Startup and migration corrections (2026-10-11)

Direct Flask startup and `run-local.sh` now use the same encrypted database/upload defaults. Previously, a direct Flask command selected the old v3 database and requested migration even after a successful copy migration. Existing environment overrides remain authoritative; select `DATABASE=instance/encrypted/demo.sqlite3` and `UPLOAD_DIR=instance/encrypted/uploads` if your terminal still points at the old dataset. Supply the existing encryption key through exactly one configured key source. No key or clinical record needs replacing for this correction.

If legacy records exist but the default encrypted copy is absent, startup refuses to create an empty replacement. A failed fresh initialization removes only the new partial database it created, so a retry does not mistake it for legacy records; existing files are preserved. Copy migration still accepts v2 directly, adding authentication only to its in-memory copy.

Migration now handles valid repeated image references by encrypting one physical file and retaining all image rows; every reference must agree on its content hash and MIME type. Reports distinguish `images` (SQL rows) from `image_files` (stored objects). Invalid image identifiers, missing images, existing destinations and unsupported source versions produce controlled actionable CLI errors. Arbitrary OS/SQL exception contents are not exposed. Encryption, source preservation, private authorized image access and fail-closed key checks remain unchanged. No migration was rerun against the existing workspace dataset.

## Current local migration result

Applied to the synthetic workspace: 4 patients, 4 cases, 3 questionnaires, 1 review, 1 diagnosis, 1 treatment and 4 referenced images copied and verified; all 7 accounts retained. The v3 source database bytes are unchanged. Active runtime is `instance/encrypted/demo.sqlite3`; key file is private `instance/encryption.key`, selected through the environment by run-local.sh. Old `instance/demo.sqlite3`, `instance/uploads` and old backup databases are plaintext rollback material, outside the active dataset. Unreferenced old image files are not imported. All six documented test credentials passed login/logout after migration.

## Security limits

Fernet authenticates each value/file and its field/storage-ID context. It does not authenticate the complete relational database or prevent an attacker with database write access from replaying a valid token within the same field, changing plaintext metadata or deleting records. Key rotation, hardware-backed secrets, OS swap protection, comprehensive audit and production hosting/authentication hardening are pending. Never enable Flask debug for sensitive data. No plaintext temporary images are written; application errors do not log clinical input, keys or arbitrary adapter exceptions. Session Secure cookies are configurable for HTTPS; local loopback HTTP intentionally keeps Secure off. Existing scrypt hashes/role links survive migration unchanged.
