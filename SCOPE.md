# SCOPE — mcp-light `knowledge_search`: provider-neutral retrieval as an agent tool

Treat this file as the complete project scope for this workspace
(`/home/svend/mcp-light-dev`, a clone of `mcp-light`). Persist nothing outside
this workspace except scope-mcp's own state. Ask only the clarification
questions that are genuinely necessary, then build.

## 1. Purpose

DPMtF's knowledge layer answers semantic queries over ten repository scopes at
`GET http://127.0.0.1:9130/api/knowledge/search` (parameters `q`, `scope`,
`top_k`, `token_budget`, `agent_role`, `flow_key`; response
`{"enabled": bool, "provider": str, "results": [{"path", "content", "score",
"scope"}], "bounded": true}`; HTTP 403 with `detail` when the scope guard
denies; HTTP 503 with `detail` when the provider is not ready). Today only
DPMtF's Prompt Compiler uses it. This scope exposes it as one MCP tool in
mcp-light so every harness that already talks to mcp-light — simple-harness
chain roles, FlowRunner families, and DeepSeek Harness — can retrieve before
exploring. The tool is provider-neutral by construction: it speaks HTTP to
DPMtF and knows nothing about LEANN.

## 2. Deliverable

One new tool in `server.py`, registered exactly like the existing 33
(`@mcp.tool(name=..., description=...)` on a `tool_...` function returning a
string):

```text
knowledge_search(query: str, scope: str = "current_repository",
                 workspace: str = "", top_k: int = 8,
                 token_budget: int = 4000, agent_role: str = "dsh",
                 flow_key: str = "") -> str   # JSON
```

Rules:

1. `scope == "current_repository"` resolves from `workspace` with the same
   rule DPMtF uses (`knowledge/scopes.py::scope_for_target`): the lowercased
   final directory name with trailing slashes stripped; the DPMtF checkout
   itself (`server.WEBUI_ROOT`, compared by resolved path) maps to
   `dpmtf-webui`. Empty `workspace` with `current_repository` returns
   `{"error": "workspace is required to resolve current_repository"}`.
   Put the rule in a module-level function `knowledge_scope_for_path(path)`
   so tests can call it directly. This duplicates DPMtF's rule on purpose
   for now; a later DPMtF run will expose it as an endpoint.
2. The HTTP call goes through one module-level helper
   `_knowledge_http_get(url, params, timeout)` (stdlib `urllib`, timeout
   30 s) so tests can replace it. Base URL from env
   `DPMTF_KNOWLEDGE_BASE_URL`, default `http://127.0.0.1:9130`.
3. Success returns JSON: `{"scope", "provider", "count", "results": [{"path",
   "score", "snippet"}]}` where `snippet` is the result's `content` cut to
   600 characters. `enabled: false` from DPMtF returns
   `{"scope", "count": 0, "results": [], "note": "knowledge retrieval is disabled in DPMtF"}`.
4. HTTP 403 returns `{"error": "denied", "scope", "detail": <server detail>}`;
   HTTP 503 returns `{"error": "not_ready", "detail": ...}`; any other
   failure returns `{"error": "unreachable", "detail": ...}`. Never raise.
5. `top_k` is clamped to 1..20 and `token_budget` to 200..12000 before the
   call; `query` shorter than 2 characters returns `{"error": "query too short"}`.
6. README: one row in the tool table and a short section "knowledge_search"
   with the scope rule, the error shapes, and the note that simple-harness
   roles need the name on their allowlist and DSH reaches it through its
   MCP client (both are configured outside this repository).
7. Tests in `tests/test_knowledge_search_tool.py`, named exactly:
   `test_scope_for_path_lowercases_the_directory_name`,
   `test_scope_for_path_maps_the_dpmtf_checkout_to_dpmtf_webui`,
   `test_current_repository_without_workspace_is_an_error`,
   `test_success_response_is_shaped_and_snippets_are_cut`,
   `test_denied_and_not_ready_and_unreachable_are_reported_not_raised`,
   `test_disabled_layer_returns_an_empty_note`,
   `test_bounds_are_clamped_before_the_call`.
   All of them replace `_knowledge_http_get`; none of them talks to a live
   server.

## 3. Constraints

- Work only in this workspace. Never edit `/home/svend/mcp-light` (the live
  service runs that tree) or `/home/svend/DPMtF-WebUI`.
- Do not commit, stage, or push. The reviewer commits after measuring.
- No new dependencies: `urllib` from the standard library.
- Python interpreter for every check: `/home/svend/mcp-light/venv/bin/python`
  (this clone has no venv of its own). `python -m py_compile server.py`
  must pass before you report done.
- The other 33 tools and every existing test stay untouched and green:
  `/home/svend/mcp-light/venv/bin/python -m pytest -q tests`.
- en-US in code, comments, docs and messages.
- Do not start, stop or restart any service or model. The live testgoal
  below is run by the reviewer.

## 4. Definition of Done

All testgoals below green when the reviewer measures them, the full test
suite green, `git status` in this workspace listing exactly `server.py`,
`README.md`, `tests/test_knowledge_search_tool.py` (plus scope-mcp's own
state directory, which is ignored), and a final `status` in scope-mcp with
coverage recorded against sections 2.1–2.7.

```testgoals
id: TG1
what: the seven named tests exist and pass
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_knowledge_search_tool.py -k "scope_for_path_lowercases_the_directory_name or scope_for_path_maps_the_dpmtf_checkout_to_dpmtf_webui or current_repository_without_workspace_is_an_error or success_response_is_shaped_and_snippets_are_cut or denied_and_not_ready_and_unreachable_are_reported_not_raised or disabled_layer_returns_an_empty_note or bounds_are_clamped_before_the_call"
expect: exit 0

id: TG2
what: the tool is registered under its name and the scope rule is a module function
run: cd /home/svend/mcp-light-dev && grep -q '@mcp.tool(name="knowledge_search"' server.py && /home/svend/mcp-light/venv/bin/python -c "import server as ml; assert callable(ml.tool_knowledge_search); assert ml.knowledge_scope_for_path('/tmp/x/FlowRunner/') == 'flowrunner'; assert ml.knowledge_scope_for_path(ml.WEBUI_ROOT) == 'dpmtf-webui'"
expect: exit 0

id: TG3
what: without a workspace, current_repository is an error and never a call
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -c "import json, server as ml; ml._knowledge_http_get = lambda *a, **k: (_ for _ in ()).throw(AssertionError('no call')); r = json.loads(ml.tool_knowledge_search('how does dispatch work')); raise SystemExit(0 if r.get('error') and 'workspace' in r['error'] else 1)"
expect: exit 0

id: TG4
what: the whole existing suite stays green
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests
expect: exit 0

id: TG5
what: README documents the tool
run: cd /home/svend/mcp-light-dev && grep -q "knowledge_search" README.md && grep -qi "current_repository" README.md
expect: exit 0

id: TG6
what: LIVE (reviewer only) — a public scope answers with sources and the internal scope is denied for role dsh
run: cd /home/svend/mcp-light-dev && /home/svend/mcp-light/venv/bin/python -c "import json, server as ml; a = json.loads(ml.tool_knowledge_search('How is a FlowApp exported and imported?', scope='current_repository', workspace='/home/svend/FlowRunner', top_k=3)); b = json.loads(ml.tool_knowledge_search('How does BridgeV002 dispatch a signal-complete?', scope='dpmtf-webui', top_k=3)); ok = a.get('count', 0) >= 1 and all('path' in r for r in a['results']) and b.get('error') == 'denied'; print(json.dumps({'a_count': a.get('count'), 'b_error': b.get('error')})); raise SystemExit(0 if ok else 1)"
expect: exit 0

id: TG7
what: FENCE — only the three files changed in this workspace
run: cd /home/svend/mcp-light-dev && test -n "$(git status --porcelain)" && test -z "$(git status --porcelain | awk '{print $2}' | grep -v -E '^(server.py|README.md|tests/test_knowledge_search_tool.py)$')"
expect: exit 0
```

## 5. Initial Execution Instruction

1. Persist this scope via scope-mcp (`init_project`), derive lightweight
   goals for sections 2.1–2.7, checkpoint before context pressure.
2. Ask now, in one message, only what is genuinely ambiguous. Everything
   else: decide and record the decision.
3. Implement, run the tests and the full suite, `py_compile`, then record
   coverage against 2.1–2.7 and call `complete_project`.
4. Report: the `git status` of this workspace and the pasted output of
   TG1–TG5. Do not attempt TG6 or any live call; the reviewer measures it.
