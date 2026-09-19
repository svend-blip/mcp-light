# mcp-light

## DPMtF — The right model, the right harness, the right role

**DPMtF (Deterministic Process Management to Finalisation)** is an open-source framework for coordinating multiple AI agents, models, and coding tools through a controlled process from defined intent to verified completion.

Instead of using the same — and often most expensive — LLM for every task, DPMtF is designed around assigning **the model that best fits each role**.

A powerful premium model can be used for architecture, planning, supervision, or difficult decisions, while lower-cost cloud models or local models can handle implementation, routine work, decomposition, or parts of the review process. The Model Allocator keeps model selection separate from the workflow itself, allowing roles to move between local and cloud-based models without redesigning the process.

The same principle applies to the tools surrounding the model.

DPMtF supports multiple **coding harnesses**, including Codex, Claude Code, OpenCode, DeepSeek Harness, Whip, Simple Harness, and others. The Harness Allocator keeps harness selection separate from model selection, because the best harness is not necessarily the same for every model or every role.

A powerful cloud agent may benefit from a feature-rich coding harness, while a local model may perform better through a lighter harness with less overhead. DPMtF therefore treats the model and the harness as separate parts of the execution configuration rather than forcing every agent through the same toolchain.

At the center, **[DPMtF-WebUI](https://github.com/svend-blip/DPMtF-WebUI)** coordinates flows, roles, governance, dispatch, gates, and verification. **[Model Allocator](https://github.com/svend-blip/model-allocator)** resolves and manages the models. **[Harness Allocator](https://github.com/svend-blip/harness-allocator)** provides the appropriate coding environment. **[mcp-light](https://github.com/svend-blip/mcp-light)** gives agents controlled, read-only access to governance and project context. **[DPMtF-LightWorker](https://github.com/svend-blip/DPMtF-LightWorker)** allows execution to be distributed to other machines while the central DPMtF system remains in control.

The result is an AI workflow that can be optimized per role for **capability, cost, speed, local hardware, privacy, and tooling** instead of using premium models and heavyweight tools everywhere.

DPMtF is not about finding one AI agent that can do everything.

It is about building a governed AI team where different agents can do what they are best suited for — and where their work is moved through a deterministic process toward a verified result.

**The right model, the right harness, the right role — premium resources only where they add value.**

**The DPMtF ecosystem:** [DPMtF-WebUI](https://github.com/svend-blip/DPMtF-WebUI) · [model-allocator](https://github.com/svend-blip/model-allocator) · [harness-allocator](https://github.com/svend-blip/harness-allocator) · [mcp-light](https://github.com/svend-blip/mcp-light) · [DPMtF-LightWorker](https://github.com/svend-blip/DPMtF-LightWorker) · [simple-harness](https://github.com/svend-blip/simple-harness)

---

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

### Ecosystem dependencies and installation order

**This repository is row 5.** It cannot start usefully before DPMtF-WebUI is checked out and its database initialised, and four of its tools — `knowledge_search`, `knowledge_scopes`, `knowledge_learning`, `knowledge_retrievals` — answer `unreachable` until knowledge-service is up. `KNOWLEDGE_SERVICE_URL` (default `http://127.0.0.1:9140`) and `KNOWLEDGE_SERVICE_TOKEN` (default: none sent) are read from the environment.

The same table is in the README of each of the six repositories; it was
written from the code on 2026-09-19 and follows it. Install top to bottom: each row
needs only rows above it.

| # | Repository | Needs | Serves | Needed by |
|---|---|---|---|---|
| 0 | a model runtime (Ollama, FreeToken, llama.cpp, a cloud endpoint) | — | an OpenAI-compatible `/v1` endpoint | every harness |
| 1 | [simple-harness](https://github.com/svend-blip/simple-harness) | Go 1.27 to build; row 0 to run | the `simple-harness` command on `PATH` | FlowRunner steps that name it, DPMtF-WebUI roles launched through harness-allocator |
| 2 | [scope-mcp](https://github.com/svend-blip/scope-mcp) | Node >= 22.5 (built-in `node:sqlite`) | a stdio MCP server; state in `<workspace>/.scope-mcp/state.db` | any harness that declares it (row 6) |
| 3 | [knowledge-service](https://github.com/svend-blip/knowledge-service) | Python >= 3.11; provider `leann`: a CUDA GPU with ~2.5 GB free VRAM; provider `portable`: CPU only | `http://127.0.0.1:9140/v1` — retrieval over LEANN indexes | mcp-light (four `knowledge_*` tools), DPMtF-WebUI (service mode) |
| 4 | [DPMtF-WebUI](https://github.com/svend-blip/DPMtF-WebUI) | Python 3.10+, tmux, git; [model-allocator](https://github.com/svend-blip/model-allocator) and [harness-allocator](https://github.com/svend-blip/harness-allocator) beside it; a harness on `PATH` (row 1); row 3 optional | `:9130`, the governance templates, BridgeV002, `DPMtF-WebUI/databases/dpmtf.db` | mcp-light (reads its files and database) |
| 5 | [mcp-light](https://github.com/svend-blip/mcp-light) | Python 3.8+, `mcp[cli]`; read access to the DPMtF-WebUI checkout and database (row 4) and to `model-allocator/allocator.db`; row 3 for the knowledge tools | `http://127.0.0.1:9135/mcp` — read-only MCP context server | any harness that declares it (row 6) |
| 6 | harness wiring | rows 1, 2, 5 | `~/.simple-harness/config.json` with an `mcp_servers` entry per server | every simple-harness run on the machine, whoever launched it |
| 7 | [FlowRunner](https://github.com/svend-blip/FlowRunner) | Go 1.27 to build; at run time, every harness a FlowApp's steps name, on `PATH` (row 1 for `simple-harness`) | the `flowrunner` command and desktop app | — |

Rows 1, 2 and 3 depend on nothing else in the table and can be installed
in any order. knowledge-service's one-time `import-registry` step reads
the DPMtF-WebUI database, so run that step after row 4; the service itself
does not need DPMtF-WebUI at run time.

#### Row 6: what wires a harness to the servers

simple-harness takes its MCP servers from its own configuration:
`~/.simple-harness/config.json`, then the nearest
`.simple-harness/config.json` at or above its working directory, then the
file `SIMPLE_HARNESS_CONFIG_FILE` names. A later file replaces an earlier
one's `mcp_servers` whole. FlowRunner writes that last file for a FlowApp
that declares `mcp_servers` (see below); DPMtF-WebUI's BridgeV002 writes
none, so its roles get what the machine's own files declare:

```json
{
  "mcp_servers": [
    { "name": "mcp-light", "transport": "http",
      "endpoint": "http://127.0.0.1:9135/mcp", "permission": "read_only",
      "allowlist": ["get_governance_index", "get_governance_file",
                    "knowledge_search", "knowledge_scopes",
                    "knowledge_learning", "knowledge_retrievals"] },
    { "name": "scope-mcp", "transport": "stdio",
      "command": ["node", "/abs/path/to/scope-mcp/src/server.js"],
      "permission": "workspace_write" }
  ]
}
```

Without the `knowledge_*` names in the allowlist an agent has no
retrieval. Without the scope-mcp entry it has no durable project state:
no simple-harness configuration declares scope-mcp unless you add it. A
stdio server is started in the workspace, so scope-mcp keeps its state
with the project.

#### How LEANN retrieval reaches an agent

```text
model in a harness
  -> the harness's MCP client              (mcp_servers, row 6)
  -> mcp-light          :9135/mcp          knowledge_search / _scopes / _learning / _retrievals
  -> knowledge-service  :9140/v1           /v1/search, /v1/scopes, /v1/learning, /v1/retrievals
  -> LEANN (hnsw, CUDA)  or the portable CPU provider
```

LEANN lives in knowledge-service and nowhere else. mcp-light is its only
MCP face. scope-mcp has no retrieval of any kind, and simple-harness has
none of its own: it is a generic MCP client that also fills in `run_id`,
`handoff_id` and `flow_key` on MCP calls from `SIMPLE_HARNESS_RUN_ID`,
`SIMPLE_HARNESS_HANDOFF_ID` and `SIMPLE_HARNESS_FLOW_KEY`, so that a
retrieval can be attributed to the run that made it.

#### What is and is not automatic

- FlowRunner has no default harness: every step of a FlowApp names one,
  and an empty `harness:` fails validation. A step that names
  `simple-harness` gets whatever `simple-harness` resolves to on `PATH`
  at dispatch — so a rebuilt simple-harness is used by the next run with
  no change to FlowRunner. The Windows bundle carries its own
  `simple-harness.exe`; FlowRunner's `build-windows-bundle.sh` script
  builds the three programs together and stamps the commits into
  `BUILD-INFO.txt`.
- A FlowApp declares its MCP servers (`mcp_servers:` in `app.yaml`:
  `endpoint_env` for an http server, a `command` with `${VAR}` references
  for a stdio one). FlowRunner's preflight connects to each — a real MCP
  handshake and tool listing — and the run is handed exactly those servers
  through `SIMPLE_HARNESS_CONFIG_FILE`, written under FlowRunner's runtime
  root, never into the workspace. `flowrunner mcp <flowapp-id>` and the
  desktop's green pills show which declared servers FlowRunner is
  connected to. A FlowApp that declares none leaves simple-harness with
  the machine's `~/.simple-harness/config.json`, as before: on a machine
  without that file such a FlowApp runs with no MCP server at all.
- A FlowApp's `knowledge:` block reaches a harness as
  `KNOWLEDGE_PROVIDERS` and `KNOWLEDGE_<NAME>_URL`. simple-harness does not
  read them: for a simple-harness step retrieval comes through an MCP
  server that offers `knowledge_search` (mcp-light does), and FlowRunner's
  preflight refuses a FlowApp that enables knowledge, runs simple-harness
  steps and declares no such server, instead of letting it run and
  retrieve nothing.
- Both launchers set the three position variables. FlowRunner sets them
  from the family run number, the handoff cycle and the FlowApp id.
  BridgeV002's role terminal sets them per delivered prompt — a pane
  outlives its handoffs — from the flow key, the run the chain is
  executing and the handoff id field of the prompt; what it does not know
  it does not set.
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
{"status": "ok", "server": "mcp-light", "version": "1.6.0", "phase": 6, "tools": 31}
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
| `KNOWLEDGE_SERVICE_URL` | `http://127.0.0.1:9140` | knowledge-service base URL, used by the four `knowledge_*` tools |
| `KNOWLEDGE_SERVICE_TOKEN` | (empty) | sent as `X-Knowledge-Token` when set; empty sends no header |

No config file; the one secret it can carry is the knowledge-service
token above, which localhost installs leave empty. The server is read-only
and unauthenticated —
its security model is the bind address (see the Tailscale section).

## Running

### Start

```bash
python3 server.py
```

The server prints no banner of its own — FastMCP/uvicorn log lines appear
as requests arrive. It listens on `http://127.0.0.1:9135/mcp`
(health: `/health`, a plain GET registered via `FastMCP.custom_route`),
reads 6 allowed roots, and registers **31 tools**
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

Two suites: `test_execution_config_tool.py` is an integration test against
the live database (run with cwd = the DPMtF-WebUI checkout, as its header
states); `test_flow_state_tools.py` covers the Phase 6 tools against a
temporary 9000-like flows root and a temporary SQLite database built in
`tests/conftest.py`, so it touches neither the live workspace nor `dpmtf.db`.

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
entirely read-only — 29 tools, no `INSERT`/`UPDATE`/`DELETE`, no file writes —
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

## Available Tools (33)

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
| `knowledge_search` | `query`, `scope?`, `workspace?`, `top_k?`, `token_budget?`, `agent_role?`, `flow_key?`, `run_id?`, `handoff_id?`, `cross_repo?`, `evidence_level?`, `include_history?` | Semantic retrieval through the knowledge service (`GET /v1/search`) over plain HTTP (provider-neutral). Default (`cross_repo: true`) spans three scopes — `ecosystem`, `experience`, then the repository scope — splitting `token_budget` 60 % / 20 % / 20 % and flowing an unused learning share back to the repository call: `{scope, provider, count, results:[{scope, path, score, snippet, metadata}], scopes_searched:[{scope, status, count}]}` on success, typed `{error, detail}` otherwise (`denied`, `unknown_scope`, `not_ready`, `unreachable`); `cross_repo: false` makes exactly one repository call; never raises |
| `knowledge_scopes` | — | The service's registry from `GET /v1/scopes`: JSON array of `{scope, provider, status, document_count}` — which repositories have memory |
| `knowledge_learning` | `view?` (`admitted`/`history`/`drafts`), `pending_only?`, `family?` | Read-only inventory of closed-run learning from `GET /v1/learning` (`history=true` for superseded/retracted) or `GET /v1/learning/drafts` (`pending=true` for still-pending ones): `{view, count, artifacts}` — `{view, count, drafts}` for drafts — rows passed through unchanged, `family` filtered client-side; typed `{error, detail}` (`denied`, `unknown_scope`, `not_ready`, `unreachable`, `unknown view`); never raises |
| `knowledge_retrievals` | `run_id?`, `handoff_id?`, `flow_key?`, `agent_role?`, `scope?`, `since?`, `until?`, `limit?`, `summary?` | Read-only view of the service's retrieval log from `GET /v1/retrievals`: every search it served, newest first, with `provider`, `scope`, `query`, `result_count`, `sources`, `retrieved_token_count`, `retrieval_duration_ms`, `agent_role`, `run_id`, `handoff_id`, `flow_key`, `created_at`. Filters combine with AND and unset ones stay out of the query string; `limit` is clamped to 1..200 here (the service clamps again at 500); `summary: true` answers the aggregate (`retrievals`, `results`, `tokens`, `duration_ms`, `scopes`, `agent_roles`, `first`, `last`) instead of rows. The service's dict passes through with each row's `query` cut to 200 characters and its `sources` to the first 5 entries; typed `{error, detail}` (`denied`, `unknown_scope`, `not_ready`, `unreachable`); never raises |

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

### Phase 6 — Flow state for supervisors (2026-09-02)

Read-only answers to "where is this flow" for a planning supervisor or a
Human, replacing the shell-command reconstruction a cold-started supervisor
otherwise performs. Paths are resolved through `bridge_flows.artifact_root`,
so sibling flows sharing one workspace (`9000-01-PLOOP` / `9000-02-ELOOP`)
report the same runs. Handoff ids match in both forms (`21` and `021`).
**tmux sessions, ports and model servers are NOT probed** — `executing`
means the run's artefacts say so, not that anything is alive (every payload
carries this in `_note`). Unknown flow, bad id or a path that would leave
the flows root come back as `{"error": ...}`; nothing raises.

| Tool | Argument | Returns |
|------|----------|---------|
| `get_flow_scope` | `flow_key`, `mode?` (`full`/`headings`/`head`) | `SCOPE.md` at the artifact root; a missing file is `exists: false`, not an error |
| `get_flow_state` | `flow_key` | Flow config (artifact root, siblings, target project, supervisor role/mandate/cadence, cold-start skill, id counters); run classification — `closed`, `executing` (the **lowest** open run with kickoff evidence: a numeric first-handoff floor or a ledger heading saying "opened"; after a bulk promotion the newest GOAL.md is not the run being worked), `promoted_waiting`, `anomalies`; the executing run's owned handoffs, current deliverables, last trace signal, last movement and staleness; GOAL-DRAFTs with promotability; dispatch/materialize queue counts + last 5 rows; trace tail for the flow's roles; `phase` ∈ `AWAIT_SCOPE`, `AUTHOR_DRAFTS`, `AWAIT_PROMOTION`, `KICKOFF_NEXT_RUN`, `CHAIN_RUNNING`, `VERDICT_READY`, `STALLED`, `ALL_RUNS_CLOSED` with a one-line `assessment`. When DPMtF's own `supervisor_state.executing_run` is importable its answer is reported under `dpmtf_cross_check` |
| `get_run` | `flow_key`, `run_id`, `include?` (`goal,ledger,end_report`; also `draft`, `backlog`), `ledger_tail_entries?` | One run: status (`closed`/`executing`/`promoted_waiting`/`draft`/`anomaly`/`missing`), artefact files, first handoff id, the handoffs it owns (bounded by the next run's floor) with deliverables and last trace signal, testgoals parse status, and the requested file contents; `ledger_tail_entries=N` returns only the last N `## ` ledger entries |
| `list_goal_drafts` | `flow_key` | Drafts from both `goals/{N}-GOAL-DRAFT.md` and `runs/NNN/GOAL-DRAFT.md` with testgoals parse status (`ok`/`malformed`/`absent`, via DPMtF's `check_testgoals.parse_block`, nothing executed) and `promotable` = whether `promote-goal` would accept it (refused when `GOAL.md` or `END-REPORT.md` exists or the block is malformed; no block = promotable with a warning) |

### knowledge_search

Semantic retrieval over the knowledge layer, spoken over plain HTTP to the
standalone knowledge service (`GET <base>/v1/search`). The tool is
provider-neutral: it knows nothing about the search provider behind that
endpoint — retrieve before exploring. By default one call consults three
scopes — `ecosystem`, then `experience`, then the resolved repository scope —
so a DSH session sees what a chain role sees.

Base URL comes from `KNOWLEDGE_SERVICE_URL` (default
`http://127.0.0.1:9140`), the shared token from `KNOWLEDGE_SERVICE_TOKEN`,
sent as `X-Knowledge-Token`; an empty token sends no header. The service also
owns the scope slug rule.

Scope rule: under `scope="current_repository"` the `workspace` path is
resolved by the service itself — one
`GET <base>/v1/scope-for-path?path=<workspace>` call per process, cached per
workspace string. Any other `scope` value passes through unchanged. An empty
`workspace` with `current_repository` returns `{"error": "workspace is required
to resolve current_repository"}` without making a call. When the service is
unreachable the lookup fails first, so the tool answers
`{"error": "unreachable", "detail": …}` before any search is attempted.

**Three-scope default and the budget split.** With `cross_repo` true (the
default) and a repository scope, the tool makes three `GET /v1/search` calls
through the same transport seam, all carrying the same `agent_role`,
`flow_key`, `run_id`, `handoff_id` and `top_k`: `ecosystem` first, then
`experience`, then the repository scope. `token_budget` (after clamping) is
split by integer division — 60 % repository, 20 % ecosystem, 20 % experience —
the two learning shares are spent first, and whatever they leave unused (their
share minus the whitespace-split tokens of the `content` the service returned)
is added to the repository call's budget: a default 4000 answers with 800 /
800 / 3800 when each learning answer used 100 tokens. `evidence_level` and
`include_history` are forwarded to the learning calls only — `include_history`
makes the service answer from `experience-history` — and the repository call
never carries them. `cross_repo: false` makes exactly one repository call; an
explicit learning scope (`ecosystem`, `experience`, `experience-history`) is
always a single call and does forward the two fields. A learning scope that
answers 403, 404, 503, a disabled envelope, an empty list, or raises
contributes no results and is only recorded in `scopes_searched`; the
repository answer is the only one that can fail the call.

`knowledge_scopes` is the discovery half: `GET <base>/v1/scopes` as a JSON
array of `{scope, provider, status, document_count}`, so an agent can see which
repositories have memory before picking a scope. Same error shapes.

Shapes: success is `{"scope", "provider", "count", "results": [{"scope",
"path", "score", "snippet", "metadata"}], "scopes_searched": [{"scope",
"status", "count"}]}` — `scope` is the repository scope (or the single explicit
scope), `count` the number of returned results across the consulted scopes,
`results` ordered repository → ecosystem → experience with each snippet the
result content cut to 600 characters, `metadata` the service's per-hit extras
passed through unchanged (`{}` on repository passages; learning hits carry
`evidence_level`, `repository`, `family`, `run`, `confidence`, plus `origin` or
`superseded_by`/`retracted_at` where present), and `scopes_searched` one entry
per call in call order with `status` ∈ `ok`, `empty`, `denied`,
`unknown_scope`, `not_ready`, `unreachable`, `disabled`. A disabled layer
returns `{"scope", "count": 0, "results": [], "note": "knowledge retrieval is
disabled in DPMtF"}`. Errors (from the repository call): HTTP 403 →
`{"error": "denied", "scope", "detail"}`; HTTP 404 → `{"error":
"unknown_scope", "scope", "detail"}`; HTTP 503 → `{"error": "not_ready",
"detail"}`; any other failure → `{"error": "unreachable", "detail"}` — the
tool never raises. Bounds are clamped before the call (`top_k` 1–20,
`token_budget` 200–12000); a query shorter than two characters returns
`{"error": "query too short"}`.

Position fields make each retrieval auditable in the service's log: `run_id`
and `handoff_id` are forwarded when set (omitted from the query string when
empty, like the other optional parameters). Under
`scope="current_repository"` an empty `flow_key` defaults to the trimmed
`workspace` path, so DSH sessions stay distinguishable per project; an
explicit `flow_key` always wins.

simple-harness roles need `knowledge_search` (and `knowledge_scopes`) on their
tool allowlist, and DeepSeek Harness reaches them through its MCP client — both
are configured outside this repository.

**knowledge-first skill.** `skills/knowledge-first/SKILL.md` teaches DSH to
retrieve before exploring: read `status` + `next_goal` from scope-mcp, then
call `knowledge_search` carrying the goal id (`handoff_id`), the objective
(`run_id`) and the workspace, then open at most the three highest-scoring
paths before any grep. That one call spans the repository, `ecosystem` and
`experience`; the skill tells the agent to read `metadata.evidence_level`
before trusting an experience hit, to pass `include_history: true` when a
conclusion looks outdated, and to read `scopes_searched` when the answer is
thin. The reviewer installs it into
`~/.agents/skills/knowledge-first/` outside this repository.

### knowledge_learning

The inventory half of the same service: what closed runs have already learned,
what was later superseded, and what still waits for admission. One read-only GET
per call through the same transport seam and the same token header — no scope
guard is involved, and nothing is cached in `_SCOPE_CACHE`.

`view` picks the route. `admitted` (the default) is `GET <base>/v1/learning`:
one object per admitted artifact with `family`, `run`, `topic`,
`evidence_level`, `confidence`, `admitted_by` and `supersedes`, in the service's
own family-then-run order. `history` is the same route with `history=true`, so
the superseded and retracted artifacts come back with their `superseded_by` and
`retracted_at`. `drafts` is `GET <base>/v1/learning/drafts`, listing the
`LEARNING-DRAFT.yaml` files under the runs root with `run_status`, `admitted`,
`valid` and `violations`; `pending_only: true` adds `pending=true` and keeps the
drafts no supervisor has admitted yet. Any other `view` answers
`{"error": "unknown view", "detail": …}` immediately, without a call.

Success is `{"view", "count", "artifacts"}` — `drafts` instead of `artifacts`
for the drafts view — with `count` the number of rows returned and the rows
passed through exactly as the service wrote them. `family` filters those rows
here rather than in the query string, so the route and its params stay exactly
as listed; matching is exact against the row's `family` field, and `count`
describes what survives the filter. Errors keep the `knowledge_search` shapes —
403 → `denied`, 404 → `unknown_scope`, 503 → `not_ready`, any other transport
failure or a raised seam → `unreachable` — and the tool never raises, so a cold
machine still gets an answer it can act on.

### knowledge_retrievals

The audit half of the same service: what the knowledge layer actually answered,
one row per served search. One read-only `GET <base>/v1/retrievals` per call
through the same transport seam and the same token header — no scope guard is
involved, nothing is cached in `_SCOPE_CACHE`, and the tool never raises.

Filters are optional and combine with AND: `run_id`, `handoff_id`, `flow_key`,
`agent_role`, `scope`, `since` and `until`. Only the ones that were given go
into the query string, so an unset filter never narrows the answer. `limit` is
coerced to an int and clamped to 1..200 before the call (the service clamps
again at 500); rows come back newest first with `provider`, `scope`, `query`,
`result_count`, `sources`, `retrieved_token_count`, `retrieval_duration_ms`,
`agent_role`, `run_id`, `handoff_id`, `flow_key` and `created_at`. `summary:
true` adds `summary=true` and otherwise changes nothing: the answer is the
aggregate — `retrievals`, `results`, `tokens`, `duration_ms`, `scopes`,
`agent_roles`, `first` and `last`.

The service's dict is returned as it wrote it, except that each row's `query` is
cut to 200 characters and its `sources` list to the first 5 entries, so a large
page cannot flood a model's context. Errors keep the `knowledge_search` shapes —
403 → `denied`, 404 → `unknown_scope`, 503 → `not_ready`, any other transport
failure or a raised seam → `unreachable`.

What did this run retrieve?

```json
{"name": "knowledge_retrievals", "arguments": {"run_id": "046", "limit": 50}}
```

Has this role retrieved today?

```json
{"name": "knowledge_retrievals",
 "arguments": {"agent_role": "dsh", "since": "2026-09-15T00:00:00", "summary": true}}
```

How much has one scope served this week?

```json
{"name": "knowledge_retrievals",
 "arguments": {"scope": "dpmtf-webui", "since": "2026-09-08T00:00:00", "summary": true}}
```

Supervising and reviewing roles learn this step in the `knowledge-first` skill:
after a run closes, read its rows by `run_id`; to see whether a role retrieves at
all, ask for the summary instead.

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
| Whitelisted tables only | `ALLOWED_TABLES` — 8 tables (Phase 6 adds the two queues and the id counters; queue `content` is never returned) |
| Flow files confined | Phase 6 reads only `<flows_root>/<artifact_root>/` and `trace.log`; `flow_state._flow_path` realpath-checks every join, `flow_key` must match `^[A-Za-z0-9_.-]+$`, `run_id` is an int |
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
| 6 — Flow state | ✅ | Supervisor cold-start state, read-only (2026-09-02), 4 tools |
