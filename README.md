# mcp-light

Local read-only MCP context server for DPMtF.

Provides Claude Code and OpenCode with access to governance, panel structure,
and project context — without being tied to a specific agent tool.

---

## Architecture

```
Claude Code ─┐
             ├── MCP client config
OpenCode  ───┘
             ↓
        mcp-light (127.0.0.1:9135)
             ↓
  DPMtF governance/context (read-only)
```

---

## Installation

### Requirements

- Python 3.8+
- No external dependencies (standard library only)
- Access to DPMtF-WebUI's filesystem (same machine)

### Start

```bash
cd /home/svend/mcp-light
python3 server.py
```

Output:
```
mcp-light v1.4.0 — Phase 4 (read-only context + SQLite + review helpers)
Listening on http://127.0.0.1:9135/mcp
Health check: http://127.0.0.1:9135/health
Allowed roots: 6
Available tools: 18
```

### Stop

`Ctrl+C` in the terminal.

### Autostart on reboot (systemd)

```bash
sudo cp mcp-light.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mcp-light
sudo systemctl start mcp-light
```

Check status:
```bash
systemctl status mcp-light
```

### Health check

```bash
curl http://127.0.0.1:9135/health
```

```json
{"status": "ok", "server": "mcp-light", "version": "1.4.0", "phase": 4}
```

---

## Client Configuration

### Claude Code

Claude Code bruger `~/.claude/settings.json` eller `settings.local.json`.

### OpenCode (opencode ≥ 1.17)

Tilføj under `"mcp"` i rollens `opencode.json`:

```json
{
  "mcp": {
    "mcp-light": {
      "type": "remote",
      "url": "http://127.0.0.1:9135/mcp",
      "enabled": true
    }
  }
}
```

Placering: `~/.config/opencode-roles/\<rolle\>/opencode.json`

**Vigtigt:** Brug `"mcp"` — ikke `"mcpServers"`. Ældre opencode-skemaer understøttede `mcpServers`, men opencode ≥ 1.17 kræver `"mcp"` med `"type": "remote"` for HTTP/SSE-servers.

---

## Available Tools (18)

### Phase 1 — Context retrieval

| Tool | Argument | Returns |
|------|----------|---------|
| `get_frontend_governance` | — | `30_FRONTEND_GOVERNANCE.md` |
| `get_governance_index` | — | List of all governance templates with titles |
| `get_governance_file` | `name` (e.g. `11_SCOPE.md`) | Content of a specific template |
| `get_required_frontend_impact_block` | — | Standard Frontend Impact block for output |
| `search_context` | `query` | Search results in governance/context files |
| `search_verdicts` | `query` | Search results in verdict files |

### Phase 2 — Frontend context

| Tool | Argument | Returns |
|------|----------|---------|
| `get_panel_groups` | — | Panel groups: Daily, Journals, Reports, Periodic, Setup |
| `get_panel_subgroups` | — | Known subgroups with keys and titles |
| `get_existing_panels` | — | Existing panels from `index.html` |
| `get_index_structure` | — | Overview of `index.html` structure |

### Phase 3 — Database (read-only SQLite)

| Tool | Argument | Returns |
|------|----------|---------|
| `get_flow` | `flow_key` | Flow details from `bridge_flows` |
| `get_role` | `role_key` | Role details from `bridge_roles` (whitelisted columns only) |
| `get_flow_steps` | `flow_key` | Steps for a flow from `bridge_flow_steps` |
| `get_panel_subgroups_dynamic` | — | Subgroups live from `panel_subgroups` |
| `get_panel_mappings` | — | Slot→subgroup mappings from `panel_subgroup_mappings` |

### Phase 4 — Review helpers

| Tool | Argument | Returns |
|------|----------|---------|
| `validate_frontend_impact` | `report_text` | `pass`/`fail` with details on what's missing |
| `find_reusable_panel` | `feature_name` | Suggestion for existing panel to reuse |
| `suggest_panel_location` | `feature_name` | Suggestion for panel group, subgroup, and key |

---

## Examples

### Validate Frontend Impact

Request:
```json
{
  "method": "tools/call",
  "params": {
    "name": "validate_frontend_impact",
    "arguments": {
      "report_text": "## Frontend Impact\n\n- Frontend impact: add button\n- index.html impact: no\n- Panel group/subgroup: setup/sg_setup_system\n- Existing panel reused: yes\n- New panel needed: no\n- Frontend verification: node --check"
    }
  }
}
```

Response:
```json
{
  "status": "pass",
  "reason": "All required Frontend Impact fields present."
}
```

### Find reusable panel

Request:
```json
{
  "method": "tools/call",
  "params": {
    "name": "find_reusable_panel",
    "arguments": {
      "feature_name": "bridge"
    }
  }
}
```

Response:
```json
{
  "feature": "bridge",
  "best_match": "bridge-flows-section — Flows (score=3)",
  "candidates": [
    "bridge-flows-section — Flows (score=3)",
    "bridge-steps-section — Steps (score=3)",
    "bridge-roles-section — Roles (score=3)"
  ]
}
```

### Suggest panel location

Request:
```json
{
  "method": "tools/call",
  "params": {
    "name": "suggest_panel_location",
    "arguments": {
      "feature_name": "Machine Profile"
    }
  }
}
```

Response:
```json
{
  "feature": "Machine Profile",
  "suggested_group": "setup",
  "reason": "Matched keywords: profile, machine",
  "existing_subgroups": ["sg_setup_flows — Flows", "sg_setup_system — System Setup"],
  "next_sort_order": 8,
  "suggested_subgroup_key": "sg_setup_machine_profile"
}
```

---

## Security

| Rule | Implementation |
|------|---------------|
| Whitelisted directories only | `ALLOWED_ROOTS` — 6 paths |
| Whitelisted tables only | `ALLOWED_TABLES` — 5 tables |
| Whitelisted columns only | `ALLOWED_COLUMNS` — per table |
| Read-only database | `mode=ro` in SQLite URI |
| No `shell=True` | All subprocess calls use list arguments |
| No write access | Only `SELECT`, no `INSERT`/`UPDATE`/`DELETE` |
| No path traversal | `os.path.realpath()` + prefix check |
| No free-form SQL | Only hardcoded parameterized queries with `?` |
| Only `.md` files | `os.path.basename()` + extension check |
| Localhost only | `127.0.0.1` — never `0.0.0.0` |

---

## Phase Plan

| Phase | Status | Content |
|------|--------|---------|
| 1 — Context | ✅ | Read-only file access, 6 tools |
| 2 — Frontend | ✅ | Panel structure, 4 tools |
| 3 — Database | ✅ | SQLite read-only, 5 tools |
| 4 — Review | ✅ | Validation and suggestions, 3 tools |
