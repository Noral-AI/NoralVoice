import { Suspense } from "react";

import SettingsTabs from "@/components/settings/SettingsTabs";
import { Skeleton } from "@/components/ui/skeleton";

export default function SettingsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">
            Manage your account, organization, integrations, models, telephony, and
            platform configuration.
          </p>
        </div>
        <Suspense fallback={<Skeleton className="h-96 w-full" />}>
          <SettingsTabs />
        </Suspense>
      </div>
    </div>
  );
}
