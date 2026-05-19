"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import CreateIntegrationButton from "@/app/integrations/CreateIntegrationButton";
import { getIntegrationsApiV1IntegrationGet } from "@/client/sdk.gen";
import type { IntegrationResponse } from "@/client/types.gen";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

function IntegrationsLoading() {
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div className="h-8 w-48 rounded bg-muted"></div>
        <div className="h-10 w-32 rounded bg-muted"></div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border border-border bg-card">
          <thead className="bg-muted">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Integration ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Channel
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Action
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Created At
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-card">
            {Array.from({ length: 5 }, (_, i) => (
              <tr key={i}>
                <td className="whitespace-nowrap px-6 py-4">
                  <div className="h-4 w-32 rounded bg-muted"></div>
                </td>
                <td className="whitespace-nowrap px-6 py-4">
                  <div className="h-4 w-24 rounded bg-muted"></div>
                </td>
                <td className="whitespace-nowrap px-6 py-4">
                  <div className="h-4 w-24 rounded bg-muted"></div>
                </td>
                <td className="whitespace-nowrap px-6 py-4">
                  <div className="h-4 w-24 rounded bg-muted"></div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function IntegrationsTab() {
  const { user, loading: authLoading } = useAuth();
  const hasFetched = useRef(false);
  const [integrations, setIntegrations] = useState<IntegrationResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !user || hasFetched.current) return;
    hasFetched.current = true;

    const fetchIntegrations = async () => {
      try {
        const response = await getIntegrationsApiV1IntegrationGet({});

        const integrationData = response.data
          ? Array.isArray(response.data)
            ? response.data
            : [response.data]
          : [];
        const sorted = [...integrationData].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        );
        setIntegrations(sorted);
      } catch (err) {
        logger.error(`Error fetching integrations: ${err}`);
        setError("Failed to load Integrations. Please Try Again Later.");
      }
    };

    fetchIntegrations();
  }, [authLoading, user]);

  if (authLoading || (integrations === null && !error)) {
    return <IntegrationsLoading />;
  }

  return (
    <div>
      <div className="mb-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Integrations</h2>
            <p className="text-muted-foreground">
              Connect Slack, Gmail, Sheets, and other tools via Nango OAuth.
            </p>
          </div>
          <CreateIntegrationButton />
        </div>

        {error ? (
          <div className="py-8 text-center text-red-500">{error}</div>
        ) : !integrations || integrations.length === 0 ? (
          <div className="py-8 text-center text-muted-foreground">
            No integrations found. Create your first integration to get started.
          </div>
        ) : (
          <div className="space-y-6">
            <div className="overflow-x-auto">
              <table className="min-w-full border border-border bg-card">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Provider
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Channel
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Action
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Created At
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-card">
                  {integrations.map((integration) => (
                    <tr key={integration.id} className="hover:bg-muted/50">
                      <td className="whitespace-nowrap px-6 py-4 text-sm font-medium">
                        {integration.provider}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                        {integration.provider === "slack" && integration.provider_data
                          ? (integration.provider_data.channel as string) || "-"
                          : "-"}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                        {integration.action}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                        {new Date(integration.created_at).toLocaleDateString("en-US", {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                        {integration.provider === "google-mail" && (
                          <Link
                            href={`/integrations/${integration.id}/gmail`}
                            className="inline-flex items-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                          >
                            Search
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
