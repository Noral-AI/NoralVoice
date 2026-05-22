import { redirect } from "next/navigation";

// The Recordings page moved under Files as the "Audio Library" tab.
// Preserve any legacy links by redirecting to the new location.
export default function LegacyRecordingsRedirect() {
    redirect("/files?tab=audio");
}
