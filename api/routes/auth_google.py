"""
Thin HTTP layer over the Google OAuth service. All flow logic lives in
`api.services.auth.google_oauth`; this file just maps it onto FastAPI
routes.
"""

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from api.services.auth.google_oauth import handle_callback, start_oauth

router = APIRouter(
    prefix="/auth/google",
    tags=["auth"],
)


@router.get("/start")
async def start(request: Request) -> RedirectResponse:
    """Begin the Google sign-in flow. 302 → Google's authorize URL."""
    return await start_oauth(request)


@router.get("/callback")
async def callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
) -> RedirectResponse:
    """Google posts the user back here. 302 → UI landing page with cookies set."""
    return await handle_callback(code, state)
