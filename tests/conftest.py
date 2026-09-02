"""Shared fixtures for the mcp-light test suite.

Phase 6 (flow state) fixtures build a temporary flows root with a 9000-like
layout and a temporary SQLite database carrying the bridge tables the tools
read, then repoint ``server.FLOWS_ROOT`` / ``server.DB_PATH`` at them. The
pre-existing execution-config test does not use these fixtures and keeps
running against the live database.

Flow keys here are prefixed ``t`` (``t9000-01-PLOOP``) so that nothing in
this suite can be mistaken for the live 9000 workspace, and so that the
advisory cross-check against DPMtF's own resolver (which reads Father's live
database) finds no such flow and stays silent.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402  (inserts scripts/bridgeV002 onto sys.path)
import flow_state  # noqa: E402

ROOT = "t9000"
PLOOP = "t9000-01-PLOOP"
ELOOP = "t9000-02-ELOOP"
DECOMPOSER = "t9000-execution-decomposer"
IMPLEMENTER = "t9000-implementer"
REVIEWER = "t9000-reviewer"
SUPERVISOR = "t9000-planning-supervisor"

VALID_TESTGOALS = """
```testgoals
id: TG1
what: the module compiles
run: python3 -m py_compile flow_state.py
expect: exit 0

id: TG2
what: the README names the tool
run: grep -q get_flow_state README.md
expect: exit 0
```
"""

MALFORMED_TESTGOALS = """
```testgoals
id: TG1
what: a field line that is not a field
this line has no key
expect: exit 0
```
"""

# Schema copied from the live dpmtf.db (`.schema <table>`), trimmed to the
# columns the tools read plus the CHECK constraints, which are the part
# worth keeping identical.
SCHEMA = """
CREATE TABLE bridge_flows (
    flow_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    step_order TEXT,
    is_default INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    target_project_path TEXT DEFAULT NULL,
    supervisor_role TEXT DEFAULT NULL,
    artifact_root TEXT NULL,
    cold_start_skill TEXT DEFAULT NULL,
    supervisor_mandate TEXT DEFAULT NULL,
    commit_cadence TEXT NOT NULL DEFAULT 'none'
);
CREATE TABLE bridge_flow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_key TEXT NOT NULL,
    step_key TEXT NOT NULL,
    from_role TEXT NOT NULL,
    to_role TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    governance_file TEXT DEFAULT NULL,
    FOREIGN KEY (flow_key) REFERENCES bridge_flows(flow_key),
    UNIQUE(flow_key, step_key)
);
CREATE TABLE bridge_roles (
    role_key TEXT PRIMARY KEY,
    tmux_session TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    governance_file TEXT DEFAULT NULL,
    role_type TEXT DEFAULT 'agent'
);
CREATE TABLE bridge_id_counters (
    flow_key TEXT PRIMARY KEY,
    next_id  INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE bridge_dispatch_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_key TEXT NOT NULL,
    from_role TEXT NOT NULL,
    to_role TEXT NOT NULL,
    handoff_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('signal-send', 'signal-complete', 'signal-escalation', 'signal-answer')),
    handoff_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    claimed_at TEXT,
    processed_at TEXT,
    error_msg TEXT,
    broker_pid INTEGER
);
CREATE INDEX bridge_dispatch_queue_status_idx ON bridge_dispatch_queue(status, id);
CREATE INDEX bridge_dispatch_queue_flow_idx ON bridge_dispatch_queue(flow_key, status, id);
CREATE TABLE bridge_materialize_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_key TEXT NOT NULL,
    run_id INTEGER,
    handoff_id INTEGER,
    role_key TEXT,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('backlog', 'run-ledger', 'handoff', 'end-report', 'escalation-response')),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    claimed_at TEXT,
    processed_at TEXT,
    error_msg TEXT,
    broker_pid INTEGER
);
CREATE INDEX bridge_materialize_queue_status_idx ON bridge_materialize_queue(status, id);
CREATE INDEX bridge_materialize_queue_flow_idx ON bridge_materialize_queue(flow_key, status, id);
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_flows_root(base: Path) -> Path:
    """A 9000-like workspace: one closed run, one executing, one promoted."""
    root = base / ROOT
    _write(root / "SCOPE.md",
           "# FlowRunner — SCOPE.md\n\n## 1. Mission\n\nText.\n\n## 2. Bounds\n\nMore.\n")

    # goals/: 34 valid, 35 malformed, 3 targets a run that already has GOAL.md
    _write(root / "goals" / "34-GOAL-DRAFT.md",
           "<run_id>34</run_id>\n\n# GOAL-DRAFT — Run 034: valid\n" + VALID_TESTGOALS)
    _write(root / "goals" / "35-GOAL-DRAFT.md",
           "# GOAL-DRAFT — Run 035: malformed\n" + MALFORMED_TESTGOALS)
    _write(root / "goals" / "3-GOAL-DRAFT.md",
           "# GOAL-DRAFT — Run 003: already promoted\n" + VALID_TESTGOALS)

    # runs/001 — closed
    _write(root / "runs" / "001" / "GOAL.md",
           "# GOAL — Run 001\n\n**First handoff id: 1**\n" + VALID_TESTGOALS)
    _write(root / "runs" / "001" / "RUN-LEDGER.md",
           "# RUN-LEDGER — run 001\n\n## 2026-09-01T10:00:00Z — Run 001 opened\n"
           "- First handoff id: 1\n\n## 2026-09-01T12:00:00Z — closed\n")
    _write(root / "runs" / "001" / "END-REPORT.md", "# END-REPORT — Run 001\n\nSUCCESS\n")

    # runs/002 — executing: promoted placeholder in GOAL.md, floor in the ledger
    _write(root / "runs" / "002" / "GOAL.md",
           "# GOAL — Run 002\n\nFirst handoff id: set by the kickoff dispatch.\n"
           + VALID_TESTGOALS)
    _write(root / "runs" / "002" / "RUN-LEDGER.md",
           "# RUN-LEDGER — run 002\n\n"
           "## 2026-09-01T18:35:46Z — GOAL promoted (recorded Human approval)\n"
           "- GOAL-DRAFT.md -> GOAL.md by `promote-goal`, approved-by: test\n"
           "## 2026-09-02T08:46:19Z — Run 002 opened (kickoff)\n"
           "- **First handoff id: 5** (flow counter next_id=5)\n")

    # runs/003 — promoted, waiting for kickoff (bulk promotion)
    _write(root / "runs" / "003" / "GOAL.md",
           "# GOAL — Run 003\n\nFirst handoff id: set by the kickoff dispatch.\n"
           + VALID_TESTGOALS)
    _write(root / "runs" / "003" / "RUN-LEDGER.md",
           "# RUN-LEDGER — run 003\n\n"
           "## 2026-09-01T18:35:47Z — GOAL promoted (recorded Human approval)\n")

    # runs/036 — a draft parked in its run directory (broker goal-draft channel)
    _write(root / "runs" / "036" / "GOAL-DRAFT.md",
           "# GOAL-DRAFT — Run 036: run-dir draft\n" + VALID_TESTGOALS)

    # chain artefacts, ids UNPADDED as the 9000 workspace writes them
    _write(root / "handoffs" / "1-handoff.md", "# handoff 1\n")
    _write(root / "results" / "1-result.md", "# result 1\n")
    _write(root / "verdicts" / "1-verdict.md", "# verdict 1\n")
    _write(root / "handoffs" / "5-handoff.md", "# handoff 5\n")
    _write(root / "handoffs" / "current.md", "# pointer, not a handoff\n")
    (root / "results").mkdir(exist_ok=True)
    (root / "verdicts").mkdir(exist_ok=True)
    _write(root / "planning" / "PLOOP-BACKLOG.md", "# PLOOP BACKLOG\n")

    trace = "\n".join([
        # an older flow, padded ids, same handoff number -- must NOT match
        f"2026-07-02T15:47:48Z | archi01pay->imple01pay | 005 | dispatched | manual | Handoff 005-handoff.md dispatched",
        # a role whose name CONTAINS ours as a substring -- must NOT match
        f"2026-09-02T07:00:00Z | x-{IMPLEMENTER}->x-{REVIEWER} | 5 | dispatched | manual | decoy",
        f"2026-09-02T08:00:00Z | {DECOMPOSER}->{IMPLEMENTER} | 1 | dispatched | manual | Handoff 1-handoff.md dispatched",
        f"2026-09-02T08:10:00Z | {IMPLEMENTER}->{REVIEWER} | 1 | signal_complete | manual | Callback dispatched",
        f"2026-09-02T08:20:00Z | {REVIEWER}->{DECOMPOSER} | 1 | signal_complete | manual | Callback dispatched",
        f"2026-09-02T08:55:23Z | {IMPLEMENTER} | 5 | receiver_execution_config | manual | flow={ELOOP} gov_file=IMPLEMENTOR.md",
        f"2026-09-02T08:55:39Z | {DECOMPOSER}->{IMPLEMENTER} | 5 | dispatched | manual | Handoff 5-handoff.md dispatched to {IMPLEMENTER}",
    ]) + "\n"
    _write(base / "trace.log", trace)
    return base


def build_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO bridge_flows (flow_key, name, target_project_path, "
            "supervisor_role, artifact_root, cold_start_skill, "
            "supervisor_mandate, commit_cadence) VALUES (?,?,?,?,?,?,?,?)",
            [
                (PLOOP, "t9000 planning", "/tmp", SUPERVISOR, ROOT, "9000", None, "none"),
                (ELOOP, "t9000 execution", "/tmp", SUPERVISOR, ROOT, "9000",
                 "Human: drive the ELOOP over promoted runs", "per_run"),
                ("t-other", "unrelated flow", None, None, None, None, None, "none"),
                ("t-escape", "artifact root escapes", None, None, "../escape", None, None, "none"),
            ],
        )
        conn.executemany(
            "INSERT INTO bridge_flow_steps (flow_key, step_key, from_role, to_role, sort_order) "
            "VALUES (?,?,?,?,?)",
            [
                (PLOOP, "human-planning", "human", SUPERVISOR, 1),
                (PLOOP, "planning-human", SUPERVISOR, "human", 2),
                (ELOOP, "decomposer-implementer", DECOMPOSER, IMPLEMENTER, 1),
                (ELOOP, "implementer-reviewer", IMPLEMENTER, REVIEWER, 2),
                (ELOOP, "reviewer-decomposer", REVIEWER, DECOMPOSER, 3),
            ],
        )
        conn.executemany(
            "INSERT INTO bridge_roles (role_key, tmux_session, role_type) VALUES (?,?,?)",
            [
                (SUPERVISOR, "t9000-sup", "agent"),
                (DECOMPOSER, "t9000-dec", "agent"),
                (IMPLEMENTER, "t9000-imp", "agent"),
                (REVIEWER, "t9000-rev", "agent"),
                ("human", "none", "human"),
            ],
        )
        conn.executemany(
            "INSERT INTO bridge_id_counters (flow_key, next_id) VALUES (?,?)",
            [(PLOOP, 37), (ELOOP, 6)],
        )
        conn.executemany(
            "INSERT INTO bridge_dispatch_queue (flow_key, from_role, to_role, handoff_id, "
            "action, status, processed_at, error_msg) VALUES (?,?,?,?,?,?,?,?)",
            [
                (ELOOP, DECOMPOSER, IMPLEMENTER, "1", "signal-send", "completed", "2026-09-02 08:00:00", None),
                (ELOOP, IMPLEMENTER, REVIEWER, "1", "signal-complete", "completed", "2026-09-02 08:10:00", None),
                (ELOOP, REVIEWER, DECOMPOSER, "001", "signal-complete", "failed", "2026-09-02 08:15:00", "pane busy"),
                (ELOOP, DECOMPOSER, IMPLEMENTER, "005", "signal-send", "completed", "2026-09-02 08:55:39", None),
                (ELOOP, IMPLEMENTER, REVIEWER, "5", "signal-complete", "pending", None, None),
                ("t-other", "a", "b", "9", "signal-send", "pending", None, None),
            ],
        )
        conn.executemany(
            "INSERT INTO bridge_materialize_queue (flow_key, run_id, handoff_id, role_key, "
            "artifact_type, content, status, processed_at) VALUES (?,?,?,?,?,?,?,?)",
            [
                (ELOOP, 1, None, None, "end-report", "# END-REPORT secret body", "completed", "2026-09-01 12:00:00"),
                (ELOOP, 2, None, None, "run-ledger", "ledger entry", "completed", "2026-09-02 08:46:20"),
                (ELOOP, 2, 5, IMPLEMENTER, "handoff", "handoff body", "processing", None),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def flows_root(tmp_path) -> Path:
    return build_flows_root(tmp_path / "flows")


@pytest.fixture
def db_path(tmp_path) -> Path:
    return build_db(tmp_path / "dpmtf-test.db")


@pytest.fixture
def root_dir(flows_root) -> Path:
    return flows_root / ROOT


@pytest.fixture
def patched_server(monkeypatch, flows_root, db_path):
    """server module with FLOWS_ROOT / DB_PATH pointed at the temp layout."""
    monkeypatch.setattr(ml, "FLOWS_ROOT", str(flows_root))
    monkeypatch.setattr(ml, "DB_PATH", str(db_path))
    return ml


@pytest.fixture
def fs():
    return flow_state
