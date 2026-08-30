# mcp-light

Local read-only MCP context server for DPMtF (Deterministic Process
Management to Finalisation — a deterministic multi-agent process
orchestration framework for taking defined work from intent to verified
finalisation through governed flows, steps, roles, harnesses, models,
gates, and artifacts).

Provides Claude Code and OpenCode with access to governance, panel structure,
and project context — without being tied to a specific agent tool.

---

## Overview

### Place in the DPMtF Ecosystem

Four components, one machine boundary:

```
   model-allocator                  model-allocator
   (Father's copy)                  (worker's copy)
         │ resolves role→model            │
         ▼                                ▼
   DPMtF-WebUI ("Father") ◄──────── DPMtF-LightWorker
   flows · dispatch · evidence      polls Father over Tailscale,
   gates · SQLite · port 9130       executes one role at a time in
         │                          disposable worktrees
         └── mcp-light (port 9135)
             read-only context: loopback for Father's own
             roles, a second tailnet instance for workers
```

| Component | Depends on | Provides |
|-----------|-----------|----------|
| model-allocator | its own machine's `models.yaml`/`roles.yaml` | role→model resolution, runtime lifecycle, client configs |
| DPMtF-WebUI | model-allocator (same machine), SQLite | flows, dispatch, evidence gates, LightWorker endpoints, watchdog |
| mcp-light | read access to DPMtF-WebUI's files and database | governance/flow/verdict lookup over MCP |
| DPMtF-LightWorker | model-allocator (worker machine), Father reachable over Tailscale | remote role execution |

**Install order — each step's preflight checks the one before it:**

1. **model-allocator** — on every machine that runs models (Father and
   each worker), with that machine's own config files.
2. **DPMtF-WebUI** — on Father: `init_db` → `migrate` → uvicorn on 9130.
3. **mcp-light** — on Father (optional but standard): loopback unit, plus
   the tailnet unit if remote workers should reach it.
4. **DPMtF-LightWorker** — on each worker: venv → `worker.yaml` → auth
   token → base client config → `preflight.sh` 16/16 → daemon.

Each repository's own Installation section covers its steps in detail.

## Architecture

```
Claude Code ─┐
             ├── MCP client config
OpenCode  ───┘
             ↓
        mcp-light (127.0.0.1:9135)          ← local roles
             ↓
  DPMtF governance/context (read-only)
             ↑
        mcp-light (<tailscale-ip>:9135)     ← remote LightWorkers
             ↑
   OpenCode on another machine, over Tailscale
```

Two instances of the same read-only server, one per bind address. See
[Remote access over Tailscale](#remote-access-over-tailscale).

---

## Requirements

- Python 3.8+
- `mcp[cli]` (see `requirements.txt`) — installed in `venv/`
- Read access to DPMtF-WebUI's filesystem

The server reads the governance and database files directly, so the process
must run on the machine that holds them. Its *clients* need not: they speak
HTTP and can be on another host (see below).

It reads TWO databases, both in read-only mode: Father's
`DPMtF-WebUI/databases/dpmtf.db` (governance, flows, roles, verdicts,
panels, i18n) and `model-allocator/allocator.db` (the i18n-completeness
check for the allocator UI).

## Installation

### Install manually

```bash
git clone https://github.com/svend-blip/mcp-light.git
cd mcp-light
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### Install using an Agent

Point your coding agent at this repository and ask it to run the manual
steps; there is one dependency (`mcp[cli]`) and one file (`server.py`).
The agent must run on the machine holding the DPMtF-WebUI checkout, or set
the root overrides (see Configuration) to reach it.

### Verify installation

```bash
venv/bin/python server.py &      # or: python3 server.py
curl http://127.0.0.1:9135/health
```

```json
{"status": "ok", "server": "mcp-light", "version": "1.4.0", "phase": 4}
```

## Configuration

Everything is environment variables with safe defaults:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MCP_LIGHT_HOST` | `127.0.0.1` | bind address (the tailnet unit overrides it) |
| `MCP_LIGHT_PORT` | `9135` | bind port |
| `DPMTF_WEBUI_ROOT` | `~/DPMtF-WebUI` | Father checkout (governance, DB, templates) |
| `DPMTF_FLOWS_ROOT` | `~/flows` | flow workspace (verdict lookup) |
| `DPMTF_ALLOCATOR_ROOT` | `~/model-allocator` | allocator checkout (i18n check) |

No config file, no secrets: the server is read-only and unauthenticated —
its security model is the bind address (see the Tailscale section).

## Running

### Start

```bash
python3 server.py
```

The server prints no banner of its own — FastMCP/uvicorn log lines appear
as requests arrive. It listens on `http://127.0.0.1:9135/mcp`
(health: `/health`), reads 6 allowed roots, and registers **24 tools**
(verify with an MCP `tools/list` call).

### Stop

`Ctrl+C` in the terminal.

### Autostart on reboot (systemd)

A **user** unit — no root needed. The server runs as the owning user, reads
that user's files and binds a high port.

```bash
cp mcp-light.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mcp-light
loginctl enable-linger $USER    # start at boot without logging in
```

Check status:
```bash
systemctl --user status mcp-light
```

Without `enable-linger` the unit starts on login and stops on logout, which
on a headless host means it never starts at all.

## Testing

```bash
venv/bin/python -m pytest tests/ -q
```

One integration test today (`test_execution_config_tool.py`, run with cwd =
the DPMtF-WebUI checkout, as its header states); broader per-tool coverage
is an open improvement.

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

## Remote access over Tailscale

A client on another machine cannot reach `127.0.0.1`. Since the server is
entirely read-only — 24 tools, no `INSERT`/`UPDATE`/`DELETE`, no file writes —
a **second instance** can serve remote clients over Tailscale without
affecting the local one. Two processes over one database cannot conflict, and
local role configs keep pointing at loopback.

### Why a second instance rather than a wider bind

Binding the existing instance to `0.0.0.0` would also expose it on the LAN and
on every docker bridge on the host — a surface that is easy to forget.
Binding the Tailscale address reaches exactly what needs reaching.

### What it changes

**mcp-light has no authentication.** Loopback-only *was* the security model:
nothing else could reach it, so nothing needed to authenticate. With a tailnet
instance running, **the tailnet is the boundary** — anything on it can read
governance, flows, roles and verdicts. Do not enable this on a tailnet you do
not control.

### Setup

`MCP_LIGHT_HOST` and `MCP_LIGHT_PORT` override the bind address; both default
to loopback and 9135, so an existing deployment is unaffected.

```bash
# on the host that holds the governance files
tailscale ip -4                       # this host's tailnet address
$EDITOR mcp-light-tailnet.service     # set MCP_LIGHT_HOST to it
cp mcp-light-tailnet.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mcp-light-tailnet
```

Both instances then listen side by side:

```bash
$ ss -ltn | grep 9135
LISTEN  0  2048  100.82.231.128:9135  0.0.0.0:*     # remote clients
LISTEN  0  2048       127.0.0.1:9135  0.0.0.0:*     # local roles
```

The unit uses `Restart=always` rather than `on-failure`: at boot it races
`tailscaled`, and binding a Tailscale address fails until the interface
exists. Retrying every 10s removes the race without a user unit having to
depend on a system unit.

### Client configuration

Identical to the local case with the address swapped:

```json
{
  "mcp": {
    "mcp-light": {
      "type": "remote",
      "url": "http://100.82.231.128:9135/mcp",
      "enabled": true,
      "timeout": 10000
    }
  }
}
```

### Verify from the client machine

`/health` answers on GET; the MCP endpoint itself needs a POST and the
streamable-http `Accept` header, which is worth knowing before concluding the
server is down:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://100.82.231.128:9135/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
       "protocolVersion":"2024-11-05","capabilities":{},
       "clientInfo":{"name":"probe","version":"1"}}}'
# 200
```

---

## Available Tools (22)

### Phase 1 — Context retrieval

| Tool | Argument | Returns |
|------|----------|---------|
| `get_frontend_governance` | — | `30_FRONTEND_GOVERNANCE.md` |
| `get_governance_index` | — | List of all governance templates with titles |
| `get_governance_file` | `name` (e.g. `11_SCOPE.md`) | Content of a specific template |
| `get_patcher_usage` | — | Deterministic Patcher usage guide (`docs/specs/DETERMINISTIC_PATCHER_USAGE.md`): PatchRequest format, engines, CLI |
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
| `get_role` | `role_key` | Role details from `bridge_roles` (whitelisted columns only). `governance_file` is the raw role-level value — step-level overrides exist in `bridge_flow_steps`. Use `get_execution_config` for the resolved governance and its source level |
| `get_flow_steps` | `flow_key` | Steps for a flow from `bridge_flow_steps` |
| `get_execution_config` | `flow_key`, `step_key` | Resolved governance/model/harness each with `source_level`, verbatim from DPMtF's resolver (`scripts/bridgeV002/execution_config.py`). THE resolution surface for step-level overrides (Run 016 / D1). Returns a JSON error string (does not raise) for unknown flow/step |
| `get_implementation_mode` | `flow_key`, `step_key?`, `role_key?` | Resolved Deterministic Patcher mode (precedence role > step > flow > `direct`) with per-level stored values |
| `get_panel_subgroups_dynamic` | — | Subgroups live from `panel_subgroups` |
| `get_panel_mappings` | — | Slot→subgroup mappings from `panel_subgroup_mappings` |

### Phase 4 — Review helpers

| Tool | Argument | Returns |
|------|----------|---------|
| `validate_frontend_impact` | `report_text` | `pass`/`fail` with details on what's missing; reports declaring new labels must also declare label-reuse check + the 4 locales |
| `find_reusable_panel` | `feature_name` | Suggestion for existing panel to reuse |
| `suggest_panel_location` | `feature_name` | Suggestion for panel group, subgroup, and key |

### Phase 5 — Coding-standard enforcement (2026-08-08)

| Tool | Argument | Returns |
|------|----------|---------|
| `validate_i18n_completeness` | `project` (`dpmtf`/`model-allocator`) | Labels missing any of the 4 mandatory locales (`en-US`, `da-DK`, `de-DE`, `es-ES`) with per-locale coverage |
| `validate_frontend_code` | `code_text`, `filename?` | Mechanical scan for 12_CODING_STANDARD auto-fail patterns (innerHTML, var, inline style, hardcoded paths); warnings for suspected un-`lbl()`ed text |
| `find_reusable_label` | `text`, `description?`, `project?` | The FIND half of find-or-create: `reuse` (existing identical label + slot-mapping SQL) or `create` (4-locale SQL template). Call BEFORE creating any label |
| `find_duplicate_labels` | `project?` | Label groups with identical text+description that should be merged (keep one, repoint slots, deactivate the rest) |

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
| Never `0.0.0.0` | Bind address is explicit; the default is `127.0.0.1` |

### There is no authentication

Every rule above limits *what* a connected client can read. None of them
limits *who* may connect. Loopback-only was the answer to that: nothing off
the machine could reach the port, so nothing needed to authenticate.

Running the tailnet instance moves that boundary to the tailnet. Anything on
it — every device, and anything running on those devices — can read the
governance, flows, roles and verdicts this server exposes. That is a
deliberate trade for letting remote workers look context up themselves, and
it is only sound on a tailnet you control.

If that is not acceptable for a given deployment, do not install
`mcp-light-tailnet.service`. Nothing else depends on it, and the loopback
instance is unaffected.

---

## Phase Plan

| Phase | Status | Content |
|------|--------|---------|
| 1 — Context | ✅ | Read-only file access, 7 tools (incl. `get_patcher_usage`, 2026-08-16) |
| 2 — Frontend | ✅ | Panel structure, 4 tools |
| 3 — Database | ✅ | SQLite read-only, 6 tools (incl. `get_implementation_mode`, 2026-08-16) |
| 4 — Review | ✅ | Validation and suggestions, 3 tools |
| 5 — Coding standard | ✅ | i18n/auto-fail enforcement (2026-08-08), 4 tools |
