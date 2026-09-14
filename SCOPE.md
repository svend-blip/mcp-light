# SCOPE — trial 1e: a read-only `knowledge_learning` tool over the service's learning routes

Treat this file as the complete project scope for this workspace
(`/home/svend/mcp-light-dev`, a clone of the live `~/mcp-light`, which runs
under two systemd units and is never edited here). It builds on trial 1d
(`knowledge_search` three-scope default, `knowledge_scopes`). Re-initialise
scope-mcp (`init_project` with `reset: true`), ask only what is genuinely
necessary, then build. The service contract is
`~/knowledge-service/README.md` §"Validated learning" (read only).

## 1. Purpose

The service now lists what closed runs learned: `GET /v1/learning`
(admitted artifacts: `family`, `run`, `topic`, `evidence_level`,
`confidence`, `admitted_by`, `supersedes`), `GET /v1/learning?history=true`
(superseded/retracted ones, additionally `superseded_by`, `retracted_at`)
and `GET /v1/learning/drafts[?pending=true]` (the LEARNING-DRAFT.yaml files
waiting under the runs root: `family`, `run`, `topic`, `evidence_level`,
`run_status`, `admitted`, `valid`, `violations`). A DSH session, a
supervisor or a chain role can search experience already, but cannot see
the inventory: what has been admitted, what was superseded, what still
waits for admission. One read-only tool closes that.

## 2. Deliverable (`server.py`, its tests, README, the knowledge-first skill)

1. **Tool `knowledge_learning(view: str = "admitted", pending_only: bool = False, family: str = "")`**
   — `view` ∈ `admitted` (`GET /v1/learning`), `history`
   (`GET /v1/learning?history=true`), `drafts` (`GET /v1/learning/drafts`,
   with `pending=true` when `pending_only`); any other view is
   `{"error": "unknown view", "detail": "..."}` without a call. `family`,
   when non-empty, filters the returned rows client-side on the `family`
   field. Through the existing `_knowledge_http_get` seam with
   `knowledge_service_headers()`; the answer is
   `{"view": ..., "count": n, "artifacts": [...]}` for `admitted`/`history`
   and `{"view": "drafts", "count": n, "drafts": [...]}` for `drafts`, rows
   passed through unchanged. Errors map through `_knowledge_failure`
   (`denied` / `unknown_scope` / `not_ready` / `unreachable`), a raise is
   `unreachable`. No `_SCOPE_CACHE` involvement.
2. **Skill** `skills/knowledge-first/SKILL.md`: one short step — before
   starting a goal that repeats an earlier family's work, call
   `knowledge_learning(view="admitted", family=...)` to see what was
   concluded, and `view="drafts", pending_only=True` when acting as a
   supervisor to see what awaits admission. Keep the procedure's shape.
3. **README**: the tool table row and a short paragraph under the
   `### knowledge_search` section (or a sibling `### knowledge_learning`).
4. **Tests** in a new `tests/test_knowledge_learning_tool.py`, every one
   replacing `_knowledge_http_get`, named exactly:
   - `test_learning_tool_lists_admitted_by_default` (one call to
     `<base>/v1/learning` with no params, the token header when
     configured; answer shape and count)
   - `test_learning_tool_history_and_drafts_views_target_their_routes`
     (`history` → `/v1/learning` with `history=true`; `drafts` →
     `/v1/learning/drafts`; `pending_only` → `pending=true`, absent
     otherwise)
   - `test_learning_tool_family_filter_is_client_side`
   - `test_learning_tool_unknown_view_and_errors_are_reported_not_raised`
     (unknown view makes no call; 503 → `not_ready`; a raise →
     `unreachable`)

## 3. Constraints

Work only in this clone; never edit `~/mcp-light`, DPMtF, the service or
its data; no commits; no network; no restart of any unit; interpreter
`/home/svend/mcp-light/venv/bin/python`; no new dependencies; en-US;
`py_compile` every changed `.py`; the 58 existing tests stay green.

## 4. Definition of Done

```testgoals
id: TG1
what: the four named tests exist and pass and the whole suite is green
run: cd /home/svend/mcp-light-dev && for t in learning_tool_lists_admitted_by_default learning_tool_history_and_drafts_views_target_their_routes learning_tool_family_filter_is_client_side learning_tool_unknown_view_and_errors_are_reported_not_raised; do grep -q "def test_$t" tests/test_knowledge_learning_tool.py || exit 1; done && PYTHONDONTWRITEBYTECODE=1 /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -n 1 | grep -E "passed" | grep -vE "failed|error"
expect: exit 0

id: TG2
what: the tool is registered, targets the learning routes, and the skill and README name it
run: cd /home/svend/mcp-light-dev && grep -q 'name="knowledge_learning"' server.py && grep -q "/v1/learning/drafts" server.py && grep -q "knowledge_learning" skills/knowledge-first/SKILL.md && grep -q "knowledge_learning" README.md
expect: exit 0

id: TG3
what: FENCE — only the deliverable paths changed
run: cd /home/svend/mcp-light-dev && test -n "$(git status --porcelain)" && test -z "$(git status --porcelain | awk '{print $2}' | grep -v -E '^(server.py|tests/|README.md|skills/knowledge-first/SKILL.md)')"
expect: exit 0

id: TG4
what: LIVE (reviewer only) — after merge and unit restart the tool lists the live service's admitted artifacts and pending drafts
run: test -f /tmp/claude-1000/-home-svend-DPMtF-WebUI/e20394ae-27d0-4204-804f-5d6a2f5da054/scratchpad/mcp-learning-live/ok
expect: exit 0
```

## 5. Initial Execution Instruction

`init_project` with `reset: true`; goals for 2.1–2.4 in order; checkpoint
after each goal; ask now, in one message, only what is genuinely ambiguous;
implement; run TG1–TG3 and `py_compile`; record coverage;
`complete_project`; report `git status` and the pasted output of TG1–TG3.
TG4 is the reviewer's; do not attempt it and do not restart anything.
