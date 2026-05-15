"""Deprecated alias of ``noralai-voice``.

This package re-exports the public API from ``noralai_voice``. New code
should ``import noralai_voice`` (or ``from noralai_voice import ...``)
directly. This shim ships for exactly one release; it will be removed
after the next minor bump.
"""

import warnings as _warnings

_warnings.warn(
    "The `dograh-sdk` package is deprecated and will be removed. "
    "Install `noralai-voice` and import from `noralai_voice` instead. "
    "See https://docs.noral.ai/voice/sdk-migration for details.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export every public symbol from noralai_voice so existing code
# (``from dograh_sdk import DograhClient``) keeps working.
from noralai_voice import *  # noqa: F401,F403
from noralai_voice import __all__  # noqa: F401

# Wire submodule access (``dograh_sdk.typed``, ``dograh_sdk.errors``, etc.)
# so legacy import paths resolve to the real modules in ``noralai_voice``.
import sys as _sys

import noralai_voice._generated_models as _generated_models
import noralai_voice.client as _client
import noralai_voice.errors as _errors
import noralai_voice.typed as _typed
import noralai_voice.workflow as _workflow

_sys.modules[__name__ + "._generated_models"] = _generated_models
_sys.modules[__name__ + ".client"] = _client
_sys.modules[__name__ + ".errors"] = _errors
_sys.modules[__name__ + ".typed"] = _typed
_sys.modules[__name__ + ".workflow"] = _workflow
