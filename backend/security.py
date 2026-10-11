"""Authenticated field/file encryption; plaintext is never a read fallback."""
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

PREFIX = 'fernet:v1:'
IMAGE_PREFIX = b'PALIDERM-FERNET-1\n'
# Only unconstrained text columns use direct tokens. Constrained numbers/JSON
# have explicit encrypted companion fields/envelopes rather than weakened SQL.
TEXT_FIELDS = {
    'Patient': ('first_name', 'last_name', 'date_of_birth', 'sex', 'phone', 'email'),
    'DermCase': ('chief_complaint',),
    'Symptom': ('additional_notes',),
    'ProviderReview': ('clinical_notes', 'patient_message', 'referral_destination', 'referral_reason', 'followup_date'),
    'Diagnosis': ('diagnosis_name',),
    'TreatmentPlan': ('medication', 'dosage', 'instructions'),
    'AIAnalysis': ('summary', 'rationale', 'limitations'),
    'AICandidate': ('diagnosis_name', 'rationale'),
}


class EncryptionError(RuntimeError):
    """Sanitized key/ciphertext failure; never includes patient data or the key."""


class Cipher:
    """Encrypt bounded values with Fernet; authenticated contexts prevent column mixups."""
    def __init__(self, key):
        """Accept a Fernet key supplied by environment/config; reject absent/invalid keys."""
        try:
            if not key:
                raise ValueError()
            self.fernet = Fernet(key.encode('ascii') if isinstance(key, str) else key)
        except (ValueError, TypeError, UnicodeError):
            raise EncryptionError('Configure a valid ENCRYPTION_KEY or ENCRYPTION_KEY_FILE; no plaintext fallback.') from None

    @classmethod
    def from_config(cls, config=None):
        """Load an explicitly selected environment key/file; never create one implicitly."""
        config = os.environ if config is None else config
        key = config.get('ENCRYPTION_KEY')
        keyfile = config.get('ENCRYPTION_KEY_FILE')
        if key and keyfile:
            raise EncryptionError('Set ENCRYPTION_KEY or ENCRYPTION_KEY_FILE, not both.')
        if keyfile:
            try:
                key = Path(keyfile).read_text(encoding='ascii').strip()
            except (OSError, UnicodeError):
                raise EncryptionError('Encryption key file is unavailable or invalid.') from None
        return cls(key)

    def encrypt(self, value, context):
        """Encrypt a JSON-compatible value with a field/image context inside the MAC."""
        raw = json.dumps({'context': context, 'value': value}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return PREFIX + self.fernet.encrypt(raw).decode('ascii')

    def decrypt(self, token, context):
        """Authenticate then decode; missing/plaintext/corrupt/wrong-context values fail."""
        try:
            if not isinstance(token, str) or not token.startswith(PREFIX):
                raise ValueError()
            payload = json.loads(self.fernet.decrypt(token[len(PREFIX):].encode('ascii')))
            if payload['context'] != context:
                raise ValueError()
            return payload['value']
        except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError):
            raise EncryptionError('Encrypted data could not be authenticated; check the key and storage integrity.') from None

    def text(self, table, field, value):
        """Encrypt nullable text after application validation, preserving exact UTF-8."""
        return None if value is None else self.encrypt(value, f'{table}.{field}')

    def reveal(self, table, row):
        """Return a decrypted row dict for authorized application use; never mutate SQL."""
        if row is None:
            return None
        result = dict(row)
        for field in TEXT_FIELDS.get(table, ()):
            if field in result and result[field] is not None:
                result[field] = self.decrypt(result[field], f'{table}.{field}')
        if table == 'Patient' and result.get('legacy_sex_encrypted') is not None:
            # Archive is not exposed in ordinary profile/template data.
            result.pop('legacy_sex_encrypted')
        if table == 'DermCase' and 'encrypted_duration' in result:
            result['duration_days'] = self.decrypt(result.pop('encrypted_duration'), 'DermCase.duration_days')
        if table == 'Symptom' and 'encrypted_answers' in result:
            result.update(self.decrypt(result.pop('encrypted_answers'), 'Symptom.answers'))
        if table == 'AIAnalysis' and 'input_snapshot_json' in result:
            try:
                envelope = json.loads(result['input_snapshot_json'])
                result['input_snapshot_json'] = self.decrypt(envelope['encrypted'], 'AIAnalysis.input_snapshot_json')
            except (ValueError, TypeError, KeyError):
                raise EncryptionError('Encrypted analysis snapshot is invalid.') from None
        return result

    def encrypt_image(self, data, storage_id):
        """Authenticate original bytes and the generated storage ID, keeping metadata intact."""
        return IMAGE_PREFIX + self.fernet.encrypt(storage_id.encode('ascii') + b'\0' + data)

    def decrypt_image(self, data, storage_id):
        """Return original image bytes only for an authentic encrypted storage object."""
        try:
            if not data.startswith(IMAGE_PREFIX):
                raise ValueError()
            payload = self.fernet.decrypt(data[len(IMAGE_PREFIX):])
            expected = storage_id.encode('ascii') + b'\0'
            if not payload.startswith(expected):
                raise ValueError()
            return payload[len(expected):]
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise EncryptionError('Encrypted image could not be authenticated.') from None


def cipher():
    """Return the configured application cipher; no process-global key or plaintext mode."""
    return current_app.extensions['cipher']


def encrypt_text(table, field, value):
    """Protect one validated nullable text value for a parameterized SQL write."""
    return cipher().text(table, field, value)


def reveal(table, row):
    """Decode a row at the service boundary using the current application's key."""
    return cipher().reveal(table, row)
