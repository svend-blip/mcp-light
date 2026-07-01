# mcp-light

Lokal read-only MCP context-server til DPMtF.

Giver Claude Code og OpenCode adgang til governance, panelstruktur og
projektcontext — uden at være bundet til ét bestemt agent-værktøj.

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

## Kør

```bash
python3 server.py
```

Lytter på `http://127.0.0.1:9135/mcp`.

Health check: `http://127.0.0.1:9135/health`

## Fase 1 — Read-only context (nuværende)

Ingen database. Ingen write. Ingen shell.

### Tilgængelige tools

| Tool | Beskrivelse |
|------|-------------|
| `get_frontend_governance` | Returnerer `30_FRONTEND_GOVERNANCE.md` |
| `get_governance_index` | Lister alle governance templates |
| `get_governance_file` | Returnerer en specifik template |
| `get_required_frontend_impact_block` | Standard Frontend Impact blok |
| `get_panel_groups` | Kendte panelgrupper |
| `get_panel_subgroups` | Kendte subgrupper |
| `get_existing_panels` | Eksisterende paneler fra index.html |
| `get_index_structure` | Oversigt over index.html struktur |
| `search_context` | Søg i governance/context filer |
| `search_verdicts` | Søg i verdicts |

### Sikkerhed

- Kun whitelistede mapper kan læses
- Ingen `shell=True`
- Ingen databaseadgang (Fase 1)
- Ingen skriveadgang
- Ingen path traversal

## Klientkonfiguration

### Claude Code

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

### OpenCode

```json
{
  "mcpServers": {
    "mcp-light": {
      "url": "http://127.0.0.1:9135/mcp"
    }
  }
}
```

## Faseplan

- **Fase 1** (nu): Read-only context, ingen database
- **Fase 2**: Frontend context (paneler, subgroups, index.html)
- **Fase 3**: SQLite read-only (faste queries)
- **Fase 4**: Review helpers (validate, suggest)
