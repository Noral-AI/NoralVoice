"use client";

import { ChevronDown, ChevronRight, Eye } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

// Mirrors the runtime marker the engine looks for when deciding whether to
// append recording response-mode instructions
// (api/services/workflow/pipecat_engine_context_composer.py).
const RECORDING_MARKER = "RECORDING_ID:";
const TEMPLATE_VAR_RE = /\{\{\s*[^}]+\}\}/;

interface PromptPreviewProps {
    /** The node's own prompt, as currently edited. */
    nodePrompt: string;
    /** Whether this node opts into the global prompt. */
    addGlobalPrompt: boolean;
    /** The workflow's global-node prompt (empty if there is no global node). */
    globalPrompt: string;
}

/**
 * Shows the full system prompt a node will actually send to the LLM at
 * runtime — the global prompt prepended to the node's own prompt — so authors
 * can see the composition that otherwise only happens at call time.
 *
 * The logic deliberately mirrors `compose_system_prompt_for_node` on the
 * backend: global first, node second, joined by a blank line; recording
 * response-mode instructions are flagged (but not inlined) because their exact
 * text is a runtime concern. Template `{{variables}}` are shown literally —
 * they resolve from call context that doesn't exist at author time.
 */
export function PromptPreview({
    nodePrompt,
    addGlobalPrompt,
    globalPrompt,
}: PromptPreviewProps) {
    const [open, setOpen] = useState(false);

    const trimmedNode = nodePrompt.trim();
    const trimmedGlobal = globalPrompt.trim();
    const globalIncluded = addGlobalPrompt && trimmedGlobal.length > 0;

    const composed = useMemo(() => {
        const parts: string[] = [];
        if (globalIncluded) parts.push(trimmedGlobal);
        if (trimmedNode) parts.push(trimmedNode);
        return parts.join("\n\n");
    }, [globalIncluded, trimmedGlobal, trimmedNode]);

    const hasRecording = nodePrompt.includes(RECORDING_MARKER);
    const hasVars = TEMPLATE_VAR_RE.test(composed);

    return (
        <div className="rounded-md border bg-muted/30">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-foreground"
            >
                {open ? (
                    <ChevronDown className="h-4 w-4 shrink-0" />
                ) : (
                    <ChevronRight className="h-4 w-4 shrink-0" />
                )}
                <Eye className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span>Combined system prompt</span>
                <span className="text-xs font-normal text-muted-foreground">
                    what the LLM receives at runtime
                </span>
            </button>

            {open && (
                <div className="space-y-2 px-3 pb-3">
                    <div className="flex flex-wrap gap-1.5">
                        <Badge active={globalIncluded}>
                            {globalIncluded
                                ? "Global prompt prepended"
                                : addGlobalPrompt
                                  ? "No global node in workflow"
                                  : "Global prompt off"}
                        </Badge>
                        {hasRecording && <Badge active>References a recording</Badge>}
                        {hasVars && <Badge active>Has {"{{variables}}"}</Badge>}
                    </div>

                    {composed ? (
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-3 font-mono text-xs leading-relaxed text-foreground">
                            {composed}
                            {hasRecording && (
                                <span className="text-muted-foreground">
                                    {"\n\n"}
                                    [+ recording response-mode instructions added
                                    automatically at runtime]
                                </span>
                            )}
                        </pre>
                    ) : (
                        <p className="rounded bg-background p-3 text-xs text-muted-foreground">
                            Add a prompt to preview the combined system prompt.
                        </p>
                    )}

                    {hasVars && (
                        <p className="text-xs text-muted-foreground">
                            {"{{variables}}"} are shown literally here — they are
                            filled in from call context at runtime.
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

function Badge({
    active,
    children,
}: {
    active?: boolean;
    children: ReactNode;
}) {
    return (
        <span
            className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                active
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground",
            )}
        >
            {children}
        </span>
    );
}
