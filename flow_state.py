#!/usr/bin/env python3
"""flow_state — read-only flow-state logic for supervisors (Phase 6).

Pure functions behind the four Phase 6 MCP tools (get_flow_scope,
get_flow_state, get_run, list_goal_drafts). Every function takes its roots
explicitly -- ``flows_root`` (the directory holding trace.log and one
subdirectory per artifact root) and ``db_path`` (Father's dpmtf.db) -- and
never consults DPMtF's ``config`` module. That is what makes the module
testable against a temporary layout and a temporary database, and it is why
the server can be repointed with DPMTF_FLOWS_ROOT / DPMTF_WEBUI_ROOT without
this module noticing.

What it reads: bridge_flows, bridge_flow_steps, bridge_id_counters,
bridge_dispatch_queue, bridge_materialize_queue (all ``mode=ro``), and under
the flow's artifact root: SCOPE.md, goals/, runs/, handoffs/, results/,
verdicts/, plus ``<flows_root>/trace.log``. It writes nothing, executes no
testgoal, and does NOT probe tmux sessions or ports -- liveness of the
chain's sessions is deliberately out of scope for an MCP tool that a
sandboxed role can call.

Where DPMtF already has a pure helper (supervisor_state.first_handoff_id,
check_testgoals.parse_block, ...) this module imports it rather than
re-implementing it, so the two readings of a GOAL.md cannot drift. The
imports are optional: on a machine without the DPMtF checkout on sys.path
the module degrades to its own equivalents and reports that in the output.

Ids are matched in BOTH forms. The 9000 workspace writes handoff files and
trace ids unpadded (``22-handoff.md``, ``| 22 |``); older flows pad
(``022-handoff.md``, ``| 022 |``). Every comparison here goes through
``int()`` so ``21`` and ``021`` are the same handoff.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Optional DPMtF helpers ─────────────────────────────────────
# server.py inserts <WEBUI_ROOT>/scripts/bridgeV002 onto sys.path before
# importing this module, so on Father these resolve. Elsewhere they may not,
# and the module must still import.
try:  # pragma: no cover - exercised only where DPMtF is absent
    import supervisor_state as _sv
except Exception:  # noqa: BLE001 - any import failure means "not available"
    _sv = None

try:  # pragma: no cover - same
    import check_testgoals as _ctg
except Exception:  # noqa: BLE001
    _ctg = None


# ── Constants ──────────────────────────────────────────────────

FLOW_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_RUN_DIR_RE = re.compile(r"^\d+$")
_HANDOFF_FILE_RE = re.compile(r"^(\d+)-handoff\.md$")
_GOALS_DRAFT_RE = re.compile(r"^(\d+)-GOAL-DRAFT\.md$")
_TRACE_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
# Same phrase supervisor_state accepts: a colon or "is" joins the phrase to
# the number; the promoted-GOAL placeholder "set by the kickoff dispatch" is
# not a floor.
_FIRST_ID_RE = re.compile(
    r"First handoff id\s*(?::|\bis\b)\s*\**\s*(\d+)", re.IGNORECASE
)
_TESTGOALS_BLOCK_RE = re.compile(
    r"^```testgoals\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL
)
_TESTGOALS_FIELD_RE = re.compile(r"^(id|what|run|expect):\s*(.*)$")

#: Seconds without movement before a working state reads as STALLED. Taken
#: from supervisor_state when available (three hours, chosen against
#: measured chain times), duplicated here only as the fallback.
STALE_AFTER_SECONDS = int(getattr(_sv, "_STALE_AFTER_SECONDS", 3 * 60 * 60))

PHASES = (
    "AWAIT_SCOPE",
    "AUTHOR_DRAFTS",
    "AWAIT_PROMOTION",
    "KICKOFF_NEXT_RUN",
    "CHAIN_RUNNING",
    "VERDICT_READY",
    "STALLED",
    "ALL_RUNS_CLOSED",
)

_QUEUE_STATUSES = ("pending", "processing", "failed", "completed")
_DISPATCH_COLUMNS = (
    "id", "flow_key", "from_role", "to_role", "handoff_id", "action",
    "status", "created_at", "processed_at", "error_msg",
)
# content is deliberately NOT exposed: a materialize row can hold a whole
# END-REPORT, and a state summary is not the place to ship it.
_MATERIALIZE_COLUMNS = (
    "id", "flow_key", "run_id", "handoff_id", "role_key", "artifact_type",
    "status", "created_at", "processed_at", "error_msg",
)

LIVENESS_NOTE = (
    "Read-only file and database state. tmux sessions, ports and model "
    "servers are NOT probed; 'executing' means the run's artefacts say so, "
    "not that anything is alive."
)


# ── Guards ─────────────────────────────────────────────────────

def validate_flow_key(flow_key):
    """Return flow_key if it is a safe identifier, else raise ValueError."""
    if not isinstance(flow_key, str) or not FLOW_KEY_RE.match(flow_key):
        raise ValueError(
            f"invalid flow_key {flow_key!r}: must match {FLOW_KEY_RE.pattern}"
        )
    return flow_key


def validate_run_id(run_id):
    """Return run_id as a non-negative int, else raise ValueError."""
    if isinstance(run_id, bool):
        raise ValueError(f"invalid run_id {run_id!r}")
    try:
        value = int(run_id)
    except (TypeError, ValueError):
        raise ValueError(f"invalid run_id {run_id!r}: must be an integer") from None
    if value < 0:
        raise ValueError(f"invalid run_id {run_id!r}: must be >= 0")
    return value


def _flow_path(flows_root, *parts):
    """Join parts under flows_root and assert the real path stays inside it.

    The artifact root comes from the database and the flow key from the
    caller; neither is trusted to be free of ``..`` or symlinks pointing
    out of the workspace.
    """
    root = os.path.realpath(str(flows_root))
    candidate = os.path.realpath(os.path.join(root, *[str(p) for p in parts]))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise ValueError(f"path {os.path.join(*parts)!r} escapes flows root")
    return Path(candidate)


def _connect_ro(db_path):
    db_abs = os.path.abspath(str(db_path))
    if not os.path.isfile(db_abs):
        # sqlite would otherwise create nothing in ro mode but report an
        # unhelpful "unable to open database file".
        raise FileNotFoundError(f"database not found: {db_abs}")
    conn = sqlite3.connect(f"file:{db_abs}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pad(handoff_id):
    return f"{int(handoff_id):03d}"


def _stat(path):
    """{size, mtime_utc} for an existing file, or None."""
    try:
        st = path.stat()
    except OSError:
        return None
    return {
        "size": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mtime_epoch": st.st_mtime,
    }


def _read(path):
    return path.read_text(encoding="utf-8", errors="replace")


# ── Flow resolution (database) ─────────────────────────────────

def resolve_flow(flow_key, db_path):
    """Flow configuration from bridge_flows, or KeyError for an unknown flow.

    Unlike bridge_lib.get_effective_artifact_root this does NOT fall back to
    the flow key for an unknown flow: a tool answering "what state is flow X
    in" for a flow that does not exist would be answering about a directory
    that happens to share the name.
    """
    validate_flow_key(flow_key)
    conn = _connect_ro(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM bridge_flows WHERE flow_key = ?", (flow_key,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown flow_key {flow_key!r} (not in bridge_flows)")
        keys = row.keys()

        def col(name, default=None):
            return row[name] if name in keys else default

        artifact_root = (col("artifact_root") or "").strip() or flow_key
        siblings = [
            r["flow_key"] for r in conn.execute(
                "SELECT flow_key FROM bridge_flows "
                "WHERE flow_key != ? "
                "AND COALESCE(NULLIF(TRIM(artifact_root), ''), flow_key) = ? "
                "ORDER BY flow_key",
                (flow_key, artifact_root),
            ).fetchall()
        ] if "artifact_root" in keys else []

        step_rows = conn.execute(
            "SELECT from_role, to_role FROM bridge_flow_steps "
            "WHERE flow_key = ? ORDER BY sort_order, id",
            (flow_key,),
        ).fetchall()
        role_keys = sorted({r for pair in step_rows for r in pair if r})

        counter = conn.execute(
            "SELECT next_id FROM bridge_id_counters WHERE flow_key = ?",
            (flow_key,),
        ).fetchone()
    finally:
        conn.close()

    return {
        "flow_key": flow_key,
        "name": col("name"),
        "is_active": col("is_active"),
        "artifact_root": artifact_root,
        "artifact_root_explicit": bool((col("artifact_root") or "").strip()),
        "target_project_path": (col("target_project_path") or "").strip() or None,
        "supervisor_role": (col("supervisor_role") or "").strip() or None,
        "cold_start_skill": (col("cold_start_skill") or "").strip() or None,
        "supervisor_mandate": (col("supervisor_mandate") or "").strip() or None,
        "commit_cadence": (col("commit_cadence") or "").strip() or "none",
        "siblings": siblings,
        "role_keys": role_keys,
        "counter_next_id": counter["next_id"] if counter else None,
    }


def flow_role_keys(db_path, flow_keys):
    """Role keys across several flows, from bridge_flow_steps."""
    if not flow_keys:
        return []
    conn = _connect_ro(db_path)
    try:
        marks = ",".join("?" * len(flow_keys))
        rows = conn.execute(
            f"SELECT from_role, to_role FROM bridge_flow_steps "
            f"WHERE flow_key IN ({marks})",
            tuple(flow_keys),
        ).fetchall()
    finally:
        conn.close()
    return sorted({r for pair in rows for r in pair if r})


def counters(db_path, flow_keys):
    """{flow_key: next_id} for the given flows (None when no row)."""
    out = {}
    if not flow_keys:
        return out
    conn = _connect_ro(db_path)
    try:
        for key in flow_keys:
            row = conn.execute(
                "SELECT next_id FROM bridge_id_counters WHERE flow_key = ?",
                (key,),
            ).fetchone()
            out[key] = row["next_id"] if row else None
    finally:
        conn.close()
    return out


# ── SCOPE.md ───────────────────────────────────────────────────

def scope(root_dir, mode="full"):
    """SCOPE.md at the artifact root.

    mode: "full" (content), "headings" (markdown headings with line
    numbers), "head" (first 60 lines). A missing SCOPE is a state, not an
    error: ``exists`` is False and nothing else is claimed.
    """
    if mode not in ("full", "headings", "head"):
        raise ValueError(f"unknown mode {mode!r}: use full, headings or head")
    path = Path(root_dir) / "SCOPE.md"
    out = {"path": str(path), "exists": path.is_file(), "mode": mode}
    if not out["exists"]:
        return out
    text = _read(path)
    out.update(_stat(path) or {})
    out.pop("mtime_epoch", None)
    out["line_count"] = text.count("\n") + (0 if text.endswith("\n") else 1)
    headings = [
        {"line": i, "text": line.rstrip()}
        for i, line in enumerate(text.splitlines(), start=1)
        if line.startswith("#")
    ]
    out["heading_count"] = len(headings)
    if mode == "full":
        out["content"] = text
    elif mode == "headings":
        out["headings"] = headings
    else:
        out["content"] = "\n".join(text.splitlines()[:60])
        out["truncated"] = out["line_count"] > 60
    return out


# ── Runs ───────────────────────────────────────────────────────

def first_handoff_id(run_path):
    """The run's floor from GOAL.md, falling back to the ledger; None if unstated."""
    helper = getattr(_sv, "first_handoff_id", None)
    if helper is not None:
        return helper(Path(run_path))
    for name in ("GOAL.md", "RUN-LEDGER.md"):
        path = Path(run_path) / name
        if not path.exists():
            continue
        match = _FIRST_ID_RE.search(_read(path))
        if match:
            return int(match.group(1))
    return None


def ledger_says_opened(run_path):
    """True when RUN-LEDGER.md has a heading containing "opened"."""
    helper = getattr(_sv, "ledger_says_opened", None)
    if helper is not None:
        return bool(helper(Path(run_path)))
    path = Path(run_path) / "RUN-LEDGER.md"
    if not path.exists():
        return False
    return any(
        line.startswith("#") and "opened" in line.lower()
        for line in _read(path).splitlines()
    )


def _run_facts(path):
    facts = {
        "run": path.name,
        "run_id": int(path.name) if _RUN_DIR_RE.match(path.name) else None,
        "goal": (path / "GOAL.md").is_file(),
        "goal_draft": (path / "GOAL-DRAFT.md").is_file(),
        "ledger": (path / "RUN-LEDGER.md").is_file(),
        "backlog": (path / "BACKLOG.md").is_file(),
        "end_report": (path / "END-REPORT.md").is_file(),
    }
    facts["first_handoff_id"] = first_handoff_id(path) if (facts["goal"] or facts["ledger"]) else None
    facts["ledger_opened"] = ledger_says_opened(path) if facts["ledger"] else False
    return facts


def classify_runs(root_dir):
    """Sort runs/ into closed, executing, promoted_waiting and anomalies.

    executing = the LOWEST run with a GOAL.md, no END-REPORT.md, and kickoff
    evidence (a numeric first-handoff floor, or a ledger heading saying it
    was opened). After a bulk promotion every promoted directory holds a
    GOAL.md and a "GOAL promoted" ledger entry, so "newest opened run" is
    the last promotion, not the run the chain is working -- that is the
    mistake this ordering exists to avoid.
    """
    base = Path(root_dir) / "runs"
    out = {
        "closed": [],
        "executing": None,
        "promoted_waiting": [],
        "anomalies": [],
        "details": {},
        "runs_dir": str(base),
        "runs_dir_exists": base.is_dir(),
    }
    if not base.is_dir():
        return out

    entries = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    candidates = []
    for path in entries:
        if not _RUN_DIR_RE.match(path.name):
            out["anomalies"].append({"run": path.name, "issue": "non-numeric run directory"})
            continue
        facts = _run_facts(path)
        out["details"][path.name] = facts
        if facts["end_report"]:
            out["closed"].append(path.name)
            if not facts["goal"]:
                out["anomalies"].append(
                    {"run": path.name, "issue": "END-REPORT.md without GOAL.md"})
            continue
        if facts["goal"]:
            if facts["first_handoff_id"] is not None or facts["ledger_opened"]:
                candidates.append(path.name)
            else:
                out["promoted_waiting"].append(path.name)
            continue
        if facts["goal_draft"]:
            # a draft parked in its run directory -- reported by drafts()
            continue
        if facts["ledger"] or facts["backlog"]:
            out["anomalies"].append(
                {"run": path.name,
                 "issue": "opened-run artefacts (ledger/backlog) but no GOAL.md"})
        else:
            out["anomalies"].append({"run": path.name, "issue": "empty run directory"})

    if candidates:
        out["executing"] = candidates[0]
        for extra in candidates[1:]:
            out["anomalies"].append(
                {"run": extra,
                 "issue": f"shows kickoff evidence while {candidates[0]} is still open"})
        low = [r for r in out["promoted_waiting"] if r < candidates[0]]
        for run in low:
            out["anomalies"].append(
                {"run": run,
                 "issue": f"promoted but never opened, below executing run {candidates[0]}"})
    return out


# ── Handoffs / deliverables / trace ────────────────────────────

def _find_artifact(root_dir, kind, handoff_id):
    """Path of results/handoffs/verdicts file for an id in either form."""
    suffix = {"handoff": "handoff", "result": "result", "verdict": "verdict"}[kind]
    base = Path(root_dir) / f"{suffix}s"
    for stem in (str(int(handoff_id)), _pad(handoff_id)):
        candidate = base / f"{stem}-{suffix}.md"
        if candidate.is_file():
            return candidate
    return None


def deliverables_for(root_dir, handoff_id):
    """Which of handoff/result/verdict exist for one id, and their file names."""
    out = {}
    for kind in ("handoff", "result", "verdict"):
        path = _find_artifact(root_dir, kind, handoff_id)
        out[kind] = path is not None
        out[f"{kind}_file"] = path.name if path else None
    return out


def handoff_ids(root_dir, floor=None):
    """Handoff ids on disk at or above the floor, as ints, ascending."""
    base = Path(root_dir) / "handoffs"
    if not base.is_dir():
        return []
    ids = set()
    for path in base.iterdir():
        match = _HANDOFF_FILE_RE.match(path.name)
        if match:
            value = int(match.group(1))
            if floor is None or value >= floor:
                ids.add(value)
    return sorted(ids)


def parse_trace_line(line):
    """{ts, from, to, roles, id, event, mode, msg, raw} or None."""
    parts = [p.strip() for p in line.rstrip("\n").split("|")]
    if len(parts) < 4:
        return None
    roles = [r.strip() for r in parts[1].split("->") if r.strip()]
    id_text = parts[2]
    try:
        id_int = int(id_text)
    except ValueError:
        id_int = None
    return {
        "ts": parts[0],
        "from": roles[0] if roles else None,
        "to": roles[1] if len(roles) > 1 else None,
        "roles": roles,
        "id": id_text,
        "id_int": id_int,
        "event": parts[3],
        "mode": parts[4] if len(parts) > 4 else None,
        "msg": " | ".join(parts[5:]) if len(parts) > 5 else None,
        "raw": line.rstrip("\n"),
    }


def _trace_lines(flows_root, role_keys):
    path = Path(flows_root) / "trace.log"
    if not path.is_file():
        return []
    wanted = set(role_keys)
    out = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            rec = parse_trace_line(line)
            if rec is None:
                continue
            # Exact match on the role field, never substring: "review01SG"
            # is contained in "imple01SG->review01SG", and a flow's role
            # name can be a prefix of another flow's.
            if any(r in wanted for r in rec["roles"]):
                out.append(rec)
    return out


def trace_tail(flows_root, role_keys, n=10):
    """Last n trace records whose role field names one of role_keys exactly."""
    n = max(0, int(n))
    lines = _trace_lines(flows_root, role_keys)
    return lines[-n:] if n else []


def last_trace_signal(flows_root, role_keys, handoff_id):
    """Final trace record for this handoff id (either form) among these roles."""
    target = int(handoff_id)
    found = None
    for rec in _trace_lines(flows_root, role_keys):
        if rec["id_int"] == target:
            found = rec
    return found


def trace_epoch(record):
    if not record:
        return None
    match = _TRACE_TS_RE.search(record["ts"] if isinstance(record, dict) else str(record))
    if not match:
        return None
    naive = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    return naive.replace(tzinfo=timezone.utc).timestamp()


def humanize_age(seconds):
    helper = getattr(_sv, "humanize_age", None)
    if helper is not None:
        return helper(seconds)
    if seconds is None:
        return "age unknown"
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes:02d}m ago"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h ago"


def last_movement(root_dir, run_path, current, last_signal):
    """Latest evidence that the run moved: {epoch, source} or None.

    Latest, never earliest -- measuring from the run's opening rather than
    the last signal is what stops a fresh run reading as a stall.
    """
    candidates = []
    epoch = trace_epoch(last_signal)
    if epoch is not None:
        candidates.append((epoch, "trace signal"))
    if current is not None:
        for kind in ("verdict", "result", "handoff"):
            path = _find_artifact(root_dir, kind, current)
            if path is not None:
                candidates.append((path.stat().st_mtime, f"{kind} file mtime"))
    if run_path is not None:
        for name, label in (("RUN-LEDGER.md", "RUN-LEDGER.md mtime"),
                            ("GOAL.md", "GOAL.md mtime (run opening)")):
            path = Path(run_path) / name
            if path.exists():
                candidates.append((path.stat().st_mtime, label))
    if not candidates:
        return None
    epoch, source = max(candidates, key=lambda pair: pair[0])
    return {"epoch": epoch, "source": source}


# ── Drafts ─────────────────────────────────────────────────────

def _parse_testgoals(text):
    """{status: ok|malformed|absent|unavailable, count, error, ids}."""
    if _ctg is not None:
        try:
            records = _ctg.parse_block(text)
        except _ctg.CriterionError as exc:
            return {"status": "malformed", "count": 0, "error": str(exc), "ids": []}
        return {"status": "ok" if records else "absent", "count": len(records),
                "error": None, "ids": [r.get("id") for r in records]}
    # Fallback mirror of check_testgoals.parse_block, used only when the
    # DPMtF checkout is not importable. Kept structurally identical.
    match = _TESTGOALS_BLOCK_RE.search(text)
    if not match:
        return {"status": "absent", "count": 0, "error": None, "ids": [],
                "parser": "fallback"}
    records, current = [], {}
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        field = _TESTGOALS_FIELD_RE.match(line)
        if not field:
            return {"status": "malformed", "count": 0, "ids": [],
                    "error": f"not a field line: {line!r}", "parser": "fallback"}
        key, value = field.group(1), field.group(2).strip()
        if key in current:
            return {"status": "malformed", "count": 0, "ids": [],
                    "error": f"{current.get('id', '?')}: duplicate {key!r}",
                    "parser": "fallback"}
        current[key] = value
    if current:
        records.append(current)
    for record in records:
        for required in ("id", "run", "expect"):
            if required not in record:
                return {"status": "malformed", "count": 0, "ids": [],
                        "error": f"{record.get('id', '?')}: missing {required!r}",
                        "parser": "fallback"}
    return {"status": "ok" if records else "absent", "count": len(records),
            "error": None, "ids": [r.get("id") for r in records],
            "parser": "fallback"}


def drafts(root_dir):
    """GOAL-DRAFT files from goals/{N}-GOAL-DRAFT.md and runs/NNN/GOAL-DRAFT.md.

    ``promotable`` mirrors promote-goal's refusals without executing
    anything: refused when the run already holds GOAL.md, when it is closed
    (END-REPORT.md), or when the testgoals block cannot be parsed. A draft
    without a testgoals block is promotable with a warning, exactly as the
    command warns. When both locations hold a draft for one id, promote-goal
    takes goals/ and the run-dir copy is marked shadowed.
    """
    root = Path(root_dir)
    found = []
    goals_dir = root / "goals"
    if goals_dir.is_dir():
        for path in sorted(goals_dir.iterdir()):
            match = _GOALS_DRAFT_RE.match(path.name)
            if match and path.is_file():
                found.append((int(match.group(1)), "goals", path))
    runs_dir = root / "runs"
    if runs_dir.is_dir():
        for path in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            draft = path / "GOAL-DRAFT.md"
            if _RUN_DIR_RE.match(path.name) and draft.is_file():
                found.append((int(path.name), "run_dir", draft))

    seen_in_goals = {rid for rid, src, _ in found if src == "goals"}
    out = []
    for run_id, source, path in sorted(found, key=lambda t: (t[0], t[1])):
        run_dir = runs_dir / f"{run_id:03d}"
        text = _read(path)
        testgoals = _parse_testgoals(text)
        reasons = []
        if (run_dir / "END-REPORT.md").is_file():
            reasons.append("run is closed (END-REPORT.md exists)")
        if (run_dir / "GOAL.md").is_file():
            reasons.append("GOAL.md already exists (a Run is promoted once)")
        if testgoals["status"] == "malformed":
            reasons.append(f"testgoals block malformed: {testgoals['error']}")
        warnings = []
        if testgoals["status"] == "absent":
            warnings.append("no ```testgoals block (would promote with a warning)")
        shadowed = source == "run_dir" and run_id in seen_in_goals
        if shadowed:
            warnings.append("shadowed: promote-goal prefers goals/ for this id")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                      if ln.startswith("#")), None)
        info = _stat(path) or {}
        info.pop("mtime_epoch", None)
        out.append({
            "run_id": run_id,
            "run": f"{run_id:03d}",
            "source": source,
            "path": str(path),
            "title": title,
            **info,
            "testgoals": testgoals,
            "promotable": not reasons and not shadowed,
            "refusal_reasons": reasons,
            "warnings": warnings,
        })
    return out


# ── Queues ─────────────────────────────────────────────────────

def _queue_block(conn, table, columns, flow_keys, limit=5):
    marks = ",".join("?" * len(flow_keys))
    try:
        counts = {s: 0 for s in _QUEUE_STATUSES}
        for row in conn.execute(
            f"SELECT status, COUNT(*) AS n FROM {table} "
            f"WHERE flow_key IN ({marks}) GROUP BY status",
            tuple(flow_keys),
        ).fetchall():
            counts[row["status"]] = row["n"]
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} "
            f"WHERE flow_key IN ({marks}) ORDER BY id DESC LIMIT ?",
            tuple(flow_keys) + (int(limit),),
        ).fetchall()
    except sqlite3.Error as exc:
        return {"unavailable": str(exc)}
    return {
        "pending": counts["pending"],
        "processing": counts["processing"],
        "failed": counts["failed"],
        "completed": counts["completed"],
        "last": [dict(r) for r in rows],
    }


def queue_summary(db_path, flow_keys, limit=5):
    """Dispatch and materialize queue counts + the last rows for these flows."""
    flow_keys = [validate_flow_key(k) for k in flow_keys]
    if not flow_keys:
        return {"dispatch": None, "materialize": None}
    conn = _connect_ro(db_path)
    try:
        return {
            "flow_keys": flow_keys,
            "dispatch": _queue_block(
                conn, "bridge_dispatch_queue", _DISPATCH_COLUMNS, flow_keys, limit),
            "materialize": _queue_block(
                conn, "bridge_materialize_queue", _MATERIALIZE_COLUMNS, flow_keys, limit),
        }
    finally:
        conn.close()


# ── Executing-run detail ───────────────────────────────────────

def _executing_summary(root_dir, flows_root, run_name, role_keys, now):
    run_path = Path(root_dir) / "runs" / run_name
    floor = first_handoff_id(run_path)
    owned = handoff_ids(root_dir, floor) if floor is not None else []
    current = owned[-1] if owned else None
    deliverables = deliverables_for(root_dir, current) if current is not None else {}
    signal = last_trace_signal(flows_root, role_keys, current) if current is not None else None
    movement = last_movement(root_dir, run_path, current, signal)
    stale = False
    if movement is not None:
        movement = dict(movement)
        movement["seconds_ago"] = max(0, int(now - movement["epoch"]))
        movement["ago"] = humanize_age(movement["seconds_ago"])
        stale = movement["seconds_ago"] > STALE_AFTER_SECONDS
    return {
        "run": run_name,
        "run_id": int(run_name),
        "first_handoff_id": floor,
        "owned_handoffs": owned,
        "current": current,
        "deliverables": deliverables,
        "last_signal": signal,
        "last_movement": movement,
        "stale": stale,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "artefacts": {
            name: (run_path / name).is_file()
            for name in ("GOAL.md", "RUN-LEDGER.md", "BACKLOG.md", "END-REPORT.md")
        },
    }


# ── Phase ──────────────────────────────────────────────────────

def phase(state):
    """(phase, assessment) for an assembled state dict. Order matters."""
    scope_info = state.get("scope") or {}
    runs = state.get("runs") or {}
    draft_list = state.get("drafts") or []
    ex = state.get("executing_run")

    if not scope_info.get("exists"):
        return "AWAIT_SCOPE", (
            "SCOPE.md is missing at the artifact root — nothing can be "
            "planned against; the Human must author it")

    if runs.get("executing"):
        run = runs["executing"]
        if ex is None:
            return "CHAIN_RUNNING", f"run {run} is executing (detail unavailable)"
        current = ex.get("current")
        d = ex.get("deliverables") or {}
        mv = ex.get("last_movement") or {}
        ago = mv.get("ago", "age unknown")
        if current is None:
            if ex.get("first_handoff_id") is None:
                return "CHAIN_RUNNING", (
                    f"run {run} is opened but states no first handoff id — "
                    f"it owns nothing until the floor is written")
            if ex.get("stale"):
                return "STALLED", (
                    f"run {run} opened {ago} and no handoff at or above "
                    f"{ex['first_handoff_id']} exists on disk")
            return "CHAIN_RUNNING", (
                f"run {run} opened ({ago}); first handoff "
                f"{ex['first_handoff_id']} not yet on disk")
        if d.get("verdict"):
            return "VERDICT_READY", (
                f"verdict for handoff {current} is on disk ({ago}) — "
                f"validate the testgoals yourself, then act")
        if ex.get("stale"):
            what = "result delivered, no verdict" if d.get("result") else "handoff dispatched, nothing back"
            return "STALLED", (
                f"handoff {current}: {what} for {ago.removesuffix(' ago')} "
                f"(> {STALE_AFTER_SECONDS // 3600}h) — check the session "
                f"before dispatching anything")
        if d.get("result"):
            return "CHAIN_RUNNING", (
                f"result for handoff {current} delivered ({ago}); the reviewer is working")
        return "CHAIN_RUNNING", (
            f"handoff {current} dispatched ({ago}); the implementer is working")

    if runs.get("promoted_waiting"):
        nxt = runs["promoted_waiting"][0]
        return "KICKOFF_NEXT_RUN", (
            f"no run is executing; run {nxt} is promoted (GOAL.md, no kickoff) — "
            f"{len(runs['promoted_waiting'])} promoted run(s) waiting")

    if draft_list:
        ok = [d["run"] for d in draft_list if d["promotable"]]
        bad = [d["run"] for d in draft_list if not d["promotable"]]
        note = f"{len(ok)} promotable"
        if bad:
            note += f", {len(bad)} refused ({', '.join(bad)})"
        return "AWAIT_PROMOTION", (
            f"no run open; {len(draft_list)} draft(s) await Human promotion — {note}")

    if runs.get("closed"):
        return "ALL_RUNS_CLOSED", (
            f"every run ({len(runs['closed'])}) holds an END-REPORT; no drafts, "
            f"nothing promoted — the next Run needs a draft from the planning supervisor")

    return "AUTHOR_DRAFTS", (
        "SCOPE.md exists but there are no runs and no drafts — author the first GOAL-DRAFT")


# ── Assembly ───────────────────────────────────────────────────

def _root_dir(flows_root, flow):
    return _flow_path(flows_root, flow["artifact_root"])


def collect_state(flow_key, flows_root, db_path, now=None, trace_n=10):
    """Everything get_flow_state returns, as a dict."""
    now = time.time() if now is None else now
    flow = resolve_flow(flow_key, db_path)
    root_dir = _root_dir(flows_root, flow)
    flow_keys = [flow_key] + list(flow["siblings"])
    role_keys = flow_role_keys(db_path, flow_keys)

    state = {
        "flow": flow,
        "root_dir": str(root_dir),
        "root_dir_exists": root_dir.is_dir(),
        "scope": scope(root_dir, "headings"),
        "runs": classify_runs(root_dir),
        "drafts": drafts(root_dir),
        "executing_run": None,
        "counters": counters(db_path, flow_keys),
        "queues": queue_summary(db_path, flow_keys),
        "trace_tail": trace_tail(flows_root, role_keys, trace_n),
        "role_keys": role_keys,
        "planning_backlog": _stat(root_dir / "planning" / "PLOOP-BACKLOG.md"),
        "helpers": {
            "supervisor_state": _sv is not None,
            "check_testgoals": _ctg is not None,
        },
        "_note": LIVENESS_NOTE,
    }
    if state["planning_backlog"]:
        state["planning_backlog"].pop("mtime_epoch", None)
    state["scope"].pop("headings", None)

    if state["runs"]["executing"]:
        state["executing_run"] = _executing_summary(
            root_dir, flows_root, state["runs"]["executing"], role_keys, now)

    state["phase"], state["assessment"] = phase(state)
    return state


def _ledger_tail(text, entries):
    """The last N '## ' entries of a ledger (plus the title line)."""
    if entries <= 0:
        return text
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if len(starts) <= entries:
        return text
    head = lines[:starts[0]] if starts else []
    return "\n".join(head + lines[starts[-entries]:])


def run_detail(flow_key, run_id, flows_root, db_path, include="goal,ledger,end_report",
               ledger_tail_entries=0, now=None):
    """One run: artefacts, classification, contents on request, handoffs."""
    run_id = validate_run_id(run_id)
    flow = resolve_flow(flow_key, db_path)
    root_dir = _root_dir(flows_root, flow)
    run_name = f"{run_id:03d}"
    run_path = _flow_path(flows_root, flow["artifact_root"], "runs", run_name)
    wanted = {p.strip() for p in str(include or "").split(",") if p.strip()}
    known = {"goal", "ledger", "end_report", "draft", "backlog"}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(f"unknown include item(s): {', '.join(unknown)}; "
                         f"choose from {', '.join(sorted(known))}")

    runs = classify_runs(root_dir)
    facts = runs["details"].get(run_name)
    if run_name in runs["closed"]:
        status = "closed"
    elif runs["executing"] == run_name:
        status = "executing"
    elif run_name in runs["promoted_waiting"]:
        status = "promoted_waiting"
    elif facts and facts.get("goal_draft"):
        status = "draft"
    elif facts:
        status = "anomaly"
    else:
        status = "missing"

    out = {
        "flow_key": flow_key,
        "artifact_root": flow["artifact_root"],
        "run": run_name,
        "run_id": run_id,
        "path": str(run_path),
        "exists": run_path.is_dir(),
        "status": status,
        "facts": facts,
        "anomalies": [a for a in runs["anomalies"] if a["run"] == run_name],
        "files": {},
        "_note": LIVENESS_NOTE,
    }
    if not run_path.is_dir():
        return out

    for name in ("GOAL.md", "GOAL-DRAFT.md", "RUN-LEDGER.md", "BACKLOG.md", "END-REPORT.md"):
        info = _stat(run_path / name)
        if info:
            info.pop("mtime_epoch", None)
        out["files"][name] = info

    contents = {}
    mapping = {"goal": "GOAL.md", "draft": "GOAL-DRAFT.md", "ledger": "RUN-LEDGER.md",
               "backlog": "BACKLOG.md", "end_report": "END-REPORT.md"}
    for key in sorted(wanted):
        path = run_path / mapping[key]
        if not path.is_file():
            contents[key] = None
            continue
        text = _read(path)
        if key == "ledger" and ledger_tail_entries:
            text = _ledger_tail(text, int(ledger_tail_entries))
        contents[key] = text
    out["contents"] = contents

    if facts and (facts["goal"] or facts["goal_draft"]):
        source = run_path / ("GOAL.md" if facts["goal"] else "GOAL-DRAFT.md")
        out["testgoals"] = _parse_testgoals(_read(source))

    floor = facts["first_handoff_id"] if facts else None
    out["first_handoff_id"] = floor
    if floor is not None:
        flow_keys = [flow_key] + list(flow["siblings"])
        role_keys = flow_role_keys(db_path, flow_keys)
        # A closed run's ids run from its floor up to the next run's floor;
        # without that bound every later handoff would be listed as its own.
        ceiling = None
        for name, f in sorted(runs["details"].items()):
            if name > run_name and f.get("first_handoff_id") is not None:
                ceiling = f["first_handoff_id"]
                break
        ids = [i for i in handoff_ids(root_dir, floor) if ceiling is None or i < ceiling]
        out["handoffs"] = [
            {"id": i, **deliverables_for(root_dir, i),
             "last_signal": last_trace_signal(flows_root, role_keys, i)}
            for i in ids
        ]
        if status == "executing":
            out["executing"] = _executing_summary(
                root_dir, flows_root, run_name, role_keys,
                time.time() if now is None else now)
    return out


# ── Compact mode (Phase 6 extension) ──────────────────────────

def get_flow_state(flow_key, mode="full", flows_root=None, db_path=None, now=None):
    """Public entry point for flow state.

    mode="compact" returns a summary dict <= 600 chars JSON-serialized:
    phase, executing run, last signal, queue depth, session status, next
    expected event. mode="full" (default) returns the full collect_state dict.
    """
    if flows_root is None:
        flows_root = os.environ.get(
            "DPMTF_FLOWS_ROOT", os.path.expanduser("~/flows"))
    if db_path is None:
        webui = os.environ.get(
            "DPMTF_WEBUI_ROOT", os.path.expanduser("~/DPMtF-WebUI"))
        db_path = os.path.join(webui, "databases", "dpmtf.db")

    state = collect_state(flow_key, flows_root, db_path, now=now)

    if mode != "compact":
        return state

    # Build compact summary
    ex = state.get("executing_run") or {}
    runs = state.get("runs") or {}
    queues = state.get("queues") or {}
    dispatch = queues.get("dispatch") or {}

    # Last signal: abbreviated event from trace
    signal_rec = ex.get("last_signal")
    sig_event = signal_rec.get("event", "?") if signal_rec else "none"

    # Session status
    if ex.get("stale"):
        session = "stale"
    elif runs.get("executing"):
        session = "active"
    else:
        session = "idle"

    # Next expected event
    ph = state.get("phase", "?")
    next_map = {
        "AWAIT_SCOPE": "scope_author",
        "AUTHOR_DRAFTS": "draft_author",
        "AWAIT_PROMOTION": "promotion",
        "KICKOFF_NEXT_RUN": "kickoff",
        "CHAIN_RUNNING": "result_or_verdict",
        "VERDICT_READY": "supervisor_action",
        "STALLED": "intervention",
        "ALL_RUNS_CLOSED": "new_draft",
    }

    compact = {
        "ph": ph,
        "run": runs.get("executing"),
        "sig": sig_event,
        "q": dispatch.get("pending", 0),
        "sess": session,
        "next": next_map.get(ph, "?"),
    }
    return compact
