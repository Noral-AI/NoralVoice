"""Tests for encryption of provider keys held in configuration tables.

The LLM, TTS and STT keys that serve production calls do not live in
external_credentials — they live inside JSON documents on user_configurations
and organization_configurations. Those have their own read paths, so the
seal/unseal seam has to be wired there too, and it has to be wired *before*
those rows are encrypted or the next call fails to authenticate.

These tests pin the two properties that matter:

  - a sealed document round-trips through the same read path that legacy
    plaintext uses, so a part-migrated table works
  - selective sealing on organization_configurations does not break the query
    that filters on a value's contents
"""

import json
import os
from unittest.mock import patch

import pytest

from api.db.organization_configuration_client import (
    SECRET_BEARING_KEYS,
    _seal_if_secret,
    unseal_configuration_value,
)
from api.enums import OrganizationConfigurationKey
from api.services.crypto import generate_key, is_sealed
from api.services.crypto.secrets import ENCRYPTION_KEY_ENV_VAR


@pytest.fixture
def encryption_key():
    with patch.dict(os.environ, {ENCRYPTION_KEY_ENV_VAR: generate_key()}):
        yield


# ---------------------------------------------------------------------------
# organization_configurations — selective sealing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
        OrganizationConfigurationKey.TWILIO_CONFIGURATION.value,
        OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value,
    ],
)
def test_secret_bearing_keys_are_sealed(key, encryption_key):
    value = {"provider": "twilio", "auth_token": "super-secret-token"}

    sealed = _seal_if_secret(key, value)

    assert is_sealed(sealed)
    assert "super-secret-token" not in json.dumps(sealed)
    assert unseal_configuration_value(sealed) == value


@pytest.mark.parametrize(
    "key",
    [
        OrganizationConfigurationKey.DISPOSITION_CODE_MAPPING.value,
        OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value,
        OrganizationConfigurationKey.DISPOSITION_MESSAGE_TEMPLATE.value,
    ],
)
def test_non_secret_keys_are_left_alone(key, encryption_key):
    """Sealing these would make them opaque to any query that inspects them,
    and they hold no credential material to protect."""
    value = {"mapping": {"busy": "BUSY"}}

    assert _seal_if_secret(key, value) == value
    assert not is_sealed(_seal_if_secret(key, value))


def test_every_secret_bearing_key_is_a_real_configuration_key():
    """Guards against a typo silently disabling encryption for a key."""
    valid = {k.value for k in OrganizationConfigurationKey}

    assert SECRET_BEARING_KEYS <= valid


def test_non_dict_values_pass_through(encryption_key):
    """The column is a general key/value store; not every value is an object."""
    for value in [42, "a string", None, ["a", "list"]]:
        key = OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
        assert _seal_if_secret(key, value) == value
        assert unseal_configuration_value(value) == value


# ---------------------------------------------------------------------------
# Backwards compatibility — the part-migrated table
# ---------------------------------------------------------------------------


def test_legacy_plaintext_value_reads_unchanged(encryption_key):
    """Rows written before encryption existed must keep working."""
    legacy = {"provider": "twilio", "auth_token": "plaintext-token"}

    assert unseal_configuration_value(legacy) == legacy


def test_legacy_plaintext_reads_without_a_key_configured():
    """Deploying this must not break an install that has no key set yet."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(ENCRYPTION_KEY_ENV_VAR, None)
        legacy = {"provider": "twilio", "auth_token": "plaintext-token"}

        assert unseal_configuration_value(legacy) == legacy


# ---------------------------------------------------------------------------
# The regression this seam exists to prevent
# ---------------------------------------------------------------------------


def test_provider_filter_still_matches_once_values_are_sealed(encryption_key):
    """get_configurations_by_provider filters on value["provider"]. A sealed
    value has no "provider" key of its own, so filtering the raw column would
    silently match nothing — every Twilio org would look unconfigured."""
    key = OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value
    sealed = _seal_if_secret(key, {"provider": "twilio", "auth_token": "tok"})

    # The bug, demonstrated: the raw column no longer carries "provider".
    assert sealed.get("provider") is None

    # The fix: unseal first, then test.
    assert unseal_configuration_value(sealed).get("provider") == "twilio"


def test_langfuse_mask_preservation_reads_through_the_seam(encryption_key):
    """save_langfuse_credentials preserves an existing key when the incoming
    value is that key's mask. Reading the sealed column directly would return
    "" for the existing key, so the mask would never match and the real secret
    would be overwritten with its own mask."""
    key = OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value
    stored = _seal_if_secret(
        key, {"host": "https://lf", "public_key": "pk-real", "secret_key": "sk-real"}
    )

    assert stored.get("secret_key", "") == ""  # the trap
    assert unseal_configuration_value(stored)["secret_key"] == "sk-real"  # the fix
