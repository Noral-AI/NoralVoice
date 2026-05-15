// Unit test for the brand-tokens module.
//
// Verifies two properties of ui/src/lib/brand.ts:
//   1. Defaults match the NoralVoice baseline when no NEXT_PUBLIC_BRAND_*
//      env vars are set.
//   2. Every field is overridable via its NEXT_PUBLIC_* env var.
//
// Because the BRAND object is evaluated once at module import, we run each
// case in a fresh child process with the relevant env scrubbed or set.
//
// Run via `npm run test:brand` from ui/, or `node ui/scripts/test-brand.mts`
// directly (Node 24+ strips TS types natively).

import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const BRAND_MODULE_PATH = resolve(__dirname, "../src/lib/brand.ts");

const BRAND_ENV_VARS = [
    "NEXT_PUBLIC_BRAND_NAME",
    "NEXT_PUBLIC_BRAND_PRODUCT_LINE",
    "NEXT_PUBLIC_PARENT_BRAND",
    "NEXT_PUBLIC_WIDGET_GLOBAL",
    "NEXT_PUBLIC_COOKIE_PREFIX",
    "NEXT_PUBLIC_DOCS_URL",
    "NEXT_PUBLIC_BRAND_DOMAIN",
    "NEXT_PUBLIC_SUPPORT_EMAIL",
];

function loadBrandWithEnv(env: Record<string, string | undefined>): Record<string, string> {
    // Strip any inherited NEXT_PUBLIC_BRAND_* so the child sees only what we pass.
    const childEnv: Record<string, string | undefined> = { ...process.env };
    for (const k of BRAND_ENV_VARS) delete childEnv[k];
    for (const [k, v] of Object.entries(env)) {
        if (v === undefined) delete childEnv[k];
        else childEnv[k] = v;
    }

    const script = `
        import { BRAND } from ${JSON.stringify(BRAND_MODULE_PATH)};
        process.stdout.write(JSON.stringify(BRAND));
    `;
    const result = spawnSync(
        process.execPath,
        ["--input-type=module", "-e", script],
        {
            env: childEnv as NodeJS.ProcessEnv,
            encoding: "utf-8",
        },
    );
    if (result.status !== 0) {
        throw new Error(
            `Brand subprocess failed: status=${result.status}\nstderr=${result.stderr}\nstdout=${result.stdout}`,
        );
    }
    return JSON.parse(result.stdout);
}

const DEFAULTS = {
    name: "NoralVoice",
    productLine: "NoralVoice",
    parentBrand: "Noral AI",
    widgetGlobalName: "NoralVoiceWidget",
    cookiePrefix: "noralvoice",
    docsUrl: "https://docs.noral.ai/voice",
    domain: "voice.noral.ai",
    supportEmail: "support@noral.ai",
};

const OVERRIDES = {
    NEXT_PUBLIC_BRAND_NAME: "Acme",
    NEXT_PUBLIC_BRAND_PRODUCT_LINE: "AcmeVoice",
    NEXT_PUBLIC_PARENT_BRAND: "Acme Inc",
    NEXT_PUBLIC_WIDGET_GLOBAL: "AcmeWidget",
    NEXT_PUBLIC_COOKIE_PREFIX: "acme",
    NEXT_PUBLIC_DOCS_URL: "https://docs.acme.example/voice",
    NEXT_PUBLIC_BRAND_DOMAIN: "voice.acme.example",
    NEXT_PUBLIC_SUPPORT_EMAIL: "help@acme.example",
};

const EXPECTED_OVERRIDDEN = {
    name: OVERRIDES.NEXT_PUBLIC_BRAND_NAME,
    productLine: OVERRIDES.NEXT_PUBLIC_BRAND_PRODUCT_LINE,
    parentBrand: OVERRIDES.NEXT_PUBLIC_PARENT_BRAND,
    widgetGlobalName: OVERRIDES.NEXT_PUBLIC_WIDGET_GLOBAL,
    cookiePrefix: OVERRIDES.NEXT_PUBLIC_COOKIE_PREFIX,
    docsUrl: OVERRIDES.NEXT_PUBLIC_DOCS_URL,
    domain: OVERRIDES.NEXT_PUBLIC_BRAND_DOMAIN,
    supportEmail: OVERRIDES.NEXT_PUBLIC_SUPPORT_EMAIL,
};

let failed = 0;

function assertDeepEqual(name: string, actual: unknown, expected: unknown): void {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a !== e) {
        console.error(`FAIL ${name}\n  expected: ${e}\n  actual:   ${a}`);
        failed++;
    } else {
        console.log(`PASS ${name}`);
    }
}

const defaultsCase = loadBrandWithEnv({});
assertDeepEqual("defaults match NoralVoice baseline", defaultsCase, DEFAULTS);

const overriddenCase = loadBrandWithEnv(OVERRIDES);
assertDeepEqual("every field is overridable", overriddenCase, EXPECTED_OVERRIDDEN);

// Partial override — only set BRAND_NAME, others should fall back to defaults.
const partial = loadBrandWithEnv({ NEXT_PUBLIC_BRAND_NAME: "PartialOnly" });
assertDeepEqual("partial override (BRAND_NAME only)", partial, {
    ...DEFAULTS,
    name: "PartialOnly",
});

if (failed > 0) {
    console.error(`\n${failed} test(s) failed`);
    process.exit(1);
}
console.log("\nAll brand-tokens tests passed");
