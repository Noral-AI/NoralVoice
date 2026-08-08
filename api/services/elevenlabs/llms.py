"""LLM catalogue for agent configuration.

Choosing among the LLMs ElevenLabs already hosts is a **configuration field**,
not infrastructure — it costs us nothing and adds no latency risk. That is a
different thing from BYO-LLM, which means running an inference endpoint inside
the latency-critical voice path, and which the plan caps at two clients behind
a stated latency budget (§9.2). Both are represented here so the distinction is
visible in code rather than remembered.

**This list will go stale, and that is expected.** The vendor ships new models
constantly. The catalogue is therefore advisory: it drives a good dropdown, but
the API accepts any string, so a model released tomorrow works without waiting
on a deploy. Validating against a frozen enum would turn every vendor release
into a code change.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Sentinel identifier ElevenLabs uses for a customer-supplied endpoint.
CUSTOM_LLM = "custom-llm"


@dataclass(frozen=True)
class LLMOption:
    identifier: str
    label: str
    provider: str
    #: Rough guidance for operators picking one, not a benchmark claim.
    note: str = ""


#: Curated subset of what the vendor hosts. Deliberately not exhaustive — the
#: full enum runs to dozens of near-identical variants, and presenting all of
#: them makes the choice harder rather than better informed.
#:
#: Verified against the ElevenLabs create-agent API reference on 2026-08-08.
CATALOGUE: tuple[LLMOption, ...] = (
    # Anthropic
    LLMOption("claude-sonnet-4-5", "Claude Sonnet 4.5", "Anthropic",
              "Strong instruction-following; good default for complex flows."),
    LLMOption("claude-haiku-4-5", "Claude Haiku 4.5", "Anthropic",
              "Fastest Claude — good where latency matters most."),
    LLMOption("claude-sonnet-4-6", "Claude Sonnet 4.6", "Anthropic"),
    LLMOption("claude-opus-4-7", "Claude Opus 4.7", "Anthropic",
              "Most capable, highest latency and cost."),
    # OpenAI
    LLMOption("gpt-4o-mini", "GPT-4o mini", "OpenAI",
              "Inexpensive and quick; fine for simple scripted agents."),
    LLMOption("gpt-4o", "GPT-4o", "OpenAI"),
    LLMOption("gpt-4.1", "GPT-4.1", "OpenAI"),
    LLMOption("gpt-5", "GPT-5", "OpenAI"),
    LLMOption("gpt-5-mini", "GPT-5 mini", "OpenAI"),
    # Google
    LLMOption("gemini-2.5-flash", "Gemini 2.5 Flash", "Google",
              "Low latency; a common choice for high-volume inbound."),
    LLMOption("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "Google",
              "Lowest latency and cost in the catalogue."),
    LLMOption("gemini-3.5-flash", "Gemini 3.5 Flash", "Google"),
    # ElevenLabs-hosted open models
    LLMOption("qwen3-30b-a3b", "Qwen3 30B", "ElevenLabs"),
    # Escape valve
    LLMOption(CUSTOM_LLM, "Custom endpoint (BYO-LLM)", "Custom",
              "Runs your own inference endpoint in the voice path. Capped at "
              "2 clients — see plan §9.2 before reaching for this."),
)


def catalogue_payload() -> list[dict[str, str]]:
    """Serialise the catalogue for the API."""
    return [
        {
            "identifier": option.identifier,
            "label": option.label,
            "provider": option.provider,
            "note": option.note,
        }
        for option in CATALOGUE
    ]


def is_known(identifier: str) -> bool:
    """Whether an identifier is one we list.

    Used for warning, never for rejection — see the module docstring. An
    unknown identifier is far more likely to be a model released since this
    file was written than a typo.
    """
    return any(option.identifier == identifier for option in CATALOGUE)


def build_custom_llm_config(
    *,
    url: str,
    model_id: str | None = None,
    api_key_secret_id: str | None = None,
    api_type: str = "chat_completions",
) -> dict:
    """Build the ``custom_llm`` block for a BYO-LLM agent.

    The API key is passed as a **reference to ElevenLabs' secret storage**, not
    as a literal value: a raw key here would end up in the agent configuration,
    which is readable by anyone who can read the agent.
    """
    config: dict = {"url": url, "api_type": api_type}
    if model_id:
        config["model_id"] = model_id
    if api_key_secret_id:
        config["api_key"] = {"secret_id": api_key_secret_id}
    return config
