# Actual verification results — 2026-10-10

Local environment: macOS, Python 3.14.7, Flask 3.1.2, Pillow 12.0.0, SQLite runtime from Python. Schema remains user_version 2; no migration applied. All data/images are fictional/geometric. These are functional software checks, not clinical validation.

## Focused automated tests

Executed:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Final run: **21 tests passed in 0.909 seconds; no failures or resource warnings.**

| Test | Result |
|---|---|
| Configured fixture success → failure → retry preserves old success, candidates, source-quality snapshot; repeated stale request creates no extra run | PASS |
| Invalid configured output commits failed attempt only, no candidates/quality changes | PASS |
| Timeout discards late output; interrupted recovery; manual review remains possible | PASS |
| Unconfigured AI returns 503, creates no attempt and does not block review | PASS |
| Patient ownership, private images, clinician assignment, worker-denied records/actions | PASS |
| End-to-end patient intake → two images → consent → clinician diagnosis/treatment → patient result; exact Arabic text and images through fresh app/DB connections | PASS |
| Foreign keys on connections, cross-case review/analysis and diagnosis/review linkage, unique primary diagnosis | PASS |
| CSRF, loopback/Host gate, invalid demo identity | PASS |
| AI output contract rejects invalid text/triage/rank/confidence/image ownership | PASS |
| Legal transitions, explicit review revision, history, closure, stale/repeated review rejection | PASS |
| en/ar page attributes, pending Arabic notice, dir=auto rendering | PASS (scaffolding only) |
| Needs-information review/message persisted without destructive patient edits | PASS (resubmission intentionally blocked) |
| Providers cannot read/claim patient drafts | PASS |
| Referral/explicit escalation documentation without diagnosis; correct lifecycle | PASS |
| Diagnosis requirements, exactly one primary, referral validation and real follow-up date | PASS |
| Forced SQL failure during treatment insert rolls back review, diagnoses, treatment and status | PASS |
| Image decode validation, multi-file rollback cleanup, limits, stored hash/MIME and absence of EXIF | PASS |
| Consent/completeness validation, NULL vs 0, double-submit safety and submitted-content freeze | PASS |
| Invalid/future dates, blank names, malformed durations/booleans/sites and questionnaire upsert | PASS |
| Existing wrong-version database rejected without overwriting records | PASS |
| Seed/reset named-demo guard, duplicate seed preserves data, explicit reset flag | PASS |

## Running-server verification

Executed `flask --app app init-db` and `seed-demo`, then launched the actual Flask development server on **127.0.0.1:5000**, debug off. Executed:

```sh
.venv/bin/python tests/http_smoke.py create
```

**PASS:** real HTTP registration, exact Arabic name/complaint/notes, draft, two image uploads, consent submission, clinician queue/assignment, clinician diagnosis/treatment/referral/follow-up, patient result with private clinician notes excluded. Created synthetic case 2 (patient 3) in the demo database; seed case 1 remains available for review.

Stopped the server process, launched a fresh process against the same database/upload directory, then executed:

```sh
.venv/bin/python tests/http_smoke.py verify
```

**PASS:** identical stored image SHA-256, exact Arabic text, clinician result, provisional certainty, treatments, referral and access persisted. Repeated the read-only verification against the final application process after AI runner integration; **PASS**. The final server is left running locally. No external deployment or GitHub push occurred.

`git diff --check` passed. `schema.sql` is unchanged (SHA-256 `c3315779f36410940f8f0a0a52cb2ee7671f6bd1a8611d9ff15332f6964158cc`); original PDF remains unchanged/preserved. Root instruction documents were appended as requested.

**Actual browser happy path: NOT RUN / BLOCKED.** Browser inventory returned no connected browser surfaces. Native Safari access was not approved by Computer Use. No browser-rendering, file-picker, JavaScript double-click or full RTL visual-verification result is claimed. HTTP checks and HTML assertions are distinct from a browser smoke test. The denied Safari action was opening/controlling Safari for this local smoke test; no more detailed reason was returned.

## Individual acceptance tracking

| ID | First-run result | Evidence / full-plan qualification |
|---|---|---|
| AT-01 Patient registration | PASS for existing fields; full requirement PARTIAL | Profile test + running-server registration/retrieval. Medical history/geographic district pending schema. |
| AT-02 Worker submission | BLOCKED / NOT RUN | No User, worker grants or submitting-user attribution in v2; worker identity intentionally cannot submit/access records. |
| AT-03 Patient submission | PASS | Complaint/duration, NULL-preserving questionnaire, multiple sites/images, consent, submission persistence and idempotence tested. |
| AT-04 Case retrieval | PASS for supported roles | Own-patient/provider retrieval, image access, patient outcome and clinician-note privacy tested; worker path pending. |
| AT-05 AI screening | BLOCKED / real inference NOT RUN | No Omar inference supplied. Typed contract + simulated attempt lifecycle/failure/retry tests pass; these do not satisfy real screening acceptance. |
| AT-06 Safety screening | BLOCKED / automated policy NOT RUN | General emergency guidance + independent protocol only. No agreed input fields/clinical policy or structured assessment store; no invented rules. |
| AT-07 Clinical review | PASS for schema-supported review | Independent no-AI review; forced database-failure rollback, assignment checks, stale request rejection and preserved revision history tested. Missing medical history separately pending. |
| AT-08 Treatment documentation | PASS | Clinician-authorized provisional diagnosis, treatment instructions, medication/dosage and follow-up stored/retrieved; primary-diagnosis rules tested. |
| AT-09 Referral/escalation | PASS for clinician documentation; automated detection BLOCKED | Referral without diagnosis, required reason/destination, explicit escalation intent and red clinician priority persist; lifecycle reviewed and clinical decision referred remain separate. No automatic escalation or structured emergency flag claimed. |
| AT-10 Persistence | PASS | Fresh app/connection tests plus real server process restart and identical private image hash; exact Arabic text retained. |
| AT-11 Authorization | PASS for local demo mechanism | Cross-patient/provider/worker denials, private images, CSRF, Host/loopback checks. Production authentication/worker access design not implemented. |
| AT-12 Failure handling | PASS for implemented boundary | Unconfigured AI and simulated configured failures/timeouts/invalid outputs preserve manual review; clinical write rollback and upload cleanup tested. Real model-specific failures pending actual inference. |

The **schema-supported local prototype is functional**. Full MVP completion is not claimed: AT-02, real AT-05 and AT-06 remain blocked, together with durable medical history/identity/revision requirements. Complete Arabic translations/RTL verification and the actual browser smoke test remain pending.
