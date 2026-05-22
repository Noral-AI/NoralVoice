from __future__ import annotations

"""Helpers for merging incoming user-configuration updates with what is already
stored, while honouring masked API keys.
"""

from typing import Any, Dict, Optional

from api.schemas.user_configuration import UserConfiguration
from api.services.configuration.masking import resolve_masked_api_keys

SERVICE_FIELDS = ("llm", "tts", "stt", "embeddings", "realtime")
OVERRIDE_SERVICE_FIELDS = ("llm", "tts", "stt", "embeddings", "realtime")


def merge_user_configurations(
    existing: UserConfiguration, incoming_partial: Dict[str, dict]
) -> UserConfiguration:
    """Merge *incoming_partial* onto *existing* and return a new UserConfiguration.

    *incoming_partial* is the body of the PUT request (already `model_dump()`ed or
    extracted via Pydantic `model_dump`).

    Rules:
    1. If a service block is absent in the request, keep the existing one.
    2. If provider unchanged and the api_key field is either missing or equal to
       the masked placeholder, preserve the existing real key.
    3. If provider changes, the incoming api_key is used verbatim (validation
       will fail later if it is missing).
    4. Non-service top-level fields (e.g. `test_phone_number`) are overwritten
       when supplied.
    """

    merged = existing.model_dump(exclude_none=True)

    def _merge_service_block(service_name: str):
        incoming_cfg = incoming_partial.get(service_name)
        if incoming_cfg is None:
            return  # nothing to do

        old_cfg = merged.get(service_name, {})

        provider_changed = (
            old_cfg.get("provider") is not None
            and incoming_cfg.get("provider") is not None
            and incoming_cfg.get("provider") != old_cfg.get("provider")
        )

        incoming_api_key = incoming_cfg.get("api_key")

        if not provider_changed:
            # conditional preservation of api_key
            if incoming_api_key is not None:
                if old_cfg and "api_key" in old_cfg:
                    incoming_cfg["api_key"] = resolve_masked_api_keys(
                        incoming_api_key, old_cfg["api_key"]
                    )
            else:
                if "api_key" in old_cfg:
                    incoming_cfg["api_key"] = old_cfg["api_key"]

        merged[service_name] = incoming_cfg

    for service in SERVICE_FIELDS:
        _merge_service_block(service)

    # other simple fields
    if "is_realtime" in incoming_partial:
        merged["is_realtime"] = incoming_partial["is_realtime"]

    if "test_phone_number" in incoming_partial:
        merged["test_phone_number"] = incoming_partial["test_phone_number"]

    if "timezone" in incoming_partial:
        merged["timezone"] = incoming_partial["timezone"]

    return UserConfiguration.model_validate(merged)


def merge_model_overrides(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Merge *incoming* workflow ``model_overrides`` on top of *existing*.

    Mirrors :func:`merge_user_configurations` but operates on the free-form
    ``model_overrides`` dict stored under ``workflow.workflow_configurations``.

    Per-service rules:

    1. A service block absent from *incoming* is dropped — that's how the UI
       signals "stop overriding this service".
    2. A service block present in both with the same provider preserves the
       real api_key when *incoming* either omits ``api_key`` or sends back a
       masked placeholder. An empty-string ``api_key`` is treated as an
       explicit clear (the user blanked the field).
    3. A service block whose provider differs is accepted as-is — the new
       provider needs its own (new) api_key.
    4. The top-level ``is_realtime`` flag is passed through unchanged.
    """
    if incoming is None:
        return None
    if not incoming:
        return incoming

    if not existing:
        return incoming

    merged: Dict[str, Any] = {}

    for service in OVERRIDE_SERVICE_FIELDS:
        incoming_cfg = incoming.get(service)
        if incoming_cfg is None:
            continue

        if not isinstance(incoming_cfg, dict):
            merged[service] = incoming_cfg
            continue

        raw_old = existing.get(service)
        old_cfg: Dict[str, Any] = raw_old if isinstance(raw_old, dict) else {}

        new_cfg = dict(incoming_cfg)

        provider_changed = (
            old_cfg.get("provider") is not None
            and new_cfg.get("provider") is not None
            and new_cfg.get("provider") != old_cfg.get("provider")
        )

        if not provider_changed:
            # api_key preservation: missing or masked → keep old.
            # Empty-string ``api_key`` is treated as explicit clear.
            if "api_key" not in new_cfg:
                if old_cfg.get("api_key"):
                    new_cfg["api_key"] = old_cfg["api_key"]
            else:
                incoming_api_key = new_cfg["api_key"]
                if incoming_api_key in (None, "", []) :
                    # Explicit clear — drop the field entirely so the override
                    # falls back to the global api_key.
                    new_cfg.pop("api_key", None)
                elif old_cfg.get("api_key"):
                    new_cfg["api_key"] = resolve_masked_api_keys(
                        incoming_api_key, old_cfg["api_key"]
                    )

        merged[service] = new_cfg

    if "is_realtime" in incoming:
        merged["is_realtime"] = incoming["is_realtime"]

    return merged


def merge_workflow_configurations(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Merge *incoming* workflow_configurations on top of *existing*.

    Only the ``model_overrides`` sub-tree gets api_key preservation; other
    fields (dictionary, voicemail_detection, template variables, …) are taken
    verbatim from *incoming* because the UI sends them as complete blocks.

    If *incoming* doesn't supply ``model_overrides``, we pass it through
    (which means "no change"); the caller is responsible for using ``existing``
    if they wanted strict preservation.
    """
    if incoming is None:
        return None

    if not existing:
        return incoming

    if "model_overrides" not in incoming:
        return incoming

    merged_overrides = merge_model_overrides(
        existing.get("model_overrides"), incoming.get("model_overrides")
    )

    out = dict(incoming)
    if merged_overrides is None:
        out.pop("model_overrides", None)
    else:
        out["model_overrides"] = merged_overrides
    return out
