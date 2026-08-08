"use client";

import { usePathname,useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppConfig } from "@/context/AppConfigContext";

import ApiKeysTab from "./tabs/ApiKeysTab";
import CloudServicesTab from "./tabs/CloudServicesTab";
import LlmTab from "./tabs/LlmTab";
import ModelsTab from "./tabs/ModelsTab";
import OrganizationTab from "./tabs/OrganizationTab";
import PlatformTab from "./tabs/PlatformTab";
import ProfileTab from "./tabs/ProfileTab";
import TelephonyTab from "./tabs/TelephonyTab";
import UsageTab from "./tabs/UsageTab";
import VoiceProviderTab from "./tabs/VoiceProviderTab";
import WebhookAuthTab from "./tabs/WebhookAuthTab";

type TabId =
  | "profile"
  | "organization"
  | "voice-provider"
  | "llm"
  | "telephony"
  | "models"
  | "webhook-auth"
  | "api-keys"
  | "cloud-services"
  | "platform"
  | "usage-billing";

const ALL_TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: "profile", label: "Profile" },
  { id: "organization", label: "Organization" },
  { id: "voice-provider", label: "Voice provider" },
  { id: "llm", label: "LLM" },
  { id: "telephony", label: "Telephony" },
  { id: "models", label: "Models" },
  { id: "webhook-auth", label: "Webhook auth" },
  { id: "api-keys", label: "API keys" },
  { id: "cloud-services", label: "Cloud services" },
  { id: "platform", label: "Platform" },
  { id: "usage-billing", label: "Usage & billing" },
];

const DEFAULT_TAB: TabId = "profile";

export default function SettingsTabs() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { config } = useAppConfig();

  // OSS deployments don't have managed cloud services — gate the Cloud
  // services tab on the same `deploymentMode` signal the legacy /api-keys
  // page already used. There is no separate MANAGED_KEYS_ENABLED env var.
  const isOSS = config?.deploymentMode === "oss";

  const visibleTabs = useMemo(
    () => ALL_TABS.filter((t) => !(t.id === "cloud-services" && isOSS)),
    [isOSS],
  );

  const requestedTab = (searchParams.get("tab") as TabId | null) ?? DEFAULT_TAB;
  const activeTab = visibleTabs.some((t) => t.id === requestedTab)
    ? requestedTab
    : DEFAULT_TAB;

  const onTabChange = useCallback(
    (newTab: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", newTab);
      router.push(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  return (
    <Tabs
      value={activeTab}
      onValueChange={onTabChange}
      orientation="vertical"
      className="flex w-full flex-col gap-6 md:flex-row"
    >
      <TabsList className="h-auto w-full flex-shrink-0 flex-col items-stretch gap-1 bg-transparent p-0 md:w-56">
        {visibleTabs.map((t) => (
          <TabsTrigger
            key={t.id}
            value={t.id}
            className="w-full justify-start data-[state=active]:bg-accent data-[state=active]:text-accent-foreground"
          >
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>

      <div className="min-w-0 flex-1">
        {visibleTabs.map((t) =>
          activeTab === t.id ? (
            <TabsContent
              key={t.id}
              value={t.id}
              className="mt-0 focus-visible:outline-none"
            >
              {renderTab(t.id)}
            </TabsContent>
          ) : null,
        )}
      </div>
    </Tabs>
  );
}

function renderTab(id: TabId) {
  switch (id) {
    case "profile":
      return <ProfileTab />;
    case "organization":
      return <OrganizationTab />;
    case "voice-provider":
      return <VoiceProviderTab />;
    case "llm":
      return <LlmTab />;
    case "telephony":
      return <TelephonyTab />;
    case "models":
      return <ModelsTab />;
    case "webhook-auth":
      return <WebhookAuthTab />;
    case "api-keys":
      return <ApiKeysTab />;
    case "cloud-services":
      return <CloudServicesTab />;
    case "platform":
      return <PlatformTab />;
    case "usage-billing":
      return <UsageTab />;
  }
}
