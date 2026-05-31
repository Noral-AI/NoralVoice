'use client';

import { Archive, Pencil, RotateCcw, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import {
    deleteWorkflowEndpointApiV1WorkflowWorkflowIdDelete,
    updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut,
} from '@/client/sdk.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
interface Workflow {
    id: number;
    name: string;
    status: string;
    created_at: string;
    total_runs?: number | null;
}

interface WorkflowTableProps {
    workflows: Workflow[];
    showArchived: boolean;
}

export function WorkflowTable({ workflows, showArchived }: WorkflowTableProps) {
    const router = useRouter();
    const [isPending, startTransition] = useTransition();
    const [loadingWorkflowId, setLoadingWorkflowId] = useState<number | null>(null);
    const [workflowToDelete, setWorkflowToDelete] = useState<Workflow | null>(null);
    const [deletingWorkflowId, setDeletingWorkflowId] = useState<number | null>(null);

    const handleEdit = (id: number) => {
        router.push(`/workflow/${id}`);
    };

    const handleArchiveToggle = async (id: number, currentStatus: string) => {
        const newStatus = currentStatus === 'active' ? 'archived' : 'active';
        const action = currentStatus === 'active' ? 'Archive' : 'Restore';

        setLoadingWorkflowId(id);

        try {
            const response = await updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut({
                path: {
                    workflow_id: id,
                },
                body: {
                    status: newStatus,
                },
            });

            if (response.data) {
                toast.success(`Workflow ${action.toLowerCase()}d successfully`);
                startTransition(() => {
                    router.refresh();
                });
            }
        } catch (error) {
            console.error(`Error ${action.toLowerCase()}ing workflow:`, error);
            toast.error(`Failed to ${action.toLowerCase()} workflow`);
        } finally {
            setLoadingWorkflowId(null);
        }
    };

    const handleDelete = async (workflow: Workflow) => {
        setDeletingWorkflowId(workflow.id);

        try {
            const { error, response } = await deleteWorkflowEndpointApiV1WorkflowWorkflowIdDelete({
                path: {
                    workflow_id: workflow.id,
                },
            });

            if (response.ok) {
                toast.success('Agent deleted');
                setWorkflowToDelete(null);
                startTransition(() => {
                    router.refresh();
                });
                return;
            }

            // Surface the backend's reason — a 409 explains what's keeping the
            // agent alive (call history, attached number, campaign, LoopTalk).
            const detail = (error as { detail?: unknown } | undefined)?.detail;
            toast.error(
                typeof detail === 'string' ? detail : 'Failed to delete agent',
            );
        } catch (err) {
            console.error('Error deleting workflow:', err);
            toast.error('Failed to delete agent');
        } finally {
            setDeletingWorkflowId(null);
        }
    };

    return (
        <>
        <div className="bg-card border rounded-lg overflow-hidden shadow-sm">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="font-semibold">ID</TableHead>
                        <TableHead className="font-semibold">Agent Name</TableHead>
                        <TableHead className="font-semibold">Created At</TableHead>
                        <TableHead className="font-semibold text-center">Total Runs</TableHead>
                        <TableHead className="font-semibold text-right">Actions</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {workflows.map((workflow) => (
                        <TableRow
                            key={workflow.id}
                            className={`hover:bg-accent transition-colors ${showArchived ? 'opacity-60' : ''}`}
                        >
                            <TableCell className="text-muted-foreground">
                                {workflow.id}
                            </TableCell>
                            <TableCell className="font-medium">
                                {workflow.name}
                            </TableCell>
                            <TableCell>
                                {new Date(workflow.created_at).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                })}
                            </TableCell>
                            <TableCell className="text-center">
                                <span className="inline-flex items-center justify-center min-w-[2rem] px-2 py-1 text-sm font-semibold bg-muted rounded-full">
                                    {workflow.total_runs || 0}
                                </span>
                            </TableCell>
                            <TableCell className="text-right">
                                <div className="flex justify-end gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleEdit(workflow.id)}
                                        className="flex items-center gap-2"
                                    >
                                        <Pencil size={16} />
                                        Edit
                                    </Button>
                                    <Button
                                        variant={showArchived ? "default" : "outline"}
                                        size="sm"
                                        onClick={() => handleArchiveToggle(workflow.id, workflow.status)}
                                        disabled={loadingWorkflowId === workflow.id || isPending}
                                        className="flex items-center gap-2"
                                    >
                                        {loadingWorkflowId === workflow.id ? (
                                            <>
                                                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                                {showArchived ? 'Restoring...' : 'Archiving...'}
                                            </>
                                        ) : (
                                            <>
                                                {showArchived ? (
                                                    <>
                                                        <RotateCcw size={16} />
                                                        Restore
                                                    </>
                                                ) : (
                                                    <>
                                                        <Archive size={16} />
                                                        Archive
                                                    </>
                                                )}
                                            </>
                                        )}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => setWorkflowToDelete(workflow)}
                                        disabled={
                                            loadingWorkflowId === workflow.id ||
                                            deletingWorkflowId === workflow.id ||
                                            isPending
                                        }
                                        className="flex items-center gap-2 text-destructive hover:bg-destructive/10 hover:text-destructive"
                                    >
                                        <Trash2 size={16} />
                                        Delete
                                    </Button>
                                </div>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>

        <AlertDialog
            open={workflowToDelete !== null}
            onOpenChange={(open) => {
                if (!open && deletingWorkflowId === null) {
                    setWorkflowToDelete(null);
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete this agent?</AlertDialogTitle>
                    <AlertDialogDescription>
                        This permanently deletes{' '}
                        <span className="font-medium text-foreground">
                            {workflowToDelete?.name}
                        </span>{' '}
                        and all of its versions. This can&apos;t be undone. Agents
                        with call history or an attached phone number can&apos;t be
                        deleted — archive them instead.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={deletingWorkflowId !== null}>
                        Cancel
                    </AlertDialogCancel>
                    <AlertDialogAction
                        onClick={(e) => {
                            e.preventDefault();
                            if (workflowToDelete) {
                                handleDelete(workflowToDelete);
                            }
                        }}
                        disabled={deletingWorkflowId !== null}
                        className="bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive"
                    >
                        {deletingWorkflowId !== null ? 'Deleting...' : 'Delete'}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
        </>
    );
}
