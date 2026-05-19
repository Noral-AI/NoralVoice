"""Pre-TTS exfiltration scan.

Ported from
``NoralOS/packages/plugins/voice-cascade/src/exfiltrationGuard.ts`` as
part of Phase 6's voice-cascade retirement. Same six pattern types,
same block-on-match semantics: if :func:`scan_for_secrets` returns any
matches, the caller MUST refuse to send the text to a TTS provider
and MUST log the event for security audit.

Pure regex analysis with zero dependencies on Pipecat / provider
infrastructure — safe to run at the route boundary as a pre-flight.

Never log the matched values themselves. The :attr:`SecretMatch.preview`
field shows the first 4 characters so audit logs can spot duplicates
without leaking secrets to log aggregation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Tuple


SecretType = Literal[
    "anthropic_key",
    "generic_sk_key",
    "slack_token",
    "github_token",
    "aws_key",
    "long_hex",
]


@dataclass(frozen=True)
class SecretMatch:
    """One regex hit. ``preview`` is the first 4 chars + ellipsis;
    never log the full matched value."""

    type: SecretType
    position: int
    length: int
    preview: str


# Patterns ported verbatim from exfiltrationGuard.ts. The Python regex
# engine matches the TS ones byte-for-byte EXCEPT that Python's ``re``
# uses Python's character-class syntax — which happens to be identical
# for these patterns. If you tweak one, mirror it on both sides until
# voice-cascade is fully retired (PR-3).
_PATTERNS: Tuple[Tuple[SecretType, "re.Pattern[str]"], ...] = (
    # Anthropic API keys: sk-ant- followed by 20+ alphanumeric/dash/underscore.
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    # Generic SK keys: sk- followed by 20+ chars, NOT starting with sk-ant-.
    ("generic_sk_key", re.compile(r"sk-(?!ant-)[A-Za-z0-9_-]{20,}")),
    # Slack bot/user tokens.
    ("slack_token", re.compile(r"xox[bp]-[A-Za-z0-9-]+")),
    # GitHub personal access tokens (ghp_ and gho_).
    ("github_token", re.compile(r"gh[po]_[A-Za-z0-9]{20,}")),
    # AWS access key IDs: AKIA + 16 alphanumeric.
    ("aws_key", re.compile(r"AKIA[A-Za-z0-9]{16}")),
    # Long hex strings (41+ chars, with non-alphanumeric boundaries).
    ("long_hex", re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{41,}(?![A-Za-z0-9])")),
)


def scan_for_secrets(text: str) -> list[SecretMatch]:
    """Return every secret match found in ``text``.

    Empty list means "safe to send to TTS". A non-empty list means the
    caller MUST refuse to synthesize and SHOULD log the match types
    (NOT the previews — those are for in-memory audit, not log
    aggregation).
    """
    matches: list[SecretMatch] = []
    for secret_type, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(0)
            matches.append(
                SecretMatch(
                    type=secret_type,
                    position=m.start(),
                    length=len(matched),
                    preview=matched[:4] + "…",
                )
            )
    return matches
