"""Tests for the knowledge_search tool (tool_knowledge_search).

Every test replaces ``server._knowledge_http_get``; none talks to a live
server. The tool must never raise: each transport outcome becomes JSON —
shaped success, empty-note, denied/not_ready/unreachable errors.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402


def test_scope_for_path_lowercases_the_directory_name():
    """Rule 1: lowercased final directory name, trailing slashes stripped."""
    assert ml.knowledge_scope_for_path("/tmp/x/FlowRunner/") == "flowrunner"
    assert ml.knowledge_scope_for_path("/home/x/AI_AdvisoryBoard") == "ai_advisoryboard"
    assert ml.knowledge_scope_for_path("/one/two/three///") == "three"


def test_scope_for_path_maps_the_dpmtf_checkout_to_dpmtf_webui():
    """Rule 1: the DPMtF checkout itself maps to dpmtf-webui by resolved path."""
    assert ml.knowledge_scope_for_path(ml.WEBUI_ROOT) == "dpmtf-webui"
    assert ml.knowledge_scope_for_path(ml.WEBUI_ROOT + "/") == "dpmtf-webui"


def test_current_repository_without_workspace_is_an_error(monkeypatch):
    """Rule 1: empty workspace -> error JSON, and the helper is never called."""
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(args)
        return 200, {"enabled": True, "results": []}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    result = json.loads(ml.tool_knowledge_search("how does dispatch work"))

    assert result["error"] == "workspace is required to resolve current_repository"
    assert "workspace" in result["error"]
    assert calls == []


def test_success_response_is_shaped_and_snippets_are_cut(monkeypatch):
    """Rule 3: shaped success; snippets are the content cut to 600 characters."""
    captured = {}
    long_content = "x" * 600 + "TAIL"
    payload = {
        "enabled": True,
        "provider": "leann",
        "bounded": True,
        "results": [
            {"path": "docs/a.md", "content": long_content, "score": 0.9, "scope": "flowrunner"},
            {"path": "docs/b.md", "content": "short body", "score": 0.4, "scope": "flowrunner"},
        ],
    }

    def fake_get(url, params, timeout):
        captured.update(url=url, params=params, timeout=timeout)
        return 200, payload

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setenv("DPMTF_KNOWLEDGE_BASE_URL", "http://127.0.0.1:9999")

    result = json.loads(ml.tool_knowledge_search(
        "How is a FlowApp exported?", workspace="/tmp/x/FlowRunner"))

    assert captured["url"] == "http://127.0.0.1:9999/api/knowledge/search"
    assert captured["timeout"] == 30
    assert captured["params"]["q"] == "How is a FlowApp exported?"
    assert captured["params"]["scope"] == "flowrunner"
    assert result["scope"] == "flowrunner"
    assert result["provider"] == "leann"
    assert result["count"] == 2
    assert len(result["results"]) == 2

    first = result["results"][0]
    assert set(first) == {"path", "score", "snippet"}
    assert first["path"] == "docs/a.md"
    assert first["score"] == 0.9
    assert len(first["snippet"]) == 600
    assert first["snippet"] == "x" * 600
    assert result["results"][1]["snippet"] == "short body"


def test_denied_and_not_ready_and_unreachable_are_reported_not_raised(monkeypatch):
    """Rule 4: 403 -> denied (+scope), 503 -> not_ready, else unreachable."""
    replies = iter([
        (403, {"detail": "scope guard denied dpmtf-webui for role dsh"}),
        (503, {"detail": "provider index is still building"}),
    ])

    def fake_get(url, params, timeout):
        return next(replies)

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    denied = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui"))
    assert denied == {
        "error": "denied",
        "scope": "dpmtf-webui",
        "detail": "scope guard denied dpmtf-webui for role dsh",
    }

    not_ready = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui"))
    assert not_ready["error"] == "not_ready"
    assert not_ready["detail"] == "provider index is still building"

    def raise_get(url, params, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(ml, "_knowledge_http_get", raise_get)

    unreachable = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui"))
    assert unreachable["error"] == "unreachable"
    assert "connection refused" in unreachable["detail"]


def test_disabled_layer_returns_an_empty_note(monkeypatch):
    """Rule 3: enabled:false -> empty results with the disabled note."""
    def fake_get(url, params, timeout):
        return 200, {"enabled": False, "provider": "leann", "results": [], "bounded": True}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    result = json.loads(ml.tool_knowledge_search("anything", workspace="/tmp/x/FlowRunner"))

    assert result == {
        "scope": "flowrunner",
        "count": 0,
        "results": [],
        "note": "knowledge retrieval is disabled in DPMtF",
    }


def test_bounds_are_clamped_before_the_call(monkeypatch):
    """Rule 5: top_k 1..20, token_budget 200..12000; short query never calls."""
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return 200, {"enabled": True, "provider": "leann", "results": []}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    ml.tool_knowledge_search("q?", top_k=99, token_budget=99999, workspace="/tmp/x/FlowRunner")
    ml.tool_knowledge_search("q?", top_k=0, token_budget=1, workspace="/tmp/x/FlowRunner")
    ml.tool_knowledge_search("q?", top_k="7", token_budget="300", workspace="/tmp/x/FlowRunner")

    assert len(calls) == 3
    assert calls[0]["top_k"] == 20 and calls[0]["token_budget"] == 12000
    assert calls[1]["top_k"] == 1 and calls[1]["token_budget"] == 200
    assert calls[2]["top_k"] == 7 and calls[2]["token_budget"] == 300

    too_short = json.loads(ml.tool_knowledge_search("q", workspace="/tmp/x/FlowRunner"))
    assert too_short == {"error": "query too short"}
    assert len(calls) == 3


def test_run_and_handoff_ids_are_forwarded(monkeypatch):
    """2.1: run_id and handoff_id reach the params; empty ones stay empty."""
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return 200, {"enabled": True, "provider": "leann", "results": []}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    ml.tool_knowledge_search("how does export work", workspace="/home/svend/FlowRunner",
                             run_id="trial-1b", handoff_id="g2")
    ml.tool_knowledge_search("how does export work", workspace="/home/svend/FlowRunner")

    assert calls[0]["run_id"] == "trial-1b"
    assert calls[0]["handoff_id"] == "g2"
    # Empty ids are left empty here; the helper omits empty params from the
    # query string, so they never reach the endpoint.
    assert calls[1]["run_id"] == ""
    assert calls[1]["handoff_id"] == ""


def test_flow_key_defaults_to_the_workspace_for_current_repository(monkeypatch):
    """2.1: empty flow_key under current_repository -> trimmed workspace path."""
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return 200, {"enabled": True, "provider": "leann", "results": []}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner/")

    assert calls[0]["flow_key"] == "/home/svend/FlowRunner"
    assert calls[0]["scope"] == "flowrunner"


def test_explicit_flow_key_wins_over_the_workspace_default(monkeypatch):
    """2.1: a non-empty flow_key is forwarded as-is, workspace default aside."""
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return 200, {"enabled": True, "provider": "leann", "results": []}

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner",
                             flow_key="9000-02-ELOOP")

    assert calls[0]["flow_key"] == "9000-02-ELOOP"
    assert calls[0]["scope"] == "flowrunner"
