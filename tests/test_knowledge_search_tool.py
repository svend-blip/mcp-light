"""Tests for the knowledge tools (tool_knowledge_search, tool_knowledge_scopes).

Every test replaces ``server._knowledge_http_get``; none talks to a live
service. The tools must never raise: each transport outcome becomes JSON —
shaped success, empty-note, denied/not_ready/unreachable errors. The service on
``KNOWLEDGE_SERVICE_URL`` owns the scope slug rule, so these tests assert which
route is spoken to, which headers ride along, and how often.

Trial 1d adds the three-scope default: by default ``knowledge_search`` speaks
to ``ecosystem``, then ``experience``, then the repository scope, splitting the
token budget 60/20/20 with the unused learning share flowing back. Tests that
check the single-call surface pass ``cross_repo=False``; the six trial 1d tests
below cover the spanning default.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402

EMPTY_SEARCH = {"enabled": True, "provider": "leann", "results": []}

# One hundred whitespace-split tokens, the shape the split-budget test measures.
HUNDRED_TOKENS = "w " * 100

REPO_SEARCH = {
    "enabled": True,
    "provider": "leann",
    "bounded": True,
    "results": [
        {"path": "docs/a.md", "content": "repository body", "score": 0.9,
         "scope": "flowrunner"},
    ],
}


def _fake_service(search_payload=None, slug=None):
    """Return ``(calls, fake_get)``; the fake answers both service routes.

    With ``slug`` unset the fake mirrors the service's own rule (last path
    segment, lowercased) so assertions read like real answers.
    """
    calls = []
    payload = EMPTY_SEARCH if search_payload is None else search_payload

    def fake_get(url, params, timeout, headers=None):
        call = {"url": url, "params": dict(params), "timeout": timeout,
                "headers": dict(headers or {})}
        calls.append(call)
        if url.endswith("/v1/scope-for-path"):
            resolved = slug or str(params.get("path") or "").rstrip("/").rsplit("/", 1)[-1]
            return 200, {"scope": resolved.lower()}
        return 200, payload

    return calls, fake_get


def _scoped_service(replies):
    """Return ``(calls, fake_get)`` answering ``/v1/search`` per requested scope.

    ``replies`` maps a scope name to a ``(status, payload)`` pair or to a
    callable producing one (for a reply that must raise).
    """
    calls = []

    def fake_get(url, params, timeout, headers=None):
        call = {"url": url, "params": dict(params), "timeout": timeout,
                "headers": dict(headers or {})}
        calls.append(call)
        if url.endswith("/v1/scope-for-path"):
            resolved = str(params.get("path") or "").rstrip("/").rsplit("/", 1)[-1]
            return 200, {"scope": resolved.lower()}
        reply = replies.get(str(params.get("scope")), EMPTY_SEARCH)
        if callable(reply):
            return reply()
        return reply

    return calls, fake_get


def _search_calls(calls):
    return [call for call in calls if call["url"].endswith("/v1/search")]


def _slug_calls(calls):
    return [call for call in calls if call["url"].endswith("/v1/scope-for-path")]


def _position(params):
    """The fields every call of one search must share."""
    return {key: params.get(key)
            for key in ("q", "top_k", "agent_role", "flow_key", "run_id", "handoff_id")}


def test_search_targets_the_service_v1_route_with_the_token_header(monkeypatch):
    """Rule 1+2: GET <base>/v1/search with today's params and X-Knowledge-Token."""
    calls, fake_get = _fake_service()
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "sekret")

    result = json.loads(ml.tool_knowledge_search(
        "How is a FlowApp exported?", scope="flowrunner", top_k=3, token_budget=900,
        agent_role="dsh", run_id="trial-1c", handoff_id="g2", cross_repo=False))

    search = _search_calls(calls)
    assert len(search) == 1
    assert search[0]["url"] == "http://127.0.0.1:9999/v1/search"
    assert search[0]["timeout"] == 30
    assert search[0]["headers"] == {"X-Knowledge-Token": "sekret"}
    assert search[0]["params"] == {
        "q": "How is a FlowApp exported?", "scope": "flowrunner", "top_k": 3,
        "token_budget": 900, "agent_role": "dsh", "flow_key": "",
        "run_id": "trial-1c", "handoff_id": "g2",
    }
    assert result["count"] == 0


def test_search_without_a_token_sends_no_header_and_uses_the_default_base(monkeypatch):
    """Rule 1: empty KNOWLEDGE_SERVICE_TOKEN -> no header; base defaults to :9140."""
    calls, fake_get = _fake_service()
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})
    monkeypatch.delenv("KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("KNOWLEDGE_SERVICE_TOKEN", raising=False)

    ml.tool_knowledge_search("export flowapp", scope="flowrunner")

    search = _search_calls(calls)
    assert search[0]["url"] == "http://127.0.0.1:9140/v1/search"
    assert search[0]["headers"] == {}


def test_current_repository_resolves_through_scope_for_path_once_per_workspace(monkeypatch):
    """Rule 3: one /v1/scope-for-path call per workspace, cached for the process."""
    calls, fake_get = _fake_service()
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    first = json.loads(ml.tool_knowledge_search("export flowapp",
                                                workspace="/home/svend/FlowRunner",
                                                cross_repo=False))
    second = json.loads(ml.tool_knowledge_search("import flowapp",
                                                 workspace="/home/svend/FlowRunner",
                                                 cross_repo=False))
    other = json.loads(ml.tool_knowledge_search("panels", workspace="/home/svend/DPMtF-WebUI",
                                                cross_repo=False))

    slugs = _slug_calls(calls)
    assert len(slugs) == 2
    assert slugs[0]["params"] == {"path": "/home/svend/FlowRunner"}
    assert slugs[1]["params"] == {"path": "/home/svend/DPMtF-WebUI"}
    assert first["scope"] == "flowrunner"
    assert second["scope"] == "flowrunner"
    assert other["scope"] == "dpmtf-webui"
    assert [c["params"]["scope"] for c in _search_calls(calls)] == [
        "flowrunner", "flowrunner", "dpmtf-webui"]


def test_scope_for_path_unreachable_is_reported_before_any_search(monkeypatch):
    """Rule 3: an unreachable service stops the search, unreachable is returned."""
    calls = []

    def raise_get(url, params, timeout, headers=None):
        calls.append(url)
        raise OSError("connection refused")

    monkeypatch.setattr(ml, "_knowledge_http_get", raise_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search("export flowapp",
                                                 workspace="/home/svend/FlowRunner"))

    assert result["error"] == "unreachable"
    assert "connection refused" in result["detail"]
    assert calls == ["http://127.0.0.1:9140/v1/scope-for-path"]


def test_current_repository_without_workspace_is_an_error(monkeypatch):
    """Rule 1: empty workspace -> error JSON, and the helper is never called."""
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(args)
        return 200, EMPTY_SEARCH

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search("how does dispatch work"))

    assert result["error"] == "workspace is required to resolve current_repository"
    assert "workspace" in result["error"]
    assert calls == []


def test_success_response_is_shaped_and_snippets_are_cut(monkeypatch):
    """Rule 2: shaped success; snippets are the content cut to 600 characters."""
    long_content = "x" * 600 + "TAIL"
    payload = {
        "enabled": True,
        "provider": "leann",
        "bounded": True,
        "results": [
            {"path": "docs/a.md", "content": long_content, "score": 0.9, "scope": "flowrunner"},
            {"path": "docs/b.md", "content": "short body", "score": 0.4, "scope": "flowrunner",
             "metadata": {"evidence_level": "observation"}},
        ],
    }
    calls, fake_get = _fake_service(payload)

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:9999")

    result = json.loads(ml.tool_knowledge_search(
        "How is a FlowApp exported?", workspace="/tmp/x/FlowRunner", cross_repo=False))

    search = _search_calls(calls)
    assert search[0]["url"] == "http://127.0.0.1:9999/v1/search"
    assert search[0]["timeout"] == 30
    assert search[0]["params"]["q"] == "How is a FlowApp exported?"
    assert result["scope"] == "flowrunner"
    assert result["provider"] == "leann"
    assert result["count"] == 2
    assert len(result["results"]) == 2

    first = result["results"][0]
    assert set(first) == {"scope", "path", "score", "snippet", "metadata"}
    assert first["path"] == "docs/a.md"
    assert first["score"] == 0.9
    assert first["scope"] == "flowrunner"
    assert len(first["snippet"]) == 600
    assert first["snippet"] == "x" * 600
    assert first["metadata"] == {}
    assert result["results"][1]["snippet"] == "short body"
    assert result["results"][1]["metadata"] == {"evidence_level": "observation"}
    assert result["scopes_searched"] == [
        {"scope": "flowrunner", "status": "ok", "count": 2}]


def test_denied_and_not_ready_and_unreachable_are_reported_not_raised(monkeypatch):
    """Rule 2: 403 -> denied (+scope), 404 -> unknown_scope, 503 -> not_ready, else unreachable."""
    replies = iter([
        (403, {"detail": "scope guard denied dpmtf-webui for role dsh"}),
        (404, {"detail": "unknown scope: dpmtf-webui"}),
        (503, {"detail": "provider index is still building"}),
    ])

    def fake_get(url, params, timeout, headers=None):
        return next(replies)

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    denied = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui",
                                                 cross_repo=False))
    assert denied == {
        "error": "denied",
        "scope": "dpmtf-webui",
        "detail": "scope guard denied dpmtf-webui for role dsh",
    }

    unknown = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui",
                                                  cross_repo=False))
    assert unknown == {
        "error": "unknown_scope",
        "scope": "dpmtf-webui",
        "detail": "unknown scope: dpmtf-webui",
    }

    not_ready = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui",
                                                    cross_repo=False))
    assert not_ready["error"] == "not_ready"
    assert not_ready["detail"] == "provider index is still building"

    def raise_get(url, params, timeout, headers=None):
        raise OSError("connection refused")

    monkeypatch.setattr(ml, "_knowledge_http_get", raise_get)

    unreachable = json.loads(ml.tool_knowledge_search("bridge dispatch", scope="dpmtf-webui",
                                                      cross_repo=False))
    assert unreachable["error"] == "unreachable"
    assert "connection refused" in unreachable["detail"]


def test_disabled_layer_returns_an_empty_note(monkeypatch):
    """Rule 2: enabled:false -> empty results with the disabled note."""
    calls, fake_get = _fake_service(
        {"enabled": False, "provider": "leann", "results": [], "bounded": True})

    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})
    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    result = json.loads(ml.tool_knowledge_search("anything", workspace="/tmp/x/FlowRunner"))

    assert result == {
        "scope": "flowrunner",
        "count": 0,
        "results": [],
        "note": "knowledge retrieval is disabled in DPMtF",
    }


def test_bounds_are_clamped_before_the_call(monkeypatch):
    """Rule 2: top_k 1..20, token_budget 200..12000; short query never calls."""
    calls, fake_get = _fake_service()

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    ml.tool_knowledge_search("q?", top_k=99, token_budget=99999, workspace="/tmp/x/FlowRunner",
                             cross_repo=False)
    ml.tool_knowledge_search("q?", top_k=0, token_budget=1, workspace="/tmp/x/FlowRunner",
                             cross_repo=False)
    ml.tool_knowledge_search("q?", top_k="7", token_budget="300", workspace="/tmp/x/FlowRunner",
                             cross_repo=False)

    search = _search_calls(calls)
    assert len(search) == 3
    assert search[0]["params"]["top_k"] == 20 and search[0]["params"]["token_budget"] == 12000
    assert search[1]["params"]["top_k"] == 1 and search[1]["params"]["token_budget"] == 200
    assert search[2]["params"]["top_k"] == 7 and search[2]["params"]["token_budget"] == 300

    too_short = json.loads(ml.tool_knowledge_search("q", workspace="/tmp/x/FlowRunner"))
    assert too_short == {"error": "query too short"}
    assert len(_search_calls(calls)) == 3


def test_run_and_handoff_ids_are_forwarded(monkeypatch):
    """2.1: run_id and handoff_id reach the params; empty ones stay empty."""
    calls, fake_get = _fake_service()

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    ml.tool_knowledge_search("how does export work", workspace="/home/svend/FlowRunner",
                             run_id="trial-1b", handoff_id="g2", cross_repo=False)
    ml.tool_knowledge_search("how does export work", workspace="/home/svend/FlowRunner",
                             cross_repo=False)

    search = _search_calls(calls)
    assert search[0]["params"]["run_id"] == "trial-1b"
    assert search[0]["params"]["handoff_id"] == "g2"
    # Empty ids are left empty here; the helper omits empty params from the
    # query string, so they never reach the endpoint.
    assert search[1]["params"]["run_id"] == ""
    assert search[1]["params"]["handoff_id"] == ""


def test_flow_key_defaults_to_the_workspace_for_current_repository(monkeypatch):
    """2.1: empty flow_key under current_repository -> trimmed workspace path."""
    calls, fake_get = _fake_service()

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner/",
                             cross_repo=False)

    search = _search_calls(calls)
    assert search[0]["params"]["flow_key"] == "/home/svend/FlowRunner"
    assert search[0]["params"]["scope"] == "flowrunner"
    assert _slug_calls(calls)[0]["params"]["path"] == "/home/svend/FlowRunner/"


def test_explicit_flow_key_wins_over_the_workspace_default(monkeypatch):
    """2.1: a non-empty flow_key is forwarded as-is, workspace default aside."""
    calls, fake_get = _fake_service()

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner",
                             flow_key="9000-02-ELOOP", cross_repo=False)

    search = _search_calls(calls)
    assert search[0]["params"]["flow_key"] == "9000-02-ELOOP"
    assert search[0]["params"]["scope"] == "flowrunner"


# ── Trial 1d: the three-scope default ──────────────────────────


def test_default_search_spans_ecosystem_experience_and_repository_with_the_split_budget(
        monkeypatch):
    """2.1+2.2: ecosystem + experience first (800 each), repository gets 3800."""
    ecosystem = {
        "enabled": True,
        "provider": "leann",
        "results": [
            {"path": "docs/architecture.md", "content": HUNDRED_TOKENS, "score": 0.7,
             "scope": "ecosystem",
             "metadata": {"origin": "flowrunner", "evidence_level": "measured_runtime"}},
        ],
    }
    experience = {
        "enabled": True,
        "provider": "leann",
        "results": [
            {"path": "2000/029", "content": HUNDRED_TOKENS, "score": 0.6,
             "scope": "experience",
             "metadata": {"evidence_level": "tests", "repository": "flowrunner",
                          "family": "2000", "run": "029", "confidence": "high"}},
        ],
    }
    calls, fake_get = _scoped_service({
        "ecosystem": (200, ecosystem),
        "experience": (200, experience),
        "flowrunner": (200, REPO_SEARCH),
    })

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search(
        "how does the harness export a FlowApp", workspace="/home/svend/FlowRunner",
        run_id="trial-1d", handoff_id="g1"))

    search = _search_calls(calls)
    assert len(search) == 3
    assert [c["params"]["scope"] for c in search] == ["ecosystem", "experience", "flowrunner"]
    # 20 % of the default budget for each learning call, spent first.
    assert search[0]["params"]["token_budget"] == 800
    assert search[1]["params"]["token_budget"] == 800
    # 60 % plus what the two learning calls left of their 800 (each used 100).
    assert search[2]["params"]["token_budget"] == 3800
    # Same position fields and top_k on every call.
    assert _position(search[0]) == _position(search[1]) == _position(search[2])

    assert result["scope"] == "flowrunner"
    assert result["provider"] == "leann"
    assert result["count"] == 3
    assert [hit["scope"] for hit in result["results"]] == [
        "flowrunner", "ecosystem", "experience"]
    assert [hit["path"] for hit in result["results"]] == ["docs/a.md", "docs/architecture.md",
                                                          "2000/029"]
    assert result["results"][0]["metadata"] == {}
    assert result["results"][1]["metadata"] == {"origin": "flowrunner",
                                                "evidence_level": "measured_runtime"}
    assert result["results"][2]["metadata"]["evidence_level"] == "tests"
    assert result["scopes_searched"] == [
        {"scope": "ecosystem", "status": "ok", "count": 1},
        {"scope": "experience", "status": "ok", "count": 1},
        {"scope": "flowrunner", "status": "ok", "count": 1},
    ]
    assert result["count"] == sum(entry["count"] for entry in result["scopes_searched"])


def test_cross_repo_false_and_explicit_learning_scopes_make_a_single_call(monkeypatch):
    """2.1: cross_repo false -> one repository call; a learning scope -> one call."""
    calls, fake_get = _scoped_service({
        "flowrunner": (200, REPO_SEARCH),
        "experience": (200, {
            "enabled": True, "provider": "portable",
            "results": [{"path": "9000/021", "content": "older note", "score": 0.5,
                         "scope": "experience",
                         "metadata": {"evidence_level": "observation"}}],
        }),
    })

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    narrowed = json.loads(ml.tool_knowledge_search("export flowapp", scope="flowrunner",
                                                   cross_repo=False))
    narrowed_calls = _search_calls(calls)
    assert len(narrowed_calls) == 1
    assert narrowed_calls[0]["params"]["scope"] == "flowrunner"
    assert "evidence_level" not in narrowed_calls[0]["params"]
    assert "include_history" not in narrowed_calls[0]["params"]
    assert narrowed["scope"] == "flowrunner"
    assert len(narrowed["scopes_searched"]) == 1

    learning = json.loads(ml.tool_knowledge_search("older conclusions", scope="experience",
                                                   evidence_level="observation",
                                                   include_history=True))
    learning_calls = _search_calls(calls)
    assert len(learning_calls) == 2
    params = learning_calls[1]["params"]
    assert params["scope"] == "experience"
    assert params["evidence_level"] == "observation"
    assert params["include_history"] == "true"
    assert learning["scope"] == "experience"
    assert learning["results"][0]["metadata"]["evidence_level"] == "observation"


def test_learning_scope_failures_never_fail_the_call(monkeypatch):
    """2.3: refused/raising/unknown/empty learning answers only show up in scopes_searched."""
    first, first_get = _scoped_service({
        "ecosystem": (403, {"detail": "scope guard denied ecosystem for role dsh"}),
        "experience": lambda: (_ for _ in ()).throw(OSError("experience store is closing")),
        "flowrunner": (200, REPO_SEARCH),
    })
    monkeypatch.setattr(ml, "_knowledge_http_get", first_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search("export flowapp",
                                                 workspace="/home/svend/FlowRunner"))

    assert result["scope"] == "flowrunner"
    assert result["count"] == 1
    assert result["results"][0]["path"] == "docs/a.md"
    assert [(entry["scope"], entry["status"]) for entry in result["scopes_searched"]] == [
        ("ecosystem", "denied"), ("experience", "unreachable"), ("flowrunner", "ok")]

    second, second_get = _scoped_service({
        "ecosystem": (404, {"detail": "unknown scope: ecosystem"}),
        "experience": (200, EMPTY_SEARCH),
        "flowrunner": (200, REPO_SEARCH),
    })
    monkeypatch.setattr(ml, "_knowledge_http_get", second_get)

    again = json.loads(ml.tool_knowledge_search("export flowapp",
                                                workspace="/home/svend/FlowRunner"))

    assert again["count"] == 1
    assert [(entry["scope"], entry["status"]) for entry in again["scopes_searched"]] == [
        ("ecosystem", "unknown_scope"), ("experience", "empty"), ("flowrunner", "ok")]
    assert len(_search_calls(second)) == 3


def test_repository_scope_404_is_the_unknown_scope_error(monkeypatch):
    """2.3: an unknown repository scope is the whole answer, with its detail."""
    calls, fake_get = _scoped_service({
        "ecosystem": (200, EMPTY_SEARCH),
        "experience": (200, EMPTY_SEARCH),
        "nope": (404, {"detail": "unknown scope: nope"}),
    })

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search("panels", scope="nope"))

    assert result == {
        "error": "unknown_scope",
        "scope": "nope",
        "detail": "unknown scope: nope",
    }
    # The learning scopes were consulted before the repository answer failed.
    assert len(_search_calls(calls)) == 3


def test_evidence_level_and_include_history_reach_only_the_learning_calls(monkeypatch):
    """2.1: the two learning fields are on ecosystem and experience, not the repository."""
    calls, fake_get = _scoped_service({
        "ecosystem": (200, EMPTY_SEARCH),
        "experience": (200, EMPTY_SEARCH),
        "flowrunner": (200, EMPTY_SEARCH),
    })

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner",
                             top_k=99, evidence_level="observation", include_history=True,
                             run_id="trial-1d", handoff_id="g5")

    eco, exp, repo = _search_calls(calls)
    assert eco["params"]["evidence_level"] == "observation"
    assert eco["params"]["include_history"] == "true"
    assert exp["params"]["evidence_level"] == "observation"
    assert exp["params"]["include_history"] == "true"
    # History switching stays the service's job: the scope name is untouched.
    assert exp["params"]["scope"] == "experience"
    assert "evidence_level" not in repo["params"]
    assert "include_history" not in repo["params"]
    # Clamped top_k and the position fields ride on all three calls alike.
    assert eco["params"]["top_k"] == exp["params"]["top_k"] == repo["params"]["top_k"] == 20
    assert _position(eco) == _position(exp) == _position(repo)
    assert repo["params"]["flow_key"] == "/home/svend/FlowRunner"

    bare, bare_get = _scoped_service({
        "ecosystem": (200, EMPTY_SEARCH),
        "experience": (200, EMPTY_SEARCH),
        "flowrunner": (200, EMPTY_SEARCH),
    })
    monkeypatch.setattr(ml, "_knowledge_http_get", bare_get)

    ml.tool_knowledge_search("export flowapp", workspace="/home/svend/FlowRunner")

    bare_eco, bare_exp, bare_repo = _search_calls(bare)
    for learning in (bare_eco, bare_exp):
        assert "evidence_level" not in learning["params"]
        assert "include_history" not in learning["params"]
    assert _position(bare_eco) == _position(bare_repo)


def test_trial_1_result_keys_are_still_present(monkeypatch):
    """2.2: scope/provider/count/results keep their trial 1 meaning alongside the new keys."""
    long_content = "y" * 600 + "TAIL"
    calls, fake_get = _scoped_service({
        "ecosystem": (200, {
            "enabled": True, "provider": "leann",
            "results": [{"path": "docs/architecture.md", "content": "eco body", "score": 0.7,
                         "scope": "ecosystem", "metadata": {"origin": "flowrunner"}}],
        }),
        "experience": (200, {
            "enabled": True, "provider": "leann",
            "results": [{"path": "2000/029", "content": "exp body", "score": 0.6,
                         "scope": "experience",
                         "metadata": {"evidence_level": "approved_architecture"}}],
        }),
        "flowrunner": (200, {
            "enabled": True, "provider": "leann", "bounded": True,
            "results": [{"path": "docs/a.md", "content": long_content, "score": 0.9,
                         "scope": "flowrunner"}],
        }),
    })

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setattr(ml, "_SCOPE_CACHE", {})

    result = json.loads(ml.tool_knowledge_search("export flowapp",
                                                 workspace="/home/svend/FlowRunner"))

    assert {"scope", "provider", "count", "results", "scopes_searched"} <= set(result)
    assert result["scope"] == "flowrunner"
    assert result["provider"] == "leann"
    assert result["count"] == len(result["results"]) == 3
    assert set(result["results"][0]) == {"scope", "path", "score", "snippet", "metadata"}
    assert result["results"][0]["snippet"] == "y" * 600
    assert result["results"][1]["snippet"] == "eco body"
    assert result["results"][2]["snippet"] == "exp body"
    assert all(set(entry) == {"scope", "status", "count"}
               for entry in result["scopes_searched"])
    assert [entry["status"] for entry in result["scopes_searched"]] == ["ok", "ok", "ok"]


def test_knowledge_scopes_lists_the_registry(monkeypatch):
    """Rule 4: GET /v1/scopes comes back as the registry array, token included."""
    registry = [
        {"scope": "flowrunner", "provider": "leann", "status": "ready",
         "document_count": 128, "indexed_at": "2026-09-14T09:00:00Z"},
        {"scope": "dpmtf-webui", "provider": "leann", "status": "ready",
         "document_count": 64, "indexed_at": "2026-09-13T18:00:00Z"},
    ]
    calls = []

    def fake_get(url, params, timeout, headers=None):
        calls.append({"url": url, "headers": dict(headers or {})})
        return 200, registry

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "sekret")

    result = json.loads(ml.tool_knowledge_scopes())

    assert calls == [{"url": "http://127.0.0.1:9140/v1/scopes",
                      "headers": {"X-Knowledge-Token": "sekret"}}]
    assert isinstance(result, list) and len(result) == 2
    assert result[0]["scope"] == "flowrunner"
    assert set(result[0]) >= {"scope", "provider", "status", "document_count"}


def test_knowledge_scopes_reports_the_same_error_shapes(monkeypatch):
    """Rule 4: denied / unknown_scope / not_ready / unreachable for discovery too."""
    replies = iter([
        (403, {"detail": "missing or invalid X-Knowledge-Token header"}),
        (404, {"detail": "unknown scope: nowhere"}),
        (503, {"detail": "provider index is still building"}),
    ])

    def fake_get(url, params, timeout, headers=None):
        return next(replies)

    monkeypatch.setattr(ml, "_knowledge_http_get", fake_get)

    denied = json.loads(ml.tool_knowledge_scopes())
    assert denied["error"] == "denied"
    assert "X-Knowledge-Token" in denied["detail"]

    unknown = json.loads(ml.tool_knowledge_scopes())
    assert unknown == {"error": "unknown_scope", "detail": "unknown scope: nowhere"}

    not_ready = json.loads(ml.tool_knowledge_scopes())
    assert not_ready == {"error": "not_ready",
                         "detail": "provider index is still building"}

    def raise_get(url, params, timeout, headers=None):
        raise OSError("connection refused")

    monkeypatch.setattr(ml, "_knowledge_http_get", raise_get)

    unreachable = json.loads(ml.tool_knowledge_scopes())
    assert unreachable["error"] == "unreachable"
    assert "connection refused" in unreachable["detail"]
