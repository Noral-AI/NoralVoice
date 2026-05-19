"use client";

import { Copy, Eye, EyeOff, Key, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  archiveApiKeyApiV1UserApiKeysApiKeyIdDelete,
  createApiKeyApiV1UserApiKeysPost,
  getApiKeysApiV1UserApiKeysGet,
  reactivateApiKeyApiV1UserApiKeysApiKeyIdReactivatePut,
} from "@/client/sdk.gen";
import type { ApiKeyResponse, CreateApiKeyResponse } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

function formatDate(dateString: string | null) {
  if (!dateString) return "Never";
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ApiKeysTab() {
  const { user, getAccessToken, redirectToLogin, loading } = useAuth();

  const [apiKeys, setApiKeys] = useState<ApiKeyResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<CreateApiKeyResponse | null>(null);
  const [showCreatedKeyDialog, setShowCreatedKeyDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) redirectToLogin();
  }, [loading, user, redirectToLogin]);

  const fetchApiKeys = useCallback(async () => {
    if (loading || !user) return;
    try {
      setIsLoading(true);
      setError(null);
      const accessToken = await getAccessToken();
      const response = await getApiKeysApiV1UserApiKeysGet({
        query: { include_archived: showArchived },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.data) setApiKeys(response.data);
    } catch (err) {
      setError("Failed to fetch API keys");
      console.error("Error fetching API keys:", err);
    } finally {
      setIsLoading(false);
    }
  }, [loading, user, getAccessToken, showArchived]);

  useEffect(() => {
    fetchApiKeys();
  }, [fetchApiKeys]);

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) {
      setError("Please enter a name for the API key");
      return;
    }
    try {
      setError(null);
      const accessToken = await getAccessToken();
      const response = await createApiKeyApiV1UserApiKeysPost({
        body: { name: newKeyName },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.data) {
        setCreatedKey(response.data);
        setIsCreateDialogOpen(false);
        setShowCreatedKeyDialog(true);
        setNewKeyName("");
        fetchApiKeys();
      }
    } catch (err) {
      setError("Failed to create API key");
      console.error("Error creating API key:", err);
    }
  };

  const handleArchiveKey = async (keyId: number) => {
    try {
      setError(null);
      const accessToken = await getAccessToken();
      await archiveApiKeyApiV1UserApiKeysApiKeyIdDelete({
        path: { api_key_id: keyId },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      fetchApiKeys();
    } catch (err) {
      setError("Failed to archive API key");
      console.error("Error archiving API key:", err);
    }
  };

  const handleReactivateKey = async (keyId: number) => {
    try {
      setError(null);
      const accessToken = await getAccessToken();
      await reactivateApiKeyApiV1UserApiKeysApiKeyIdReactivatePut({
        path: { api_key_id: keyId },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      fetchApiKeys();
    } catch (err) {
      setError("Failed to reactivate API key");
      console.error("Error reactivating API key:", err);
    }
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      console.error("Failed to copy to clipboard:", err);
    }
  };

  if (loading || !user) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">API keys</h2>
        <p className="text-muted-foreground">
          Create and manage API keys for programmatic access to your NoralVoice
          organization.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>API Keys</CardTitle>
              <CardDescription>
                Create and manage API keys for your organization.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowArchived(!showArchived)}>
                {showArchived ? <Eye className="mr-2 h-4 w-4" /> : <EyeOff className="mr-2 h-4 w-4" />}
                {showArchived ? "Hide" : "Show"} Archived
              </Button>
              <Button onClick={() => setIsCreateDialogOpen(true)} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Create New Key
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border p-4">
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                  <Skeleton className="h-8 w-20" />
                </div>
              ))}
            </div>
          ) : apiKeys.length === 0 ? (
            <div className="py-12 text-center">
              <Key className="mx-auto mb-4 h-12 w-12 text-muted-foreground" />
              <p className="mb-4 text-muted-foreground">No API keys found</p>
              <Button onClick={() => setIsCreateDialogOpen(true)}>Create Your First API Key</Button>
            </div>
          ) : (
            <div className="space-y-4">
              {apiKeys.map((key) => (
                <div
                  key={key.id}
                  className={`flex items-center justify-between rounded-lg border p-4 ${
                    key.archived_at ? "bg-muted opacity-60" : "bg-card"
                  }`}
                >
                  <div className="flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="font-medium">{key.name}</span>
                      {key.archived_at ? (
                        <Badge variant="secondary">Archived</Badge>
                      ) : key.is_active ? (
                        <Badge variant="default">Active</Badge>
                      ) : (
                        <Badge variant="destructive">Inactive</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <span className="rounded bg-muted px-2 py-1 font-mono">{key.key_prefix}...</span>
                      <span className="text-xs text-muted-foreground/70">
                        (Full key hidden for security)
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      Created: {formatDate(key.created_at)} • Last used:{" "}
                      {formatDate(key.last_used_at ?? null)}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {key.archived_at ? (
                      <Button variant="outline" size="sm" onClick={() => handleReactivateKey(key.id)}>
                        <RefreshCw className="mr-1 h-4 w-4" />
                        Reactivate
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleArchiveKey(key.id)}
                        className="text-destructive hover:text-destructive/90"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/10 p-4">
        <p className="text-sm text-yellow-600 dark:text-yellow-500">
          <strong>Important:</strong> Keep your API keys secure. Never share them publicly
          or commit them to version control. API keys provide full access to your
          organization&apos;s resources.
        </p>
      </div>

      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New API Key</DialogTitle>
            <DialogDescription>
              Enter a descriptive name for your API key to help you identify it later.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Key Name</Label>
              <Input
                id="name"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="e.g., Production Server, Development Environment"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateKey}>Create Key</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showCreatedKeyDialog} onOpenChange={setShowCreatedKeyDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API Key Created Successfully</DialogTitle>
            <DialogDescription>
              Make sure to copy your API key now. You won&apos;t be able to see it again!
            </DialogDescription>
          </DialogHeader>
          {createdKey && (
            <div className="space-y-4">
              <div className="rounded-lg bg-muted p-4">
                <p className="mb-2 text-sm text-muted-foreground">Your API Key:</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-background p-2 font-mono text-sm">
                    {createdKey.api_key}
                  </code>
                  <Button size="sm" variant="outline" onClick={() => copyToClipboard(createdKey.api_key)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/10 p-4">
                <p className="text-sm text-yellow-600 dark:text-yellow-500">
                  Store this key securely. It will only be shown once and cannot be retrieved later.
                </p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              onClick={() => {
                setShowCreatedKeyDialog(false);
                setCreatedKey(null);
              }}
            >
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
