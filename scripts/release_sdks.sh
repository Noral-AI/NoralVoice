#!/usr/bin/env bash
# Cut a release of the NoralVoice SDKs at the given version.
#
# Ships two packages from this one script:
#
#   - noralai-voice       (PyPI)
#   - @noralai/voice-sdk  (npm)
#
# Usage:
#   ./scripts/release_sdks.sh 0.2.0
#
# Prerequisites (one-time):
#   - `pip install --upgrade build twine`
#   - `npm login` as a member of the `@noralai` org. The publish steps
#     prompt for 2FA OTPs — run this script in a terminal where you can
#     type them.
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
    echo "error: not logged in to npm. Run 'npm login' as a member of" >&2
    echo "       the @noralai org before re-running this script" >&2
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

echo "→ Bumping versions to $VERSION in both packages..."
VERSION="$VERSION" python - <<'PY'
import os
import pathlib
import re

version = os.environ["VERSION"]

py = pathlib.Path("sdk/python/pyproject.toml")
py.write_text(
    re.sub(r'^version = "[^"]+"', f'version = "{version}"', py.read_text(), count=1, flags=re.M)
)
ts = pathlib.Path("sdk/typescript/package.json")
ts.write_text(
    re.sub(r'"version": "[^"]+"', f'"version": "{version}"', ts.read_text(), count=1)
)

print(f"  sdk/python/pyproject.toml       -> {version}")
print(f"  sdk/typescript/package.json     -> {version}")
PY

echo "→ Building Python wheel + sdist (noralai-voice)..."
(
    cd sdk/python
    rm -rf dist build
    python -m build >/dev/null
    twine check dist/*
)

echo "→ Building TypeScript + running tests (@noralai/voice-sdk)..."
(
    cd sdk/typescript
    rm -rf dist
    npm ci --silent
    npm run build
    npm test
)

echo
echo "============================================================"
echo "  Built two packages at version $VERSION:"
echo "    - noralai-voice"
echo "    - @noralai/voice-sdk"
echo "  Nothing has been published yet."
echo "============================================================"
echo

if confirm "Upload noralai-voice==$VERSION to TestPyPI first (recommended)?"; then
    (cd sdk/python && twine upload --repository testpypi dist/*)
    echo "  -> https://test.pypi.org/project/noralai-voice/$VERSION/"
    echo
fi

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

if confirm "Create annotated git tag sdks-v$VERSION at HEAD?"; then
    git tag -a "sdks-v$VERSION" -m "noralai-voice + @noralai/voice-sdk $VERSION"
    echo "  -> created tag (not pushed). Push with:"
    echo "     git push origin sdks-v$VERSION"
fi

echo "✓ Done."
