"""GENERATED — do not edit. Source: filtered OpenAPI from `api.app`.

Regenerate with `./scripts/generate_sdk.sh`.

`DograhClient` mixes in this class to get HTTP methods for every route
decorated with `sdk_expose(...)` on the backend. Request/response types
come from `_generated_models` (datamodel-codegen output).
"""

from __future__ import annotations

from typing import Any

from dograh_sdk._generated_models import (
    BatchRecordingCreateRequestSchema,
    BatchRecordingCreateResponseSchema,
    BatchRecordingUploadRequestSchema,
    BatchRecordingUploadResponseSchema,
    CampaignProgressResponse,
    CampaignResponse,
    CampaignRunsResponse,
    CampaignSourceDownloadResponse,
    CampaignsResponse,
    ChunkSearchRequestSchema,
    ChunkSearchResponseSchema,
    CreateCampaignRequest,
    CreateToolRequest,
    CreateWorkflowRequest,
    CredentialResponse,
    DailyReportResponse,
    DocumentListResponseSchema,
    DocumentResponseSchema,
    DocumentUploadRequestSchema,
    DocumentUploadResponseSchema,
    EmbedTokenRequest,
    EmbedTokenResponse,
    InitiateCallRequest,
    NodeSpec,
    NodeTypesResponse,
    ProcessDocumentRequestSchema,
    RecordingListResponseSchema,
    RecordingResponseSchema,
    RecordingUpdateRequestSchema,
    RedialCampaignRequest,
    ToolResponse,
    UpdateCampaignRequest,
    UpdateToolRequest,
    UpdateWorkflowRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowRunDetail,
)


class _GeneratedClient:
    # `DograhClient.__init__` installs `self._request` (see client.py).

    def create_campaign(self, *, body: CreateCampaignRequest) -> CampaignResponse:
        """Create a new outbound campaign."""
        data = self._request("POST", "/campaign/create", json=body.model_dump(mode="json", exclude_none=True))
        return CampaignResponse.model_validate(data)

    def create_kb_upload_url(self, *, body: DocumentUploadRequestSchema) -> DocumentUploadResponseSchema:
        """Get a pre-signed PUT URL for uploading a knowledge-base document."""
        data = self._request("POST", "/knowledge-base/upload-url", json=body.model_dump(mode="json", exclude_none=True))
        return DocumentUploadResponseSchema.model_validate(data)

    def create_persistent_embed_token(self, workflow_id: int, *, body: EmbedTokenRequest) -> EmbedTokenResponse:
        """Create or refresh the persistent embed_token used by browser widgets."""
        data = self._request("POST", f"/workflow/{workflow_id}/embed-token", json=body.model_dump(mode="json", exclude_none=True))
        return EmbedTokenResponse.model_validate(data)

    def create_recording_upload_urls(self, *, body: BatchRecordingUploadRequestSchema) -> BatchRecordingUploadResponseSchema:
        """Mint pre-signed PUT URLs for uploading one or more recording audio files."""
        data = self._request("POST", "/workflow-recordings/upload-url", json=body.model_dump(mode="json", exclude_none=True))
        return BatchRecordingUploadResponseSchema.model_validate(data)

    def create_recordings(self, *, body: BatchRecordingCreateRequestSchema) -> BatchRecordingCreateResponseSchema:
        """Register one or more recording rows after audio has been uploaded via the presigned URLs."""
        data = self._request("POST", "/workflow-recordings/", json=body.model_dump(mode="json", exclude_none=True))
        return BatchRecordingCreateResponseSchema.model_validate(data)

    def create_tool(self, *, body: CreateToolRequest) -> ToolResponse:
        """Create a new HTTP tool definition (workflow agents can invoke during calls)."""
        data = self._request("POST", "/tools/", json=body.model_dump(mode="json", exclude_none=True))
        return ToolResponse.model_validate(data)

    def create_workflow(self, *, body: CreateWorkflowRequest) -> WorkflowResponse:
        """Create a new workflow from a workflow definition."""
        data = self._request("POST", "/workflow/create/definition", json=body.model_dump(mode="json", exclude_none=True))
        return WorkflowResponse.model_validate(data)

    def delete_kb_document(self, document_uuid: str) -> Any:
        """Soft-delete a knowledge-base document and its chunks."""
        return self._request("DELETE", f"/knowledge-base/documents/{document_uuid}")

    def delete_recording(self, recording_id: str) -> Any:
        """Soft-delete a recording."""
        return self._request("DELETE", f"/workflow-recordings/{recording_id}")

    def delete_tool(self, tool_uuid: str) -> Any:
        """Soft-delete a tool definition."""
        return self._request("DELETE", f"/tools/{tool_uuid}")

    def get_campaign(self, campaign_id: int) -> CampaignResponse:
        """Get a campaign by id."""
        data = self._request("GET", f"/campaign/{campaign_id}")
        return CampaignResponse.model_validate(data)

    def get_campaign_progress(self, campaign_id: int) -> CampaignProgressResponse:
        """Get aggregate progress (calls placed, completed, success rate)."""
        data = self._request("GET", f"/campaign/{campaign_id}/progress")
        return CampaignProgressResponse.model_validate(data)

    def get_campaign_report(self, campaign_id: int, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """Download a CSV report of campaign outcomes."""
        params: dict[str, Any] = {}
        if start_date is not None:
            params["start_date"] = start_date
        if end_date is not None:
            params["end_date"] = end_date
        return self._request("GET", f"/campaign/{campaign_id}/report", params=params)

    def get_campaign_source_url(self, campaign_id: int) -> CampaignSourceDownloadResponse:
        """Get a pre-signed URL to download the campaign's source CSV."""
        data = self._request("GET", f"/campaign/{campaign_id}/source-download-url")
        return CampaignSourceDownloadResponse.model_validate(data)

    def get_daily_report(self, *, date: str | None = None, timezone: str | None = None, workflow_id: int | None = None) -> DailyReportResponse:
        """Daily call-volume and disposition report for an organization, optionally filtered by workflow."""
        params: dict[str, Any] = {}
        if date is not None:
            params["date"] = date
        if timezone is not None:
            params["timezone"] = timezone
        if workflow_id is not None:
            params["workflow_id"] = workflow_id
        data = self._request("GET", "/organizations/reports/daily", params=params)
        return DailyReportResponse.model_validate(data)

    def get_kb_document(self, document_uuid: str) -> DocumentResponseSchema:
        """Get knowledge-base document details (processing status, chunks, metadata)."""
        data = self._request("GET", f"/knowledge-base/documents/{document_uuid}")
        return DocumentResponseSchema.model_validate(data)

    def get_node_type(self, name: str) -> NodeSpec:
        """Fetch a single node spec by name."""
        data = self._request("GET", f"/node-types/{name}")
        return NodeSpec.model_validate(data)

    def get_persistent_embed_token(self, workflow_id: int) -> Any:
        """Get the active persistent embed_token for a workflow, if one exists."""
        return self._request("GET", f"/workflow/{workflow_id}/embed-token")

    def get_tool(self, tool_uuid: str) -> ToolResponse:
        """Get a tool definition by UUID."""
        data = self._request("GET", f"/tools/{tool_uuid}")
        return ToolResponse.model_validate(data)

    def get_workflow(self, workflow_id: int) -> WorkflowResponse:
        """Get a single workflow by ID (returns draft if one exists, else published)."""
        data = self._request("GET", f"/workflow/fetch/{workflow_id}")
        return WorkflowResponse.model_validate(data)

    def list_campaign_runs(self, campaign_id: int, *, page: int | None = None, limit: int | None = None, filters: str | None = None, sort_by: str | None = None, sort_order: str | None = None) -> CampaignRunsResponse:
        """List runs (one per dialed lead) for a campaign."""
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if limit is not None:
            params["limit"] = limit
        if filters is not None:
            params["filters"] = filters
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        data = self._request("GET", f"/campaign/{campaign_id}/runs", params=params)
        return CampaignRunsResponse.model_validate(data)

    def list_campaigns(self) -> CampaignsResponse:
        """List all campaigns in the organization."""
        data = self._request("GET", "/campaign/")
        return CampaignsResponse.model_validate(data)

    def list_credentials(self) -> list[CredentialResponse]:
        """List webhook credentials available to the authenticated organization."""
        data = self._request("GET", "/credentials/")
        return [CredentialResponse.model_validate(x) for x in data]

    def list_daily_runs(self, *, date: str | None = None, timezone: str | None = None, workflow_id: int | None = None) -> list[WorkflowRunDetail]:
        """Per-run detail (phone number, disposition, duration) for a given day."""
        params: dict[str, Any] = {}
        if date is not None:
            params["date"] = date
        if timezone is not None:
            params["timezone"] = timezone
        if workflow_id is not None:
            params["workflow_id"] = workflow_id
        data = self._request("GET", "/organizations/reports/daily/runs", params=params)
        return [WorkflowRunDetail.model_validate(x) for x in data]

    def list_documents(self, *, status: str | None = None, limit: int | None = None, offset: int | None = None) -> DocumentListResponseSchema:
        """List knowledge base documents available to the authenticated organization."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        data = self._request("GET", "/knowledge-base/documents", params=params)
        return DocumentListResponseSchema.model_validate(data)

    def list_node_types(self) -> NodeTypesResponse:
        """List every registered node type with its spec. Pinned to spec_version."""
        data = self._request("GET", "/node-types")
        return NodeTypesResponse.model_validate(data)

    def list_recordings(self, *, workflow_id: int | None = None, tts_provider: str | None = None, tts_model: str | None = None, tts_voice_id: str | None = None) -> RecordingListResponseSchema:
        """List workflow recordings available to the authenticated organization."""
        params: dict[str, Any] = {}
        if workflow_id is not None:
            params["workflow_id"] = workflow_id
        if tts_provider is not None:
            params["tts_provider"] = tts_provider
        if tts_model is not None:
            params["tts_model"] = tts_model
        if tts_voice_id is not None:
            params["tts_voice_id"] = tts_voice_id
        data = self._request("GET", "/workflow-recordings/", params=params)
        return RecordingListResponseSchema.model_validate(data)

    def list_tools(self, *, status: str | None = None, category: str | None = None) -> list[ToolResponse]:
        """List tools available to the authenticated organization."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if category is not None:
            params["category"] = category
        data = self._request("GET", "/tools/", params=params)
        return [ToolResponse.model_validate(x) for x in data]

    def list_workflows(self, *, status: str | None = None) -> list[WorkflowListResponse]:
        """List all workflows in the authenticated organization."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        data = self._request("GET", "/workflow/fetch", params=params)
        return [WorkflowListResponse.model_validate(x) for x in data]

    def pause_campaign(self, campaign_id: int) -> CampaignResponse:
        """Pause an in-progress campaign run."""
        data = self._request("POST", f"/campaign/{campaign_id}/pause")
        return CampaignResponse.model_validate(data)

    def process_kb_document(self, *, body: ProcessDocumentRequestSchema) -> DocumentResponseSchema:
        """Trigger async parsing/embedding of an uploaded knowledge-base document."""
        data = self._request("POST", "/knowledge-base/process-document", json=body.model_dump(mode="json", exclude_none=True))
        return DocumentResponseSchema.model_validate(data)

    def redial_campaign(self, campaign_id: int, *, body: RedialCampaignRequest) -> CampaignResponse:
        """Re-attempt unanswered or failed calls in a campaign."""
        data = self._request("POST", f"/campaign/{campaign_id}/redial", json=body.model_dump(mode="json", exclude_none=True))
        return CampaignResponse.model_validate(data)

    def resume_campaign(self, campaign_id: int) -> CampaignResponse:
        """Resume a paused campaign run."""
        data = self._request("POST", f"/campaign/{campaign_id}/resume")
        return CampaignResponse.model_validate(data)

    def revoke_persistent_embed_token(self, workflow_id: int) -> Any:
        """Deactivate the workflow's persistent embed_token."""
        return self._request("DELETE", f"/workflow/{workflow_id}/embed-token")

    def search_kb(self, *, body: ChunkSearchRequestSchema) -> ChunkSearchResponseSchema:
        """Semantic search against the knowledge base; returns matching chunks."""
        data = self._request("POST", "/knowledge-base/search", json=body.model_dump(mode="json", exclude_none=True))
        return ChunkSearchResponseSchema.model_validate(data)

    def start_campaign(self, campaign_id: int) -> CampaignResponse:
        """Start a campaign run."""
        data = self._request("POST", f"/campaign/{campaign_id}/start")
        return CampaignResponse.model_validate(data)

    def test_phone_call(self, *, body: InitiateCallRequest) -> Any:
        """Place a test call from a workflow to a phone number."""
        return self._request("POST", "/telephony/initiate-call", json=body.model_dump(mode="json", exclude_none=True))

    def unarchive_tool(self, tool_uuid: str) -> ToolResponse:
        """Restore a soft-deleted tool definition."""
        data = self._request("POST", f"/tools/{tool_uuid}/unarchive")
        return ToolResponse.model_validate(data)

    def update_campaign(self, campaign_id: int, *, body: UpdateCampaignRequest) -> CampaignResponse:
        """Update mutable fields on a campaign."""
        data = self._request("PATCH", f"/campaign/{campaign_id}", json=body.model_dump(mode="json", exclude_none=True))
        return CampaignResponse.model_validate(data)

    def update_recording(self, id: int, *, body: RecordingUpdateRequestSchema) -> RecordingResponseSchema:
        """Rename a recording (recording_id slug); cascades to workflow definitions referencing it."""
        data = self._request("PATCH", f"/workflow-recordings/{id}", json=body.model_dump(mode="json", exclude_none=True))
        return RecordingResponseSchema.model_validate(data)

    def update_tool(self, tool_uuid: str, *, body: UpdateToolRequest) -> ToolResponse:
        """Update an existing tool definition."""
        data = self._request("PUT", f"/tools/{tool_uuid}", json=body.model_dump(mode="json", exclude_none=True))
        return ToolResponse.model_validate(data)

    def update_workflow(self, workflow_id: int, *, body: UpdateWorkflowRequest) -> WorkflowResponse:
        """Update a workflow's name and/or definition. Saves as a new draft."""
        data = self._request("PUT", f"/workflow/{workflow_id}", json=body.model_dump(mode="json", exclude_none=True))
        return WorkflowResponse.model_validate(data)
