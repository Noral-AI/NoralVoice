import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

const OSS_TOKEN_COOKIE = 'noralvoice_auth_token';
const OSS_USER_COOKIE = 'noralvoice_auth_user';
// PHASE-5 COOKIE-MIGRATION — Phase 0 renamed the auth cookies but
// didn't ship a dual-write window. Phase 5b1 adds it retroactively so
// a user with a stale `dograh_*` cookie isn't bounced to login on
// first visit. Remove these constants + the dual writes below in a
// follow-up after one release.
const LEGACY_OSS_TOKEN_COOKIE = 'dograh_auth_token';
const LEGACY_OSS_USER_COOKIE = 'dograh_auth_user';

export async function POST(request: NextRequest) {
  const { token, user } = await request.json();

  if (!token) {
    return NextResponse.json({ error: 'Missing token' }, { status: 400 });
  }

  const cookieStore = await cookies();
  const baseOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax' as const,
    maxAge: 60 * 60 * 24 * 30,
    path: '/',
  };

  cookieStore.set(OSS_TOKEN_COOKIE, token, baseOpts);
  cookieStore.set(OSS_USER_COOKIE, JSON.stringify(user), baseOpts);
  // PHASE-5 COOKIE-MIGRATION — also write the legacy names so any
  // tooling still keyed on the old cookies keeps working through the
  // window. Reader paths check the new name first and fall back.
  cookieStore.set(LEGACY_OSS_TOKEN_COOKIE, token, baseOpts);
  cookieStore.set(LEGACY_OSS_USER_COOKIE, JSON.stringify(user), baseOpts);

  return NextResponse.json({ success: true });
}
