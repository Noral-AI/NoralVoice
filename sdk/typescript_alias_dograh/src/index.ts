/**
 * Deprecated alias of `@noralai/voice-sdk`.
 *
 * This package re-exports the public API from `@noralai/voice-sdk`. New
 * code should `import { DograhClient, Workflow } from "@noralai/voice-sdk"`.
 * This shim ships for exactly one release; it will be removed after the
 * next minor bump.
 */

// Emit a one-time deprecation warning on first import. We use a module-
// scoped guard so multiple `import` statements across a codebase only log
// once per process.
declare const globalThis: { __dograhSdkDeprecationLogged?: boolean };

if (typeof globalThis !== "undefined" && !globalThis.__dograhSdkDeprecationLogged) {
    globalThis.__dograhSdkDeprecationLogged = true;
    // eslint-disable-next-line no-console
    console.warn(
        "[deprecation] @dograh/sdk is deprecated and will be removed. " +
            "Install @noralai/voice-sdk and import from there instead. " +
            "See https://docs.noral.ai/voice/sdk-migration for details.",
    );
}

export * from "@noralai/voice-sdk";
