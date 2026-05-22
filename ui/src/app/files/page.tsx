"use client";

import { Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";

import DocumentList from "./DocumentList";
import DocumentUpload from "./DocumentUpload";
import RecordingsList from "./RecordingsList";
import { RecordingsUploadDialog } from "./RecordingsUploadDialog";

type FilesTab = "documents" | "audio";

const VALID_TABS: ReadonlyArray<FilesTab> = ["documents", "audio"];

function isValidTab(value: string | null): value is FilesTab {
    return value !== null && (VALID_TABS as ReadonlyArray<string>).includes(value);
}

export default function FilesPage() {
    const { user, redirectToLogin, loading } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();

    const initialTab: FilesTab = isValidTab(searchParams.get("tab"))
        ? (searchParams.get("tab") as FilesTab)
        : "documents";

    const [activeTab, setActiveTab] = useState<FilesTab>(initialTab);
    const [docRefreshKey, setDocRefreshKey] = useState(0);
    const [audioRefreshKey, setAudioRefreshKey] = useState(0);
    const [isDocUploadOpen, setIsDocUploadOpen] = useState(false);
    const [isAudioUploadOpen, setIsAudioUploadOpen] = useState(false);

    // Redirect if not authenticated
    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    // Keep the URL in sync when the tab changes
    const handleTabChange = useCallback(
        (value: string) => {
            if (!isValidTab(value)) return;
            setActiveTab(value);
            const params = new URLSearchParams(searchParams.toString());
            if (value === "documents") {
                params.delete("tab");
            } else {
                params.set("tab", value);
            }
            const qs = params.toString();
            router.replace(qs ? `/files?${qs}` : "/files", { scroll: false });
        },
        [router, searchParams]
    );

    const handleDocUploadSuccess = () => {
        setDocRefreshKey((k) => k + 1);
        setIsDocUploadOpen(false);
    };

    const handleAudioUploadComplete = () => {
        setAudioRefreshKey((k) => k + 1);
    };

    if (loading || !user) {
        return (
            <div className="container mx-auto px-4 py-8">
                <div className="space-y-4">
                    <Skeleton className="h-12 w-64" />
                    <Skeleton className="h-64 w-full" />
                </div>
            </div>
        );
    }

    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mb-8">
                <h1 className="text-3xl font-bold mb-2">Files</h1>
                <p className="text-muted-foreground">
                    Reusable documents and audio clips your voice agents can reference. Organization-wide.
                </p>
            </div>

            <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-4">
                <TabsList>
                    <TabsTrigger value="documents">Documents</TabsTrigger>
                    <TabsTrigger value="audio">Audio Library</TabsTrigger>
                </TabsList>

                <TabsContent value="documents">
                    <Card>
                        <CardHeader>
                            <div className="flex justify-between items-center">
                                <div>
                                    <CardTitle>Knowledge Base Documents</CardTitle>
                                    <CardDescription>
                                        PDFs and documents your agents can reference, shared across the organization.
                                    </CardDescription>
                                </div>
                                <Button onClick={() => setIsDocUploadOpen(true)}>
                                    <Upload className="w-4 h-4 mr-2" />
                                    Upload Document
                                </Button>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <DocumentList refreshTrigger={docRefreshKey} />
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="audio">
                    <Card>
                        <CardHeader>
                            <div className="flex justify-between items-center">
                                <div>
                                    <CardTitle>Audio Library</CardTitle>
                                    <CardDescription>
                                        Reusable audio clips (greetings, hold music, transition messages). Insert
                                        them in any prompt field by typing{" "}
                                        <code className="rounded bg-muted px-1 text-xs">@</code>, or use them as
                                        tool-call transition messages.
                                    </CardDescription>
                                </div>
                                <Button onClick={() => setIsAudioUploadOpen(true)}>
                                    <Upload className="w-4 h-4 mr-2" />
                                    Upload Audio
                                </Button>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <RecordingsList refreshKey={audioRefreshKey} />
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            <Dialog open={isDocUploadOpen} onOpenChange={setIsDocUploadOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Upload Document</DialogTitle>
                        <DialogDescription>
                            Upload a PDF or document file to add to your knowledge base
                        </DialogDescription>
                    </DialogHeader>
                    <DocumentUpload onUploadSuccess={handleDocUploadSuccess} />
                </DialogContent>
            </Dialog>

            <RecordingsUploadDialog
                open={isAudioUploadOpen}
                onOpenChange={setIsAudioUploadOpen}
                onUploadComplete={handleAudioUploadComplete}
            />
        </div>
    );
}
