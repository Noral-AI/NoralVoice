from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from api.routes.agent_stream import router as agent_stream_router
from api.routes.agents import router as agents_router
from api.routes.auth import router as auth_router
from api.routes.auth_google import router as auth_google_router
from api.routes.calls import router as calls_router
from api.routes.campaign import router as campaign_router
from api.routes.credentials import router as credentials_router
from api.routes.elevenlabs_webhooks import router as elevenlabs_webhooks_router
from api.routes.embed import router as embed_router
from api.routes.integration_webhooks import router as integration_webhooks_router
from api.routes.knowledge_base import router as knowledge_base_router
from api.routes.llm_settings import router as llm_settings_router
from api.routes.looptalk import router as looptalk_router
from api.routes.n8n_integration import router as n8n_integration_router
from api.routes.node_types import router as node_types_router
from api.routes.organization import router as organization_router
from api.routes.organization_usage import router as organization_usage_router
from api.routes.public_agent import router as public_agent_router
from api.routes.public_download import router as public_download_router
from api.routes.public_embed import router as public_embed_router
from api.routes.reports import router as reports_router
from api.routes.s3_signed_url import router as s3_router
from api.routes.service_keys import router as service_keys_router
from api.routes.superuser import router as superuser_router
from api.routes.telephony import router as telephony_router
from api.routes.tool import router as tool_router
from api.routes.turn_credentials import router as turn_credentials_router
from api.routes.user import router as user_router
from api.routes.webrtc_signaling import router as webrtc_signaling_router
from api.routes.workflow import router as workflow_router
from api.routes.workflow_embed import router as workflow_embed_router
from api.routes.workflow_recording import router as workflow_recording_router

router = APIRouter(
    tags=["main"],
    responses={404: {"description": "Not found"}},
)

router.include_router(telephony_router)
router.include_router(superuser_router)
router.include_router(workflow_router)
router.include_router(user_router)
router.include_router(campaign_router)
router.include_router(credentials_router)
router.include_router(tool_router)
router.include_router(integration_webhooks_router)
router.include_router(elevenlabs_webhooks_router)
router.include_router(agents_router)
router.include_router(calls_router)
router.include_router(llm_settings_router)
router.include_router(n8n_integration_router)
router.include_router(organization_router)
router.include_router(s3_router)
router.include_router(service_keys_router)
router.include_router(looptalk_router)
router.include_router(organization_usage_router)
router.include_router(reports_router)
router.include_router(webrtc_signaling_router)
router.include_router(turn_credentials_router)
router.include_router(public_embed_router)
router.include_router(embed_router)
router.include_router(public_agent_router)
router.include_router(public_download_router)
router.include_router(workflow_embed_router)
router.include_router(knowledge_base_router)
router.include_router(workflow_recording_router)
router.include_router(auth_router)
router.include_router(auth_google_router)
router.include_router(node_types_router)
router.include_router(agent_stream_router)


class HealthResponse(BaseModel):
    status: str
    version: str
    backend_api_endpoint: str
    deployment_mode: str
    auth_provider: str
    turn_enabled: bool
    force_turn_relay: bool
    google_oauth_enabled: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from api.constants import (
        APP_VERSION,
        AUTH_PROVIDER,
        DEPLOYMENT_MODE,
        FORCE_TURN_RELAY,
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        GOOGLE_OAUTH_ENABLED,
        TURN_SECRET,
    )
    from api.utils.common import get_backend_endpoints

    logger.debug("Health endpoint called")
    backend_endpoint, _ = await get_backend_endpoints()
    # Only report the button as enabled if the flag AND credentials are
    # set. Mirrors _require_enabled() in google_oauth.py so the UI hides
    # buttons that would 503 on click.
    google_oauth_ready = bool(
        GOOGLE_OAUTH_ENABLED and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
    )
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        backend_api_endpoint=backend_endpoint,
        deployment_mode=DEPLOYMENT_MODE,
        auth_provider=AUTH_PROVIDER,
        turn_enabled=bool(TURN_SECRET),
        force_turn_relay=FORCE_TURN_RELAY,
        google_oauth_enabled=google_oauth_ready,
    )
