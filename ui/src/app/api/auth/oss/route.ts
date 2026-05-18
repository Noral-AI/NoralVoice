/*
  Provides authentication token to LocalProviderWrapper once loaded
  in the browser.
*/
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { getAuthProvider } from "@/lib/auth/config";

const OSS_TOKEN_COOKIE = "noralvoice_auth_token";
const OSS_USER_COOKIE = "noralvoice_auth_user";
const LEGACY_OSS_TOKEN_COOKIE = "dograh_auth_token";
const LEGACY_OSS_USER_COOKIE = "dograh_auth_user";

// Decode Python http.cookies octal escapes (e.g. \054 -> ",") and
// double-quote escapes (\" -> "). These are valid cookie escapes
// produced by Starlette/FastAPI but are not valid JSON, so JSON.parse
// fails unless we normalize them first.
function decodeOctalEscapes(s: string): string {
  return s
    .replace(/\\([0-3][0-7][0-7])/g, (_m, oct) => String.fromCharCode(parseInt(oct, 8)))
    .replace(/\\"/g, "\"")
    .replace(/\\\\/g, "\\");
}

export async function GET() {
  const authProvider = await getAuthProvider();

  if (authProvider !== "local" && authProvider !== "noral") {
    return NextResponse.json({ error: "Not in OSS mode" }, { status: 400 });
  }

  const cookieStore = await cookies();
  const token =
    cookieStore.get(OSS_TOKEN_COOKIE)?.value ??
    cookieStore.get(LEGACY_OSS_TOKEN_COOKIE)?.value;
  const userRaw =
    cookieStore.get(OSS_USER_COOKIE)?.value ??
    cookieStore.get(LEGACY_OSS_USER_COOKIE)?.value;

  if (!token) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  let user: unknown = { id: token, name: "Local User", provider: "local" };
  if (userRaw) {
    try {
      user = JSON.parse(userRaw);
    } catch {
      try {
        user = JSON.parse(decodeOctalEscapes(userRaw));
      } catch {
        // Fall through to placeholder user.
      }
    }
  }

  return NextResponse.json({ token, user });
}
