"use client";

import ServiceConfiguration from "@/components/ServiceConfiguration";
import { SETTINGS_DOCUMENTATION_URLS } from "@/constants/documentation";

export default function ModelsTab() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Models</h2>
        <p className="text-muted-foreground">
          Configure the LLM, TTS, and STT providers your voice agents use by default.
        </p>
      </div>
      <ServiceConfiguration docsUrl={SETTINGS_DOCUMENTATION_URLS.modelOverrides} />
    </div>
  );
}
