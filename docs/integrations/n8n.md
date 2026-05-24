# Hidden n8n Automation Layer

NoralVoice can trigger workflows in a self-hosted n8n instance without exposing n8n to customers. NoralVoice owns the user experience, auth, organizations, roles, permissions, workflow selection, and customer-facing controls. n8n only runs backend automations after NoralVoice sends signed server-to-server webhook events.

Do not iframe n8n, redirect customers to n8n, or use n8n users/roles as the NoralVoice permission system.

## Required Environment Variables

Set these on the NoralVoice API server only:

```bash
N8N_ENABLED=true
N8N_BASE_URL=https://automation.noral.ai
N8N_WEBHOOK_SECRET=<shared webhook secret>
```

Optional:

```bash
N8N_API_KEY=<only if REST API calls are added later>
N8N_TIMEOUT_MS=10000
N8N_RETRY_COUNT=2
```

If `N8N_ENABLED` is missing or false, NoralVoice skips n8n safely. If enabled without `N8N_BASE_URL` or `N8N_WEBHOOK_SECRET`, triggers fail closed and log a non-secret configuration error.

## Webhook URL Pattern

NoralVoice sends POST requests to:

```text
{N8N_BASE_URL}/webhook/noralvoice/{event-slug}
```

Examples:

```text
POST /webhook/noralvoice/inbound-call-received
POST /webhook/noralvoice/call-completed
POST /webhook/noralvoice/lead-captured
POST /webhook/noralvoice/appointment-booked
POST /webhook/noralvoice/human-handoff-required
```

Internal event names are normalized to URL-safe slugs. For example, `CALL_COMPLETED` becomes `call-completed`.

## n8n Webhook Header Check

Every n8n webhook workflow should verify this header before doing work:

```text
X-Noral-Webhook-Secret: <shared webhook secret>
```

In n8n, add an IF node or Code node immediately after the Webhook trigger and compare `$headers["x-noral-webhook-secret"]` with the expected secret stored in n8n credentials or environment variables.

## Example Payload

```json
{
  "eventType": "CALL_COMPLETED",
  "source": "noralvoice",
  "occurredAt": "2026-05-24T12:00:00+00:00",
  "metadata": {
    "eventType": "CALL_COMPLETED",
    "source": "noralvoice",
    "companyId": 42,
    "accountId": 42,
    "callId": "CA123",
    "sessionId": 9001,
    "environment": "production"
  },
  "payload": {
    "companyId": 42,
    "accountId": 42,
    "agentId": 7,
    "workflowId": 7,
    "workflowRunId": 9001,
    "callId": "CA123",
    "sessionId": 9001,
    "direction": "inbound",
    "callerPhone": "+15551234567",
    "calleePhone": "+15557654321",
    "callStatus": "completed",
    "startedAt": "2026-05-24T11:58:00+00:00",
    "endedAt": "2026-05-24T12:00:00+00:00",
    "durationSeconds": 120,
    "recordingUrl": "recordings/9001.wav",
    "transcriptUrl": "transcripts/9001.txt",
    "summary": "Caller requested a roof repair estimate.",
    "disposition": "qualified_lead",
    "lead": {
      "firstName": "Avery",
      "lastName": "Stone",
      "phone": "+15551234567",
      "email": "avery@example.com",
      "serviceType": "roof repair",
      "urgency": "high"
    },
    "appointment": {
      "requestedDate": "2026-05-25",
      "confirmedDate": "2026-05-25T15:00:00-04:00",
      "calendarEventId": "evt_123"
    },
    "metadata": {
      "sourceProvider": "twilio",
      "rawProviderEventId": "CA123",
      "traceId": "trace_abc"
    }
  }
}
```

Transcript text is not included by default. Recording and transcript references are included when available so downstream workflows can decide whether to fetch them through approved NoralVoice access paths.

## Supported Events

- `INBOUND_CALL_RECEIVED`
- `CALL_STARTED`
- `CALL_COMPLETED`
- `MISSED_CALL`
- `VOICEMAIL_RECEIVED`
- `LEAD_CAPTURED`
- `APPOINTMENT_REQUESTED`
- `APPOINTMENT_BOOKED`
- `SMS_FOLLOW_UP_REQUESTED`
- `CRM_SYNC_REQUESTED`
- `HUMAN_HANDOFF_REQUIRED`
- `POST_CALL_SUMMARY_CREATED`
- `TRANSCRIPT_READY`
- `AGENT_ESCALATION`

## Diagnostics

Superusers can inspect non-secret status:

```text
GET /api/v1/integrations/n8n/status
```

Superusers can send a synthetic event:

```text
POST /api/v1/integrations/n8n/test
```

The diagnostics never return the webhook secret or API key.

## Recommended Production Setup

- Self-host n8n behind HTTPS.
- Use Postgres for n8n persistence.
- Use Redis and n8n queue mode if workflow volume grows.
- Keep n8n UI private through firewall rules, VPN, SSO, or private networking where possible.
- Restrict the NoralVoice API server to server-to-server access to n8n webhooks.
- Configure backups for n8n Postgres and credentials.
- Set execution retention limits so sensitive workflow data is not stored forever.
- Rotate `N8N_WEBHOOK_SECRET` if it is ever exposed.

## Security Warnings

- Do not expose n8n UI to NoralVoice customers.
- Do not use n8n as the NoralVoice permission system.
- Do not put customer users inside n8n unless licensing, tenancy, and security have been reviewed.
- Do not store n8n secrets in frontend code or public documentation.
- Do not log n8n secrets, API keys, or auth headers.
