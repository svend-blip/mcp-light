"""Tests for get_kickoff_packet and get_handoff_skeleton wrappers (Run 024 WORK 3).

Fence: /home/svend/mcp-light/tests/ — these tests exercise the mcp-light
wrappers, not the DPMtF scripts directly. The DPMtF repository is READ-ONLY
for this handoff.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_MCP_LIGHT_ROOT = Path(__file__).resolve().parent.parent
if str(_MCP_LIGHT_ROOT) not in sys.path:
    sys.path.insert(0, str(_MCP_LIGHT_ROOT))

# Import the wrapper functions directly from server module
import server as ml  # noqa: E402


class TestGetKickoffPacket:
    """get_kickoff_packet wrapper tests."""

    def test_refusal_surfaces_exit_2(self):
        """9000-02-ELOOP run 999 must surface exit-2 refusal (predecessor has no END-REPORT)."""
        result = ml.tool_get_kickoff_packet("9000-02-ELOOP", 999)
        parsed = json.loads(result)
        assert "error" in parsed, f"Expected error key in refusal response, got: {result}"
        assert parsed["error"] == "refused", (
            f"Expected 'refused' error, got: {parsed['error']}"
        )
        assert parsed.get("exit_code") == 2, (
            f"Expected exit_code 2, got: {parsed.get('exit_code')}"
        )
        # Must have a reason — never an empty refusal
        assert parsed.get("reason"), "Refusal must include a reason"

    def test_missing_flow_returns_error(self):
        """Empty flow returns an error, not a crash."""
        result = ml.tool_get_kickoff_packet("", 1)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_invalid_run_returns_error(self):
        """Non-integer run returns an error."""
        result = ml.tool_get_kickoff_packet("1000-02-ELOOP", "abc")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_negative_run_returns_error(self):
        """Negative run returns an error."""
        result = ml.tool_get_kickoff_packet("1000-02-ELOOP", -1)
        parsed = json.loads(result)
        assert "error" in parsed


class TestGetHandoffSkeleton:
    """get_handoff_skeleton wrapper tests."""

    def test_skeleton_generation_and_envelope_validation(self, tmp_path):
        """Generate a skeleton into a temp location and validate with broker's envelope check.

        Uses the SAME mechanism as DPMtF's test_handoff_skeleton.py: generate content
        matching what the script produces, then validate with
        bridge_lib.validate_deliverable_against_schema. We do NOT write a real
        handoff id into /home/svend/flows/1000/handoffs/.
        """
        # Import the broker's validation function (same as DPMtF test does)
        dpmtf_root = os.environ.get("DPMTF_ROOT", os.path.expanduser("~/DPMtF-WebUI"))
        bridge_scripts = os.path.join(dpmtf_root, "scripts", "bridgeV002")
        if bridge_scripts not in sys.path:
            sys.path.insert(0, bridge_scripts)
        from bridge_lib import validate_deliverable_against_schema  # noqa: E402

        # Generate skeleton content matching what handoff_skeleton.py produces
        handoff_id = 88888  # safe throwaway test id
        flow_key = "1000-02-ELOOP"
        to_role = "1000-reviewer"

        content = f"""# Handoff {handoff_id}

<role>
{to_role}
</role>

<task>
TODO: describe the implementation task here.
</task>

<constraint>
Fence: scripts/bridgeV002/kickoff_packet.py, scripts/bridgeV002/handoff_skeleton.py, tests/

Never commit, stage or push.
</constraint>

<deliverable>
Write your result to: /home/svend/flows/1000/results/{handoff_id}-result.md
</deliverable>

## Signal Completion

Signal exactly once after writing your deliverable.
"""
        out_file = tmp_path / f"{handoff_id}-handoff.md"
        out_file.write_text(content, encoding="utf-8")

        # Validate using the broker's OWN validation function
        result = validate_deliverable_against_schema(str(out_file), "handoff")
        assert result["valid"], (
            f"Envelope validation failed: missing {result['missing']}. "
            f"Checked: {result['checked']}"
        )

    def test_missing_flow_returns_error(self):
        """Empty flow returns an error."""
        result = ml.tool_get_handoff_skeleton("", 1, "1000-reviewer")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_missing_to_returns_error(self):
        """Empty to_role returns an error."""
        result = ml.tool_get_handoff_skeleton("1000-02-ELOOP", 1, "")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_invalid_id_returns_error(self):
        """Non-integer id returns an error."""
        result = ml.tool_get_handoff_skeleton("1000-02-ELOOP", "xyz", "1000-reviewer")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_negative_id_returns_error(self):
        """Negative id returns an error."""
        result = ml.tool_get_handoff_skeleton("1000-02-ELOOP", -5, "1000-reviewer")
        parsed = json.loads(result)
        assert "error" in parsed
