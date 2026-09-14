# SCOPE — trial 1d: `knowledge_search` searches repository + ecosystem + experience by default

Treat this file as the complete project scope for this workspace
(`/home/svend/mcp-light-dev`, a clone of the live `~/mcp-light`, which runs
under two systemd units and is never edited here). It builds on trial 1c
(the tool speaks to the knowledge service on `http://127.0.0.1:9140`).
Re-initialise scope-mcp (`init_project` with `reset: true`), ask only what
is genuinely necessary, then build. Read DPMtF's
`docs/SCOPE-ADDENDUM-KNOWLEDGE-2-VALIDATED-LEARNING.md` §4–§7 first (read
only).

## 1. Purpose

The service now holds three non-repository scopes beside the repository
scopes: `experience` (validated learning artifacts, filtered by evidence
level), `ecosystem` (their architecture implications) and
`experience-history` (superseded/retracted ones, searched only on
`include_history=true`). Every result carries a `metadata` object
(`evidence_level`, `repository`, `family`, `run`, `confidence`, `origin`,
`superseded_by`, `retracted_at` where present; `{}` on repository
passages). `/v1/search` answers 404 `{"detail": "unknown scope: …"}` for an
unknown scope and 503 for a missing store. DPMtF's compiler already searches
all three by default with a fixed budget split (addendum 2 §6); the tool is
the second consumer and must behave the same, so a DSH session sees what a
chain role sees.

## 2. Deliverable (`server.py`, its tests, README, the knowledge-first skill)

1. **Three-scope default.** `knowledge_search` gains `cross_repo: bool = True`,
   `evidence_level: str = ""` and `include_history: bool = False`. When the
   effective scope is a repository scope (`current_repository` resolved, or
   an explicit name that is not one of the three learning scopes) and
   `cross_repo` is true, the tool makes three `GET /v1/search` calls through
   the existing `_knowledge_http_get` seam, all with the same `agent_role`,
   `flow_key`, `run_id`, `handoff_id` and `top_k`: `ecosystem` first, then
   `experience`, then the repository scope. The token budget is split
   60 % repository, 20 % ecosystem, 20 % experience (integer division of
   the clamped `token_budget`); the two learning shares are used first and
   whatever they leave unused — share minus the whitespace-split tokens of
   the `content` the service returned for that scope — is added to the
   repository call's `token_budget`. `evidence_level` and
   `include_history` are forwarded to the learning calls only (with
   `include_history` the service targets `experience-history` for the
   experience call); the repository call never carries them. With
   `cross_repo` false, or an explicit learning scope, the tool makes exactly
   one call as today (an explicit learning scope forwards the two fields).
2. **Result shape.** `{scope, provider, count, results, scopes_searched}` —
   `scope` stays the repository scope (or the single explicit scope);
   `results` are ordered repository → ecosystem → experience, each
   `{scope, path, score, snippet, metadata}` with `metadata` passed through
   from the service unchanged (`{}` when absent) and `scope` the scope the
   hit came from; `scopes_searched` is a list of `{scope, status, count}`
   in call order with `status` one of `ok`, `empty`, `denied`,
   `unknown_scope`, `not_ready`, `unreachable`, `disabled`. The existing
   keys keep their meaning, so trial 1's consumers still parse the answer.
3. **Failure semantics.** The repository call keeps today's behaviour: a
   failure is the whole answer (`denied` / `not_ready` / `unreachable`, plus
   the new `{"error": "unknown_scope", "scope": …, "detail": …}` for 404).
   A learning call that answers 403, 404, 503, a disabled envelope, an empty
   list, or raises, contributes no results and is recorded in
   `scopes_searched` with its status — it never fails the call and never
   hides the repository results. `_knowledge_failure` learns the 404 mapping.
4. **Skill.** `skills/knowledge-first/SKILL.md`: the default call now
   consults the repository, ecosystem and experience; read
   `metadata.evidence_level` before trusting an experience hit (the five
   levels, strongest first: `tests`, `measured_runtime`,
   `approved_architecture`, `reviewer_conclusion`, `observation`; the
   default filter returns the first three); pass `include_history: true`
   when a conclusion looks outdated; `scopes_searched` says what was
   consulted and why a scope gave nothing. Keep the procedure's shape.
5. **README.** The tool table row (new parameters) and the
   `### knowledge_search` section (three-scope default, the split, the
   result shape with `metadata` and `scopes_searched`, `cross_repo: false`).
6. **Tests**, in `tests/test_knowledge_search_tool.py`, every one replacing
   `_knowledge_http_get` and resetting `_SCOPE_CACHE` like the existing
   ones, named exactly:
   - `test_default_search_spans_ecosystem_experience_and_repository_with_the_split_budget`
     (default `token_budget` 4000: ecosystem and experience calls carry
     `token_budget` 800 each and come before the repository call; the
     learning calls' content uses 100 tokens each, so the repository call
     carries 2400 + 1400 = 3800; three calls; results ordered repository →
     ecosystem → experience; every result has `scope` and `metadata`;
     `scopes_searched` has three `ok` entries with counts)
   - `test_cross_repo_false_and_explicit_learning_scopes_make_a_single_call`
     (`cross_repo=False` → one repository call without `evidence_level`;
     `scope="experience"` with `evidence_level="observation"` and
     `include_history=True` → one call carrying both)
   - `test_learning_scope_failures_never_fail_the_call` (ecosystem 403,
     experience raising → repository results returned, `scopes_searched`
     says `denied` and `unreachable`; then ecosystem 404 and experience
     empty → `unknown_scope` and `empty`)
   - `test_repository_scope_404_is_the_unknown_scope_error`
   - `test_evidence_level_and_include_history_reach_only_the_learning_calls`
   - `test_trial_1_result_keys_are_still_present` (`scope`, `provider`,
     `count`, `results[].path/score/snippet` unchanged in meaning)

## 3. Constraints

Work only in this clone; never edit `~/mcp-light`, DPMtF, the service or
its data; no commits; no network; no restart of any unit; interpreter
`/home/svend/mcp-light/venv/bin/python`; no new dependencies; en-US; `py_compile` every changed file; the
existing tests stay green (the service's contract is the one in
`~/knowledge-service/README.md` — read it, do not guess).

## 4. Definition of Done

```testgoals
id: TG1
what: the six named tests exist and pass and the whole suite is green
run: cd /home/svend/mcp-light-dev && for t in default_search_spans_ecosystem_experience_and_repository_with_the_split_budget cross_repo_false_and_explicit_learning_scopes_make_a_single_call learning_scope_failures_never_fail_the_call repository_scope_404_is_the_unknown_scope_error evidence_level_and_include_history_reach_only_the_learning_calls trial_1_result_keys_are_still_present; do grep -q "def test_$t" tests/test_knowledge_search_tool.py || exit 1; done && PYTHONDONTWRITEBYTECODE=1 /home/svend/mcp-light/venv/bin/python -m pytest -q -p no:cacheprovider tests 2>&1 | tail -n 1 | grep -E "passed" | grep -vE "failed|error"
expect: exit 0

id: TG2
what: the tool, the failure mapping, the skill and the README carry the new surface
run: cd /home/svend/mcp-light-dev && grep -q "cross_repo" server.py && grep -q "include_history" server.py && grep -q "evidence_level" server.py && grep -q "scopes_searched" server.py && grep -q "unknown_scope" server.py && grep -q "ecosystem" skills/knowledge-first/SKILL.md && grep -q "evidence_level" skills/knowledge-first/SKILL.md && grep -q "scopes_searched" README.md && grep -q "cross_repo" README.md
expect: exit 0

id: TG3
what: FENCE — only the deliverable paths changed
run: cd /home/svend/mcp-light-dev && test -n "$(git status --porcelain)" && test -z "$(git status --porcelain | awk '{print $2}' | grep -v -E '^(server.py|tests/|README.md|skills/knowledge-first/SKILL.md)')"
expect: exit 0

id: TG4
what: LIVE (reviewer only) — after merge and unit restart, one knowledge_search from a DSH-style caller consults three scopes on 9140 and returns metadata
run: test -f /tmp/claude-1000/-home-svend-DPMtF-WebUI/e20394ae-27d0-4204-804f-5d6a2f5da054/scratchpad/mcp-3scope-live/ok
expect: exit 0
```

## 5. Initial Execution Instruction

`init_project` with `reset: true`; goals for 2.1–2.6 in order; checkpoint
after each goal; ask now, in one message, only what is genuinely ambiguous;
implement; run TG1–TG3 and `py_compile`; record coverage;
`complete_project`; report `git status` and the pasted output of TG1–TG3.
TG4 is the reviewer's; do not attempt it and do not restart anything.
