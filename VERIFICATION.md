# mcp-light FastMCP migration verification

Date: 2026-07-05

## Server

- systemd status: `active (running)`, Main PID = fresh venv process
- endpoint: http://127.0.0.1:9135/mcp
- transport: streamable-http (Uvicorn backend, FastMCP)
- bind: 127.0.0.1 only
- ExecStart: `/home/svend/mcp-light/venv/bin/python /home/svend/mcp-light/server.py`

## Tools

Verified all 18 expected tools via real MCP handshake (Python `mcp` client
`streamablehttp_client` + `ClientSession.initialize()` + `list_tools()`):

```
find_reusable_panel, get_existing_panels, get_flow, get_flow_steps,
get_frontend_governance, get_governance_file, get_governance_index,
get_index_structure, get_panel_groups, get_panel_mappings,
get_panel_subgroups, get_panel_subgroups_dynamic,
get_required_frontend_impact_block, get_role, search_context,
search_verdicts, suggest_panel_location, validate_frontend_impact
```

No missing, no extra. Real tool call `get_governance_index` returned 2510 chars
of governance-template content.

## OpenCode

- `opencode mcp list` (imple01 config): `✓ mcp-light connected` at
  http://127.0.0.1:9135/mcp
- no SSE 404 error observed
- `opencode run` real tool call: opencode (qwen3.6:27b-q4_K_M) invoked
  `mcp-light_get_governance_index` and returned a result — end-to-end round-trip
  confirmed

## Claude Code

- `claude mcp list`: `mcp-light: http://127.0.0.1:9135/mcp (HTTP) - ✔ Connected`
- `claude mcp get mcp-light`: Status `✔ Connected`, Type `http`
- (was `✘ Failed to connect` before migration; auto-connected once the server
  became a real MCP HTTP server — no re-registration needed)

## Write capability review

No write/create/update/delete/exec tools exposed. All 18 tool names are
`get_*` / `search_*` / `validate_*` / `find_*` / `suggest_*` — read-only.

## Configs

- All 11 opencode role configs standardized on canonical `mcp.mcp-light` block:
  `{"type":"remote","url":"http://127.0.0.1:9135/mcp","enabled":true,"timeout":10000}`
- No `mcpServers` key remains in any live config.
- Backups at `*.opencode.json.bak-mcp-http` (gitignored).

## Acceptance criteria (all met)

1. systemctl status mcp-light active running ✓
2. ss -ltnp shows 127.0.0.1:9135 listening ✓
3. Python MCP client can initialize against http://127.0.0.1:9135/mcp ✓
4. Python MCP client lists all 18 expected tools ✓
5. OpenCode /mcp shows mcp-light connected ✓
6. OpenCode no longer logs SSE 404 ✓
7. Claude Code mcp-light connected ✓
8. No write/exec/delete/update tools exposed ✓
9. OpenCode configs use only canonical mcp.mcp-light, not mcpServers ✓
