#!/bin/sh
# Select the encrypted dataset and environment-managed key file; never generate
# a replacement key at startup. exec keeps Ctrl-C attached to the Flask process.
set -eu
cd -- "$(dirname -- "$0")"
export DATABASE="${DATABASE:-instance/encrypted/demo.sqlite3}"
export UPLOAD_DIR="${UPLOAD_DIR:-instance/encrypted/uploads}"
if [ -z "${ENCRYPTION_KEY:-}" ]; then
    export ENCRYPTION_KEY_FILE="${ENCRYPTION_KEY_FILE:-instance/encryption.key}"
fi
exec .venv/bin/python -m flask --app app run --host 127.0.0.1 --port "${PORT:-5000}"
