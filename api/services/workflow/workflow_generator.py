"""Generate a voice-agent workflow from a natural-language description.

This replaces the dependency on the hosted Dograh MPS workflow-generation
service (``services.dograh.com/api/v1/workflow/create-workflow``) with local
generation driven by the *user's own* configured LLM — the same provider,
model, and key used to run their calls. That removes the cross-service
service-key handshake that was returning 401 for self-hosted deployments and
lets a user build a workflow end to end without any external dependency.

The LLM is asked for a small, forgiving intermediate JSON shape (nodes with a
type/prompt, edges with a condition). This module then assembles the strict
``ReactFlowDTO`` deterministically — minting node/edge ids, canvas positions,
and the boundary flags — so the model never has to get ReactFlow plumbing
exactly right. The assembled definition is validated against ``ReactFlowDTO``;
on failure the validation error is fed back for a single retry.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from loguru import logger
from pipecat.processors.aggregators.llm_context import LLMContext

from api.services.gen_ai.json_parser import parse_llm_json
from api.services.pipecat.service_factory import create_llm_service_from_provider
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.qa.llm_config import resolve_user_llm_config_by_id

# Node types the generator is allowed to emit. Triggers, webhooks, and QA
# nodes are intentionally excluded — they are advanced add-ons the author
# wires up later, not part of the core conversational spine.
_ALLOWED_NODE_TYPES = {"startCall", "agentNode", "endCall"}

# Canvas layout constants (purely cosmetic — the builder lets the user
# rearrange, and several layouts re-flow on load).
_COLUMN_X = 250.0
_ROW_GAP_Y = 200.0
_GLOBAL_X = -250.0


class WorkflowGenerationError(Exception):
    """Raised when the LLM cannot produce a usable workflow definition."""


_SYSTEM_PROMPT = """\
You are a generator for a voice AI platform. Given a use case, you design a \
conversational workflow that a voice agent follows during a phone call.

A workflow is a directed graph of NODES connected by EDGES.

NODE TYPES (use only these):
- "startCall": the entry point. Exactly ONE per workflow. Plays the opening \
turn. May carry an optional spoken "greeting". No edges may point INTO it.
- "agentNode": a focused mid-call step (e.g. "Qualify budget", "Book a \
demo"). Most workflows are a chain of these. Each must have at least one \
edge pointing INTO it.
- "endCall": a terminal step that wraps up and ends the call. No edges may \
leave it.

Each node has:
- "id": a short unique lowercase slug you assign (e.g. "start", "qualify", \
"book", "end").
- "type": one of the node types above.
- "name": a short human label (e.g. "Qualify Budget").
- "prompt": the system prompt telling the agent what to say/do in this step. \
Write voice-friendly instructions: short sentences, no special characters \
that cannot be spoken. Do NOT restate global persona here.
- "greeting" (startCall only, optional): the first thing spoken when the call \
connects.
- "extraction" (optional): a list of variables to capture from the caller in \
this step, each {"name": "snake_case", "type": "string"|"number"|"boolean", \
"hint": "what to look for"}. Captured variables can be referenced later in \
any prompt as {{variable_name}}.

EDGES connect nodes and describe WHEN the agent should move on. Each edge:
- "from": source node id.
- "to": target node id.
- "label": a short transition name (e.g. "interested", "not_interested").
- "condition": a natural-language description of when to take this edge \
(e.g. "The caller agreed to hear more"). The agent decides based on the \
conversation, so make conditions clear and mutually distinct.

There is also an optional "global_prompt": persona, tone, and shared rules \
that apply to the WHOLE call (e.g. "You are Sarah, a warm representative from \
Acme. Speak in short sentences."). Put shared persona here, not in every node.

RULES:
- Exactly one "startCall". At least one "agentNode". End the main path with \
an "endCall".
- Every non-start node must be reachable: it needs at least one incoming edge.
- Keep it focused: 3 to 6 nodes is usually right. Do not invent tools, \
phone numbers, or integrations.

OUTPUT FORMAT — return ONLY a single JSON object, no markdown fences, no \
commentary:
{
  "name": "<short workflow name>",
  "global_prompt": "<persona/tone for the whole call, or empty string>",
  "nodes": [ { "id": ..., "type": ..., "name": ..., "prompt": ..., \
"greeting": ..., "extraction": [...] }, ... ],
  "edges": [ { "from": ..., "to": ..., "label": ..., "condition": ... }, ... ]
}"""


def _build_user_message(
    call_type: str, use_case: str, activity_description: str
) -> str:
    direction = (
        "This is an INBOUND workflow: the caller dials in and the agent answers."
        if call_type.upper() == "INBOUND"
        else "This is an OUTBOUND workflow: the agent places the call to the caller."
    )
    return (
        f"{direction}\n\n"
        f"Use case: {use_case}\n\n"
        f"What the agent should do:\n{activity_description}\n\n"
        "Design the workflow now."
    )


def _coerce_extraction(raw: Any) -> tuple[bool, Optional[list[dict]]]:
    """Normalize an LLM "extraction" list into node-data fields."""
    if not isinstance(raw, list) or not raw:
        return False, None
    variables: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        var_type = item.get("type", "string")
        if var_type not in ("string", "number", "boolean"):
            var_type = "string"
        variables.append(
            {"name": str(name), "type": var_type, "prompt": item.get("hint")}
        )
    if not variables:
        return False, None
    return True, variables


def _assemble_definition(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn the LLM's intermediate JSON into a strict ReactFlow definition.

    Raises WorkflowGenerationError for structural problems we can detect
    before handing off to Pydantic (clearer messages for the retry prompt).
    """
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise WorkflowGenerationError("No nodes were produced.")

    seen_ids: set[str] = set()
    start_count = 0
    nodes: list[dict[str, Any]] = []

    # Optional global node first (laid out to the left of the spine).
    global_prompt = (spec.get("global_prompt") or "").strip()
    if global_prompt:
        nodes.append(
            {
                "id": "global",
                "type": "globalNode",
                "position": {"x": _GLOBAL_X, "y": 0.0},
                "data": {"name": "Global", "prompt": global_prompt},
            }
        )
        seen_ids.add("global")

    for idx, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise WorkflowGenerationError(f"Node #{idx} is not an object.")
        node_type = raw.get("type")
        if node_type not in _ALLOWED_NODE_TYPES:
            raise WorkflowGenerationError(
                f"Node #{idx} has unsupported type {node_type!r}."
            )
        node_id = str(raw.get("id") or f"node_{idx}")
        if node_id in seen_ids:
            node_id = f"{node_id}_{idx}"
        seen_ids.add(node_id)

        prompt = (raw.get("prompt") or "").strip()
        if not prompt:
            raise WorkflowGenerationError(
                f"Node {node_id!r} is missing a prompt."
            )

        data: dict[str, Any] = {
            "name": (raw.get("name") or node_id).strip() or node_id,
            "prompt": prompt,
        }

        extraction_enabled, variables = _coerce_extraction(raw.get("extraction"))
        if extraction_enabled:
            data["extraction_enabled"] = True
            data["extraction_variables"] = variables

        if node_type == "startCall":
            start_count += 1
            data["is_start"] = True
            greeting = (raw.get("greeting") or "").strip()
            if greeting:
                data["greeting"] = greeting
                data["greeting_type"] = "text"
        elif node_type == "endCall":
            data["is_end"] = True

        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "position": {"x": _COLUMN_X, "y": float(idx) * _ROW_GAP_Y},
                "data": data,
            }
        )

    if start_count != 1:
        raise WorkflowGenerationError(
            f"Expected exactly one startCall node, found {start_count}."
        )

    raw_edges = spec.get("edges") or []
    edges: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or "")
        target = str(raw.get("to") or "")
        if source not in seen_ids or target not in seen_ids:
            raise WorkflowGenerationError(
                f"Edge #{idx} references an unknown node "
                f"({source!r} -> {target!r})."
            )
        label = (raw.get("label") or "next").strip() or "next"
        condition = (raw.get("condition") or "").strip() or "Continue."
        edges.append(
            {
                "id": f"edge_{source}_{target}_{idx}",
                "source": source,
                "target": target,
                "data": {"label": label, "condition": condition},
            }
        )

    definition = {"nodes": nodes, "edges": edges}
    # Final authoritative gate: must satisfy the same schema the runtime loads.
    ReactFlowDTO.model_validate(definition)
    return definition


async def _run_inference(
    provider: str,
    model: str,
    api_key: str,
    service_kwargs: dict,
    user_message: str,
    repair_note: Optional[str] = None,
) -> str:
    llm = create_llm_service_from_provider(
        provider, model, api_key, **service_kwargs
    )
    system_prompt = _SYSTEM_PROMPT
    if repair_note:
        system_prompt = (
            f"{_SYSTEM_PROMPT}\n\nYour previous attempt was invalid: "
            f"{repair_note}\nFix it and return corrected JSON only."
        )
    context = LLMContext()
    context.set_messages([{"role": "user", "content": user_message}])
    response = await llm.run_inference(context, system_instruction=system_prompt)
    if not response:
        raise WorkflowGenerationError("The LLM returned an empty response.")
    return response


async def generate_workflow_definition(
    *,
    call_type: str,
    use_case: str,
    activity_description: str,
    user_id: int,
) -> dict[str, Any]:
    """Generate a workflow from a natural-language description.

    Args:
        call_type: "INBOUND" or "OUTBOUND".
        use_case: Short use-case label.
        activity_description: What the agent should do.
        user_id: Whose configured LLM to generate with.

    Returns:
        ``{"name": str, "workflow_definition": {"nodes": [...], "edges": [...]}}``
        — the same shape the route previously consumed from the MPS service.

    Raises:
        WorkflowGenerationError: if no usable workflow can be produced.
    """
    provider, model, api_key, service_kwargs = await resolve_user_llm_config_by_id(
        user_id
    )
    if not api_key:
        raise WorkflowGenerationError(
            "No LLM is configured for your account. Set up an LLM provider in "
            "settings before generating a workflow."
        )

    user_message = _build_user_message(call_type, use_case, activity_description)

    repair_note: Optional[str] = None
    last_error: Optional[str] = None
    for attempt in range(2):
        try:
            raw = await _run_inference(
                provider,
                model,
                api_key,
                service_kwargs,
                user_message,
                repair_note=repair_note,
            )
            spec = parse_llm_json(raw)
            if not isinstance(spec, dict):
                raise WorkflowGenerationError(
                    "Expected a JSON object describing the workflow."
                )
            definition = _assemble_definition(spec)
            name = (spec.get("name") or use_case).strip() or use_case
            return {"name": name, "workflow_definition": definition}
        except Exception as e:  # noqa: BLE001 — retry on any generation failure
            last_error = str(e)
            repair_note = last_error
            logger.warning(
                f"Workflow generation attempt {attempt + 1} failed: {e!r}"
            )

    raise WorkflowGenerationError(
        f"Could not generate a valid workflow after 2 attempts: {last_error}"
    )
