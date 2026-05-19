"use client";

import { ExternalLink } from "lucide-react";

import type { ExternalActorAttribution } from "@/client/types.gen";
import { Badge } from "@/components/ui/badge";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";

interface ActedByBadgeProps {
    /**
     * The created_by_external attribution from the API response. When null /
     * undefined, the badge renders nothing (the row was a direct human action,
     * which is the default and needs no badge).
     */
    attribution: ExternalActorAttribution | null | undefined;
    /**
     * Optional last-modified attribution. When supplied AND distinct from
     * `attribution`, the badge shows the modifier instead — useful on detail
     * pages where the most recent action is the most relevant one.
     */
    lastModified?: ExternalActorAttribution | null;
    /**
     * Compact variant — smaller padding, used inside dense tables. Default
     * is the standard size used on detail pages.
     */
    compact?: boolean;
}

/**
 * Phase 7.5 — "Acted by" badge.
 *
 * Renders a small pill showing which external system (today: a NoralOS
 * agent) made the write that produced or last touched this row. Hovering
 * the badge reveals the full attribution payload (actor ID, run ID).
 *
 * Renders NOTHING when attribution is absent — direct human actions look
 * exactly as they did before Phase 7.5 shipped.
 */
export function ActedByBadge({
    attribution,
    lastModified,
    compact = false,
}: ActedByBadgeProps) {
    const effective = lastModified ?? attribution;
    if (!effective || !effective.actor_id) return null;

    const label = effective.label ?? "Unknown agent (NoralOS)";
    const runId = effective.run_id ?? null;
    const actorId = effective.actor_id;

    return (
        <TooltipProvider delayDuration={150}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <Badge
                        variant="secondary"
                        className={
                            compact
                                ? "gap-1 px-1.5 py-0 text-[10px] font-medium"
                                : "gap-1 px-2 py-0.5 text-xs font-medium"
                        }
                        data-testid="acted-by-badge"
                    >
                        <ExternalLink className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />
                        {label}
                    </Badge>
                </TooltipTrigger>
                <TooltipContent
                    side="top"
                    className="max-w-xs space-y-1 text-xs"
                >
                    <div className="font-semibold">{label}</div>
                    <div className="font-mono text-[10px] opacity-75">
                        actor: {actorId.slice(0, 8)}…
                    </div>
                    {runId && (
                        <div className="font-mono text-[10px] opacity-75">
                            run: {runId.slice(0, 8)}…
                        </div>
                    )}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

/**
 * Returns true when a row was authored by any non-human actor. Used by the
 * run-history "Acted by → NoralOS agents" filter.
 */
export function hasExternalAttribution(
    attribution: ExternalActorAttribution | null | undefined,
): boolean {
    return Boolean(attribution?.actor_id);
}
