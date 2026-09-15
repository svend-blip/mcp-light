# SCOPE — trial 1f: a read-only `knowledge_retrievals` tool over the service's retrieval log

Treat this file as the complete project scope for this workspace
(`/home/svend/mcp-light-dev`, a clone of the live `~/mcp-light`, which
runs under two systemd units and is never edited here). It builds on
trials 1c–1e (`knowledge_search`, `knowledge_scopes`,
`knowledge_learning`). Re-initialise scope-mcp (`init_project` with
`reset: true`), ask only what is genuinely necessary, then build. The
service contract is `~/knowledge-service/README.md` §"Retrieval log"
(read only).

## 1. Purpose

The knowledge service now answers `GET /v1/retrievals`: every search it
served, with `provider`, `scope`, `query`, `result_count`, `sources`,
`retrieved_token_count`, `retrieval_duration_ms`, `agent_role`, `run_id`,
`handoff_id`, `flow_key` and `created_at`, filtered by any of
`run_id`, `handoff_id`, `flow_key`, `agent_role`, `scope`, `since`,
`until`, paged with `limit`/`offset` (limit clamped to 1..500), newest
first, and `summary=true` for the aggregate
(`retrievals`, `results`, `tokens`, `duration_ms`, `scopes`,
`agent_roles`, `first`, `last`). Only a human with a shell or an HTTP
client can read it; no agent can. A supervising session that wants to
know what a run retrieved, or whether a role is retrieving at all, has to
leave its tools to find out. One read-only tool closes that.

## 2. Deliverable (`server.py`, its tests, README, the knowledge-first skill)

1. **Tool** `knowledge_retrievals(run_id: str = "", handoff_id: str = "",
   flow_key: str = "", agent_role: str = "", scope: str = "",
   since: str = "", until: str = "", limit: int = 20, summary: bool = False)`
   — one `GET <base>/v1/retrievals` through the existing
   `_knowledge_http_get` seam with `knowledge_service_headers()`; empty
   filters are left out of the query string; `limit` is coerced to an int
   and clamped to 1..200 by the tool before it is sent (the service
   clamps again at 500); `summary` sends `summary=true` and nothing else
   changes. The answer is the service's own dict passed through unchanged
   except that each row's `query` is truncated to 200 characters and its
   `sources` list to the first 5 entries, so a large page cannot flood a
   model's context. Errors map through `_knowledge_failure` (`denied` /
   `unknown_scope` / `not_ready` / `unreachable`), a raise is
   `unreachable`, and `_SCOPE_CACHE` is not involved.
2. **Skill** `skills/knowledge-first/SKILL.md`: one short step for a
   supervising or reviewing role — after a run closes, call
   `knowledge_retrievals(run_id=...)` to see what it looked up, and
   `summary=True` to see whether a role retrieves at all.
3. **README**: the tool-table row and a sibling `### knowledge_retrievals`
   section with one example per question (what did this run retrieve, has
   this role retrieved today, how much has a scope served).
4. **Tests** in a new `tests/test_knowledge_retrievals_tool.py`, every one
   replacing `_knowledge_http_get`, named exactly:
   - `test_retrievals_sends_only_the_set_filters_and_the_token_header`
   - `test_retrievals_clamps_the_limit_and_forwards_summary`
   - `test_retrievals_truncates_long_queries_and_source_lists`
   - `test_retrievals_errors_are_reported_not_raised`

## 3. Constraints

Work only in this clone; never edit `~/mcp-light`, DPMtF, the service or
its data; no commits; no network; no restart of any unit; interpreter
`/home/svend/mcp-light/venv/bin/python`; no new dependencies; en-US;
`py_compile` every changed `.py`; the 62 existing tests stay green.

## 4. Definition of Done

```testgoals
id: TG1
what: the four named tests exist and pass and the whole suite is green
run: cd /home/svend/mcp-light-dev && for t in retrievals_sends_only_the_set_filters_and_the_token_header retrievals_clamps_the_limit_and_forwards_summary retrievals_truncates_long_queries_and_source_lists retrievals_errors_are_reported_not_raised; do grep -q "def test_$t" tests/test_knowledge_retrievals_tool.py || exit 1; done && PYTHONDONTWRITEBYTECODE=1 /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -n 1 | grep -E "passed" | grep -vE "failed|error"
expect: exit 0

id: TG2
what: the tool is registered against the route and the skill and README name it
run: cd /home/svend/mcp-light-dev && grep -q 'name="knowledge_retrievals"' server.py && grep -q "/v1/retrievals" server.py && grep -q "knowledge_retrievals" skills/knowledge-first/SKILL.md && grep -q "knowledge_retrievals" README.md
expect: exit 0

id: TG3
what: FENCE — only the deliverable paths changed
run: cd /home/svend/mcp-light-dev && test -n "$(git status --porcelain)" && test -z "$(git status --porcelain | awk '{print $2}' | grep -v -E '^(server.py|tests/|README.md|skills/knowledge-first/SKILL.md|SCOPE.md)')"
expect: exit 0

id: TG4
what: LIVE (reviewer only) — after merge and unit restart the tool answers over the service's real rows
run: test -f /tmp/claude-1000/-home-svend-DPMtF-WebUI/e20394ae-27d0-4204-804f-5d6a2f5da054/scratchpad/mcp-retrievals-live/ok
expect: exit 0
```

## 5. Initial Execution Instruction

`init_project` with `reset: true`; goals for 2.1–2.4 in order; checkpoint
after each goal; ask now, in one message, only what is genuinely ambiguous;
implement; run TG1–TG3 and `py_compile`; record coverage;
`complete_project`; report `git status` and the pasted output of TG1–TG3.
TG4 is the reviewer's; do not attempt it and do not restart anything.
