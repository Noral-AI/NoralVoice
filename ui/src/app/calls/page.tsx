"use client";

import { AlertCircle, Clock, Phone } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

/** Calls dashboard — transcript, extracted fields and recording per call. */

interface CallSummary {
  run_id: number;
  conversation_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  duration_seconds: number | null;
  sentiment: string | null;
  created_at: string | null;
  has_recording: boolean;
}

interface TranscriptTurn {
  role?: string;
  message?: string;
}

interface CallDetail extends CallSummary {
  transcript: TranscriptTurn[] | null;
  extracted_data: Record<string, unknown>;
  recording_url: string | null;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Renders whatever shape the extractor produced without assuming one. */
function extractedValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object" && "value" in (value as Record<string, unknown>)) {
    return String((value as Record<string, unknown>).value ?? "—");
  }
  return String(value);
}

export default function CallsPage() {
  const { user, loading: authLoading } = useAuth();

  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [selected, setSelected] = useState<CallDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const hasFetched = useRef(false);

  const fetchCalls = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await client.get({ url: "/api/v1/calls/" });
      if (response.data) {
        setCalls((response.data as { calls: CallSummary[] }).calls);
      }
    } catch (err) {
      setError("Could not load calls.");
      console.error("Error loading calls:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void fetchCalls();
  }, [authLoading, user, fetchCalls]);

  const openCall = useCallback(async (runId: number) => {
    try {
      setError(null);
      const response = await client.get({ url: `/api/v1/calls/${runId}` });
      if (response.data) setSelected(response.data as CallDetail);
    } catch (err) {
      setError("Could not open that call.");
      console.error("Error opening call:", err);
    }
  }, []);

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Calls</h1>
        <p className="text-muted-foreground">
          Every call handled by this client&apos;s agents, with transcript and
          extracted fields.
        </p>
      </div>

      {error && (
        <p className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4" />
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {isLoading ? (
              <>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </>
            ) : calls.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">
                No calls yet. They appear here within seconds of completing.
              </p>
            ) : (
              calls.map((call) => (
                <button
                  key={call.run_id}
                  onClick={() => openCall(call.run_id)}
                  className={`flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left hover:bg-accent ${
                    selected?.run_id === call.run_id ? "bg-accent" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {call.agent_name ?? "Unknown agent"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatDate(call.created_at)}
                    </p>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    {call.sentiment && (
                      <Badge variant="secondary" className="text-xs">
                        {call.sentiment}
                      </Badge>
                    )}
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      {formatDuration(call.duration_seconds)}
                    </span>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {selected ? (selected.agent_name ?? "Call") : "Select a call"}
            </CardTitle>
            {selected && (
              <CardDescription>
                {formatDate(selected.created_at)} ·{" "}
                {formatDuration(selected.duration_seconds)}
              </CardDescription>
            )}
          </CardHeader>

          {selected && (
            <CardContent className="space-y-6">
              {selected.recording_url ? (
                <audio controls src={selected.recording_url} className="w-full">
                  Your browser does not support audio playback.
                </audio>
              ) : (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Phone className="h-4 w-4" />
                  No recording stored for this call.
                </p>
              )}

              {Object.keys(selected.extracted_data ?? {}).length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Extracted fields</h3>
                  <dl className="grid gap-2 rounded-md border p-4 text-sm sm:grid-cols-2">
                    {Object.entries(selected.extracted_data).map(([key, value]) => (
                      <div key={key}>
                        <dt className="text-muted-foreground">{key}</dt>
                        <dd className="font-medium">{extractedValue(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}

              <div>
                <h3 className="mb-2 text-sm font-medium">Transcript</h3>
                {selected.transcript && selected.transcript.length > 0 ? (
                  <div className="max-h-[28rem] space-y-3 overflow-y-auto rounded-md border p-4">
                    {selected.transcript.map((turn, i) => (
                      <div key={i} className="text-sm">
                        <span className="font-medium capitalize text-muted-foreground">
                          {turn.role ?? "unknown"}:{" "}
                        </span>
                        <span>{turn.message}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No transcript stored for this call.
                  </p>
                )}
              </div>
            </CardContent>
          )}
        </Card>
      </div>
    </div>
  );
}
