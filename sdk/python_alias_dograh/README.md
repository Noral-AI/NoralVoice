# dograh-sdk (deprecated alias)

`dograh-sdk` has been renamed to `noralai-voice`. This package is a
deprecated alias for one release. Migrate before the next minor bump.

```bash
pip uninstall dograh-sdk
pip install noralai-voice
```

```diff
- from dograh_sdk import DograhClient, Workflow
+ from noralai_voice import DograhClient, Workflow
```

Class names (`DograhClient`, `Workflow`, ...) are unchanged — only the
package name moved.

Installing this alias prints a `DeprecationWarning` on first import and
pulls in `noralai-voice==0.2.0` as a transitive dependency, so existing
code continues to work without change.

See <https://docs.noral.ai/voice/sdk-migration> for the full migration
note.
