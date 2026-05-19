"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { WorkflowRunResponseSchema } from "@/client/types.gen";
import { ActedByBadge, hasExternalAttribution } from "@/components/attribution/ActedByBadge";
import { FilterBuilder } from "@/components/filters/FilterBuilder";
import { MediaPreviewButton, MediaPreviewDialog } from "@/components/MediaPreviewDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { ActiveFilter, FilterAttribute } from "@/types/filters";

export interface WorkflowRunsTableProps {
    // Data
    runs: WorkflowRunResponseSchema[];
    loading: boolean;
    error: string | null;

    // Pagination
    currentPage: number;
    totalPages: number;
    totalCount: number;
    onPageChange: (page: number) => void;

    // Filters
    availableAttributes: FilterAttribute[];
    activeFilters: ActiveFilter[];
    onFiltersChange: (filters: ActiveFilter[]) => void;
    onApplyFilters: () => void;
    onClearFilters: () => void;
    isExecutingFilters: boolean;
    hasAppliedFilters?: boolean;

    // Sorting
    sortBy?: string | null;
    sortOrder?: 'asc' | 'desc';
    onSort?: (field: string) => void;

    // Navigation & Actions
    workflowId: number;

    // Reload
    onReload?: () => void;

    // Optional customization
    title?: string;
    subtitle?: string;
    showFilters?: boolean;
    emptyMessage?: string;
}

/**
 * Phase 7.5 — three-way toggle on the run-history page. "external" =
 * agent-driven runs (any NoralOS actor); "human" = direct-user runs.
 */
type ActedByFilter = "all" | "human" | "external";
const ACTED_BY_FILTER_STORAGE_KEY = "noralvoice.workflow_runs.acted_by_filter";

export function WorkflowRunsTable({
    runs,
    loading,
    error,
    currentPage,
    totalPages,
    totalCount,
    onPageChange,
    availableAttributes,
    activeFilters,
    onFiltersChange,
    onApplyFilters,
    onClearFilters,
    isExecutingFilters,
    hasAppliedFilters = false,
    sortBy,
    sortOrder = 'desc',
    onSort,
    workflowId,
    onReload,
    title = "Workflow Run History",
    subtitle,
    showFilters = true,
    emptyMessage = "No workflow runs found",
}: WorkflowRunsTableProps) {
    const [selectedRowId, setSelectedRowId] = useState<number | null>(null);

    // Phase 7.5 — "Acted by" filter. Persisted per-user in localStorage so
    // the choice survives page reloads. Client-side filter over the
    // server-paginated runs because the page already cursors through pages
    // and a server-side filter would double the SQL surface for what's
    // essentially a visualisation toggle. Acceptable trade-off: the count
    // and pagination reflect server totals; the filter narrows what's
    // visible on the current page only.
    const [actedByFilter, setActedByFilter] = useState<ActedByFilter>("all");
    useEffect(() => {
        const stored = window.localStorage.getItem(ACTED_BY_FILTER_STORAGE_KEY);
        if (stored === "human" || stored === "external") {
            setActedByFilter(stored);
        }
    }, []);
    useEffect(() => {
        window.localStorage.setItem(ACTED_BY_FILTER_STORAGE_KEY, actedByFilter);
    }, [actedByFilter]);

    const visibleRuns = useMemo(() => {
        if (actedByFilter === "all") return runs;
        if (actedByFilter === "external") {
            return runs.filter((r) => hasExternalAttribution(r.created_by_external));
        }
        return runs.filter((r) => !hasExternalAttribution(r.created_by_external));
    }, [runs, actedByFilter]);

    // Media preview dialog
    const mediaPreview = MediaPreviewDialog();

    const formatDate = (dateString: string) => new Date(dateString).toLocaleString();

    const handleRowClick = (runId: number) => {
        window.open(`/workflow/${workflowId}/run/${runId}`, '_blank');
    };

    return (
        <div className="space-y-6">
            {/* Title and Filters */}
            {showFilters && (
                <div className="mb-6">
                    <h1 className="text-2xl font-bold mb-4">{title}</h1>
                    <FilterBuilder
                        availableAttributes={availableAttributes}
                        activeFilters={activeFilters}
                        onFiltersChange={onFiltersChange}
                        onApplyFilters={onApplyFilters}
                        onClearFilters={onClearFilters}
                        isExecuting={isExecutingFilters}
                        hasAppliedFilters={hasAppliedFilters}
                    />
                </div>
            )}

            {/* Loading State */}
            {loading ? (
                <div className="flex justify-center">
                    <div className="animate-pulse">Loading workflow runs...</div>
                </div>
            ) : error ? (
                <div className="bg-destructive/10 border border-destructive/30 text-destructive px-4 py-3 rounded">
                    {error}
                </div>
            ) : runs.length === 0 ? (
                <div className="text-center py-8">
                    <p className="text-muted-foreground">{emptyMessage}</p>
                </div>
            ) : (
                <Card>
                    <CardHeader>
                        <div className="flex items-center justify-between">
                            <div>
                                <CardTitle>Workflow Runs</CardTitle>
                                <CardDescription>
                                    {subtitle ||
                                        (actedByFilter === "all"
                                            ? `Showing ${runs.length} of ${totalCount} total runs`
                                            : `Showing ${visibleRuns.length} of ${runs.length} runs on this page (filtered)`)}
                                </CardDescription>
                            </div>
                            <div className="flex items-center gap-2">
                                <Select
                                    value={actedByFilter}
                                    onValueChange={(v) => setActedByFilter(v as ActedByFilter)}
                                >
                                    <SelectTrigger className="w-[180px]" aria-label="Filter by actor">
                                        <SelectValue placeholder="Acted by" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">Acted by: All</SelectItem>
                                        <SelectItem value="human">Human users</SelectItem>
                                        <SelectItem value="external">NoralOS agents</SelectItem>
                                    </SelectContent>
                                </Select>
                                {onReload && (
                                    <Button
                                        variant="outline"
                                        size="icon"
                                        onClick={onReload}
                                        disabled={loading}
                                        title="Reload"
                                    >
                                        <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                                    </Button>
                                )}
                            </div>
                        </div>
                    </CardHeader>
                    <CardContent>
                        <div className="bg-card border border-border rounded-lg overflow-hidden shadow-sm">
                            <Table>
                                <TableHeader>
                                    <TableRow className="bg-muted/50">
                                        <TableHead className="font-semibold">ID</TableHead>
                                        <TableHead className="font-semibold">Status</TableHead>
                                        <TableHead className="font-semibold">Created At</TableHead>
                                        <TableHead className="font-semibold">Call Type</TableHead>
                                        <TableHead
                                            className="font-semibold cursor-pointer hover:bg-muted/50 select-none"
                                            onClick={() => onSort?.('duration')}
                                        >
                                            <div className="flex items-center gap-1">
                                                Duration
                                                {sortBy === 'duration' ? (
                                                    sortOrder === 'asc' ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />
                                                ) : (
                                                    <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
                                                )}
                                            </div>
                                        </TableHead>
                                        <TableHead className="font-semibold">Disposition</TableHead>
                                        <TableHead className="font-semibold">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {visibleRuns.map((run) => (
                                        <TableRow
                                            key={run.id}
                                            className={`cursor-pointer hover:bg-muted/50 ${selectedRowId === run.id ? "bg-primary/20 ring-1 ring-primary/50" : ""}`}
                                            onClick={() => handleRowClick(run.id)}
                                        >
                                            <TableCell className="font-mono text-sm">
                                                <div className="flex items-center gap-1.5">
                                                    <span>#{run.id}</span>
                                                    <ActedByBadge
                                                        attribution={run.created_by_external}
                                                        lastModified={run.last_modified_by_external}
                                                        compact
                                                    />
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={run.is_completed ? "default" : "secondary"}>
                                                    {run.is_completed ? "Completed" : "In Progress"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-sm">{formatDate(run.created_at)}</TableCell>
                                            <TableCell>
                                                <Badge variant={run.call_type === 'inbound' ? "secondary" : "default"}>
                                                    {run.call_type === 'inbound' ? 'Inbound' : 'Outbound'}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-sm">
                                                {typeof run.cost_info?.call_duration_seconds === 'number'
                                                    ? `${run.cost_info.call_duration_seconds.toFixed(1)}s`
                                                    : "-"}
                                            </TableCell>
                                            <TableCell>
                                                {run.gathered_context?.mapped_call_disposition ? (
                                                    <Badge variant="default">
                                                        {run.gathered_context.mapped_call_disposition as string}
                                                    </Badge>
                                                ) : (
                                                    <span className="text-sm text-muted-foreground">-</span>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex space-x-2" onClick={(e) => e.stopPropagation()}>
                                                    <MediaPreviewButton
                                                        recordingUrl={run.recording_url}
                                                        transcriptUrl={run.transcript_url}
                                                        runId={run.id}
                                                        onOpenPreview={mediaPreview.openPreview}
                                                        onSelect={setSelectedRowId}
                                                    />
                                                    <Button
                                                        variant="outline"
                                                        size="icon"
                                                        onClick={() => window.open(`/workflow/${workflowId}/run/${run.id}`, '_blank')}
                                                    >
                                                        <ExternalLink className="h-4 w-4" />
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>

                        {/* Pagination */}
                        {totalPages > 1 && (
                            <div className="flex items-center justify-between mt-6">
                                <p className="text-sm text-muted-foreground">
                                    Page {currentPage} of {totalPages}
                                </p>
                                <div className="flex gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => onPageChange(currentPage - 1)}
                                        disabled={currentPage === 1}
                                    >
                                        <ChevronLeft className="h-4 w-4" />
                                        Previous
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => onPageChange(currentPage + 1)}
                                        disabled={currentPage === totalPages}
                                    >
                                        Next
                                        <ChevronRight className="h-4 w-4" />
                                    </Button>
                                </div>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* Media Preview Dialog */}
            {mediaPreview.dialog}
        </div>
    );
}
