"use client";

import { AlertCircle, Check, Cpu, Loader2 } from "lucide-react";
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
 * Platform-level LLM selection.
 *
 * One choice for the organization, inherited by every agent it creates — not a
 * per-agent setting. Hosted models need no API key; ElevenLabs runs them and
 * bills through the existing account. Only a custom endpoint needs credentials,
 * and that path is capped.
 */

const CUSTOM_LLM = "custom-llm";

interface LLMOption {
  identifier: string;
  label: string;
  provider: string;
  note: string;
}

interface LLMSelection {
  identifier: string;
  is_default: boolean;
  is_known: boolean;
  custom_url: string | null;
  custom_model_id: string | null;
}

export default function LlmTab() {
  const { user, loading: authLoading } = useAuth();

  const [options, setOptions] = useState<LLMOption[]>([]);
  const [selection, setSelection] = useState<LLMSelection | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [customUrl, setCustomUrl] = useState("");
  const [customModelId, setCustomModelId] = useState("");

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const hasFetched = useRef(false);

  const load = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [cat, sel] = await Promise.all([
        client.get({ url: "/api/v1/llm/catalogue" }),
        client.get({ url: "/api/v1/llm/selection" }),
      ]);
      if (cat.data) setOptions(cat.data as LLMOption[]);
      if (sel.data) {
        const current = sel.data as LLMSelection;
        setSelection(current);
        setChosen(current.identifier);
        setCustomUrl(current.custom_url ?? "");
        setCustomModelId(current.custom_model_id ?? "");
      }
    } catch (err) {
      setError("Could not load LLM settings.");
      console.error("Error loading LLM settings:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void load();
  }, [authLoading, user, load]);

  const save = useCallback(async () => {
    try {
      setIsSaving(true);
      setError(null);
      setNotice(null);

      const response = await client.put({
        url: "/api/v1/llm/selection",
        body: {
          identifier: chosen,
          custom_url: chosen === CUSTOM_LLM ? customUrl.trim() : null,
          custom_model_id:
            chosen === CUSTOM_LLM ? customModelId.trim() || null : null,
        },
      });

      if (response.data) setSelection(response.data as LLMSelection);
      setNotice("Saved. New agents will use this model.");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail ?? "Could not save the LLM selection.");
      console.error("Error saving LLM selection:", err);
    } finally {
      setIsSaving(false);
    }
  }, [chosen, customUrl, customModelId]);

  const grouped = options.reduce<Record<string, LLMOption[]>>((acc, option) => {
    (acc[option.provider] ??= []).push(option);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">LLM</h2>
        <p className="text-muted-foreground">
          Which language model this organization&apos;s voice agents run on. One
          choice for the platform — every agent inherits it.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <Cpu className="h-4 w-4" />
                Active model
              </CardTitle>
              <CardDescription>
                Hosted models need no API key — ElevenLabs runs them and bills
                through your existing account. Switching between them is free.
              </CardDescription>
            </div>
            {selection && !isLoading && (
              <Badge variant={selection.is_default ? "secondary" : "default"}>
                {selection.is_default ? "Using default" : selection.identifier}
              </Badge>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <>
              {Object.entries(grouped).map(([provider, items]) => (
                <div key={provider} className="space-y-2">
                  <h3 className="text-sm font-medium text-muted-foreground">
                    {provider}
                  </h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {items.map((option) => (
                      <button
                        key={option.identifier}
                        onClick={() => setChosen(option.identifier)}
                        className={`rounded-md border p-3 text-left transition-colors hover:bg-accent ${
                          chosen === option.identifier
                            ? "border-primary bg-accent"
                            : ""
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">
                            {option.label}
                          </span>
                          {chosen === option.identifier && (
                            <Check className="h-4 w-4 flex-shrink-0" />
                          )}
                        </div>
                        <p className="font-mono text-xs text-muted-foreground">
                          {option.identifier}
                        </p>
                        {option.note && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {option.note}
                          </p>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              {chosen === CUSTOM_LLM && (
                <div className="space-y-4 rounded-md border border-amber-500/50 p-4">
                  <p className="text-sm text-muted-foreground">
                    A custom endpoint runs inference inside the call path. It is
                    capped at two organizations — a third is a decision to
                    revisit, not a setting to change.
                  </p>
                  <div className="space-y-2">
                    <Label htmlFor="custom-url">Endpoint URL</Label>
                    <Input
                      id="custom-url"
                      value={customUrl}
                      onChange={(e) => setCustomUrl(e.target.value)}
                      placeholder="https://your-endpoint/v1"
                      className="font-mono text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="custom-model">Model id (optional)</Label>
                    <Input
                      id="custom-model"
                      value={customModelId}
                      onChange={(e) => setCustomModelId(e.target.value)}
                      placeholder="my-model"
                      className="font-mono text-sm"
                    />
                  </div>
                </div>
              )}

              {error && (
                <p className="flex items-start gap-2 text-sm text-destructive">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  {error}
                </p>
              )}
              {notice && (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Check className="h-4 w-4" />
                  {notice}
                </p>
              )}

              <div className="flex items-center gap-3 border-t pt-4">
                <Button
                  onClick={save}
                  disabled={isSaving || !chosen || chosen === selection?.identifier}
                >
                  {isSaving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Save selection"
                  )}
                </Button>
                <p className="text-xs text-muted-foreground">
                  Applies to agents created from here on. Existing agents keep
                  the model they were created with.
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
