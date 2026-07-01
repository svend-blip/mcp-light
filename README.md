# mcp-light

Lokal read-only MCP context-server til DPMtF.

Giver Claude Code og OpenCode adgang til governance, panelstruktur og
projektcontext — uden at være bundet til ét bestemt agent-værktøj.

---

## Arkitektur

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

### Krav

- Python 3.8+
- Ingen eksterne dependencies (kun standardbibliotek)
- Adgang til DPMtF-WebUI's filsystem (samme maskine)

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

`Ctrl+C` i terminalen.

### Autostart ved reboot (systemd)

```bash
sudo cp mcp-light.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mcp-light
sudo systemctl start mcp-light
```

Tjek status:
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

## Klientkonfiguration

### Claude Code

Opret `~/.mcp.json`:

```json
{
  "mcpServers": {
    "mcp-light": {
      "type": "http",
      "url": "http://127.0.0.1:9135/mcp"
    }
  }
}
```

Eller brug CLI:
```bash
claude mcp add mcp-light --type http --url http://127.0.0.1:9135/mcp
```

### OpenCode

Tilføj i rollens `opencode.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "mcp-light": {
      "url": "http://127.0.0.1:9135/mcp"
    }
  }
}
```

Eksempel for `imple01`:
`~/.config/opencode-roles/imple01/opencode.json`

---

## Tilgængelige tools (18)

### Fase 1 — Context retrieval

| Tool | Argument | Returnerer |
|------|----------|-----------|
| `get_frontend_governance` | — | `30_FRONTEND_GOVERNANCE.md` |
| `get_governance_index` | — | Liste over alle governance templates med titler |
| `get_governance_file` | `name` (f.eks. `11_SCOPE.md`) | Indhold af en specifik template |
| `get_required_frontend_impact_block` | — | Standard Frontend Impact blok til output |
| `search_context` | `query` | Søgeresultater i governance/context filer |
| `search_verdicts` | `query` | Søgeresultater i verdict filer |

### Fase 2 — Frontend context

| Tool | Argument | Returnerer |
|------|----------|-----------|
| `get_panel_groups` | — | Panelgrupper: Daily, Journals, Reports, Periodic, Setup |
| `get_panel_subgroups` | — | Kendte subgrupper med nøgler og titler |
| `get_existing_panels` | — | Eksisterende paneler fra `index.html` |
| `get_index_structure` | — | Oversigt over `index.html` struktur |

### Fase 3 — Database (read-only SQLite)

| Tool | Argument | Returnerer |
|------|----------|-----------|
| `get_flow` | `flow_key` | Flow detaljer fra `bridge_flows` |
| `get_role` | `role_key` | Rolle detaljer fra `bridge_roles` (kun whitelistede kolonner) |
| `get_flow_steps` | `flow_key` | Steps for et flow fra `bridge_flow_steps` |
| `get_panel_subgroups_dynamic` | — | Subgrupper live fra `panel_subgroups` |
| `get_panel_mappings` | — | Slot→subgroup mappings fra `panel_subgroup_mappings` |

### Fase 4 — Review helpers

| Tool | Argument | Returnerer |
|------|----------|-----------|
| `validate_frontend_impact` | `report_text` | `pass`/`fail` med detaljer om hvad der mangler |
| `find_reusable_panel` | `feature_name` | Forslag til eksisterende panel der kan genbruges |
| `suggest_panel_location` | `feature_name` | Forslag til panelgruppe, subgroup og nøgle |

---

## Eksempler

### Valider Frontend Impact

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

### Find genbrugeligt panel

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

### Foreslå panelplacering

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
  "existing_subgroups": ["sg_setup_flows — Flows", "sg_setup_system — Systemopsætning"],
  "next_sort_order": 8,
  "suggested_subgroup_key": "sg_setup_machine_profile"
}
```

---

## Sikkerhed

| Regel | Implementering |
|-------|---------------|
| Kun whitelistede mapper | `ALLOWED_ROOTS` — 6 stier |
| Kun whitelistede tabeller | `ALLOWED_TABLES` — 5 tabeller |
| Kun whitelistede kolonner | `ALLOWED_COLUMNS` — per tabel |
| Read-only database | `mode=ro` i SQLite URI |
| Ingen `shell=True` | Alle subprocess-kald bruger liste-argumenter |
| Ingen skriveadgang | Kun `SELECT`, ingen `INSERT`/`UPDATE`/`DELETE` |
| Ingen path traversal | `os.path.realpath()` + prefix-check |
| Ingen fri SQL | Kun hardcodede parameteriserede queries med `?` |
| Kun `.md` filer | `os.path.basename()` + endelse-check |
| Kun localhost | `127.0.0.1` — aldrig `0.0.0.0` |

---

## Faseplan

| Fase | Status | Indhold |
|------|--------|---------|
| 1 — Context | ✅ | Read-only fil-adgang, 6 tools |
| 2 — Frontend | ✅ | Panelstruktur, 4 tools |
| 3 — Database | ✅ | SQLite read-only, 5 tools |
| 4 — Review | ✅ | Validering og forslag, 3 tools |
