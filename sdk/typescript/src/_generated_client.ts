// GENERATED — do not edit. Source: filtered OpenAPI from `api.app`.
//
// Regenerate with `./scripts/generate_sdk.sh`.
//
// `DograhClient` extends this base to get HTTP methods for every route
// decorated with `sdk_expose(...)`. Request/response types come from
// `_generated_models` (openapi-typescript output, --root-types).

import type {
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
    PhoneNumberCreateRequest,
    PhoneNumberResponse,
    ProcessDocumentRequestSchema,
    RecordingListResponseSchema,
    RecordingResponseSchema,
    RecordingUpdateRequestSchema,
    RedialCampaignRequest,
    TelephonyConfigurationCreateRequest,
    TelephonyConfigurationDetail,
    TelephonyConfigurationListResponse,
    ToolResponse,
    UpdateCampaignRequest,
    UpdateToolRequest,
    UpdateWorkflowRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowRunDetail,
} from "./_generated_models.js";

export abstract class _GeneratedClient {
    protected abstract request<T = unknown>(
        method: string,
        path: string,
        opts?: { json?: unknown; params?: Record<string, unknown> },
    ): Promise<T>;

    /** Register a phone number under an existing telephony configuration, optionally assigning it to a workflow for inbound routing. Returns the provider sync status when an inbound workflow is set. */
    async addPhoneNumber(configId: number, opts: { body: PhoneNumberCreateRequest }): Promise<PhoneNumberResponse> {
        return this.request<PhoneNumberResponse>("POST", `/organizations/telephony-configs/${configId}/phone-numbers`, { json: opts.body });
    }

    /** Create a new outbound campaign. */
    async createCampaign(opts: { body: CreateCampaignRequest }): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("POST", "/campaign/create", { json: opts.body });
    }

    /** Get a pre-signed PUT URL for uploading a knowledge-base document. */
    async createKbUploadUrl(opts: { body: DocumentUploadRequestSchema }): Promise<DocumentUploadResponseSchema> {
        return this.request<DocumentUploadResponseSchema>("POST", "/knowledge-base/upload-url", { json: opts.body });
    }

    /** Create or refresh the persistent embed_token used by browser widgets. */
    async createPersistentEmbedToken(workflowId: number, opts: { body: EmbedTokenRequest }): Promise<EmbedTokenResponse> {
        return this.request<EmbedTokenResponse>("POST", `/workflow/${workflowId}/embed-token`, { json: opts.body });
    }

    /** Mint pre-signed PUT URLs for uploading one or more recording audio files. */
    async createRecordingUploadUrls(opts: { body: BatchRecordingUploadRequestSchema }): Promise<BatchRecordingUploadResponseSchema> {
        return this.request<BatchRecordingUploadResponseSchema>("POST", "/workflow-recordings/upload-url", { json: opts.body });
    }

    /** Register one or more recording rows after audio has been uploaded via the presigned URLs. */
    async createRecordings(opts: { body: BatchRecordingCreateRequestSchema }): Promise<BatchRecordingCreateResponseSchema> {
        return this.request<BatchRecordingCreateResponseSchema>("POST", "/workflow-recordings/", { json: opts.body });
    }

    /** Create a new telephony provider configuration for the org (e.g. Twilio account_sid + auth_token). Sensitive fields are masked in the response. */
    async createTelephonyConfig(opts: { body: TelephonyConfigurationCreateRequest }): Promise<TelephonyConfigurationDetail> {
        return this.request<TelephonyConfigurationDetail>("POST", "/organizations/telephony-configs", { json: opts.body });
    }

    /** Create a new HTTP tool definition (workflow agents can invoke during calls). */
    async createTool(opts: { body: CreateToolRequest }): Promise<ToolResponse> {
        return this.request<ToolResponse>("POST", "/tools/", { json: opts.body });
    }

    /** Create a new workflow from a workflow definition. */
    async createWorkflow(opts: { body: CreateWorkflowRequest }): Promise<WorkflowResponse> {
        return this.request<WorkflowResponse>("POST", "/workflow/create/definition", { json: opts.body });
    }

    /** Soft-delete a knowledge-base document and its chunks. */
    async deleteKbDocument(documentUuid: string): Promise<unknown> {
        return this.request("DELETE", `/knowledge-base/documents/${documentUuid}`);
    }

    /** Soft-delete a recording. */
    async deleteRecording(recordingId: string): Promise<unknown> {
        return this.request("DELETE", `/workflow-recordings/${recordingId}`);
    }

    /** Soft-delete a tool definition. */
    async deleteTool(toolUuid: string): Promise<unknown> {
        return this.request("DELETE", `/tools/${toolUuid}`);
    }

    /** Get a campaign by id. */
    async getCampaign(campaignId: number): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("GET", `/campaign/${campaignId}`);
    }

    /** Get aggregate progress (calls placed, completed, success rate). */
    async getCampaignProgress(campaignId: number): Promise<CampaignProgressResponse> {
        return this.request<CampaignProgressResponse>("GET", `/campaign/${campaignId}/progress`);
    }

    /** Download a CSV report of campaign outcomes. */
    async getCampaignReport(campaignId: number, opts: { startDate?: string; endDate?: string } = {}): Promise<unknown> {
        const params: Record<string, unknown> = {
            ...(opts.startDate !== undefined ? { "start_date": opts.startDate } : {}),
            ...(opts.endDate !== undefined ? { "end_date": opts.endDate } : {}),
        };
        return this.request("GET", `/campaign/${campaignId}/report`, { params });
    }

    /** Get a pre-signed URL to download the campaign's source CSV. */
    async getCampaignSourceUrl(campaignId: number): Promise<CampaignSourceDownloadResponse> {
        return this.request<CampaignSourceDownloadResponse>("GET", `/campaign/${campaignId}/source-download-url`);
    }

    /** Daily call-volume and disposition report for an organization, optionally filtered by workflow. */
    async getDailyReport(opts: { date?: string; timezone?: string; workflowId?: number } = {}): Promise<DailyReportResponse> {
        const params: Record<string, unknown> = {
            ...(opts.date !== undefined ? { "date": opts.date } : {}),
            ...(opts.timezone !== undefined ? { "timezone": opts.timezone } : {}),
            ...(opts.workflowId !== undefined ? { "workflow_id": opts.workflowId } : {}),
        };
        return this.request<DailyReportResponse>("GET", "/organizations/reports/daily", { params });
    }

    /** Get knowledge-base document details (processing status, chunks, metadata). */
    async getKbDocument(documentUuid: string): Promise<DocumentResponseSchema> {
        return this.request<DocumentResponseSchema>("GET", `/knowledge-base/documents/${documentUuid}`);
    }

    /** Fetch a single node spec by name. */
    async getNodeType(name: string): Promise<NodeSpec> {
        return this.request<NodeSpec>("GET", `/node-types/${name}`);
    }

    /** Get the active persistent embed_token for a workflow, if one exists. */
    async getPersistentEmbedToken(workflowId: number): Promise<unknown> {
        return this.request("GET", `/workflow/${workflowId}/embed-token`);
    }

    /** Get a tool definition by UUID. */
    async getTool(toolUuid: string): Promise<ToolResponse> {
        return this.request<ToolResponse>("GET", `/tools/${toolUuid}`);
    }

    /** Get a single workflow by ID (returns draft if one exists, else published). */
    async getWorkflow(workflowId: number): Promise<WorkflowResponse> {
        return this.request<WorkflowResponse>("GET", `/workflow/fetch/${workflowId}`);
    }

    /** List runs (one per dialed lead) for a campaign. */
    async listCampaignRuns(campaignId: number, opts: { page?: number; limit?: number; filters?: string; sortBy?: string; sortOrder?: string } = {}): Promise<CampaignRunsResponse> {
        const params: Record<string, unknown> = {
            ...(opts.page !== undefined ? { "page": opts.page } : {}),
            ...(opts.limit !== undefined ? { "limit": opts.limit } : {}),
            ...(opts.filters !== undefined ? { "filters": opts.filters } : {}),
            ...(opts.sortBy !== undefined ? { "sort_by": opts.sortBy } : {}),
            ...(opts.sortOrder !== undefined ? { "sort_order": opts.sortOrder } : {}),
        };
        return this.request<CampaignRunsResponse>("GET", `/campaign/${campaignId}/runs`, { params });
    }

    /** List all campaigns in the organization. */
    async listCampaigns(): Promise<CampaignsResponse> {
        return this.request<CampaignsResponse>("GET", "/campaign/");
    }

    /** List webhook credentials available to the authenticated organization. */
    async listCredentials(): Promise<CredentialResponse[]> {
        return this.request<CredentialResponse[]>("GET", "/credentials/");
    }

    /** Per-run detail (phone number, disposition, duration) for a given day. */
    async listDailyRuns(opts: { date?: string; timezone?: string; workflowId?: number } = {}): Promise<WorkflowRunDetail[]> {
        const params: Record<string, unknown> = {
            ...(opts.date !== undefined ? { "date": opts.date } : {}),
            ...(opts.timezone !== undefined ? { "timezone": opts.timezone } : {}),
            ...(opts.workflowId !== undefined ? { "workflow_id": opts.workflowId } : {}),
        };
        return this.request<WorkflowRunDetail[]>("GET", "/organizations/reports/daily/runs", { params });
    }

    /** List knowledge base documents available to the authenticated organization. */
    async listDocuments(opts: { status?: string; limit?: number; offset?: number } = {}): Promise<DocumentListResponseSchema> {
        const params: Record<string, unknown> = {
            ...(opts.status !== undefined ? { "status": opts.status } : {}),
            ...(opts.limit !== undefined ? { "limit": opts.limit } : {}),
            ...(opts.offset !== undefined ? { "offset": opts.offset } : {}),
        };
        return this.request<DocumentListResponseSchema>("GET", "/knowledge-base/documents", { params });
    }

    /** List every registered node type with its spec. Pinned to spec_version. */
    async listNodeTypes(): Promise<NodeTypesResponse> {
        return this.request<NodeTypesResponse>("GET", "/node-types");
    }

    /** List workflow recordings available to the authenticated organization. */
    async listRecordings(opts: { workflowId?: number; ttsProvider?: string; ttsModel?: string; ttsVoiceId?: string } = {}): Promise<RecordingListResponseSchema> {
        const params: Record<string, unknown> = {
            ...(opts.workflowId !== undefined ? { "workflow_id": opts.workflowId } : {}),
            ...(opts.ttsProvider !== undefined ? { "tts_provider": opts.ttsProvider } : {}),
            ...(opts.ttsModel !== undefined ? { "tts_model": opts.ttsModel } : {}),
            ...(opts.ttsVoiceId !== undefined ? { "tts_voice_id": opts.ttsVoiceId } : {}),
        };
        return this.request<RecordingListResponseSchema>("GET", "/workflow-recordings/", { params });
    }

    /** List the org's telephony provider configurations (Twilio, Plivo, etc.) with phone-number counts. Sensitive credential fields are masked server-side before return. */
    async listTelephonyConfigs(): Promise<TelephonyConfigurationListResponse> {
        return this.request<TelephonyConfigurationListResponse>("GET", "/organizations/telephony-configs");
    }

    /** List tools available to the authenticated organization. */
    async listTools(opts: { status?: string; category?: string } = {}): Promise<ToolResponse[]> {
        const params: Record<string, unknown> = {
            ...(opts.status !== undefined ? { "status": opts.status } : {}),
            ...(opts.category !== undefined ? { "category": opts.category } : {}),
        };
        return this.request<ToolResponse[]>("GET", "/tools/", { params });
    }

    /** List all workflows in the authenticated organization. */
    async listWorkflows(opts: { status?: string } = {}): Promise<WorkflowListResponse[]> {
        const params: Record<string, unknown> = {
            ...(opts.status !== undefined ? { "status": opts.status } : {}),
        };
        return this.request<WorkflowListResponse[]>("GET", "/workflow/fetch", { params });
    }

    /** Pause an in-progress campaign run. */
    async pauseCampaign(campaignId: number): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("POST", `/campaign/${campaignId}/pause`);
    }

    /** Trigger async parsing/embedding of an uploaded knowledge-base document. */
    async processKbDocument(opts: { body: ProcessDocumentRequestSchema }): Promise<DocumentResponseSchema> {
        return this.request<DocumentResponseSchema>("POST", "/knowledge-base/process-document", { json: opts.body });
    }

    /** Re-attempt unanswered or failed calls in a campaign. */
    async redialCampaign(campaignId: number, opts: { body: RedialCampaignRequest }): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("POST", `/campaign/${campaignId}/redial`, { json: opts.body });
    }

    /** Resume a paused campaign run. */
    async resumeCampaign(campaignId: number): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("POST", `/campaign/${campaignId}/resume`);
    }

    /** Deactivate the workflow's persistent embed_token. */
    async revokePersistentEmbedToken(workflowId: number): Promise<unknown> {
        return this.request("DELETE", `/workflow/${workflowId}/embed-token`);
    }

    /** Semantic search against the knowledge base; returns matching chunks. */
    async searchKb(opts: { body: ChunkSearchRequestSchema }): Promise<ChunkSearchResponseSchema> {
        return this.request<ChunkSearchResponseSchema>("POST", "/knowledge-base/search", { json: opts.body });
    }

    /** Start a campaign run. */
    async startCampaign(campaignId: number): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("POST", `/campaign/${campaignId}/start`);
    }

    /** Place a test call from a workflow to a phone number. */
    async testPhoneCall(opts: { body: InitiateCallRequest }): Promise<unknown> {
        return this.request("POST", "/telephony/initiate-call", { json: opts.body });
    }

    /** Restore a soft-deleted tool definition. */
    async unarchiveTool(toolUuid: string): Promise<ToolResponse> {
        return this.request<ToolResponse>("POST", `/tools/${toolUuid}/unarchive`);
    }

    /** Update mutable fields on a campaign. */
    async updateCampaign(campaignId: number, opts: { body: UpdateCampaignRequest }): Promise<CampaignResponse> {
        return this.request<CampaignResponse>("PATCH", `/campaign/${campaignId}`, { json: opts.body });
    }

    /** Rename a recording (recording_id slug); cascades to workflow definitions referencing it. */
    async updateRecording(id: number, opts: { body: RecordingUpdateRequestSchema }): Promise<RecordingResponseSchema> {
        return this.request<RecordingResponseSchema>("PATCH", `/workflow-recordings/${id}`, { json: opts.body });
    }

    /** Update an existing tool definition. */
    async updateTool(toolUuid: string, opts: { body: UpdateToolRequest }): Promise<ToolResponse> {
        return this.request<ToolResponse>("PUT", `/tools/${toolUuid}`, { json: opts.body });
    }

    /** Update a workflow's name and/or definition. Saves as a new draft. */
    async updateWorkflow(workflowId: number, opts: { body: UpdateWorkflowRequest }): Promise<WorkflowResponse> {
        return this.request<WorkflowResponse>("PUT", `/workflow/${workflowId}`, { json: opts.body });
    }
}
