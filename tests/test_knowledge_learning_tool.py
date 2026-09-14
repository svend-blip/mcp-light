"""Tests for the read-only ``knowledge_learning`` tool.

Every test replaces ``server._knowledge_http_get``; none talks to a live
service. The tool answers one of the service's three learning routes --
``GET /v1/learning``, the same route with ``history=true``, and
``GET /v1/learning/drafts`` (plus ``pending=true``) -- passes the service's rows
through unchanged, filters by ``family`` on this side of the wire, and turns
every transport outcome into JSON instead of raising.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402

ARTIFACTS = [
    {"family": "2000", "run": "041", "topic": "Budget split is a resolver rule",
     "evidence_level": "tests", "confidence": "medium", "admitted_by": "svend",
     "supersedes": "2000/040"},
    {"family": "9000", "run": "021", "topic": "Supervisor owns admission",
     "evidence_level": "approved_architecture", "confidence": "high",
     "admitted_by": "svend", "supersedes": None},
]

DRAFTS = [
    {"family": "2000", "run": "042", "topic": "Draft budget split",
     "evidence_level": "tests", "run_status": "SUCCESS", "admitted": False,
     "valid": True, "violations": 0},
    {"family": "9000", "run": "022", "topic": "Draft admission rule",
     "evidence_level": "observation", "run_status": "SUCCESS", "admitted": True,
     "valid": True, "violations": 0},
]

DRAFTS_URL_SUFFIX = "/v1/learning/drafts"


def _learning_service(replies=None):
    """Return ``(calls, fake_get)`` answering both learning routes.

    ``replies`` maps ``"admitted"`` (shared by ``admitted`` and ``history``) and
    ``"drafts"`` to a payload, a ``(status, payload)`` pair, or a callable
    producing one. Without an entry the fake mirrors the service: the drafts
    route wraps in ``{"drafts": [...]}``, the learning route in
    ``{"artifacts": [...]}``.
    """
    calls = []
    overrides = dict(replies or {})

    def fake_get(url, params, timeout, headers=None):
        calls.append({"url": url, "params": dict(params), "timeout": timeout,
                      "headers": dict(headers or {})})
        is_drafts = url.endswith(DRAFTS_URL_SUFFIX)
        reply = overrides.get("drafts" if is_drafts else "admitted")
        if reply is None:
            reply = {"drafts": DRAFTS} if is_drafts else {"artifacts": ARTIFACTS}
        if callable(reply):
            reply = reply()
        if isinstance(reply, tuple):
            return reply
        return 200, reply

    return calls, fake_get


def _install(monkeypatch, fake_get):
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")


def test_learning_tool_lists_admitted_by_default(monkeypatch):
    """Default view: one call to ``<base>/v1/learning`` with no params."""
    calls, fake_get = _learning_service()
    _install(monkeypatch, fake_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "sekret")

    result = json.loads(ml.tool_knowledge_learning())

    assert len(calls) == 1
    assert calls[0]["url"] == "http://127.0.0.1:9999/v1/learning"
    assert calls[0]["params"] == {}
    assert calls[0]["timeout"] == 30
    assert calls[0]["headers"] == {"X-Knowledge-Token": "sekret"}
    assert result["view"] == "admitted"
    assert result["count"] == len(ARTIFACTS)
    # Rows pass through unchanged: the service's order and fields survive.
    assert result["artifacts"] == ARTIFACTS

    # A bare list answer reads the same as the wrapped one.
    bare_calls, bare_get = _learning_service({"admitted": ARTIFACTS})
    _install(monkeypatch, bare_get)
    bare = json.loads(ml.tool_knowledge_learning(view="admitted"))
    assert len(bare_calls) == 1
    assert bare == {"view": "admitted", "count": len(ARTIFACTS),
                    "artifacts": ARTIFACTS}

    # No token configured -> no header.
    notoken_calls, notoken_get = _learning_service()
    monkeypatch.setattr(ml, "_knowledge_http_get", notoken_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")
    monkeypatch.delenv("KNOWLEDGE_SERVICE_TOKEN", raising=False)
    json.loads(ml.tool_knowledge_learning())
    assert notoken_calls[0]["headers"] == {}


def test_learning_tool_history_and_drafts_views_target_their_routes(monkeypatch):
    """``history`` adds ``history=true``; ``drafts`` uses its own route."""
    calls, fake_get = _learning_service()
    _install(monkeypatch, fake_get)

    history = json.loads(ml.tool_knowledge_learning(view="history"))
    drafts = json.loads(ml.tool_knowledge_learning(view="drafts"))
    pending = json.loads(ml.tool_knowledge_learning(view="drafts",
                                                   pending_only=True))
    off = json.loads(ml.tool_knowledge_learning(view="drafts",
                                               pending_only="false"))

    assert calls[0]["url"] == "http://127.0.0.1:9999/v1/learning"
    assert calls[0]["params"] == {"history": "true"}
    assert calls[1]["url"] == f"http://127.0.0.1:9999{DRAFTS_URL_SUFFIX}"
    assert calls[1]["params"] == {}
    assert calls[2]["params"] == {"pending": "true"}
    # An off flag leaves the parameter out rather than sending "false".
    assert calls[3]["params"] == {}

    assert history["view"] == "history"
    assert history["count"] == len(ARTIFACTS)
    assert history["artifacts"] == ARTIFACTS
    assert drafts == {"view": "drafts", "count": len(DRAFTS), "drafts": DRAFTS}
    assert pending["view"] == "drafts"
    assert pending["drafts"] == DRAFTS


def test_learning_tool_family_filter_is_client_side(monkeypatch):
    """``family`` narrows the rows here; the query string stays untouched."""
    calls, fake_get = _learning_service()
    _install(monkeypatch, fake_get)

    answer = json.loads(ml.tool_knowledge_learning(view="admitted", family="9000"))

    assert calls[0]["params"] == {}
    assert answer["count"] == 1
    assert [row["run"] for row in answer["artifacts"]] == ["021"]

    drafts = json.loads(ml.tool_knowledge_learning(view="drafts",
                                                  pending_only=True,
                                                  family="2000"))
    assert calls[1]["params"] == {"pending": "true"}
    assert drafts["count"] == 1
    assert drafts["drafts"][0]["run"] == "042"

    empty = json.loads(ml.tool_knowledge_learning(view="admitted",
                                                 family="no-such-family"))
    assert empty == {"view": "admitted", "count": 0, "artifacts": []}


def test_learning_tool_unknown_view_and_errors_are_reported_not_raised(monkeypatch):
    """Unknown view answers without a call; every transport outcome is JSON."""
    calls, fake_get = _learning_service()
    _install(monkeypatch, fake_get)

    unknown = json.loads(ml.tool_knowledge_learning(view="everything"))
    assert unknown["error"] == "unknown view"
    assert unknown["detail"]
    assert calls == []

    # Surrounding whitespace and case still name a real view.
    spaced = json.loads(ml.tool_knowledge_learning(view=" Drafts "))
    assert spaced["view"] == "drafts"
    assert calls[0]["url"] == f"http://127.0.0.1:9999{DRAFTS_URL_SUFFIX}"

    monkeypatch.setattr(ml, "_knowledge_http_get",
                        lambda *a, **k: (503, {"detail": "provider starting"}))
    not_ready = json.loads(ml.tool_knowledge_learning())
    assert not_ready == {"error": "not_ready", "detail": "provider starting"}

    def boom(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(ml, "_knowledge_http_get", boom)
    unreachable = json.loads(ml.tool_knowledge_learning(view="drafts",
                                                       pending_only=True))
    assert unreachable["error"] == "unreachable"
    assert "no route to host" in unreachable["detail"]
