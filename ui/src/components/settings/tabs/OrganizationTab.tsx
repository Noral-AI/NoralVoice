"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// PR-A note: /organizations/current with org name + members + branding does
// not exist as a backend endpoint today. Rather than ship a new backend
// inside the settings-collapse PR, this tab renders a placeholder. A
// follow-up adds a real org-details endpoint and wires this surface up.

export default function OrganizationTab() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Organization</h2>
        <p className="text-muted-foreground">Organization name, members, and branding.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Coming soon</CardTitle>
          <CardDescription>
            Members and branding management for your organization will live here. For
            now, organization-level controls are managed via the Telephony tab (for
            providers) and the Platform tab (for telemetry).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Need to manage members today? Contact your administrator.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
