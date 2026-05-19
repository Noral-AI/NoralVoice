"use client";

import { Copy, Eye, EyeOff, Key, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  archiveServiceKeyApiV1UserServiceKeysServiceKeyIdDelete,
  createServiceKeyApiV1UserServiceKeysPost,
  getServiceKeysApiV1UserServiceKeysGet,
} from "@/client/sdk.gen";
import type { CreateServiceKeyResponse, ServiceKeyResponse } from "@/client/types.gen";
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
import { useAppConfig } from "@/context/AppConfigContext";
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

export default function CloudServicesTab() {
  const { user, getAccessToken, redirectToLogin, loading } = useAuth();
  const { config } = useAppConfig();
  const isOSS = config?.deploymentMode === "oss";

  const [serviceKeys, setServiceKeys] = useState<ServiceKeyResponse[]>([]);
  const [isServiceKeysLoading, setIsServiceKeysLoading] = useState(true);
  const [showServiceArchived, setShowServiceArchived] = useState(false);
  const [isCreateServiceDialogOpen, setIsCreateServiceDialogOpen] = useState(false);
  const [newServiceKeyName, setNewServiceKeyName] = useState("");
  const [createdServiceKey, setCreatedServiceKey] = useState<CreateServiceKeyResponse | null>(
    null,
  );
  const [showCreatedServiceKeyDialog, setShowCreatedServiceKeyDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) redirectToLogin();
  }, [loading, user, redirectToLogin]);

  const fetchServiceKeys = useCallback(async () => {
    if (loading || !user) return;
    try {
      setIsServiceKeysLoading(true);
      setError(null);
      const accessToken = await getAccessToken();
      const response = await getServiceKeysApiV1UserServiceKeysGet({
        query: { include_archived: showServiceArchived },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.data) setServiceKeys(response.data);
    } catch (err) {
      setError("Failed to fetch service keys");
      console.error("Error fetching service keys:", err);
    } finally {
      setIsServiceKeysLoading(false);
    }
  }, [loading, user, getAccessToken, showServiceArchived]);

  useEffect(() => {
    fetchServiceKeys();
  }, [fetchServiceKeys]);

  const handleCreateServiceKey = async () => {
    if (!newServiceKeyName.trim()) {
      setError("Please enter a name for the service key");
      return;
    }
    try {
      setError(null);
      const accessToken = await getAccessToken();
      const response = await createServiceKeyApiV1UserServiceKeysPost({
        body: { name: newServiceKeyName, expires_in_days: 90 },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (response.data) {
        setCreatedServiceKey(response.data);
        setIsCreateServiceDialogOpen(false);
        setShowCreatedServiceKeyDialog(true);
        setNewServiceKeyName("");
        fetchServiceKeys();
      }
    } catch (err) {
      setError("Failed to create service key");
      console.error("Error creating service key:", err);
    }
  };

  const handleArchiveServiceKey = async (keyId: string) => {
    try {
      setError(null);
      const accessToken = await getAccessToken();
      await archiveServiceKeyApiV1UserServiceKeysServiceKeyIdDelete({
        path: { service_key_id: keyId },
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      fetchServiceKeys();
    } catch (err) {
      setError("Failed to archive service key");
      console.error("Error archiving service key:", err);
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

  const activeServiceKeys = serviceKeys.filter((k) => !k.archived_at);
  const canCreateServiceKey = !isOSS || activeServiceKeys.length === 0;
  const showServiceKeyArchiveControls = !isOSS;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Cloud services</h2>
        <p className="text-muted-foreground">
          Manage service keys for accessing managed AI services (LLM, TTS, STT) hosted
          by NoralAI.
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
              <CardTitle>Model Service Keys</CardTitle>
              <CardDescription>
                Manage service keys for accessing AI services (LLM, TTS, STT).
              </CardDescription>
            </div>
            <div className="flex gap-2">
              {showServiceKeyArchiveControls && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowServiceArchived(!showServiceArchived)}
                >
                  {showServiceArchived ? <Eye className="mr-2 h-4 w-4" /> : <EyeOff className="mr-2 h-4 w-4" />}
                  {showServiceArchived ? "Hide" : "Show"} Archived
                </Button>
              )}
              {canCreateServiceKey ? (
                <Button onClick={() => setIsCreateServiceDialogOpen(true)} size="sm">
                  <Plus className="mr-2 h-4 w-4" />
                  Create Service Key
                </Button>
              ) : (
                <span className="text-sm text-muted-foreground">
                  Contact your NoralAI admin to generate additional service keys.
                </span>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isServiceKeysLoading ? (
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border p-4">
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                  <Skeleton className="h-8 w-20" />
                </div>
              ))}
            </div>
          ) : serviceKeys.length === 0 ? (
            <div className="py-12 text-center">
              <Key className="mx-auto mb-4 h-12 w-12 text-muted-foreground" />
              <p className="mb-4 text-muted-foreground">No service keys found</p>
              {canCreateServiceKey && (
                <Button onClick={() => setIsCreateServiceDialogOpen(true)}>
                  Create Your First Service Key
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {serviceKeys.map((key) => (
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
                      {key.expires_at && new Date(key.expires_at) > new Date() && (
                        <Badge variant="outline">Expires: {formatDate(key.expires_at)}</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <span className="rounded bg-muted px-2 py-1 font-mono">
                        {key.key_prefix}...
                      </span>
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
                    {!key.archived_at && showServiceKeyArchiveControls && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleArchiveServiceKey(String(key.id))}
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

      <Dialog open={isCreateServiceDialogOpen} onOpenChange={setIsCreateServiceDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Service Key</DialogTitle>
            <DialogDescription>
              Create a service key to access AI services (LLM, TTS, STT).
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="service-name">Service Key Name</Label>
              <Input
                id="service-name"
                value={newServiceKeyName}
                onChange={(e) => setNewServiceKeyName(e.target.value)}
                placeholder="e.g., Production AI Services, Development LLM Access"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateServiceDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateServiceKey}>Create Service Key</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showCreatedServiceKeyDialog} onOpenChange={setShowCreatedServiceKeyDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Service Key Created Successfully</DialogTitle>
            <DialogDescription>
              Make sure to copy your service key now. You won&apos;t be able to see it again!
            </DialogDescription>
          </DialogHeader>
          {createdServiceKey && (
            <div className="space-y-4">
              <div className="rounded-lg bg-muted p-4">
                <p className="mb-2 text-sm text-muted-foreground">Your Service Key:</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-background p-2 font-mono text-sm">
                    {createdServiceKey.service_key}
                  </code>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => copyToClipboard(createdServiceKey.service_key)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-4">
                <p className="text-sm text-blue-600 dark:text-blue-500">
                  This key provides access to AI services including LLM, Text-to-Speech,
                  and Speech-to-Text.
                  {createdServiceKey.expires_at && (
                    <span className="mt-1 block">
                      Expires on: {formatDate(createdServiceKey.expires_at)}
                    </span>
                  )}
                </p>
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
                setShowCreatedServiceKeyDialog(false);
                setCreatedServiceKey(null);
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
