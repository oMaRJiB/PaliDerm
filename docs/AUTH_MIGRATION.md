# Authentication migration v2 → v3 (second pass)

The user authorized actual login/logout and patient signup with a minimal additive migration. This document specifies that migration before implementation. The original `schema.sql` stays at v2 and is not edited. Runtime v3 consists of the original clinical tables plus one Account table; clinical records, IDs, reviews, consent and image references remain unchanged.

## Added structure

`Account(account_id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK patient/provider/worker, patient_id INTEGER UNIQUE REFERENCES Patient, provider_id INTEGER UNIQUE REFERENCES Provider, active INTEGER NOT NULL DEFAULT 1 CHECK IN(0,1), created_at TEXT NOT NULL UTC)`.

A table CHECK requires exactly one linked Patient for patient accounts, exactly one linked Provider for provider accounts, and neither for workers. Usernames are canonical ASCII lowercase identifiers (3–64 characters, letters/digits/dot/underscore/hyphen). Display names and all clinical free text remain exact UTF-8, including Arabic. Unique linked entity IDs prevent two accounts claiming the same patient/provider record. Passwords are salted scrypt hashes from the maintained [Werkzeug security library](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash); plaintext passwords never enter SQL, logs, URLs, sessions or documentation.

Public signup atomically creates a new Patient and an Account of role patient. It accepts no existing patient/provider ID or selectable role. Privileged accounts and links to existing records are created only by a local operator through `provision-account`, with a hidden password prompt. The migration creates no accounts/passwords and never infers identity from contact information. Existing records without an Account are preserved but inaccessible until deliberately linked by the operator.

## Applying it

Stop the server first. Run from the repository root:

```sh
.venv/bin/python -m backend.db migrate-auth --database instance/demo.sqlite3
```

The command refuses absent/unknown-version databases, checks foreign keys, creates a SQLite-consistent timestamped backup alongside the database, then adds Account and advances user_version to 3 in one transaction. It never runs base CREATE TABLE statements against an existing database. Repeating on v3 is a no-op. Startup requires v3: an existing v2 database gets an actionable migration command instead of a silent migration. A newly created runtime database explicitly applies base v2 then this declared additive extension during first initialization. Failures roll back the extension and version change; the pre-migration backup remains. No uploads are changed.

No destructive rollback command is provided. If a migration fails, preserve the runtime database and backup; inspect the reported version/integrity before retrying. Restoring a backup is an operator action and must not overwrite newer clinical records blindly.

## Scope

Only authentication/role linkage is implemented in v3. Worker-to-patient grants, submitting-user attribution, medical history, submission revisions, safety fields and comprehensive audit events remain pending, with future versions to be assigned explicitly. Password reset/recovery, email verification, MFA, persistent server-side session revocation and production login throttling are outside this local second pass. Loopback-only access remains enforced. Password login alone is not production security or a deployment approval.
