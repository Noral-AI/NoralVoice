"use client";

import { ChevronRight, MessageSquare, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { listTestSessionsApiV1LooptalkTestSessionsGet } from "@/client/sdk.gen";
import type { TestSessionResponse } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

import LoopTalkLayout from "./LoopTalkLayout";

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  const normalized = status.toLowerCase();
  if (normalized === "running" || normalized === "started" || normalized === "active") return "default";
  if (normalized === "completed" || normalized === "done") return "secondary";
  if (normalized === "failed" || normalized === "errored") return "destructive";
  return "outline";
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function LoopTalkListPage() {
  const { user, loading: authLoading } = useAuth();
  const [sessions, setSessions] = useState<TestSessionResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    if (authLoading || !user) return;
    setLoading(true);
    try {
      const res = await listTestSessionsApiV1LooptalkTestSessionsGet();
      if (res.error) throw new Error("Failed to load test sessions");
      const sorted = (res.data ?? [])
        .slice()
        .sort((a, b) => b.id - a.id);
      setSessions(sorted);
      setError(null);
    } catch (err) {
      logger.error(`LoopTalk listing fetch failed: ${err}`);
      setError(err instanceof Error ? err.message : "Failed to load test sessions");
    } finally {
      setLoading(false);
    }
  }, [authLoading, user]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  return (
    <LoopTalkLayout>
      <div className="container mx-auto space-y-6 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="mb-2 text-3xl font-bold">LoopTalk</h1>
            <p className="text-muted-foreground">
              Voice agents talking to each other. Run a test session to generate a
              synthetic conversation between an actor agent and an adversary agent.
            </p>
          </div>
          <Button
            onClick={() => toast.info("Start a new session from a workflow's detail page.")}
            variant="outline"
          >
            <Plus className="mr-2 h-4 w-4" /> Start new session
          </Button>
        </div>

        {loading ? (
          <div className="grid gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : error ? (
          <Card>
            <CardHeader>
              <CardTitle>Could not load sessions</CardTitle>
              <CardDescription>{error}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={fetchSessions}>Try again</Button>
            </CardContent>
          </Card>
        ) : !sessions || sessions.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>No test sessions yet</CardTitle>
              <CardDescription>
                Pair two workflows into an actor/adversary test session to capture
                synthetic conversation transcripts.
              </CardDescription>
            </CardHeader>
            <CardContent className="text-center text-muted-foreground">
              <MessageSquare className="mx-auto mb-4 h-12 w-12" />
              <p>
                LoopTalk sessions are started from a workflow&apos;s detail page. Once
                you start a session it will appear in this list.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3">
            {sessions.map((session) => (
              <Card key={session.id}>
                <Link
                  href={`/looptalk/${session.id}`}
                  className="flex items-center gap-4 p-4 hover:bg-accent/30"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{session.name || `Session #${session.id}`}</span>
                      <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
                      {session.load_test_group_id && (
                        <Badge variant="outline">Load test</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Session #{session.id} • Actor workflow {session.actor_workflow_id} ·
                      Adversary workflow {session.adversary_workflow_id}
                    </div>
                    {("created_at" in session) && (
                      <div className="text-xs text-muted-foreground">
                        Created {formatTimestamp((session as { created_at?: string }).created_at)}
                      </div>
                    )}
                  </div>
                  <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
                </Link>
              </Card>
            ))}
          </div>
        )}
      </div>
    </LoopTalkLayout>
  );
}
