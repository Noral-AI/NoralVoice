"use client";

import { Volume2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

let activeAudio: HTMLAudioElement | null = null;
let activeVoiceId: string | null = null;
const subscribers = new Set<(voiceId: string | null) => void>();

const notify = () => {
    subscribers.forEach((cb) => cb(activeVoiceId));
};

const stopActive = () => {
    if (activeAudio) {
        activeAudio.pause();
        activeAudio.currentTime = 0;
    }
    activeAudio = null;
    activeVoiceId = null;
    notify();
};

const playPreview = (previewUrl: string, voiceId: string) => {
    if (activeVoiceId === voiceId) {
        stopActive();
        return;
    }
    stopActive();
    activeVoiceId = voiceId;
    const audio = new Audio(previewUrl);
    activeAudio = audio;
    audio.onended = stopActive;
    audio.onerror = stopActive;
    notify();
    audio.play().catch(stopActive);
};

interface VoicePreviewButtonProps {
    previewUrl: string;
    voiceId: string;
    className?: string;
}

export const VoicePreviewButton: React.FC<VoicePreviewButtonProps> = ({
    previewUrl,
    voiceId,
    className,
}) => {
    const [playingId, setPlayingId] = useState<string | null>(activeVoiceId);

    useEffect(() => {
        subscribers.add(setPlayingId);
        return () => {
            subscribers.delete(setPlayingId);
        };
    }, []);

    const isPlaying = playingId === voiceId;

    return (
        <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn("h-8 w-8 p-0 shrink-0", className)}
            onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                playPreview(previewUrl, voiceId);
            }}
            aria-label={isPlaying ? "Stop preview" : "Play preview"}
        >
            <Volume2
                className={cn(
                    "h-4 w-4",
                    isPlaying && "text-primary animate-pulse"
                )}
            />
        </Button>
    );
};
