"""Phase 6 — flow-state tools (get_flow_scope, get_flow_state, get_run,
list_goal_drafts) and the flow_state module behind them.

Every test runs against the temporary layout and database built in
conftest.py; nothing here touches the live flows root or dpmtf.db.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import (
    DECOMPOSER, ELOOP, IMPLEMENTER, PLOOP, REVIEWER, ROOT, VALID_TESTGOALS,
)

_TOOLS = ("tool_get_flow_scope", "tool_get_flow_state", "tool_get_run",
          "tool_list_goal_drafts")


def _state(server, flow=ELOOP):
    return json.loads(server.tool_get_flow_state(flow))


# ---------------------------------------------------------------------------
# Errors are reported, never raised
# ---------------------------------------------------------------------------

def test_unknown_flow_reports_error(patched_server):
    for name in _TOOLS:
        tool = getattr(patched_server, name)
        args = ("no-such-flow", 1) if name == "tool_get_run" else ("no-such-flow",)
        out = tool(*args)
        assert isinstance(out, str)
        parsed = json.loads(out)
        assert "error" in parsed, (name, parsed)
        assert "no-such-flow" in parsed["error"]


def test_every_tool_returns_str(patched_server):
    outs = [
        patched_server.tool_get_flow_scope(ELOOP),
        patched_server.tool_get_flow_scope(ELOOP, "headings"),
        patched_server.tool_get_flow_state(ELOOP),
        patched_server.tool_get_run(ELOOP, 2),
        patched_server.tool_get_run(ELOOP, "002", include="ledger", ledger_tail_entries=1),
        patched_server.tool_list_goal_drafts(PLOOP),
        patched_server.tool_get_run(ELOOP, "abc"),
        patched_server.tool_get_flow_scope(ELOOP, "bogus-mode"),
    ]
    for out in outs:
        assert isinstance(out, str)
        json.loads(out)
    assert "error" in json.loads(outs[-2])
    assert "error" in json.loads(outs[-1])


def test_path_traversal_in_flow_key_rejected(patched_server, fs):
    for bad in ("../t9000", "t9000/../..", "a b", "", "x;y"):
        parsed = json.loads(patched_server.tool_get_flow_state(bad))
        assert "error" in parsed, bad
        parsed = json.loads(patched_server.tool_get_flow_scope(bad))
        assert "error" in parsed, bad
    # ".." satisfies the character class but is not a flow -> KeyError, not a read
    assert "error" in json.loads(patched_server.tool_get_flow_scope(".."))
    # an artifact_root that escapes the flows root is refused by _flow_path
    parsed = json.loads(patched_server.tool_get_flow_scope("t-escape"))
    assert "error" in parsed and "escapes" in parsed["error"]
    with pytest.raises(ValueError):
        fs._flow_path("/tmp/flows-root-that-need-not-exist", "..", "etc")


# ---------------------------------------------------------------------------
# Flow resolution
# ---------------------------------------------------------------------------

def test_resolve_flow_siblings_share_root(fs, db_path):
    a = fs.resolve_flow(ELOOP, db_path)
    b = fs.resolve_flow(PLOOP, db_path)
    assert a["artifact_root"] == b["artifact_root"] == ROOT
    assert a["siblings"] == [PLOOP]
    assert b["siblings"] == [ELOOP]
    assert a["supervisor_mandate"].startswith("Human:")
    assert a["commit_cadence"] == "per_run"
    assert b["supervisor_mandate"] is None and b["commit_cadence"] == "none"
    assert a["cold_start_skill"] == "9000"
    assert a["role_keys"] == sorted([DECOMPOSER, IMPLEMENTER, REVIEWER])
    assert a["counter_next_id"] == 6
    other = fs.resolve_flow("t-other", db_path)
    assert other["artifact_root"] == "t-other" and other["siblings"] == []
    with pytest.raises(KeyError):
        fs.resolve_flow("nope", db_path)


# ---------------------------------------------------------------------------
# SCOPE
# ---------------------------------------------------------------------------

def test_scope_missing_is_not_an_error(patched_server, root_dir):
    (root_dir / "SCOPE.md").unlink()
    parsed = json.loads(patched_server.tool_get_flow_scope(ELOOP))
    assert "error" not in parsed
    assert parsed["exists"] is False
    state = _state(patched_server)
    assert state["phase"] == "AWAIT_SCOPE"


def test_scope_modes(patched_server):
    full = json.loads(patched_server.tool_get_flow_scope(ELOOP, "full"))
    assert full["exists"] and "## 1. Mission" in full["content"]
    heads = json.loads(patched_server.tool_get_flow_scope(ELOOP, "headings"))
    assert [h["text"] for h in heads["headings"]] == [
        "# FlowRunner — SCOPE.md", "## 1. Mission", "## 2. Bounds"]
    assert "content" not in heads
    assert heads["artifact_root"] == ROOT


# ---------------------------------------------------------------------------
# Run classification
# ---------------------------------------------------------------------------

def test_bulk_promoted_layout_selects_lowest_executing_run(fs, root_dir):
    runs = fs.classify_runs(root_dir)
    assert runs["closed"] == ["001"]
    assert runs["executing"] == "002"          # not 003, the newest promotion
    assert runs["promoted_waiting"] == ["003"]
    assert runs["anomalies"] == []
    assert runs["details"]["002"]["first_handoff_id"] == 5
    assert runs["details"]["003"]["first_handoff_id"] is None
    assert runs["details"]["003"]["ledger_opened"] is False


def test_many_promoted_runs_still_lowest(fs, root_dir):
    # promote 004..010 in bulk: every one gets GOAL.md + "GOAL promoted"
    for n in range(4, 11):
        d = root_dir / "runs" / f"{n:03d}"
        d.mkdir()
        (d / "GOAL.md").write_text("First handoff id: set by the kickoff dispatch.\n")
        (d / "RUN-LEDGER.md").write_text("## 2026-09-01T18:35:47Z — GOAL promoted\n")
    runs = fs.classify_runs(root_dir)
    assert runs["executing"] == "002"
    assert runs["promoted_waiting"] == [f"{n:03d}" for n in range(3, 11)]


def test_second_opened_run_is_an_anomaly(fs, root_dir):
    ledger = root_dir / "runs" / "003" / "RUN-LEDGER.md"
    ledger.write_text(ledger.read_text() + "## 2026-09-02T09:00:00Z — Run 003 opened\n")
    runs = fs.classify_runs(root_dir)
    assert runs["executing"] == "002"
    assert any(a["run"] == "003" for a in runs["anomalies"])


def test_ledger_without_goal_is_an_anomaly(fs, root_dir):
    (root_dir / "runs" / "002" / "GOAL.md").unlink()
    runs = fs.classify_runs(root_dir)
    assert runs["executing"] is None
    assert [a["run"] for a in runs["anomalies"]] == ["002"]


# ---------------------------------------------------------------------------
# Unpadded ids: deliverables and trace
# ---------------------------------------------------------------------------

def test_unpadded_ids_resolve_deliverables_and_trace(patched_server, fs, flows_root, root_dir):
    state = _state(patched_server)
    ex = state["executing_run"]
    assert ex["first_handoff_id"] == 5
    assert ex["owned_handoffs"] == [5]
    assert ex["current"] == 5
    assert ex["deliverables"]["handoff"] is True
    assert ex["deliverables"]["handoff_file"] == "5-handoff.md"
    assert ex["deliverables"]["result"] is False
    sig = ex["last_signal"]
    assert sig["event"] == "dispatched" and sig["id"] == "5"
    assert sig["from"] == DECOMPOSER and sig["to"] == IMPLEMENTER

    # both forms name the same handoff
    assert fs.deliverables_for(root_dir, "005")["handoff_file"] == "5-handoff.md"
    assert fs.deliverables_for(root_dir, 1)["verdict"] is True
    (root_dir / "verdicts" / "005-verdict.md").write_text("padded verdict\n")
    assert fs.deliverables_for(root_dir, 5)["verdict_file"] == "005-verdict.md"

    # the decoy lines (padded id from another flow; substring role) never match
    roles = [DECOMPOSER, IMPLEMENTER, REVIEWER]
    tail = fs.trace_tail(flows_root, roles, 50)
    assert len(tail) == 5
    assert all("decoy" not in (t["msg"] or "") for t in tail)
    assert all("archi01pay" not in t["raw"] for t in tail)
    assert fs.trace_tail(flows_root, roles, 2)[-1]["raw"].endswith(f"dispatched to {IMPLEMENTER}")
    assert fs.trace_tail(flows_root, ["x-" + IMPLEMENTER], 5)[0]["msg"] == "decoy"
    assert fs.last_trace_signal(flows_root, roles, "005")["ts"] == "2026-09-02T08:55:39Z"


def test_get_run_owned_handoffs_bounded_by_next_floor(patched_server):
    closed = json.loads(patched_server.tool_get_run(ELOOP, 1, include="end_report"))
    assert closed["status"] == "closed"
    assert closed["first_handoff_id"] == 1
    assert [h["id"] for h in closed["handoffs"]] == [1]      # 5 belongs to run 002
    assert closed["handoffs"][0]["verdict"] is True
    assert closed["contents"]["end_report"].startswith("# END-REPORT")
    assert "goal" not in closed["contents"]

    ex = json.loads(patched_server.tool_get_run(ELOOP, "002", include="ledger", ledger_tail_entries=1))
    assert ex["status"] == "executing"
    assert [h["id"] for h in ex["handoffs"]] == [5]
    assert "GOAL promoted" not in ex["contents"]["ledger"]
    assert "Run 002 opened" in ex["contents"]["ledger"]
    assert ex["executing"]["current"] == 5

    waiting = json.loads(patched_server.tool_get_run(ELOOP, 3))
    assert waiting["status"] == "promoted_waiting" and "handoffs" not in waiting
    assert waiting["testgoals"]["status"] == "ok"
    missing = json.loads(patched_server.tool_get_run(ELOOP, 99))
    assert missing["status"] == "missing" and missing["exists"] is False
    bad = json.loads(patched_server.tool_get_run(ELOOP, 2, include="goal,nonsense"))
    assert "error" in bad


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

def test_drafts_from_both_locations(patched_server):
    parsed = json.loads(patched_server.tool_list_goal_drafts(PLOOP))
    by_run = {(d["run"], d["source"]): d for d in parsed["drafts"]}
    assert set(by_run) == {("003", "goals"), ("034", "goals"), ("035", "goals"),
                           ("036", "run_dir")}
    assert parsed["count"] == 4
    assert parsed["promotable"] == ["034", "036"]
    good = by_run[("034", "goals")]
    assert good["testgoals"]["status"] == "ok"
    assert good["testgoals"]["ids"] == ["TG1", "TG2"]
    assert good["promotable"] is True and good["refusal_reasons"] == []
    assert good["title"].startswith("GOAL-DRAFT — Run 034")
    assert by_run[("036", "run_dir")]["promotable"] is True


def test_malformed_testgoals_reported_not_raised(patched_server):
    parsed = json.loads(patched_server.tool_list_goal_drafts(PLOOP))
    bad = next(d for d in parsed["drafts"] if d["run"] == "035")
    assert bad["testgoals"]["status"] == "malformed"
    assert "not a field line" in bad["testgoals"]["error"]
    assert bad["promotable"] is False
    assert any("malformed" in r for r in bad["refusal_reasons"])


def test_promotable_false_when_goal_exists(patched_server, root_dir):
    parsed = json.loads(patched_server.tool_list_goal_drafts(PLOOP))
    d = next(x for x in parsed["drafts"] if x["run"] == "003")
    assert d["promotable"] is False
    assert d["refusal_reasons"] == ["GOAL.md already exists (a Run is promoted once)"]
    # a draft for a closed run is refused on both counts
    (root_dir / "goals" / "1-GOAL-DRAFT.md").write_text("# draft 1\n" + VALID_TESTGOALS)
    parsed = json.loads(patched_server.tool_list_goal_drafts(PLOOP))
    d = next(x for x in parsed["drafts"] if x["run"] == "001")
    assert d["promotable"] is False
    assert len(d["refusal_reasons"]) == 2
    # no testgoals block -> promotable with a warning, as promote-goal warns
    (root_dir / "goals" / "40-GOAL-DRAFT.md").write_text("# draft 40, no block\n")
    parsed = json.loads(patched_server.tool_list_goal_drafts(PLOOP))
    d = next(x for x in parsed["drafts"] if x["run"] == "040")
    assert d["promotable"] is True and d["testgoals"]["status"] == "absent"
    assert d["warnings"]


# ---------------------------------------------------------------------------
# Queues, counters, note
# ---------------------------------------------------------------------------

def test_queue_summary_and_counters(patched_server):
    state = _state(patched_server)
    q = state["queues"]
    assert q["flow_keys"] == [ELOOP, PLOOP]
    assert (q["dispatch"]["pending"], q["dispatch"]["failed"], q["dispatch"]["completed"]) == (1, 1, 3)
    assert len(q["dispatch"]["last"]) == 5
    assert q["dispatch"]["last"][0]["status"] == "pending"        # newest first
    assert all(r["flow_key"] != "t-other" for r in q["dispatch"]["last"])
    assert q["materialize"]["processing"] == 1
    assert all("content" not in r for r in q["materialize"]["last"])
    assert state["counters"] == {ELOOP: 6, PLOOP: 37}
    assert state["flow"]["siblings"] == [PLOOP]
    assert "NOT probed" in state["_note"]
    assert state["planning_backlog"]["size"] > 0


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def test_phase_chain_running(patched_server):
    state = _state(patched_server)
    assert state["phase"] == "CHAIN_RUNNING"
    assert "handoff 5 dispatched" in state["assessment"]
    assert state["runs"]["executing"] == "002"


def test_phase_verdict_ready(patched_server, root_dir):
    (root_dir / "results" / "5-result.md").write_text("result\n")
    (root_dir / "verdicts" / "5-verdict.md").write_text("verdict\n")
    state = _state(patched_server)
    assert state["phase"] == "VERDICT_READY"
    assert state["executing_run"]["deliverables"]["verdict_file"] == "5-verdict.md"


def test_phase_stalled(fs, flows_root, db_path):
    state = fs.collect_state(ELOOP, flows_root, db_path,
                             now=time.time() + fs.STALE_AFTER_SECONDS + 60)
    assert state["phase"] == "STALLED"
    assert state["executing_run"]["stale"] is True


def test_phase_kickoff_next_run(patched_server, root_dir):
    (root_dir / "runs" / "002" / "END-REPORT.md").write_text("SUCCESS\n")
    state = _state(patched_server)
    assert state["phase"] == "KICKOFF_NEXT_RUN"
    assert state["runs"]["executing"] is None
    assert "003" in state["assessment"]


def test_phase_await_promotion_then_all_closed_then_author(patched_server, root_dir):
    (root_dir / "runs" / "002" / "END-REPORT.md").write_text("SUCCESS\n")
    (root_dir / "runs" / "003" / "END-REPORT.md").write_text("SUCCESS\n")
    state = _state(patched_server)
    assert state["phase"] == "AWAIT_PROMOTION"
    assert "refused" in state["assessment"]         # 035 malformed, 003 has GOAL.md

    for p in (root_dir / "goals").iterdir():
        p.unlink()
    (root_dir / "runs" / "036" / "GOAL-DRAFT.md").unlink()
    (root_dir / "runs" / "036").rmdir()
    state = _state(patched_server)
    assert state["phase"] == "ALL_RUNS_CLOSED"

    for run in ("001", "002", "003"):
        for f in (root_dir / "runs" / run).iterdir():
            f.unlink()
        (root_dir / "runs" / run).rmdir()
    state = _state(patched_server)
    assert state["phase"] == "AUTHOR_DRAFTS"


def test_phase_values_are_in_the_contract(fs):
    assert set(fs.PHASES) == {
        "AWAIT_SCOPE", "AUTHOR_DRAFTS", "AWAIT_PROMOTION", "KICKOFF_NEXT_RUN",
        "CHAIN_RUNNING", "VERDICT_READY", "STALLED", "ALL_RUNS_CLOSED"}
