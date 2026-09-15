"""Tests for the read-only ``knowledge_retrievals`` tool.

Every test replaces ``server._knowledge_http_get``; none talks to a live
service. The tool answers the service's ``GET /v1/retrievals`` through that one
seam: it puts only the filters that were given into the query string (plus the
always-present clamped ``limit``), clamps the limit to 1..200 before the call,
forwards ``summary=true``, shortens each row's ``query`` and ``sources`` so a
large page cannot flood a model's context, and turns every transport outcome
into JSON instead of raising.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402

ROWS = [
    {"created_at": "2026-09-15T09:12:04", "provider": "leann", "scope": "dpmtf-webui",
     "query": "supervisor owns admission", "result_count": 3,
     "sources": ["docs/a.md", "docs/b.md"], "retrieved_token_count": 412,
     "retrieval_duration_ms": 180, "agent_role": "dsh", "run_id": "046",
     "handoff_id": "H2", "flow_key": "9000-01-PLOOP"},
    {"created_at": "2026-09-15T08:02:11", "provider": "leann", "scope": "dpmtf",
     "query": "budget split", "result_count": 1, "sources": ["README.md"],
     "retrieved_token_count": 90, "retrieval_duration_ms": 121,
     "agent_role": "supervisor", "run_id": "045", "handoff_id": "H1",
     "flow_key": "9000-02-ELOOP"},
]

SUMMARY = {"retrievals": 4, "results": 11, "tokens": 2600, "duration_ms": 940,
           "scopes": ["dpmtf", "dpmtf-webui"], "agent_roles": ["dsh", "supervisor"],
           "first": "2026-09-15T08:02:11", "last": "2026-09-15T09:12:04"}


def _retrievals_service(reply=None):
    """Return ``(calls, fake_get)`` answering ``GET /v1/retrievals``.

    ``reply`` is a payload, a ``(status, payload)`` pair, or a callable
    producing one; without it the fake mirrors the service's rows envelope.
    """
    calls = []
    override = reply

    def fake_get(url, params, timeout, headers=None):
        calls.append({"url": url, "params": dict(params), "timeout": timeout,
                      "headers": dict(headers or {})})
        payload = override if override is not None else {
            "rows": ROWS, "total": len(ROWS), "limit": 20, "offset": 0}
        if callable(payload):
            payload = payload()
        if isinstance(payload, tuple):
            return payload
        return 200, payload

    return calls, fake_get


def _install(monkeypatch, fake_get):
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")


def test_retrievals_sends_only_the_set_filters_and_the_token_header(monkeypatch):
    """Set filters go into the query string; unset ones stay out."""
    calls, fake_get = _retrievals_service()
    _install(monkeypatch, fake_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "sekret")

    result = json.loads(ml.tool_knowledge_retrievals(run_id="046",
                                                    agent_role="dsh"))

    assert len(calls) == 1
    assert calls[0]["url"] == "http://127.0.0.1:9999/v1/retrievals"
    assert calls[0]["params"] == {"run_id": "046", "agent_role": "dsh",
                                 "limit": 20}
    assert calls[0]["timeout"] == 30
    assert calls[0]["headers"] == {"X-Knowledge-Token": "sekret"}
    # The service's rows envelope comes back with its paging keys intact.
    assert result["total"] == len(ROWS)
    assert [row["run_id"] for row in result["rows"]] == ["046", "045"]

    # Surrounding whitespace is trimmed; every other filter is still omitted.
    spaced = json.loads(ml.tool_knowledge_retrievals(run_id=" 046 ", flow_key=" "))
    assert calls[1]["params"] == {"run_id": "046", "limit": 20}
    assert spaced["total"] == len(ROWS)

    # No filter at all: only the clamped default limit is sent.
    bare = json.loads(ml.tool_knowledge_retrievals())
    assert calls[2]["params"] == {"limit": 20}
    assert bare["rows"] == ROWS

    # No token configured -> no header.
    notoken_calls, notoken_get = _retrievals_service()
    monkeypatch.setattr(ml, "_knowledge_http_get", notoken_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")
    monkeypatch.delenv("KNOWLEDGE_SERVICE_TOKEN", raising=False)
    json.loads(ml.tool_knowledge_retrievals(handoff_id="H2"))
    assert notoken_calls[0]["headers"] == {}
    assert notoken_calls[0]["params"] == {"handoff_id": "H2", "limit": 20}


def test_retrievals_clamps_the_limit_and_forwards_summary(monkeypatch):
    """``limit`` is clamped here before the call; ``summary`` adds one param."""
    calls, fake_get = _retrievals_service()
    _install(monkeypatch, fake_get)

    json.loads(ml.tool_knowledge_retrievals(limit=5000))
    json.loads(ml.tool_knowledge_retrievals(limit=0))
    json.loads(ml.tool_knowledge_retrievals(limit="7"))
    json.loads(ml.tool_knowledge_retrievals(limit="many"))

    assert [call["params"]["limit"] for call in calls] == [200, 1, 7, 20]

    summary_calls, summary_get = _retrievals_service({"rows": [], "total": 0,
                                                     **SUMMARY})
    _install(monkeypatch, summary_get)

    summary = json.loads(ml.tool_knowledge_retrievals(scope="dpmtf", summary=True))
    off = json.loads(ml.tool_knowledge_retrievals(scope="dpmtf", summary=False))
    text_flag = json.loads(ml.tool_knowledge_retrievals(scope="dpmtf",
                                                       summary="true"))
    off_text = json.loads(ml.tool_knowledge_retrievals(scope="dpmtf",
                                                      summary="false"))

    # Nothing else changes: the filter and the limit ride along unchanged.
    assert summary_calls[0]["params"] == {"scope": "dpmtf", "limit": 20,
                                         "summary": "true"}
    assert summary_calls[1]["params"] == {"scope": "dpmtf", "limit": 20}
    assert summary_calls[2]["params"] == {"scope": "dpmtf", "limit": 20,
                                         "summary": "true"}
    assert summary_calls[3]["params"] == {"scope": "dpmtf", "limit": 20}

    assert summary["retrievals"] == SUMMARY["retrievals"]
    assert summary["scopes"] == SUMMARY["scopes"]


def test_retrievals_truncates_long_queries_and_source_lists(monkeypatch):
    """Only ``query`` (200 chars) and ``sources`` (5 entries) are shortened."""
    long_query = "coordination note " + ("abcdefghijklmnop" * 12)   # 272 chars
    exact_query = "x" * 200
    many_sources = [f"docs/source-{index}.md" for index in range(1, 8)]
    payload = {"rows": [
        {"created_at": "2026-09-15T09:12:04", "query": long_query,
         "sources": many_sources, "run_id": "046", "result_count": 7},
        {"created_at": "2026-09-15T08:02:11", "query": exact_query,
         "sources": ["docs/only.md"], "run_id": "045", "result_count": 1},
    ], "total": 2, "limit": 20, "offset": 0}
    calls, fake_get = _retrievals_service(payload)
    _install(monkeypatch, fake_get)

    answer = json.loads(ml.tool_knowledge_retrievals(run_id="046"))

    assert len(calls) == 1
    first, second = answer["rows"]
    assert len(first["query"]) == ml.RETRIEVAL_QUERY_CHARS
    assert first["query"] == long_query[:ml.RETRIEVAL_QUERY_CHARS]
    assert first["sources"] == many_sources[:ml.RETRIEVAL_SOURCES_KEPT]
    # A row already inside the bounds is returned untouched.
    assert second["query"] == exact_query
    assert second["sources"] == ["docs/only.md"]
    # Everything the service wrote around the rows survives unchanged.
    assert first["run_id"] == "046"
    assert first["result_count"] == 7
    assert {k: v for k, v in answer.items() if k != "rows"} == {
        "total": 2, "limit": 20, "offset": 0}

    # A summary answer has no rows and passes through as written.
    summary_calls, summary_get = _retrievals_service({"rows": [], **SUMMARY})
    _install(monkeypatch, summary_get)
    assert json.loads(ml.tool_knowledge_retrievals(summary=True)) == {
        "rows": [], **SUMMARY}

    # A bare-list answer is returned as it came, without trimming.
    list_calls, list_get = _retrievals_service(ROWS)
    _install(monkeypatch, list_get)
    assert json.loads(ml.tool_knowledge_retrievals()) == ROWS


def test_retrievals_errors_are_reported_not_raised(monkeypatch):
    """Every transport outcome becomes the tool's typed JSON error dict."""
    calls, fake_get = _retrievals_service((403, {"detail": "scope guard denied"}))
    _install(monkeypatch, fake_get)

    denied = json.loads(ml.tool_knowledge_retrievals(scope="dpmtf"))
    assert denied == {"error": "denied", "detail": "scope guard denied"}
    assert len(calls) == 1

    monkeypatch.setattr(ml, "_knowledge_http_get",
                        lambda *a, **k: (404, {"detail": "no such scope"}))
    unknown = json.loads(ml.tool_knowledge_retrievals(scope="nope"))
    assert unknown == {"error": "unknown_scope", "detail": "no such scope"}

    monkeypatch.setattr(ml, "_knowledge_http_get",
                        lambda *a, **k: (503, {"detail": "provider starting"}))
    not_ready = json.loads(ml.tool_knowledge_retrievals(run_id="046"))
    assert not_ready == {"error": "not_ready", "detail": "provider starting"}

    # Any other status is unreachable with the status named.
    monkeypatch.setattr(ml, "_knowledge_http_get",
                        lambda *a, **k: (500, {"detail": "boom"}))
    broken = json.loads(ml.tool_knowledge_retrievals())
    assert broken == {"error": "unreachable", "detail": "HTTP 500"}

    # A raising seam is reported, not raised.
    def boom(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(ml, "_knowledge_http_get", boom)
    unreachable = json.loads(ml.tool_knowledge_retrievals(run_id="046",
                                                         summary=True))
    assert unreachable["error"] == "unreachable"
    assert "no route to host" in unreachable["detail"]
