"""Optional synchronous adapter orchestration for one local server process.

Inference runs outside DB transactions. A bounded daemon worker supplies a timeout;
Python threads cannot kill stuck native inference. The one worker slot stays occupied
until the call exits, so an unresponsive adapter cannot accumulate unbounded threads.
"""
from contextlib import closing
from dataclasses import asdict
import json
from queue import Queue, Empty
from threading import BoundedSemaphore, Thread
from backend.ai.adapter import AIUnavailable, AnalysisOutput, UnconfiguredAdapter
from backend.db import connect, get_db
from backend import services as svc

_SLOT = BoundedSemaphore(1)


def recover_interrupted(path):
    with closing(connect(path)) as db:
        with db:
            db.execute("UPDATE AIAnalysis SET status='failed',completed_at=?,error_message='interrupted' "
                       "WHERE status IN ('pending','running')", (svc.now(),))


def run_analysis(case_id, identity, adapter, analysis_base, timeout):
    svc.role(identity, 'provider')
    svc.case_access(case_id, identity)
    if isinstance(adapter, UnconfiguredAdapter):
        raise AIUnavailable('AI integration pending')
    metadata = tuple(getattr(adapter, key, None) for key in ('model_name', 'model_version', 'prompt_version'))
    if any(not isinstance(v, str) or not v.strip() for v in metadata):
        raise svc.Problem('ai_configuration', 503)
    if not _SLOT.acquire(blocking=False):
        raise svc.Problem('ai_busy', 503)
    worker_started = False
    try:
        with svc.transaction() as db:
            svc.case_access(case_id, identity, db)
            latest = db.execute('SELECT analysis_id,status FROM AIAnalysis WHERE case_id=? ORDER BY analysis_id DESC LIMIT 1', (case_id,)).fetchone()
            latest_id = latest['analysis_id'] if latest else 0
            if str(latest_id) != analysis_base or latest and latest['status'] in ('pending', 'running'):
                return latest_id  # repeated form POST returns the existing attempt
            payload = svc.build_analysis_input(case_id, identity)
            snapshot = json.dumps(asdict(payload), ensure_ascii=False, allow_nan=False)
            attempt = db.execute('INSERT INTO AIAnalysis(case_id,model_name,model_version,prompt_version,input_snapshot_json) '
                                 'VALUES(?,?,?,?,?)', (case_id, *metadata, snapshot)).lastrowid
        with svc.transaction() as db:
            db.execute("UPDATE AIAnalysis SET status='running' WHERE analysis_id=?", (attempt,))
        channel = Queue(maxsize=1)

        def invoke():
            try:
                channel.put((True, adapter.analyze_case(payload)))
            except Exception:
                channel.put((False, None))
            finally:
                _SLOT.release()

        worker = Thread(target=invoke, daemon=True, name='local-ai-adapter')
        worker.start()
        worker_started = True
        try:
            success, output = channel.get(timeout=timeout)
            if not success or not isinstance(output, AnalysisOutput):
                raise ValueError('Adapter failed')
            output.validate(payload)
            if (output.model_name, output.model_version, output.prompt_version) != metadata:
                raise ValueError('Output metadata mismatch')
            with svc.transaction() as db:
                db.execute("UPDATE AIAnalysis SET status='completed',completed_at=?,triage_level=?,summary=?,rationale=?,limitations=? "
                           'WHERE analysis_id=?',
                           (svc.now(),output.triage_level,output.summary,output.rationale,output.limitations,attempt))
                for candidate in output.candidates:
                    db.execute('INSERT INTO AICandidate(analysis_id,rank,diagnosis_name,confidence,rationale) VALUES(?,?,?,?,?)',
                               (attempt,candidate.rank,candidate.diagnosis_name,candidate.confidence,candidate.rationale))
                for image_id, quality in output.image_quality.items():
                    # validate() has already checked that every image belongs to this input/case.
                    db.execute('UPDATE LesionImage SET image_quality=? WHERE image_id=?', (quality,image_id))
        except Exception as error:
            # No intake content, model traceback or arbitrary adapter exception enters logs/DB.
            code = 'timeout' if isinstance(error, Empty) else 'adapter_error'
            with svc.transaction() as db:
                db.execute("UPDATE AIAnalysis SET status='failed',completed_at=?,error_message=? WHERE analysis_id=?",
                           (svc.now(),code,attempt))
        return attempt
    finally:
        if not worker_started:
            _SLOT.release()
