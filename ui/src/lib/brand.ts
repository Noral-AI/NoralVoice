// Brand-tokens module. Single source of truth for the strings that vary
// per deploy (white-label, fork, parent-brand swap). Read from environment
// at module load with safe defaults for NoralVoice.
//
// Phase 0 of the consolidation only *adds* this module — no callsites are
// changed here. Phase 5 (brand purge) is where every hardcoded "Dograh"
// literal is replaced with a reference to one of these tokens.

export const BRAND = {
    name: process.env.NEXT_PUBLIC_BRAND_NAME ?? "NoralVoice",
    productLine: process.env.NEXT_PUBLIC_BRAND_PRODUCT_LINE ?? "NoralVoice",
    parentBrand: process.env.NEXT_PUBLIC_PARENT_BRAND ?? "Noral AI",
    widgetGlobalName: process.env.NEXT_PUBLIC_WIDGET_GLOBAL ?? "NoralVoiceWidget",
    cookiePrefix: process.env.NEXT_PUBLIC_COOKIE_PREFIX ?? "noralvoice",
    docsUrl: process.env.NEXT_PUBLIC_DOCS_URL ?? "https://docs.noral.ai/voice",
    domain: process.env.NEXT_PUBLIC_BRAND_DOMAIN ?? "voice.noral.ai",
    supportEmail: process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "support@noral.ai",
} as const;

export type Brand = typeof BRAND;
