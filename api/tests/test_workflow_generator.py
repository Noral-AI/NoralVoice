"""Tests for local workflow generation (api.services.workflow.workflow_generator).

Covers the deterministic assembly that turns the LLM's forgiving intermediate
JSON into a strict, schema-valid ReactFlow definition, plus the
generate/validate/retry loop with the LLM call stubbed out.
"""

import pytest

from api.services.workflow import workflow_generator as wg
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.workflow_generator import (
    WorkflowGenerationError,
    _assemble_definition,
    _coerce_extraction,
    generate_workflow_definition,
)


def _valid_spec() -> dict:
    return {
        "name": "Lead Qualifier",
        "global_prompt": "You are Sarah from Acme. Be warm and brief.",
        "nodes": [
            {
                "id": "start",
                "type": "startCall",
                "name": "Greeting",
                "prompt": "Greet the caller and ask how you can help.",
                "greeting": "Hi, this is Sarah from Acme.",
            },
            {
                "id": "qualify",
                "type": "agentNode",
                "name": "Qualify",
                "prompt": "Ask about budget and timeline.",
                "extraction": [
                    {"name": "budget_usd", "type": "number", "hint": "stated budget"},
                ],
            },
            {
                "id": "end",
                "type": "endCall",
                "name": "Wrap",
                "prompt": "Thank them and end the call.",
            },
        ],
        "edges": [
            {
                "from": "start",
                "to": "qualify",
                "label": "begin",
                "condition": "Caller is ready to talk.",
            },
            {
                "from": "qualify",
                "to": "end",
                "label": "done",
                "condition": "Budget captured.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# _coerce_extraction
# ---------------------------------------------------------------------------


class TestCoerceExtraction:
    def test_empty_or_missing(self):
        assert _coerce_extraction(None) == (False, None)
        assert _coerce_extraction([]) == (False, None)
        assert _coerce_extraction("nope") == (False, None)

    def test_normalizes_variables_and_defaults_type(self):
        enabled, variables = _coerce_extraction(
            [
                {"name": "budget", "type": "number", "hint": "the budget"},
                {"name": "weird", "type": "bogus"},  # invalid type -> string
                {"hint": "no name"},  # dropped
            ]
        )
        assert enabled is True
        assert variables == [
            {"name": "budget", "type": "number", "prompt": "the budget"},
            {"name": "weird", "type": "string", "prompt": None},
        ]


# ---------------------------------------------------------------------------
# _assemble_definition
# ---------------------------------------------------------------------------


class TestAssembleDefinition:
    def test_happy_path_is_schema_valid(self):
        d = _assemble_definition(_valid_spec())
        # The authoritative gate — must validate against the runtime schema.
        ReactFlowDTO.model_validate(d)

        types = [n["type"] for n in d["nodes"]]
        assert types == ["globalNode", "startCall", "agentNode", "endCall"]

        start = next(n for n in d["nodes"] if n["type"] == "startCall")
        assert start["data"]["is_start"] is True
        assert start["data"]["greeting_type"] == "text"

        end = next(n for n in d["nodes"] if n["type"] == "endCall")
        assert end["data"]["is_end"] is True

        qualify = next(n for n in d["nodes"] if n["id"] == "qualify")
        assert qualify["data"]["extraction_enabled"] is True
        assert [v["name"] for v in qualify["data"]["extraction_variables"]] == [
            "budget_usd"
        ]

        assert [(e["source"], e["target"]) for e in d["edges"]] == [
            ("start", "qualify"),
            ("qualify", "end"),
        ]

    def test_no_global_node_when_global_prompt_empty(self):
        spec = _valid_spec()
        spec["global_prompt"] = ""
        d = _assemble_definition(spec)
        assert all(n["type"] != "globalNode" for n in d["nodes"])

    def test_rejects_no_nodes(self):
        with pytest.raises(WorkflowGenerationError):
            _assemble_definition({"nodes": [], "edges": []})

    def test_rejects_multiple_start_nodes(self):
        spec = {
            "nodes": [
                {"id": "a", "type": "startCall", "prompt": "x"},
                {"id": "b", "type": "startCall", "prompt": "y"},
            ],
            "edges": [],
        }
        with pytest.raises(WorkflowGenerationError, match="exactly one startCall"):
            _assemble_definition(spec)

    def test_rejects_unsupported_node_type(self):
        spec = {
            "nodes": [{"id": "a", "type": "startCall", "prompt": "x"}, {"id": "w", "type": "webhook"}],
            "edges": [],
        }
        with pytest.raises(WorkflowGenerationError, match="unsupported type"):
            _assemble_definition(spec)

    def test_rejects_missing_prompt(self):
        spec = {"nodes": [{"id": "a", "type": "startCall", "prompt": "  "}], "edges": []}
        with pytest.raises(WorkflowGenerationError, match="missing a prompt"):
            _assemble_definition(spec)

    def test_rejects_edge_to_unknown_node(self):
        spec = {
            "nodes": [{"id": "a", "type": "startCall", "prompt": "x"}],
            "edges": [{"from": "a", "to": "ghost", "label": "l", "condition": "c"}],
        }
        with pytest.raises(WorkflowGenerationError, match="unknown node"):
            _assemble_definition(spec)

    def test_duplicate_ids_are_disambiguated(self):
        spec = {
            "nodes": [
                {"id": "n", "type": "startCall", "prompt": "x"},
                {"id": "n", "type": "agentNode", "prompt": "y"},
            ],
            "edges": [],
        }
        d = _assemble_definition(spec)
        ids = [n["id"] for n in d["nodes"]]
        assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# generate_workflow_definition (LLM stubbed)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_llm_config(monkeypatch):
    async def _resolve(_user_id):
        return ("openai", "gpt-4.1", "sk-test", {})

    monkeypatch.setattr(wg, "resolve_user_llm_config_by_id", _resolve)


class TestGenerateWorkflowDefinition:
    async def test_returns_name_and_definition(self, monkeypatch, stub_llm_config):
        import json

        async def _fake_inference(*args, **kwargs):
            return json.dumps(_valid_spec())

        monkeypatch.setattr(wg, "_run_inference", _fake_inference)

        result = await generate_workflow_definition(
            call_type="INBOUND",
            use_case="Lead Qualification",
            activity_description="Qualify inbound leads.",
            user_id=1,
        )
        assert result["name"] == "Lead Qualifier"
        ReactFlowDTO.model_validate(result["workflow_definition"])

    async def test_retries_then_succeeds(self, monkeypatch, stub_llm_config):
        import json

        calls = {"n": 0}

        async def _fake_inference(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return "this is not json"
            return json.dumps(_valid_spec())

        monkeypatch.setattr(wg, "_run_inference", _fake_inference)

        result = await generate_workflow_definition(
            call_type="OUTBOUND",
            use_case="Survey",
            activity_description="Run a short survey.",
            user_id=1,
        )
        assert calls["n"] == 2
        ReactFlowDTO.model_validate(result["workflow_definition"])

    async def test_raises_after_two_bad_attempts(self, monkeypatch, stub_llm_config):
        async def _fake_inference(*args, **kwargs):
            return "still not json"

        monkeypatch.setattr(wg, "_run_inference", _fake_inference)

        with pytest.raises(WorkflowGenerationError):
            await generate_workflow_definition(
                call_type="INBOUND",
                use_case="x",
                activity_description="y",
                user_id=1,
            )

    async def test_raises_when_no_api_key(self, monkeypatch):
        async def _resolve(_user_id):
            return ("openai", "gpt-4.1", "", {})

        monkeypatch.setattr(wg, "resolve_user_llm_config_by_id", _resolve)

        with pytest.raises(WorkflowGenerationError, match="No LLM is configured"):
            await generate_workflow_definition(
                call_type="INBOUND",
                use_case="x",
                activity_description="y",
                user_id=1,
            )
