"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// PR-A note: The /credentials backend has GET/POST/PUT/DELETE today but
// no UI. Surfacing it with CRUD + secret reveal is a non-trivial UI
// addition that belongs in a follow-up to PR-A. Until then, this tab
// is a placeholder pointing operators at the API directly so the route
// is reachable from the new /settings surface.

export default function WebhookAuthTab() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Webhook auth</h2>
        <p className="text-muted-foreground">
          Reusable HTTP-auth credentials (basic, bearer, header, OAuth2) for outbound
          webhook destinations on your workflows.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Coming soon</CardTitle>
          <CardDescription>
            The credentials API (<code className="font-mono text-xs">/api/v1/credentials</code>)
            is live; the UI lands in a follow-up to the settings-collapse PR.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            To manage webhook credentials today, use the API directly. See the docs
            for the request shape.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
