"""Application-level encryption for credentials at rest.

Provider secrets (ElevenLabs API keys, webhook auth, LLM keys) are entered in
the platform UI and stored in Postgres. They are encrypted here before they
touch the database so that a database dump, backup, or replica snapshot does
not disclose them.

See ``api/services/crypto/secrets.py`` for the envelope format and key
management.
"""

from api.services.crypto.secrets import (
    ENCRYPTED_FIELD_KEY,
    CredentialEncryptionError,
    MissingEncryptionKeyError,
    decrypt_json,
    decrypt_secret,
    encrypt_json,
    encrypt_secret,
    generate_key,
    is_encrypted,
    is_sealed,
    last_four,
    seal_credential_data,
    unseal_credential_data,
)

__all__ = [
    "ENCRYPTED_FIELD_KEY",
    "CredentialEncryptionError",
    "MissingEncryptionKeyError",
    "decrypt_json",
    "decrypt_secret",
    "encrypt_json",
    "encrypt_secret",
    "generate_key",
    "is_encrypted",
    "is_sealed",
    "last_four",
    "seal_credential_data",
    "unseal_credential_data",
]
