"""Private image bytes, validation, storage IDs and hashes; no HTTP handling."""
import hashlib
import io
import re
import warnings
from pathlib import Path
from uuid import uuid4
from PIL import Image, UnidentifiedImageError
from backend.validation import Problem
from backend.security import Cipher


class ImageStorage:
    """Validate originals, encrypt private files and authenticate/decrypt them without plaintext caching."""
    def __init__(self, config, encryption=None):
        """Use an explicitly supplied validated cipher or environment-managed key; never allow plaintext mode."""
        self.cipher = encryption or Cipher.from_config(config)
        self.root = Path(config['UPLOAD_DIR'])
        self.max_bytes = config['MAX_IMAGE_BYTES']
        self.max_count = config['MAX_IMAGE_COUNT']

    def path(self, storage_id):
        """Resolve only a generated JPEG/PNG basename inside the configured private root."""
        if not isinstance(storage_id, str) or not re.fullmatch(r'[a-f0-9]{32}\.(?:png|jpg)', storage_id):
            raise Problem('not_found', 404)
        return self.root / storage_id

    def existing_path(self, storage_id):
        """Require the generated storage file to exist; raise a sanitized not-found Problem otherwise."""
        path = self.path(storage_id)
        if not path.is_file():
            raise Problem('not_found', 404)
        return path

    def read_original(self, storage_id, expected_hash=None):
        """Decrypt into memory for authorized routes/adapters; verify source hash if supplied.

        Callers must authorize the case first. Missing files raise Problem; bad
        ciphertext/key raises EncryptionError. No plaintext temporary file exists.
        """
        data = self.cipher.decrypt_image(self.existing_path(storage_id).read_bytes(), storage_id)
        if expected_hash is not None and hashlib.sha256(data).hexdigest() != expected_hash:
            raise Problem('storage', 409)
        return data

    def verify(self, image):
        """Authenticate/decrypt and hash the exact source bytes before submission/inference."""
        self.read_original(image['image_uri'], image['content_sha256'])
        return self.path(image['image_uri'])

    def save(self, upload):
        """Validate original bytes, encrypt to a new private file and return MIME/source-hash metadata."""
        data, mime, suffix = self.validate_original(upload)
        storage_id = uuid4().hex + suffix
        path = self.path(storage_id)
        try:
            with path.open('xb') as file:
                # SQL hashes describe original bytes, not randomized ciphertext.
                file.write(self.cipher.encrypt_image(data, storage_id))
            path.chmod(0o600)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {'image_uri': storage_id, 'mime_type': mime,
                'content_sha256': hashlib.sha256(data).hexdigest()}

    def discard(self, storage_id):
        """Remove only a validated generated storage object, including failed-transaction files."""
        self.path(storage_id).unlink(missing_ok=True)

    def validate_original(self, upload):
        """Decode a bounded JPEG/PNG and return unchanged bytes, MIME and suffix; raise Problem on invalid input."""
        raw = upload.stream.read(self.max_bytes + 1)
        if not raw or len(raw) > self.max_bytes:
            raise Problem('bad_image')
        try:
            with warnings.catch_warnings():
                # Keep Pillow's built-in decoder resource protection; no app pixel cap.
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw), formats=('JPEG', 'PNG')) as im:
                    if getattr(im, 'n_frames', 1) != 1:
                        raise ValueError()
                    im.load()
                    mime, suffix = ('image/jpeg', '.jpg') if im.format == 'JPEG' else ('image/png', '.png')
            # Exact bytes retain orientation, EXIF/GPS, ICC and other source metadata.
            return raw, mime, suffix
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise Problem('bad_image') from None
