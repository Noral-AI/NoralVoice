"""Symmetric encryption for credentials stored in Postgres.

Design notes
------------
**Why this exists.** Before this module, every provider credential in the
platform — webhook auth, LLM keys, TTS keys — sat in plaintext JSON columns.
Anything with read access to the database, a backup, or a replica had them.

**Envelope format.** Ciphertext is stored as a self-describing string::

    v1:<urlsafe-base64 of (24-byte nonce || ciphertext || MAC)>

The ``v1:`` prefix does two jobs. It lets :func:`is_encrypted` distinguish an
encrypted value from a legacy plaintext one without a schema flag, so reads
stay backwards compatible while rows are migrated. And it gives us somewhere
to put ``v2:`` when the key or algorithm is rotated.

**Algorithm.** libsodium ``SecretBox`` (XSalsa20-Poly1305) via PyNaCl, which
is already a direct dependency. Authenticated, so tampering is detected on
decrypt rather than producing garbage. Nonces are random per encryption —
never reused, never derived from the plaintext.

**Key management.** The 32-byte key is read from the ``CREDENTIAL_ENCRYPTION_KEY``
environment variable, base64-encoded. This is the one secret that legitimately
belongs in the environment: it bears no credential itself, and it is what lets
every *actual* credential live in the database under the operator's control.
Generate one with::

    python -c "from api.services.crypto import generate_key; print(generate_key())"

Losing the key makes existing ciphertext unrecoverable — credentials would have
to be re-entered in the UI. Back it up with your other deploy secrets.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Final

from nacl import exceptions as nacl_exceptions
from nacl import secret, utils

#: Environment variable holding the base64-encoded 32-byte master key.
ENCRYPTION_KEY_ENV_VAR: Final[str] = "CREDENTIAL_ENCRYPTION_KEY"

#: Current envelope version prefix. Bump when the key or algorithm changes.
_ENVELOPE_PREFIX: Final[str] = "v1:"


class CredentialEncryptionError(Exception):
    """Raised when a credential cannot be encrypted or decrypted."""


class MissingEncryptionKeyError(CredentialEncryptionError):
    """Raised when ``CREDENTIAL_ENCRYPTION_KEY`` is absent or malformed.

    Deliberately distinct from the generic error so that callers can tell a
    misconfigured deployment ("you never set the key") apart from a genuine
    decryption failure ("this ciphertext is corrupt or was written under a
    different key").
    """


def generate_key() -> str:
    """Return a fresh base64-encoded key suitable for ``CREDENTIAL_ENCRYPTION_KEY``.

    Intended for operators bootstrapping a deployment. Not called at runtime —
    a key generated on the fly would silently orphan every existing credential.
    """
    return base64.b64encode(utils.random(secret.SecretBox.KEY_SIZE)).decode("ascii")


def _load_key() -> bytes:
    """Read and validate the master key from the environment.

    Read on every call rather than cached at import time so that tests (and
    key rotation) can change the environment without reloading the module.
    """
    raw = os.getenv(ENCRYPTION_KEY_ENV_VAR)
    if not raw:
        raise MissingEncryptionKeyError(
            f"{ENCRYPTION_KEY_ENV_VAR} is not set. Credentials cannot be encrypted. "
            f"Generate one with: python -c "
            f"\"from api.services.crypto import generate_key; print(generate_key())\""
        )

    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise MissingEncryptionKeyError(
            f"{ENCRYPTION_KEY_ENV_VAR} is not valid base64."
        ) from exc

    if len(key) != secret.SecretBox.KEY_SIZE:
        raise MissingEncryptionKeyError(
            f"{ENCRYPTION_KEY_ENV_VAR} must decode to exactly "
            f"{secret.SecretBox.KEY_SIZE} bytes, got {len(key)}."
        )

    return key


def is_encrypted(value: Any) -> bool:
    """Return True if ``value`` is an envelope produced by :func:`encrypt_secret`.

    Used to keep reads working against rows written before encryption existed,
    and to make the data migration idempotent.
    """
    return isinstance(value, str) and value.startswith(_ENVELOPE_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a string, returning a ``v1:``-prefixed envelope.

    Raises:
        MissingEncryptionKeyError: if the master key is absent or malformed.
        CredentialEncryptionError: if ``plaintext`` is not a string.
    """
    if not isinstance(plaintext, str):
        raise CredentialEncryptionError(
            f"encrypt_secret expects a string, got {type(plaintext).__name__}"
        )

    box = secret.SecretBox(_load_key())
    # SecretBox generates a fresh random nonce and prepends it to the output.
    encrypted = box.encrypt(plaintext.encode("utf-8"))
    return _ENVELOPE_PREFIX + base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_secret(envelope: str) -> str:
    """Decrypt a ``v1:`` envelope back to its plaintext string.

    A value that is not an envelope is returned unchanged. That is deliberate:
    rows written before this module existed hold bare plaintext, and reads must
    keep working while those rows are migrated.

    Raises:
        MissingEncryptionKeyError: if the master key is absent or malformed.
        CredentialEncryptionError: if the ciphertext fails authentication —
            corrupt data, or encrypted under a different key.
    """
    if not is_encrypted(envelope):
        return envelope

    box = secret.SecretBox(_load_key())
    payload = envelope[len(_ENVELOPE_PREFIX) :]

    try:
        raw = base64.urlsafe_b64decode(payload)
    except Exception as exc:
        raise CredentialEncryptionError(
            "Credential envelope is not valid base64; the stored value is corrupt."
        ) from exc

    try:
        return box.decrypt(raw).decode("utf-8")
    except nacl_exceptions.CryptoError as exc:
        # Deliberately does not echo the ciphertext or key into the message.
        raise CredentialEncryptionError(
            "Credential failed to decrypt. The stored value is corrupt, or it was "
            f"encrypted under a different {ENCRYPTION_KEY_ENV_VAR}."
        ) from exc


def encrypt_json(data: dict) -> str:
    """Serialise a dict and encrypt it as a single envelope.

    The whole document is encrypted rather than selected fields, so a new
    sensitive key added to a credential payload cannot be left in the clear by
    omission.
    """
    return encrypt_secret(json.dumps(data, separators=(",", ":"), sort_keys=True))


def decrypt_json(envelope: str) -> dict:
    """Inverse of :func:`encrypt_json`.

    Raises:
        CredentialEncryptionError: if the decrypted payload is not a JSON object.
    """
    decrypted = decrypt_secret(envelope)

    try:
        parsed = json.loads(decrypted)
    except json.JSONDecodeError as exc:
        raise CredentialEncryptionError(
            "Decrypted credential payload is not valid JSON."
        ) from exc

    if not isinstance(parsed, dict):
        raise CredentialEncryptionError(
            f"Decrypted credential payload is a {type(parsed).__name__}, expected an object."
        )

    return parsed


def last_four(plaintext: str) -> str:
    """Return the last four characters of a secret, for display in the UI.

    Lets the settings page show which key is installed without the read path
    ever decrypting it. Secrets shorter than eight characters return an empty
    string rather than leaking most of themselves.
    """
    if not isinstance(plaintext, str) or len(plaintext) < 8:
        return ""
    return plaintext[-4:]
