# SCOPE — trial 1c: `knowledge_search` speaks to the knowledge-service

Treat this file as the complete project scope for this workspace
(`/home/svend/mcp-light-dev`). It builds on trials 1 and 1b (the tool exists
and forwards the DSH position). Re-initialise scope-mcp (`init_project` with
`reset: true`), ask only what is genuinely necessary, then build.

## 1. Purpose

The knowledge layer is now a standalone service on `http://127.0.0.1:9140`
(`~/knowledge-service`, user unit `knowledge-service.service`) with the
contract `GET /v1/search`, `POST /v1/refresh`, `GET /v1/scopes`,
`GET /v1/scope-for-path?path=…`, `GET /v1/health`; response shapes and status
codes are those DPMtF's `/api/knowledge/search` used (`enabled`, `provider`,
`results[{path, content, score, scope}]`, `bounded`; 403 `detail` when
denied; 503 `detail` when not ready; optional header `X-Knowledge-Token`).
`knowledge_search` still calls DPMtF on 9130 and duplicates the slug rule.
Point it at the service and drop the duplicate, so every mcp-light client
(simple-harness roles, FlowRunner families, DeepSeek Harness) reads the same
service that DPMtF itself is moving to.

## 2. Deliverable (`server.py`, its tests, README)

1. Base URL from env `KNOWLEDGE_SERVICE_URL`, default `http://127.0.0.1:9140`;
   token from env `KNOWLEDGE_SERVICE_TOKEN` (empty = no header). The old
   `DPMTF_KNOWLEDGE_BASE_URL` is removed.
2. `knowledge_search` calls `GET <base>/v1/search` with the same parameters
   as today (`q`, `scope`, `top_k`, `token_budget`, `agent_role`,
   `flow_key`, `run_id`, `handoff_id`), through the existing
   `_knowledge_http_get` seam (extend it with an optional headers argument).
   Result and error shapes to the caller stay exactly as trial 1 defined
   them (`{scope, provider, count, results[{path, score, snippet}]}`;
   `denied` / `not_ready` / `unreachable`; the disabled note).
3. `scope == "current_repository"` resolves through
   `GET <base>/v1/scope-for-path?path=<workspace>` (one call, cached per
   process in a dict keyed by the workspace string). `knowledge_scope_for_path`
   is removed together with its tests; when the service is unreachable the
   tool returns `{"error": "unreachable", "detail": ...}` before any search.
4. A second tool `knowledge_scopes()` returning `GET /v1/scopes` as JSON
   (list of `{scope, provider, status, document_count}`), so an agent can
   discover which repositories have memory. Same error shapes.
5. Tests in `tests/test_knowledge_search_tool.py`, named exactly:
   `test_search_targets_the_service_v1_route_with_the_token_header`,
   `test_current_repository_resolves_through_scope_for_path_once_per_workspace`,
   `test_scope_for_path_unreachable_is_reported_before_any_search`,
   `test_knowledge_scopes_lists_the_registry`.
   The trial-1/1b tests that asserted the DPMtF URL or the local slug rule
   are updated to the service; every other test stays green.
6. README: the `knowledge_search` section names the service, the two env
   variables and `knowledge_scopes`; the DPMtF-URL and slug-duplication
   sentences go.

## 3. Constraints

Work only in this workspace; never edit `/home/svend/mcp-light`,
`/home/svend/knowledge-service` or `/home/svend/DPMtF-WebUI`. No commits.
No new dependencies. Interpreter `/home/svend/mcp-light/venv/bin/python`.
The other tools and every existing test stay untouched and green. en-US.
Do not start, stop or restart any service; the live testgoals are the
reviewer's.

## 4. Definition of Done

Testgoals green when the reviewer measures them; `git status` listing
exactly `server.py`, `README.md`, `tests/test_knowledge_search_tool.py`;
coverage recorded; `complete_project` called.

```testgoals
id: TG1
what: the four named tests exist and pass and the tool file's suite is green
run: cd /home/svend/mcp-light-dev && grep -q "def test_knowledge_scopes_lists_the_registry" tests/test_knowledge_search_tool.py && /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_knowledge_search_tool.py -k "search_targets_the_service_v1_route_with_the_token_header or current_repository_resolves_through_scope_for_path_once_per_workspace or scope_for_path_unreachable_is_reported_before_any_search or knowledge_scopes_lists_the_registry" 2>&1 | tail -n 1 | grep -E "^4 passed" && /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_knowledge_search_tool.py 2>&1 | tail -n 1 | grep -E "passed" | grep -vE "failed|error"
expect: exit 0

id: TG2
what: the service route and the token header are used and the local slug rule is gone
run: cd /home/svend/mcp-light-dev && ! grep -q "DPMTF_KNOWLEDGE_BASE_URL" server.py && ! grep -q "def knowledge_scope_for_path" server.py && grep -q "/v1/search" server.py && grep -q "/v1/scope-for-path" server.py && grep -q "X-Knowledge-Token" server.py && grep -q '@mcp.tool(name="knowledge_scopes"' server.py
expect: exit 0

id: TG3
what: the whole existing suite stays green
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -n 1 | grep -E "passed" | grep -vE "failed|error"
expect: exit 0

id: TG4
what: LIVE (reviewer only) — current_repository on the FlowRunner checkout answers with FlowRunner sources through the service, dpmtf-webui is denied for role nobody, and knowledge_scopes lists ten scopes
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -c "import json, server as ml; a = json.loads(ml.tool_knowledge_search('How is a FlowApp exported and imported?', scope='current_repository', workspace='/home/svend/FlowRunner', top_k=3)); b = json.loads(ml.tool_knowledge_search('x', scope='dpmtf-webui', agent_role='nobody', top_k=1)); c = json.loads(ml.tool_knowledge_scopes()); ok = a.get('scope') == 'flowrunner' and a.get('count', 0) >= 1 and b.get('error') == 'denied' and isinstance(c, list) and len(c) >= 10; print(json.dumps({'a': a.get('count'), 'b': b.get('error'), 'scopes': len(c) if isinstance(c, list) else c})); raise SystemExit(0 if ok else 1)"
expect: exit 0

id: TG5
what: FENCE — only the three files changed
run: cd /home/svend/mcp-light-dev && test -n "$(git status --porcelain)" && test -z "$(git status --porcelain | awk '{print $2}' | grep -v -E '^(server.py|README.md|tests/test_knowledge_search_tool.py)$')"
expect: exit 0
```

## 5. Initial Execution Instruction

`init_project` with `reset: true`; goals for 2.1–2.6; implement; run
TG1–TG3 and `py_compile server.py`; record coverage; `complete_project`;
report `git status` and the pasted output of TG1–TG3. Do not run TG4.
