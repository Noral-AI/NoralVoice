"use client";

import { MCPSection } from "@/components/MCPSection";
import { TelemetrySection } from "@/components/TelemetrySection";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function PlatformTab() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Platform</h2>
        <p className="text-muted-foreground">
          Manage your platform configuration: MCP, telemetry, and other platform-wide
          settings.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>MCP Server</CardTitle>
          <CardDescription>
            Let AI agents access your NoralVoice workspace via the Model Context Protocol.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MCPSection />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Telemetry</CardTitle>
          <CardDescription>
            Configure Langfuse tracing for your voice agent calls.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TelemetrySection />
        </CardContent>
      </Card>
    </div>
  );
}
