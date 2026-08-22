#!/usr/bin/env python3
"""Test suite for the get_execution_config MCP tool (Run 016 / D3).

Self-locating: derives its import paths from __file__ so the suite runs
from any cwd (TG4 binds pytest with cwd=/home/svend/DPMtF-WebUI).

Four test functions, each selectable by `-k <keyword>` (GOAL.md §2
"Names bound"):

  -k parity            -> test_parity_repointed_step, test_parity_role_level_step
  -k unknown           -> test_unknown_flow_step_reports_error
  -k serves_generic    -> test_serves_generic_governance_files_by_name
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `import server` work regardless of the caller's cwd. server.py's
# top-level import block already inserts scripts/bridgeV002 onto sys.path
# (via _BRIDGE_DIR derived from WEBUI_ROOT), so once `server` is imported
# `execution_config` is reachable as a top-level module.
_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

import server as ml  # noqa: E402  (imports first; inserts bridgeV002 onto sys.path)
import execution_config as ec  # noqa: E402  (depends on server's path setup)


# ---------------------------------------------------------------------------
# 1. Parity — repointed step (governance_file set at step level)
# ---------------------------------------------------------------------------


def test_parity_repointed_step():
    """strict_review/archi01-imple01 has ARCHITECT.md at step level.

    The resolver and the MCP tool must return IDENTICAL 13-key dicts,
    with governance_source_level == 'step'. The dict equality is the
    parity invariant; the source-level assertion names the case so a
    regression to 'role' is caught with a useful message.
    """
    flow_key = "strict_review"
    step_key = "archi01-imple01"

    a = ec.resolve_execution_config(flow_key, step_key)
    b = json.loads(ml.tool_get_execution_config(flow_key, step_key))

    assert a == b, (
        f"resolver/tool parity violated for repointed step {flow_key}/"
        f"{step_key}: keys only in a={set(a)-set(b)}, keys only in "
        f"b={set(b)-set(a)}"
    )
    assert a["governance_source_level"] == "step", (
        f"expected step-level resolution, got {a['governance_source_level']!r}"
    )
    assert a["governance_file"] == "ARCHITECT.md"


# ---------------------------------------------------------------------------
# 2. Parity — non-repointed step (governance_file falls through to role)
# ---------------------------------------------------------------------------


def test_parity_role_level_step():
    """trade_cockpit_simulation_v001/trend01-market01: step is NULL, role
    resolves 431_TRADE_TREND01.md at source_level 'role'."""
    flow_key = "trade_cockpit_simulation_v001"
    step_key = "trend01-market01"

    a = ec.resolve_execution_config(flow_key, step_key)
    b = json.loads(ml.tool_get_execution_config(flow_key, step_key))

    assert a == b, (
        f"resolver/tool parity violated for role-level step {flow_key}/"
        f"{step_key}: keys only in a={set(a)-set(b)}, keys only in "
        f"b={set(b)-set(a)}"
    )
    assert a["governance_source_level"] == "role", (
        f"expected role-level resolution, got "
        f"{a['governance_source_level']!r}"
    )


# ---------------------------------------------------------------------------
# 3. Unknown flow/step — tool REPORTS the error, does not RAISE
# ---------------------------------------------------------------------------


def test_unknown_flow_step_reports_error():
    """An unknown flow_key/step_key pair must NOT raise — the tool returns
    a JSON string with an 'error' field (Run 016 / D3, GOAL.md §1 D3).

    The assertion that the call returned normally is implicit in reaching
    the json.loads() call; an unhandled exception would fail the test
    before then.
    """
    result = ml.tool_get_execution_config("nope_flow", "nope_step")

    # The tool returns a JSON string (not a dict) — assert that shape too
    # so a future regression to dict-return doesn't slip past silently.
    assert isinstance(result, str), (
        f"tool should return a JSON string, got {type(result).__name__}"
    )
    parsed = json.loads(result)
    assert "error" in parsed, (
        f"expected an 'error' key in the unknown-step payload: {parsed!r}"
    )


# ---------------------------------------------------------------------------
# 4. _resolve_governance_file serves the generic governance files by name
# ---------------------------------------------------------------------------


def test_serves_generic_governance_files_by_name():
    """The pre-existing mcp-light helper _resolve_governance_file must
    resolve the four generic governance filenames used by dispatch (the
    ones Run 016 / D2 / D3 must keep working) and reject a nonexistent
    file."""
    from server import _resolve_governance_file

    for name in (
        "SUPERVISOR_AUTONOMOUS.md",
        "ARCHITECT.md",
        "IMPLEMENTOR.md",
        "REVIEW.md",
    ):
        path = _resolve_governance_file(name)
        assert path is not None, (
            f"_resolve_governance_file({name!r}) returned None"
        )
        assert str(path).endswith(name), (
            f"_resolve_governance_file({name!r}) returned {path!r}, "
            f"expected it to end with {name!r}"
        )

    # Unknown file must NOT be served (None, not a path).
    assert _resolve_governance_file("DOES_NOT_EXIST.md") is None
