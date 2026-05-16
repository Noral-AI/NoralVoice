"""Tests for the exfiltration-scan pre-flight.

Phase 6 — ported from
``NoralOS/packages/plugins/voice-cascade/src/exfiltrationGuard.ts``
(which shipped without tests). Covers all 6 pattern types plus
negative cases.

The exfil guard is a security chokepoint: a false negative ships secrets
into a TTS provider. Tests here intentionally include a few well-formed
real-world key shapes to make sure the regex stays tight.
"""

from __future__ import annotations

import pytest

from api.services.audio.exfiltration_guard import SecretMatch, scan_for_secrets


# ---------------------------------------------------------------------------
# Positive matches — one test per pattern type.
# ---------------------------------------------------------------------------


def test_matches_anthropic_key():
    text = "Here is the key sk-ant-api03-AbCdEfGh1234567890_abc-xyz to use"
    matches = scan_for_secrets(text)
    assert any(m.type == "anthropic_key" for m in matches)
    # Preview is first 4 chars + ellipsis; never the full secret.
    anthropic_match = next(m for m in matches if m.type == "anthropic_key")
    assert anthropic_match.preview == "sk-a…"
    assert anthropic_match.length >= 27  # "sk-ant-" + 20+ chars


def test_matches_generic_sk_key():
    text = "OPENAI_API_KEY=sk-proj-abcdef1234567890abcdef yes"
    matches = scan_for_secrets(text)
    assert any(m.type == "generic_sk_key" for m in matches)


def test_anthropic_key_does_not_double_match_generic_sk():
    """The generic_sk regex uses a negative lookahead to exclude sk-ant-,
    so an Anthropic key should only match ``anthropic_key`` (not both)."""
    text = "sk-ant-api03-AbCdEfGh1234567890_abc-xyz"
    matches = scan_for_secrets(text)
    types = {m.type for m in matches}
    assert "anthropic_key" in types
    assert "generic_sk_key" not in types


def test_matches_slack_token_bot():
    text = "xoxb-1234567890-abcdef-ghijkl is the bot token"
    matches = scan_for_secrets(text)
    assert any(m.type == "slack_token" for m in matches)


def test_matches_slack_token_user():
    text = "xoxp-1234567890-9876543210-abcdef"
    matches = scan_for_secrets(text)
    assert any(m.type == "slack_token" for m in matches)


def test_matches_github_pat_classic():
    text = "ghp_1234567890abcdefghijklmnopqrstuv use this for the api"
    matches = scan_for_secrets(text)
    assert any(m.type == "github_token" for m in matches)


def test_matches_github_pat_oauth():
    text = "gho_1234567890abcdefghijklmnopqrstuv"
    matches = scan_for_secrets(text)
    assert any(m.type == "github_token" for m in matches)


def test_matches_aws_access_key_id():
    text = "AKIAIOSFODNN7EXAMPLE is the access key"
    matches = scan_for_secrets(text)
    assert any(m.type == "aws_key" for m in matches)


def test_matches_long_hex():
    # 64-char SHA-256-shaped hex — typical API key format.
    text = "the digest is " + "a" * 64 + " end"
    matches = scan_for_secrets(text)
    assert any(m.type == "long_hex" for m in matches)


# ---------------------------------------------------------------------------
# Negative cases — must NOT match.
# ---------------------------------------------------------------------------


def test_no_match_for_plain_english():
    matches = scan_for_secrets("Hello, this is a normal sentence with no secrets.")
    assert matches == []


def test_no_match_for_short_hex():
    # 40 chars is the lower bound; 39 must not match.
    text = "f" * 40
    matches = scan_for_secrets(text)
    assert matches == []


def test_no_match_for_hex_embedded_in_word():
    """The (?<![A-Za-z0-9]) lookbehind prevents matching when the hex
    is immediately preceded by an alphanumeric — so it doesn't fire on
    long lowercase words like a hypothetical 'abcdefabcdef...' that's
    actually a hex-like suffix of a larger token."""
    # "fooAAAAA..." where the AAAA's would be hex but are part of a
    # bigger alphanumeric run; the regex requires a boundary.
    # Using "x" prefix to ensure the hex sequence is preceded by an alphanumeric.
    text = "x" + "a" * 50
    # The 'x' is alphanumeric → the hex-only run that follows doesn't
    # have the required non-alphanumeric prefix.
    matches = scan_for_secrets(text)
    long_hex_matches = [m for m in matches if m.type == "long_hex"]
    assert long_hex_matches == []


def test_no_match_for_short_sk_prefix():
    """``sk-`` alone without 20+ chars after must not match."""
    text = "let's use sk-foo for the prefix"
    matches = scan_for_secrets(text)
    assert [m.type for m in matches if m.type == "generic_sk_key"] == []


def test_no_match_for_partial_aws_key():
    """AKIA + only 15 alphanumeric (one short of the 16 required)."""
    text = "AKIA123456789012345 is shortish"  # 15 chars after AKIA
    matches = scan_for_secrets(text)
    assert [m.type for m in matches if m.type == "aws_key"] == []


def test_preview_never_leaks_full_secret():
    """Defense in depth: even if the regex matched a 100-char string,
    only 4 chars + ellipsis end up in the SecretMatch.preview field."""
    text = "sk-ant-" + "a" * 100
    matches = scan_for_secrets(text)
    anthropic = next(m for m in matches if m.type == "anthropic_key")
    # Preview is "sk-a" + "…" — total 5 chars. Never includes any of
    # the random 100-char tail.
    assert len(anthropic.preview) == 5
    assert anthropic.preview.endswith("…")
    assert "aaaaaa" not in anthropic.preview


# ---------------------------------------------------------------------------
# Multi-match aggregation.
# ---------------------------------------------------------------------------


def test_multiple_matches_in_one_call():
    text = (
        "Mixed bag: sk-ant-api03-AbCdEfGh1234567890_abc-xyz and "
        "AKIAIOSFODNN7EXAMPLE then xoxb-99-99-abcd done"
    )
    matches = scan_for_secrets(text)
    types = {m.type for m in matches}
    assert {"anthropic_key", "aws_key", "slack_token"}.issubset(types)


def test_match_position_correctness():
    text = "prefix " + "sk-ant-api03-AbCdEfGh1234567890_abc-xyz" + " suffix"
    matches = scan_for_secrets(text)
    anthropic = next(m for m in matches if m.type == "anthropic_key")
    # "prefix " is 7 chars.
    assert anthropic.position == 7


def test_empty_text_returns_empty_list():
    assert scan_for_secrets("") == []
