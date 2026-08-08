"""Tests for api.services.crypto.secrets.

Covers the round trip, the backwards-compatibility path for rows written
before encryption existed, and the failure modes that matter operationally:
a missing key, a malformed key, and ciphertext that fails authentication.
"""

import base64
import json
import os
from unittest.mock import patch

import pytest
from nacl import secret, utils

from api.services.crypto import (
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
from api.services.crypto.secrets import ENCRYPTION_KEY_ENV_VAR


@pytest.fixture
def encryption_key():
    """Install a deterministic key for the duration of a test."""
    key = generate_key()
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: key}):
        yield key


@pytest.fixture
def no_encryption_key():
    """Remove the key entirely, simulating an unconfigured deployment."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(ENCRYPTION_KEY_ENV_VAR, None)
        yield


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip(encryption_key):
    plaintext = "sk_elevenlabs_abcdef0123456789"
    assert decrypt_secret(encrypt_secret(plaintext)) == plaintext


def test_ciphertext_does_not_contain_plaintext(encryption_key):
    """The whole point: the secret must not be readable in the stored value."""
    plaintext = "sk_elevenlabs_abcdef0123456789"
    envelope = encrypt_secret(plaintext)

    assert plaintext not in envelope
    # Nor after decoding the base64 — i.e. it is genuinely encrypted, not encoded.
    raw = base64.urlsafe_b64decode(envelope[len("v1:") :])
    assert plaintext.encode() not in raw


def test_nonce_is_random_so_same_plaintext_differs(encryption_key):
    """Equal secrets must not produce equal ciphertext, or the DB leaks which
    organizations share a key."""
    a = encrypt_secret("identical-secret")
    b = encrypt_secret("identical-secret")

    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "identical-secret"


def test_unicode_survives_round_trip(encryption_key):
    plaintext = "clé-secrète-🔐-Ω"
    assert decrypt_secret(encrypt_secret(plaintext)) == plaintext


def test_empty_string_round_trip(encryption_key):
    assert decrypt_secret(encrypt_secret("")) == ""


# ---------------------------------------------------------------------------
# Envelope detection / backwards compatibility
# ---------------------------------------------------------------------------


def test_is_encrypted_recognises_envelope(encryption_key):
    assert is_encrypted(encrypt_secret("x")) is True


@pytest.mark.parametrize(
    "value",
    ["sk_plaintext_key", "", "v2:something", None, 42, {"a": 1}],
)
def test_is_encrypted_rejects_non_envelopes(value):
    assert is_encrypted(value) is False


def test_decrypt_passes_through_legacy_plaintext(encryption_key):
    """Rows written before encryption existed must keep reading correctly."""
    assert decrypt_secret("legacy-plaintext-key") == "legacy-plaintext-key"


def test_decrypt_passes_through_plaintext_without_a_key(no_encryption_key):
    """Legacy reads must not require a key to be configured — otherwise adding
    encryption would break every existing deployment on startup."""
    assert decrypt_secret("legacy-plaintext-key") == "legacy-plaintext-key"


def test_encryption_is_idempotent_guard(encryption_key):
    """Encrypting an already-encrypted value double-wraps it; the migration
    relies on is_encrypted() to avoid that, so assert the shape it checks."""
    once = encrypt_secret("secret")
    twice = encrypt_secret(once)

    assert is_encrypted(once) and is_encrypted(twice)
    assert decrypt_secret(twice) == once  # one layer peeled, not the original


# ---------------------------------------------------------------------------
# JSON payloads
# ---------------------------------------------------------------------------


def test_encrypt_json_round_trip(encryption_key):
    data = {"api_key": "sk_live_123", "header_name": "xi-api-key", "nested": {"a": [1, 2]}}
    assert decrypt_json(encrypt_json(data)) == data


def test_encrypt_json_hides_every_field(encryption_key):
    """Whole-document encryption means a newly added sensitive field cannot be
    left in the clear by omission."""
    envelope = encrypt_json({"api_key": "sk_live_123", "token": "tok_secret"})

    assert "sk_live_123" not in envelope
    assert "tok_secret" not in envelope
    assert "api_key" not in envelope


def test_decrypt_json_rejects_non_object(encryption_key):
    envelope = encrypt_secret(json.dumps(["not", "an", "object"]))
    with pytest.raises(CredentialEncryptionError, match="expected an object"):
        decrypt_json(envelope)


def test_decrypt_json_rejects_non_json(encryption_key):
    with pytest.raises(CredentialEncryptionError, match="not valid JSON"):
        decrypt_json(encrypt_secret("this is not json"))


# ---------------------------------------------------------------------------
# Key configuration failures
# ---------------------------------------------------------------------------


def test_encrypt_without_key_raises_actionable_error(no_encryption_key):
    with pytest.raises(MissingEncryptionKeyError) as exc:
        encrypt_secret("secret")

    # The message must tell an operator how to fix it.
    assert ENCRYPTION_KEY_ENV_VAR in str(exc.value)
    assert "generate_key" in str(exc.value)


def test_decrypt_envelope_without_key_raises(no_encryption_key, ):
    with pytest.raises(MissingEncryptionKeyError):
        decrypt_secret("v1:c29tZS1jaXBoZXJ0ZXh0")


def test_malformed_base64_key_raises(no_encryption_key):
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: "not!valid!base64!"}):
        with pytest.raises(MissingEncryptionKeyError, match="valid base64"):
            encrypt_secret("secret")


def test_wrong_length_key_raises(no_encryption_key):
    short = base64.b64encode(b"tooshort").decode()
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: short}):
        with pytest.raises(MissingEncryptionKeyError, match="exactly 32 bytes"):
            encrypt_secret("secret")


def test_generate_key_produces_usable_key(no_encryption_key):
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: generate_key()}):
        assert decrypt_secret(encrypt_secret("secret")) == "secret"


# ---------------------------------------------------------------------------
# Tampering and key mismatch
# ---------------------------------------------------------------------------


def test_decrypt_under_different_key_fails_loudly(encryption_key):
    """Authenticated encryption must reject, not return garbage."""
    envelope = encrypt_secret("secret")

    other = base64.b64encode(utils.random(secret.SecretBox.KEY_SIZE)).decode()
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: other}):
        with pytest.raises(CredentialEncryptionError, match="different"):
            decrypt_secret(envelope)


def test_tampered_ciphertext_is_rejected(encryption_key):
    envelope = encrypt_secret("secret")
    raw = bytearray(base64.urlsafe_b64decode(envelope[len("v1:") :]))
    raw[-1] ^= 0xFF  # flip a bit in the MAC
    tampered = "v1:" + base64.urlsafe_b64encode(bytes(raw)).decode()

    with pytest.raises(CredentialEncryptionError):
        decrypt_secret(tampered)


def test_corrupt_base64_is_rejected(encryption_key):
    with pytest.raises(CredentialEncryptionError, match="corrupt"):
        decrypt_secret("v1:!!!not-base64!!!")


def test_error_message_never_echoes_the_secret(encryption_key):
    """A decryption failure must not put credential material into logs."""
    envelope = encrypt_secret("super-secret-value")
    raw = bytearray(base64.urlsafe_b64decode(envelope[len("v1:") :]))
    raw[-1] ^= 0xFF
    tampered = "v1:" + base64.urlsafe_b64encode(bytes(raw)).decode()

    with pytest.raises(CredentialEncryptionError) as exc:
        decrypt_secret(tampered)

    assert "super-secret-value" not in str(exc.value)
    assert tampered not in str(exc.value)


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("sk_live_abcd1234", "1234"),
        ("12345678", "5678"),
        ("1234567", ""),  # too short to mask meaningfully
        ("", ""),
        (None, ""),
        (12345678, ""),
    ],
)
def test_last_four(value, expected):
    assert last_four(value) == expected


def test_encrypt_rejects_non_string(encryption_key):
    with pytest.raises(CredentialEncryptionError, match="expects a string"):
        encrypt_secret({"not": "a string"})


# ---------------------------------------------------------------------------
# Sealing for JSON-column storage
#
# The column holds a JSON object, not a bare string, so a sealed credential is
# stored as {"__enc__": "v1:…"}. These tests pin that shape, because the data
# migration and every legacy row depend on it being distinguishable.
# ---------------------------------------------------------------------------


def test_seal_produces_the_documented_wrapper(encryption_key):
    sealed = seal_credential_data({"api_key": "sk-live-abcd1234"})

    assert set(sealed) == {ENCRYPTED_FIELD_KEY}
    assert is_encrypted(sealed[ENCRYPTED_FIELD_KEY])


def test_seal_unseal_round_trip(encryption_key):
    original = {"header_name": "X-API-Key", "api_key": "sk-live-abcd1234"}

    assert unseal_credential_data(seal_credential_data(original)) == original


def test_sealed_document_hides_every_field(encryption_key):
    sealed = seal_credential_data(
        {"username": "admin", "password": "hunter2", "header_name": "X-API-Key"}
    )
    blob = json.dumps(sealed)

    for secret_value in ("admin", "hunter2", "X-API-Key"):
        assert secret_value not in blob


def test_unseal_passes_through_legacy_plaintext_row(encryption_key):
    """A row written before encryption existed must still read correctly."""
    legacy = {"token": "legacy-plaintext-token"}

    assert unseal_credential_data(legacy) == legacy


def test_unseal_legacy_row_works_without_a_key_configured(no_encryption_key):
    """Deploying this must not break an installation that has no key yet."""
    legacy = {"token": "legacy-plaintext-token"}

    assert unseal_credential_data(legacy) == legacy


@pytest.mark.parametrize("empty", [None, {}])
def test_unseal_handles_empty_credential_data(empty):
    assert unseal_credential_data(empty) == {}


def test_is_sealed_discriminates(encryption_key):
    assert is_sealed(seal_credential_data({"a": "b"})) is True
    assert is_sealed({"api_key": "plaintext"}) is False
    assert is_sealed(None) is False
    assert is_sealed("v1:not-a-dict") is False


def test_sealing_is_not_doubly_applied_by_accident(encryption_key):
    """Sealing twice is detectable, so the migration can guard on is_sealed."""
    once = seal_credential_data({"api_key": "sk-live-abcd1234"})
    twice = seal_credential_data(once)

    # Both are sealed, so a naive migration would double-encrypt. is_sealed is
    # what stops that, and unsealing twice must recover the intermediate form.
    assert is_sealed(twice)
    assert unseal_credential_data(twice) == once


def test_unseal_rejects_tampered_sealed_document(encryption_key):
    sealed = seal_credential_data({"api_key": "sk-live-abcd1234"})
    envelope = sealed[ENCRYPTED_FIELD_KEY]
    # Flip a character in the base64 body.
    body = envelope[3:]
    tampered = "v1:" + ("A" if body[0] != "A" else "B") + body[1:]

    with pytest.raises(CredentialEncryptionError):
        unseal_credential_data({ENCRYPTED_FIELD_KEY: tampered})


def test_unseal_sealed_row_without_a_key_raises(no_encryption_key):
    """A sealed row cannot be read without the key, and says so clearly."""
    sealed = {ENCRYPTED_FIELD_KEY: "v1:c29tZS1jaXBoZXJ0ZXh0"}

    with pytest.raises(MissingEncryptionKeyError):
        unseal_credential_data(sealed)
