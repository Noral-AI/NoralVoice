# @dograh/sdk (deprecated alias)

`@dograh/sdk` has been renamed to `@noralai/voice-sdk`. This package is a
deprecated alias for one release. Migrate before the next minor bump.

```bash
npm uninstall @dograh/sdk
npm install @noralai/voice-sdk
```

```diff
- import { DograhClient, Workflow } from "@dograh/sdk";
+ import { DograhClient, Workflow } from "@noralai/voice-sdk";
```

Class names (`DograhClient`, `Workflow`, `DograhSdkError`, ...) are
unchanged — only the package name moved.

Installing this alias prints a `console.warn` on first import and pulls
in `@noralai/voice-sdk@0.2.0` as a transitive dependency, so existing
code continues to work without change.

See <https://docs.noral.ai/voice/sdk-migration> for the full migration
note.
