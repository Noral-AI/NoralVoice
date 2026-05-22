"""Tests for workflow ``model_overrides`` api_key preservation.

Covers:
- ``mask_model_overrides`` / ``mask_workflow_configurations`` (read path)
- ``merge_model_overrides`` / ``merge_workflow_configurations`` (write path)

The behavior mirrors :func:`merge_user_configurations` for global user config,
but operates on the free-form dict stored under
``workflow.workflow_configurations.model_overrides``.
"""

from api.services.configuration.masking import (
    mask_key,
    mask_model_overrides,
    mask_workflow_configurations,
)
from api.services.configuration.merge import (
    merge_model_overrides,
    merge_workflow_configurations,
)


# ---------------------------------------------------------------------------
# mask_model_overrides
# ---------------------------------------------------------------------------


class TestMaskModelOverrides:
    def test_masks_string_api_key_per_service(self):
        overrides = {
            "llm": {"provider": "anthropic", "model": "claude-x", "api_key": "sk-ant-abcdefghij"},
            "tts": {"provider": "cartesia", "voice": "v1", "api_key": "ck_xyz123456789"},
        }
        masked = mask_model_overrides(overrides)
        assert masked["llm"]["api_key"] == mask_key("sk-ant-abcdefghij")
        assert masked["tts"]["api_key"] == mask_key("ck_xyz123456789")

    def test_masks_list_api_keys(self):
        overrides = {"llm": {"provider": "openai", "api_key": ["sk-aaaa1111", "sk-bbbb2222"]}}
        masked = mask_model_overrides(overrides)
        assert masked["llm"]["api_key"] == [mask_key("sk-aaaa1111"), mask_key("sk-bbbb2222")]

    def test_no_api_key_no_mutation(self):
        overrides = {"llm": {"provider": "anthropic", "model": "claude-x"}}
        masked = mask_model_overrides(overrides)
        assert masked == overrides
        assert masked is not overrides  # deep copy

    def test_none_and_empty_passthrough(self):
        assert mask_model_overrides(None) is None
        assert mask_model_overrides({}) == {}

    def test_preserves_is_realtime_flag(self):
        overrides = {"is_realtime": True, "llm": {"provider": "anthropic", "api_key": "sk-x"}}
        masked = mask_model_overrides(overrides)
        assert masked["is_realtime"] is True

    def test_does_not_mutate_input(self):
        overrides = {"llm": {"provider": "anthropic", "api_key": "sk-ant-abcdefghij"}}
        original_snapshot = {"llm": {"provider": "anthropic", "api_key": "sk-ant-abcdefghij"}}
        mask_model_overrides(overrides)
        assert overrides == original_snapshot


# ---------------------------------------------------------------------------
# mask_workflow_configurations
# ---------------------------------------------------------------------------


class TestMaskWorkflowConfigurations:
    def test_masks_only_model_overrides_subtree(self):
        cfg = {
            "dictionary": "{}",
            "model_overrides": {
                "llm": {"provider": "anthropic", "api_key": "sk-ant-abcdefghij"},
            },
            "voicemail_detection": {"enabled": True, "api_key": "sk-vm-doNOTmask"},
        }
        masked = mask_workflow_configurations(cfg)
        assert masked["model_overrides"]["llm"]["api_key"] == mask_key("sk-ant-abcdefghij")
        # Voicemail block lives outside model_overrides and is intentionally untouched
        assert masked["voicemail_detection"]["api_key"] == "sk-vm-doNOTmask"
        assert masked["dictionary"] == "{}"

    def test_passthrough_without_model_overrides(self):
        cfg = {"dictionary": "{}", "template_variables": {}}
        assert mask_workflow_configurations(cfg) == cfg

    def test_none_passthrough(self):
        assert mask_workflow_configurations(None) is None


# ---------------------------------------------------------------------------
# merge_model_overrides
# ---------------------------------------------------------------------------


REAL_ANTHROPIC = "sk-ant-real-abcdefghij"
REAL_OPENAI = "sk-openai-real-xyz12345"


class TestMergeModelOverrides:
    # --- preservation when api_key absent ---------------------------------

    def test_preserves_api_key_when_incoming_omits_it(self):
        existing = {"llm": {"provider": "anthropic", "model": "claude-x", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "anthropic", "model": "claude-y"}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["llm"]["api_key"] == REAL_ANTHROPIC
        assert merged["llm"]["model"] == "claude-y"

    def test_preserves_api_key_when_incoming_sends_mask(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "anthropic", "model": "claude-y", "api_key": mask_key(REAL_ANTHROPIC)}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["llm"]["api_key"] == REAL_ANTHROPIC

    # --- explicit clear ---------------------------------------------------

    def test_empty_string_api_key_clears_field(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "anthropic", "model": "claude-y", "api_key": ""}}
        merged = merge_model_overrides(existing, incoming)
        assert "api_key" not in merged["llm"]

    def test_empty_list_api_key_clears_field(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "anthropic", "api_key": []}}
        merged = merge_model_overrides(existing, incoming)
        assert "api_key" not in merged["llm"]

    # --- provider change accepts incoming as-is ---------------------------

    def test_provider_change_accepts_incoming_api_key(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "openai", "model": "gpt-4", "api_key": REAL_OPENAI}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["llm"]["api_key"] == REAL_OPENAI

    def test_provider_change_without_api_key_uses_incoming_as_is(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "openai", "model": "gpt-4"}}
        merged = merge_model_overrides(existing, incoming)
        # No api_key copied across providers (would be wrong for new provider)
        assert "api_key" not in merged["llm"]
        assert merged["llm"]["provider"] == "openai"

    # --- new key replaces old --------------------------------------------

    def test_new_unmasked_key_overwrites(self):
        new_key = "sk-ant-rotated-key123"
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"llm": {"provider": "anthropic", "api_key": new_key}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["llm"]["api_key"] == new_key

    # --- removing a service from incoming drops the override --------------

    def test_service_absent_from_incoming_is_dropped(self):
        existing = {
            "llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC},
            "tts": {"provider": "cartesia", "api_key": "ck_secret_abc12345"},
        }
        incoming = {"llm": {"provider": "anthropic"}}  # tts intentionally absent
        merged = merge_model_overrides(existing, incoming)
        assert "tts" not in merged
        assert merged["llm"]["api_key"] == REAL_ANTHROPIC

    # --- is_realtime ------------------------------------------------------

    def test_is_realtime_pass_through(self):
        existing = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        incoming = {"is_realtime": True, "llm": {"provider": "anthropic"}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["is_realtime"] is True
        assert merged["llm"]["api_key"] == REAL_ANTHROPIC

    # --- edge cases -------------------------------------------------------

    def test_none_incoming_returns_none(self):
        assert merge_model_overrides({"llm": {}}, None) is None

    def test_empty_incoming_returns_empty(self):
        assert merge_model_overrides({"llm": {}}, {}) == {}

    def test_no_existing_returns_incoming(self):
        incoming = {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}
        merged = merge_model_overrides(None, incoming)
        assert merged == incoming

    def test_realtime_service_block(self):
        existing = {"realtime": {"provider": "openai-realtime", "api_key": REAL_OPENAI}}
        incoming = {"realtime": {"provider": "openai-realtime", "model": "preview-2"}}
        merged = merge_model_overrides(existing, incoming)
        assert merged["realtime"]["api_key"] == REAL_OPENAI
        assert merged["realtime"]["model"] == "preview-2"


# ---------------------------------------------------------------------------
# merge_workflow_configurations
# ---------------------------------------------------------------------------


class TestMergeWorkflowConfigurations:
    def test_preserves_model_overrides_api_keys_when_masked(self):
        existing = {
            "dictionary": "{}",
            "model_overrides": {
                "llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC},
            },
        }
        incoming = {
            "dictionary": "{}",
            "model_overrides": {
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-new",
                    "api_key": mask_key(REAL_ANTHROPIC),
                },
            },
        }
        merged = merge_workflow_configurations(existing, incoming)
        assert merged["model_overrides"]["llm"]["api_key"] == REAL_ANTHROPIC
        assert merged["model_overrides"]["llm"]["model"] == "claude-new"

    def test_other_fields_taken_from_incoming(self):
        existing = {
            "dictionary": "old",
            "voicemail_detection": {"enabled": False},
            "model_overrides": {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}},
        }
        incoming = {
            "dictionary": "new",
            "voicemail_detection": {"enabled": True},
            "model_overrides": {"llm": {"provider": "anthropic"}},
        }
        merged = merge_workflow_configurations(existing, incoming)
        assert merged["dictionary"] == "new"
        assert merged["voicemail_detection"]["enabled"] is True
        assert merged["model_overrides"]["llm"]["api_key"] == REAL_ANTHROPIC

    def test_no_existing_returns_incoming(self):
        incoming = {"model_overrides": {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}}
        assert merge_workflow_configurations(None, incoming) == incoming

    def test_no_incoming_model_overrides_passes_through(self):
        existing = {"model_overrides": {"llm": {"provider": "anthropic", "api_key": REAL_ANTHROPIC}}}
        incoming = {"dictionary": "x"}
        merged = merge_workflow_configurations(existing, incoming)
        # Incoming didn't mention model_overrides → result mirrors incoming
        # (the caller can fall back to existing if they want strict preservation).
        assert "model_overrides" not in merged
        assert merged["dictionary"] == "x"

    def test_incoming_none_returns_none(self):
        assert merge_workflow_configurations({"dictionary": "x"}, None) is None
