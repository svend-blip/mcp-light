"""validate_flow_family — the 104_FLOW_CREATION structural checker.

Runs against the temporary t9000 layout/database from conftest.py; never
touches the live workspace. Asserts the tool RUNS read-only and reports a
per-item PASS/FAIL line-set, rather than pinning t9000 to a full pass (the
tmp fixture carries no roles.yaml entry or skill files, so those items are
expected FAILs — the point is the tool never raises).
"""
from __future__ import annotations

from conftest import ROOT


def test_returns_string_and_reports_both_flows(patched_server):
    out = patched_server.tool_validate_flow_family(ROOT)
    assert isinstance(out, str)
    assert "validate_flow_family" in out
    # t9000's two flows exist in the fixture DB -> the flows check passes.
    assert "[PASS] both flows exist" in out


def test_unknown_family_all_fail_no_crash(patched_server):
    out = patched_server.tool_validate_flow_family("zzzz-none")
    assert isinstance(out, str)
    assert "[FAIL] both flows exist" in out  # graceful, not an exception


def test_empty_family_errors(patched_server):
    out = patched_server.tool_validate_flow_family("")
    assert out.startswith("Error")
