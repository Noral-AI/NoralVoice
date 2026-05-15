import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const OSS_TOKEN_COOKIE = 'noralvoice_auth_token';
const OSS_USER_COOKIE = 'noralvoice_auth_user';
// PHASE-5 COOKIE-MIGRATION — clear the legacy names too while the
// dual-write window is open. Remove in a follow-up.
const LEGACY_OSS_TOKEN_COOKIE = 'dograh_auth_token';
const LEGACY_OSS_USER_COOKIE = 'dograh_auth_user';

export async function POST() {
  const cookieStore = await cookies();
  const clearOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax' as const,
    maxAge: 0,
    path: '/',
  };

  cookieStore.set(OSS_TOKEN_COOKIE, '', clearOpts);
  cookieStore.set(OSS_USER_COOKIE, '', clearOpts);
  cookieStore.set(LEGACY_OSS_TOKEN_COOKIE, '', clearOpts);
  cookieStore.set(LEGACY_OSS_USER_COOKIE, '', clearOpts);

  return NextResponse.json({ success: true });
}
