"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { LocalUser } from "@/lib/auth";
import { useAuth } from "@/lib/auth";

export default function ProfileTab() {
  const { user, loading, provider } = useAuth();

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const email =
    (user as LocalUser | undefined)?.email ||
    (user as { primaryEmail?: string } | undefined)?.primaryEmail ||
    null;
  const displayName = user?.displayName ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Profile</h2>
        <p className="text-muted-foreground">Your account details.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>
            Signed in via the {provider === "stack" ? "Stack" : "local"} auth provider.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[10rem_1fr]">
            <span className="text-sm font-medium text-muted-foreground">Display name</span>
            <span className="text-sm">{displayName || <em className="text-muted-foreground">Not set</em>}</span>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[10rem_1fr]">
            <span className="text-sm font-medium text-muted-foreground">Email</span>
            <span className="text-sm">{email || <em className="text-muted-foreground">Not available</em>}</span>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[10rem_1fr]">
            <span className="text-sm font-medium text-muted-foreground">Auth provider</span>
            <span className="text-sm capitalize">{provider}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
