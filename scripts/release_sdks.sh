#!/usr/bin/env bash
# Cut a release of the NoralVoice SDKs at the given version.
#
# Phase 1+ ships **four** packages from this one script:
#
#   New canonical:
#     - noralai-voice       (PyPI)
#     - @noralai/voice-sdk  (npm)
#
#   Deprecated alias (one release of dual-publish, then drop):
#     - dograh-sdk          (PyPI)  — thin shim depending on noralai-voice
#     - @dograh/sdk         (npm)   — thin shim depending on @noralai/voice-sdk
#
# Usage:
#   ./scripts/release_sdks.sh 0.2.0
#
# Prerequisites (one-time):
#   - `pip install --upgrade build twine`
#   - `npm login` as a member of both the `@noralai` and (for the alias)
#     `@dograh` npm orgs. The publish steps prompt for 2FA OTPs — run
#     this script in a terminal where you can type them.
#
# Each publish is gated by a y/N prompt so you can dry-run the build
# and bail before anything hits a registry.

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "usage: $0 <version>   # e.g. 0.2.0" >&2
    exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.\-][A-Za-z0-9.]+)?$ ]]; then
    echo "error: '$VERSION' does not look like semver (e.g. 0.2.0 or 0.2.0-rc.1)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

confirm() {
    local reply
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

echo "→ Pre-flight checks..."
if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm not found in PATH" >&2
    exit 1
fi
if ! NPM_USER="$(npm whoami 2>/dev/null)"; then
    echo "error: not logged in to npm. Run 'npm login' as a member of both" >&2
    echo "       the @noralai and @dograh orgs before re-running this script" >&2
    exit 1
fi
echo "  npm: logged in as $NPM_USER"

echo "→ Regenerating typed SDK sources from node_specs..."
./scripts/generate_sdk.sh

if ! git diff --quiet -- sdk/python/src/noralai_voice/typed sdk/typescript/src/typed; then
    echo
    echo "⚠  node_specs regeneration changed typed files. Review the diff"
    echo "   above and commit before releasing — otherwise the tag will"
    echo "   point at a tree that disagrees with what ships to the registry."
    if ! confirm "Continue anyway?"; then
        exit 1
    fi
fi

echo "→ Bumping versions to $VERSION in all four packages..."
VERSION="$VERSION" python - <<'PY'
import os
import pathlib
import re

version = os.environ["VERSION"]

# Canonical packages — versions live in their own files.
py = pathlib.Path("sdk/python/pyproject.toml")
py.write_text(
    re.sub(r'^version = "[^"]+"', f'version = "{version}"', py.read_text(), count=1, flags=re.M)
)
ts = pathlib.Path("sdk/typescript/package.json")
ts.write_text(
    re.sub(r'"version": "[^"]+"', f'"version": "{version}"', ts.read_text(), count=1)
)

# Alias packages — their version AND their dependency on the canonical
# both bump in lock-step. The alias is only meaningful if it pulls in
# the matching canonical version.
py_alias = pathlib.Path("sdk/python_alias_dograh/pyproject.toml")
content = py_alias.read_text()
content = re.sub(r'^version = "[^"]+"', f'version = "{version}"', content, count=1, flags=re.M)
content = re.sub(r'"noralai-voice==[^"]+"', f'"noralai-voice=={version}"', content)
py_alias.write_text(content)

ts_alias = pathlib.Path("sdk/typescript_alias_dograh/package.json")
content = ts_alias.read_text()
content = re.sub(r'"version": "[^"]+"', f'"version": "{version}"', content, count=1)
content = re.sub(r'"@noralai/voice-sdk": "[^"]+"', f'"@noralai/voice-sdk": "{version}"', content)
ts_alias.write_text(content)

print(f"  sdk/python/pyproject.toml                   -> {version}")
print(f"  sdk/typescript/package.json                 -> {version}")
print(f"  sdk/python_alias_dograh/pyproject.toml      -> {version} (depends_on noralai-voice=={version})")
print(f"  sdk/typescript_alias_dograh/package.json    -> {version} (depends_on @noralai/voice-sdk@{version})")
PY

echo "→ Building Python wheel + sdist (canonical: noralai-voice)..."
(
    cd sdk/python
    rm -rf dist build
    python -m build >/dev/null
    twine check dist/*
)

echo "→ Building Python wheel + sdist (alias: dograh-sdk)..."
(
    cd sdk/python_alias_dograh
    rm -rf dist build
    python -m build >/dev/null
    twine check dist/*
)

echo "→ Building TypeScript + running tests (canonical: @noralai/voice-sdk)..."
(
    cd sdk/typescript
    rm -rf dist
    npm ci --silent
    npm run build
    npm test
)

echo "→ Building TypeScript (alias: @dograh/sdk)..."
(
    cd sdk/typescript_alias_dograh
    rm -rf dist
    # The alias declares "@noralai/voice-sdk": "<VERSION>" as a runtime
    # dep. During the local build this resolves from the registry (or
    # from a published TestPyPI/TestNPM tarball if you've staged one);
    # if the canonical isn't yet published, this install will fail —
    # the dual-publish ordering below publishes canonical first.
    npm install --silent
    npm run build
)

echo
echo "============================================================"
echo "  Built four packages at version $VERSION:"
echo "    - noralai-voice"
echo "    - dograh-sdk (deprecated alias)"
echo "    - @noralai/voice-sdk"
echo "    - @dograh/sdk (deprecated alias)"
echo "  Nothing has been published yet."
echo "============================================================"
echo

if confirm "Upload noralai-voice==$VERSION to TestPyPI first (recommended)?"; then
    (cd sdk/python && twine upload --repository testpypi dist/*)
    echo "  -> https://test.pypi.org/project/noralai-voice/$VERSION/"
    echo
fi

# Canonical publishes BEFORE aliases — alias install resolves the
# canonical dep at install time.
if confirm "Publish @noralai/voice-sdk@$VERSION to npm? (will prompt for 2FA OTP)"; then
    (cd sdk/typescript && npm publish --access public)
    echo "  -> https://www.npmjs.com/package/@noralai/voice-sdk/v/$VERSION"
    echo
fi

if confirm "Upload noralai-voice==$VERSION to PyPI?"; then
    (cd sdk/python && twine upload dist/*)
    echo "  -> https://pypi.org/project/noralai-voice/$VERSION/"
    echo
fi

if confirm "Publish @dograh/sdk@$VERSION (deprecated alias) to npm?"; then
    (cd sdk/typescript_alias_dograh && npm publish --access public)
    echo "  -> https://www.npmjs.com/package/@dograh/sdk/v/$VERSION (deprecated)"
    echo
fi

if confirm "Upload dograh-sdk==$VERSION (deprecated alias) to PyPI?"; then
    (cd sdk/python_alias_dograh && twine upload dist/*)
    echo "  -> https://pypi.org/project/dograh-sdk/$VERSION/ (deprecated)"
    echo
fi

if confirm "Create annotated git tag sdks-v$VERSION at HEAD?"; then
    git tag -a "sdks-v$VERSION" -m "noralai-voice + @noralai/voice-sdk $VERSION (+ deprecated aliases dograh-sdk / @dograh/sdk)"
    echo "  -> created tag (not pushed). Push with:"
    echo "     git push origin sdks-v$VERSION"
fi

echo "✓ Done."
