"use client";

import { AlertCircle, CheckCircle2, KeyRound, Loader2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

/**
 * ElevenLabs credential management.
 *
 * The key is entered here and nowhere else — not in env, not in code. The API
 * never returns it once written, so this component can show which key is
 * installed (last four, when it was rotated) but can never redisplay the key
 * itself. That is deliberate: there is no "reveal" affordance to build, because
 * there is nothing on the server capable of revealing it.
 */

const PROVIDER = "elevenlabs";

interface ProviderCredential {
  provider: string;
  configured: boolean;
  last_four: string | null;
  rotated_at: string | null;
  created_at: string | null;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function VoiceProviderTab() {
  const { user, loading: authLoading } = useAuth();

  const [credential, setCredential] = useState<ProviderCredential | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRevoking, setIsRevoking] = useState(false);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const hasFetched = useRef(false);

  const fetchCredential = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await client.get({
        url: `/api/v1/credentials/providers/${PROVIDER}`,
      });
      if (response.data) {
        setCredential(response.data as ProviderCredential);
      }
    } catch (err) {
      setError("Could not load the ElevenLabs credential status.");
      console.error("Error fetching provider credential:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // The auth interceptor only attaches a Bearer token once auth has loaded;
  // fetching earlier sends an unauthenticated request that silently fails.
  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void fetchCredential();
  }, [authLoading, user, fetchCredential]);

  const handleSave = useCallback(async () => {
    const trimmed = secret.trim();
    if (!trimmed) {
      setError("Enter a key before saving.");
      return;
    }

    try {
      setIsSaving(true);
      setError(null);
      setNotice(null);

      const wasConfigured = credential?.configured ?? false;

      const response = await client.put({
        url: `/api/v1/credentials/providers/${PROVIDER}`,
        body: { secret: trimmed },
      });

      if (response.data) {
        setCredential(response.data as ProviderCredential);
      }
      // Clear immediately — the key should not linger in a DOM input once it
      // has been stored.
      setSecret("");
      setNotice(wasConfigured ? "Key rotated." : "Key saved.");
    } catch (err) {
      setError("Could not save the key. Check that it is correct and try again.");
      console.error("Error saving provider credential:", err);
    } finally {
      setIsSaving(false);
    }
  }, [secret, credential]);

  const handleRevoke = useCallback(async () => {
    try {
      setIsRevoking(true);
      setError(null);
      setNotice(null);

      await client.delete({
        url: `/api/v1/credentials/providers/${PROVIDER}`,
      });

      setCredential({
        provider: PROVIDER,
        configured: false,
        last_four: null,
        rotated_at: null,
        created_at: null,
      });
      setNotice("Key revoked. Voice features will stop working until a new key is saved.");
    } catch (err) {
      setError("Could not revoke the key.");
      console.error("Error revoking provider credential:", err);
    } finally {
      setIsRevoking(false);
    }
  }, []);

  const isConfigured = credential?.configured ?? false;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Voice provider</h2>
        <p className="text-muted-foreground">
          The ElevenLabs API key used to create and run this organization&apos;s voice
          agents.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="h-4 w-4" />
                ElevenLabs
              </CardTitle>
              <CardDescription>
                Stored encrypted. Once saved, the key cannot be displayed again — only
                replaced or revoked.
              </CardDescription>
            </div>
            {!isLoading &&
              (isConfigured ? (
                <Badge variant="default" className="flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  Configured
                </Badge>
              ) : (
                <Badge variant="secondary">Not configured</Badge>
              ))}
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : (
            <>
              {isConfigured && (
                <dl className="grid grid-cols-2 gap-4 rounded-md border p-4 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-muted-foreground">Key</dt>
                    <dd className="font-mono">
                      {credential?.last_four ? `••••${credential.last_four}` : "••••"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Added</dt>
                    <dd>{formatDate(credential?.created_at ?? null)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Last rotated</dt>
                    <dd>{formatDate(credential?.rotated_at ?? null)}</dd>
                  </div>
                </dl>
              )}

              <div className="space-y-2">
                <Label htmlFor="elevenlabs-key">
                  {isConfigured ? "Replace key" : "API key"}
                </Label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    id="elevenlabs-key"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="sk_..."
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                    disabled={isSaving}
                    className="font-mono"
                  />
                  <Button
                    onClick={handleSave}
                    disabled={isSaving || !secret.trim()}
                    className="sm:w-32"
                  >
                    {isSaving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : isConfigured ? (
                      "Rotate"
                    ) : (
                      "Save"
                    )}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Find this in your ElevenLabs dashboard under Profile → API Keys.
                </p>
              </div>

              {error && (
                <p className="flex items-center gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </p>
              )}
              {notice && (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-4 w-4" />
                  {notice}
                </p>
              )}

              {isConfigured && (
                <div className="flex items-center justify-between border-t pt-4">
                  <div className="text-sm">
                    <p className="font-medium">Revoke this key</p>
                    <p className="text-muted-foreground">
                      Voice agents stop working until a new key is saved.
                    </p>
                  </div>
                  <Button
                    variant="destructive"
                    onClick={handleRevoke}
                    disabled={isRevoking}
                  >
                    {isRevoking ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Revoke
                      </>
                    )}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
