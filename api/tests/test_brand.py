"""Unit tests for the brand-tokens namespace in api.constants.

Mirrors ui/scripts/test-brand.mts. Verifies:
  1. Defaults match the NoralVoice baseline when no BRAND_* env vars set.
  2. Every field is overridable via its env var.

BRAND is evaluated at module import, so each case reloads api.constants
under patched os.environ.
"""

import importlib
import os
from unittest import mock

import pytest


BRAND_ENV_VARS = [
    "BRAND_NAME",
    "BRAND_PRODUCT_LINE",
    "PARENT_BRAND",
    "WIDGET_GLOBAL",
    "COOKIE_PREFIX",
    "DOCS_URL",
    "BRAND_DOMAIN",
    "SUPPORT_EMAIL",
]


def _reload_constants():
    import api.constants

    return importlib.reload(api.constants)


def _env_without_brand(extra: dict | None = None) -> dict:
    """Build an environ dict with BRAND_* stripped, then layer `extra`."""
    base = {k: v for k, v in os.environ.items() if k not in BRAND_ENV_VARS}
    if extra:
        base.update(extra)
    return base


def test_brand_defaults_match_noralvoice_baseline():
    with mock.patch.dict(os.environ, _env_without_brand(), clear=True):
        constants = _reload_constants()
        brand = constants.BRAND

    assert brand.name == "NoralVoice"
    assert brand.product_line == "NoralVoice"
    assert brand.parent_brand == "Noral AI"
    assert brand.widget_global_name == "NoralVoiceWidget"
    assert brand.cookie_prefix == "noralvoice"
    assert brand.docs_url == "https://docs.noral.ai/voice"
    assert brand.domain == "voice.noral.ai"
    assert brand.support_email == "support@noral.ai"


def test_brand_every_field_is_overridable():
    overrides = {
        "BRAND_NAME": "Acme",
        "BRAND_PRODUCT_LINE": "AcmeVoice",
        "PARENT_BRAND": "Acme Inc",
        "WIDGET_GLOBAL": "AcmeWidget",
        "COOKIE_PREFIX": "acme",
        "DOCS_URL": "https://docs.acme.example/voice",
        "BRAND_DOMAIN": "voice.acme.example",
        "SUPPORT_EMAIL": "help@acme.example",
    }
    with mock.patch.dict(os.environ, _env_without_brand(overrides), clear=True):
        constants = _reload_constants()
        brand = constants.BRAND

    assert brand.name == "Acme"
    assert brand.product_line == "AcmeVoice"
    assert brand.parent_brand == "Acme Inc"
    assert brand.widget_global_name == "AcmeWidget"
    assert brand.cookie_prefix == "acme"
    assert brand.docs_url == "https://docs.acme.example/voice"
    assert brand.domain == "voice.acme.example"
    assert brand.support_email == "help@acme.example"


def test_brand_partial_override_falls_back_to_defaults():
    with mock.patch.dict(
        os.environ,
        _env_without_brand({"BRAND_NAME": "PartialOnly"}),
        clear=True,
    ):
        constants = _reload_constants()
        brand = constants.BRAND

    assert brand.name == "PartialOnly"
    # Other fields still defaulted.
    assert brand.product_line == "NoralVoice"
    assert brand.parent_brand == "Noral AI"
    assert brand.cookie_prefix == "noralvoice"


@pytest.fixture(autouse=True)
def _restore_constants_after_test():
    """Reload api.constants after each test so the live module reflects
    the real env again — protects later tests in the same process."""
    yield
    _reload_constants()
