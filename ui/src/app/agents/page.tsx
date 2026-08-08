"use client";

import { AlertCircle, Bot, Loader2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { client } from "@/client/client.gen";
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
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/lib/auth";

/**
 * Agent list and editor.
 *
 * The list comes from our own records rather than from ElevenLabs: the vendor's
 * agent list is workspace-wide, so on a shared workspace it would show every
 * client's agents. Ownership is a property of our database, not theirs.
 */

interface AgentSummary {
  workflow_id: number;
  agent_id: string | null;
  name: string;
}

interface AgentDetail {
  agent_id?: string;
  name?: string;
  conversation_config?: {
    agent?: {
      prompt?: { prompt?: string };
      first_message?: string;
      language?: string;
    };
    tts?: { voice_id?: string };
  };
}

/** True when the API says the organization has no ElevenLabs key yet. */
function isNotConfigured(status: number | undefined): boolean {
  return status === 409;
}

export default function AgentsPage() {
  const { user, loading: authLoading } = useAuth();

  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selected, setSelected] = useState<AgentDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [needsKey, setNeedsKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [firstMessage, setFirstMessage] = useState("");

  const hasFetched = useRef(false);

  const fetchAgents = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await client.get({ url: "/api/v1/agents/" });
      if (response.data) setAgents(response.data as AgentSummary[]);
    } catch (err) {
      setError("Could not load agents.");
      console.error("Error loading agents:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;
    void fetchAgents();
  }, [authLoading, user, fetchAgents]);

  const openAgent = useCallback(async (agentId: string) => {
    try {
      setError(null);
      setIsCreating(false);
      const response = await client.get({ url: `/api/v1/agents/${agentId}` });
      const detail = response.data as AgentDetail;
      setSelected(detail);
      setName(detail.name ?? "");
      setPrompt(detail.conversation_config?.agent?.prompt?.prompt ?? "");
      setFirstMessage(detail.conversation_config?.agent?.first_message ?? "");
    } catch (err) {
      setError("Could not open that agent.");
      console.error("Error opening agent:", err);
    }
  }, []);

  const startCreating = useCallback(() => {
    setIsCreating(true);
    setSelected(null);
    setName("");
    setPrompt("");
    setFirstMessage("");
    setError(null);
  }, []);

  const save = useCallback(async () => {
    if (!name.trim() || !prompt.trim()) {
      setError("A name and a prompt are required.");
      return;
    }

    try {
      setIsSaving(true);
      setError(null);
      setNeedsKey(false);

      if (isCreating) {
        await client.post({
          url: "/api/v1/agents/",
          body: {
            name: name.trim(),
            prompt: prompt.trim(),
            first_message: firstMessage.trim() || null,
          },
        });
      } else if (selected?.agent_id) {
        await client.patch({
          url: `/api/v1/agents/${selected.agent_id}`,
          body: {
            name: name.trim(),
            prompt: prompt.trim(),
            first_message: firstMessage.trim() || null,
          },
        });
      }

      setIsCreating(false);
      await fetchAgents();
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (isNotConfigured(status)) {
        setNeedsKey(true);
      } else {
        setError("Could not save the agent.");
      }
      console.error("Error saving agent:", err);
    } finally {
      setIsSaving(false);
    }
  }, [isCreating, selected, name, prompt, firstMessage, fetchAgents]);

  const remove = useCallback(async () => {
    if (!selected?.agent_id) return;
    try {
      setError(null);
      await client.delete({ url: `/api/v1/agents/${selected.agent_id}` });
      setSelected(null);
      await fetchAgents();
    } catch (err) {
      setError("Could not delete the agent.");
      console.error("Error deleting agent:", err);
    }
  }, [selected, fetchAgents]);

  const isEditing = isCreating || selected !== null;

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agents</h1>
          <p className="text-muted-foreground">
            Voice agents for this client, running on ElevenLabs.
          </p>
        </div>
        <Button onClick={startCreating}>
          <Plus className="mr-2 h-4 w-4" />
          New agent
        </Button>
      </div>

      {needsKey && (
        <Card className="border-amber-500/50">
          <CardHeader>
            <CardTitle className="text-base">No ElevenLabs key yet</CardTitle>
            <CardDescription>
              Add one under Settings → Voice provider, then come back.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-[280px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your agents</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {isLoading ? (
              <>
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </>
            ) : agents.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">
                No agents yet.
              </p>
            ) : (
              agents.map((agent) => (
                <button
                  key={agent.workflow_id}
                  onClick={() => agent.agent_id && openAgent(agent.agent_id)}
                  className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-accent ${
                    selected?.agent_id === agent.agent_id ? "bg-accent" : ""
                  }`}
                >
                  <Bot className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{agent.name}</span>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {isCreating ? "New agent" : selected ? "Edit agent" : "Select an agent"}
            </CardTitle>
            {!isEditing && (
              <CardDescription>
                Pick an agent on the left, or create one.
              </CardDescription>
            )}
          </CardHeader>

          {isEditing && (
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="agent-name">Name</Label>
                <Input
                  id="agent-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="After-hours reception"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="agent-first-message">First message</Label>
                <Input
                  id="agent-first-message"
                  value={firstMessage}
                  onChange={(e) => setFirstMessage(e.target.value)}
                  placeholder="Thanks for calling — how can I help?"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="agent-prompt">System prompt</Label>
                <Textarea
                  id="agent-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={12}
                  placeholder="You are a receptionist for…"
                  className="font-mono text-sm"
                />
              </div>

              {error && (
                <p className="flex items-center gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </p>
              )}

              <div className="flex items-center justify-between border-t pt-4">
                <Button onClick={save} disabled={isSaving}>
                  {isSaving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : isCreating ? (
                    "Create agent"
                  ) : (
                    "Save changes"
                  )}
                </Button>

                {selected && (
                  <Button variant="destructive" onClick={remove}>
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </Button>
                )}
              </div>
            </CardContent>
          )}
        </Card>
      </div>
    </div>
  );
}
