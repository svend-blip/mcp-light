#!/usr/bin/env python3
"""mcp-light — Local read-only MCP context server for DPMtF.

Phase 3: Read-only context + SQLite (fixed queries).
No write access, no shell execution, no free SQL.

Listens on 127.0.0.1:9135/mcp (HTTP JSON-RPC).
"""

import json
import os
import re
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 9135

# Whitelisted directories — only these may be read
ALLOWED_ROOTS = [
    "/home/svend/DPMtF-WebUI/docs/governance-templates-v2",
    "/home/svend/DPMtF-WebUI/docs/dpmtf",
    "/home/svend/DPMtF-WebUI/docs/prompt-runs",
    "/home/svend/DPMtF-WebUI/templates",
    "/home/svend/DPMtF-WebUI/static/js",
    "/home/svend/flows/strict_review/verdicts",
]

# Whitelisted files for direct access (must be under ALLOWED_ROOTS)
ALLOWED_FILES = {
    "frontend_governance": "30_FRONTEND_GOVERNANCE.md",
    "scope": "11_SCOPE.md",
    "gates": "20_GATES.md",
    "validation": "13_VALIDATION.md",
    "coding_standard": "12_CODING_STANDARD.md",
    "architecture": "14_ARCHITECTURE.md",
    "database": "17_DATABASE.md",
    "review": "04_REVIEW.md",
    "architect": "02_ARCHITECT.md",
    "implementor": "03_IMPLEMENTOR.md",
    "human": "01_HUMAN.md",
    "role_interaction": "99_ROLEINTERACTION.md",
    "bridge": "100_BRIDGE.md",
    "git_policy": "15_GIT_POLICY.md",
    "file_access": "16_FILE_ACCESS.md",
    "index_html": "../templates/index.html",
}

FRONTEND_IMPACT_BLOCK = """## Frontend Impact

- Frontend impact: <what changes in the UI>
- index.html impact: <yes/no, what changes>
- Panel group/subgroup: <which group, which subgroup>
- Existing panel reused: <yes/no, which>
- New panel needed: <yes/no, why>
- Frontend verification: <how to verify the change>"""

NO_FRONTEND_IMPACT_BLOCK = """## Frontend Impact

No frontend impact.

Reason: <why frontend is not affected>"""

# ── Database configuration (Phase 3) ───────────────────────────

DB_PATH = "/home/svend/DPMtF-WebUI/databases/dpmtf.db"

# Whitelisted tables for read-only queries
ALLOWED_TABLES = {
    "bridge_flows",
    "bridge_roles",
    "bridge_flow_steps",
    "panel_subgroups",
    "panel_subgroup_mappings",
}

# Whitelisted columns per table (empty = all columns allowed)
ALLOWED_COLUMNS = {
    "bridge_roles": {
        "role_key", "tmux_session", "default_runtime", "default_provider",
        "default_model", "config_dir", "model_type", "cloud_model",
        "ollama_model", "governance_file", "role_type", "enter_command",
        "is_active",
    },
}


def _get_db_connection():
    """Open a read-only SQLite connection."""
    db_abs = os.path.abspath(DB_PATH)
    conn = sqlite3.connect(f"file:{db_abs}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_table(table_name):
    """Validate table name against whitelist."""
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Table not allowed: {table_name}")
    return table_name


def _safe_columns(table_name, columns):
    """Filter columns to only allowed ones for the table."""
    allowed = ALLOWED_COLUMNS.get(table_name)
    if allowed is None:
        return columns  # All columns allowed
    return [c for c in columns if c in allowed]


def _row_to_dict(row, table_name, columns):
    """Convert a sqlite3.Row to a safe dict with only allowed columns."""
    if row is None:
        return None
    safe_cols = _safe_columns(table_name, columns)
    return {c: row[c] for c in safe_cols if c in row.keys()}


# ── Security helpers ───────────────────────────────────────────

def _is_allowed_path(path):
    """Check if a resolved path is under one of the allowed roots."""
    resolved = os.path.realpath(path)
    for root in ALLOWED_ROOTS:
        root_resolved = os.path.realpath(root)
        if resolved.startswith(root_resolved + os.sep) or resolved == root_resolved:
            return True
    return False


def _resolve_governance_file(name):
    """Resolve a governance file name to its full path under allowed roots."""
    for root in ALLOWED_ROOTS:
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate) and _is_allowed_path(candidate):
            return candidate
    return None


# ── Tool handlers ──────────────────────────────────────────────

def tool_get_frontend_governance():
    path = _resolve_governance_file("30_FRONTEND_GOVERNANCE.md")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "30_FRONTEND_GOVERNANCE.md not found in allowed roots."


def tool_get_governance_index():
    """Return list of governance files with their purpose."""
    index = []
    for root in ALLOWED_ROOTS:
        if not os.path.isdir(root):
            continue
        for fname in sorted(os.listdir(root)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            if not _is_allowed_path(fpath):
                continue
            # Extract title from first heading
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("# ") and not line.startswith("## "):
                            title = line[2:].strip()
                            index.append(f"{fname} — {title}")
                            break
            except Exception:
                index.append(fname)
    return "\n".join(index) if index else "No governance files found."


def tool_get_governance_file(name):
    """Return a specific governance file by name."""
    # Security: only allow .md files, no path traversal
    name = os.path.basename(name)
    if not name.endswith(".md"):
        return f"Error: Only .md files allowed. Got: {name}"

    path = _resolve_governance_file(name)
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return f"Governance file not found: {name}"


def tool_get_required_frontend_impact_block():
    return FRONTEND_IMPACT_BLOCK + "\n\n" + NO_FRONTEND_IMPACT_BLOCK


def tool_get_panel_groups():
    return "Daily, Journals, Reports, Periodic, Setup"


def tool_get_panel_subgroups():
    """Return panel subgroups from the database (Phase 2) or static list."""
    # Phase 1: return static list from known subgroups
    return (
        "Setup subgroups:\n"
        "  sg_setup_flows — Flows\n"
        "  sg_setup_steps — Trin/Steps\n"
        "  sg_setup_roles — Roller/Roles\n"
        "  sg_setup_conventions — Konventioner/Conventions\n"
        "  sg_setup_export — Eksport/Export\n"
        "  sg_setup_db_status — Database Status\n"
        "  sg_setup_system — Systemopsætning/System Setup\n"
        "\n"
        "Periodic subgroups:\n"
        "  sg_periodic_phase — Fase/Phase\n"
        "  sg_periodic_planning — Planlægning/Planning\n"
        "  sg_periodic_existing — Eksisterende Projekter/Existing Projects"
    )


def tool_get_existing_panels():
    """Return existing panels from index.html structure."""
    index_path = os.path.join(
        ALLOWED_ROOTS[3], "index.html"  # templates dir
    )
    # Actually index.html is in templates/ which is ALLOWED_ROOTS[3]
    # But the path is templates/index.html, let me fix:
    index_path = "/home/svend/DPMtF-WebUI/templates/index.html"
    if not _is_allowed_path(index_path):
        return "Error: index.html not accessible."

    panels = []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find all section IDs
        for match in re.finditer(r'<section[^>]*id="([^"]*)"', content):
            section_id = match.group(1)
            # Find the heading inside this section
            section_start = match.start()
            section_end = content.find("</section>", section_start)
            if section_end == -1:
                section_end = len(content)
            section_text = content[section_start:section_end]
            heading_match = re.search(
                r'<h[23][^>]*data-slot="([^"]*)"[^>]*>([^<]*)</h[23]>',
                section_text
            )
            if heading_match:
                slot = heading_match.group(1)
                title = heading_match.group(2).strip()
                panels.append(f"  {section_id} — slot={slot} — \"{title}\"")
            else:
                panels.append(f"  {section_id}")
    except Exception as e:
        return f"Error reading index.html: {e}"

    return "Existing panels in index.html:\n" + "\n".join(panels) if panels else "No panels found."


def tool_get_index_structure():
    """Return a short overview of index.html structure."""
    index_path = "/home/svend/DPMtF-WebUI/templates/index.html"
    if not _is_allowed_path(index_path):
        return "Error: index.html not accessible."

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading index.html: {e}"

    # Extract panel groups
    groups = re.findall(r'id="pg-(\w+)"', content)
    # Extract sections with data-slot
    sections = re.findall(
        r'<section[^>]*id="([^"]*)"[^>]*>.*?<h[23][^>]*data-slot="([^"]*)"[^>]*>([^<]*)</h[23]>',
        content, re.DOTALL
    )

    lines = ["Panel groups: " + ", ".join(groups), ""]
    for sec_id, slot, title in sections:
        lines.append(f"  {sec_id}: {title} (slot={slot})")

    return "\n".join(lines)


def tool_search_context(query):
    """Search for a query in allowed governance files."""
    if not query or len(query) < 2:
        return "Error: Query must be at least 2 characters."

    results = []
    for root in ALLOWED_ROOTS:
        if not os.path.isdir(root):
            continue
        for fname in os.listdir(root):
            if not fname.endswith(".md") and not fname.endswith(".html"):
                continue
            fpath = os.path.join(root, fname)
            if not _is_allowed_path(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(
                                f"{fname}:{lineno}: {line.strip()[:120]}"
                            )
            except Exception:
                pass

    if not results:
        return f"No results found for: {query}"
    return "\n".join(results[:50])  # Max 50 results


def tool_search_verdicts(query):
    """Search for a query in verdict files."""
    if not query or len(query) < 2:
        return "Error: Query must be at least 2 characters."

    verdicts_dir = "/home/svend/flows/strict_review/verdicts"
    if not os.path.isdir(verdicts_dir):
        return "Verdicts directory not found."

    results = []
    for fname in sorted(os.listdir(verdicts_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(verdicts_dir, fname)
        if not _is_allowed_path(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        results.append(
                            f"{fname}:{lineno}: {line.strip()[:120]}"
                        )
        except Exception:
            pass

    if not results:
        return f"No results found for: {query}"
    return "\n".join(results[:50])


# ── Database tool handlers (Phase 3) ───────────────────────────


def tool_get_flow(flow_key):
    """Return flow details from database."""
    if not flow_key:
        return "Error: flow_key is required."
    conn = _get_db_connection()
    try:
        table = _safe_table("bridge_flows")
        row = conn.execute(
            f"SELECT * FROM {table} WHERE flow_key = ?", (flow_key,)
        ).fetchone()
        if row is None:
            return f"Flow not found: {flow_key}"
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
        return json.dumps(_row_to_dict(row, table, cols), indent=2, default=str)
    finally:
        conn.close()


def tool_get_role(role_key):
    """Return role details from database."""
    if not role_key:
        return "Error: role_key is required."
    conn = _get_db_connection()
    try:
        table = _safe_table("bridge_roles")
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})")]
        safe_cols = _safe_columns(table, cols)
        col_str = ", ".join(safe_cols)
        row = conn.execute(
            f"SELECT {col_str} FROM {table} WHERE role_key = ?", (role_key,)
        ).fetchone()
        if row is None:
            return f"Role not found: {role_key}"
        return json.dumps(_row_to_dict(row, table, safe_cols), indent=2, default=str)
    finally:
        conn.close()


def tool_get_flow_steps(flow_key):
    """Return steps for a flow from database."""
    if not flow_key:
        return "Error: flow_key is required."
    conn = _get_db_connection()
    try:
        table = _safe_table("bridge_flow_steps")
        rows = conn.execute(
            f"SELECT step_key, from_role, to_role, deliverable_dir, "
            f"deliverable_pattern, rule_key, sort_order, is_active "
            f"FROM {table} WHERE flow_key = ? ORDER BY sort_order",
            (flow_key,),
        ).fetchall()
        if not rows:
            return f"No steps found for flow: {flow_key}"
        return json.dumps([dict(r) for r in rows], indent=2, default=str)
    finally:
        conn.close()


def tool_get_panel_subgroups_dynamic():
    """Return panel subgroups from database (replaces Phase 1 static list)."""
    conn = _get_db_connection()
    try:
        table = _safe_table("panel_subgroups")
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY group_name, sort_order"
        ).fetchall()
        if not rows:
            return "No panel subgroups found."
        return json.dumps([dict(r) for r in rows], indent=2, default=str)
    finally:
        conn.close()


def tool_get_panel_mappings():
    """Return panel subgroup mappings from database."""
    conn = _get_db_connection()
    try:
        table = _safe_table("panel_subgroup_mappings")
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY subgroup_key, slot_key"
        ).fetchall()
        if not rows:
            return "No panel mappings found."
        return json.dumps([dict(r) for r in rows], indent=2, default=str)
    finally:
        conn.close()


# ── Tool registry ──────────────────────────────────────────────

TOOLS = {
    "get_frontend_governance": {
        "description": "Return content from FRONTEND_GOVERNANCE.md",
        "handler": tool_get_frontend_governance,
    },
    "get_governance_index": {
        "description": "Return list of governance v2 templates and their purpose",
        "handler": tool_get_governance_index,
    },
    "get_governance_file": {
        "description": "Return a specific governance template by name (e.g. 11_SCOPE.md)",
        "handler": tool_get_governance_file,
    },
    "get_required_frontend_impact_block": {
        "description": "Return the standard Frontend Impact block for output",
        "handler": tool_get_required_frontend_impact_block,
    },
    "get_panel_groups": {
        "description": "Return known panel groups (Daily, Journals, Reports, Periodic, Setup)",
        "handler": tool_get_panel_groups,
    },
    "get_panel_subgroups": {
        "description": "Return known panel subgroups with their keys and titles",
        "handler": tool_get_panel_subgroups,
    },
    "get_existing_panels": {
        "description": "Return existing panels with keys, titles, and locations",
        "handler": tool_get_existing_panels,
    },
    "get_index_structure": {
        "description": "Return a short overview of index.html structure",
        "handler": tool_get_index_structure,
    },
    "search_context": {
        "description": "Search for a query in allowed governance/context files",
        "handler": tool_search_context,
    },
    "search_verdicts": {
        "description": "Search for a query in verdict files",
        "handler": tool_search_verdicts,
    },
    # Phase 3 — Database tools
    "get_flow": {
        "description": "Return flow details from database (Phase 3)",
        "handler": tool_get_flow,
    },
    "get_role": {
        "description": "Return role details from database (Phase 3)",
        "handler": tool_get_role,
    },
    "get_flow_steps": {
        "description": "Return steps for a flow from database (Phase 3)",
        "handler": tool_get_flow_steps,
    },
    "get_panel_subgroups_dynamic": {
        "description": "Return panel subgroups from database (Phase 3)",
        "handler": tool_get_panel_subgroups_dynamic,
    },
    "get_panel_mappings": {
        "description": "Return panel subgroup mappings from database (Phase 3)",
        "handler": tool_get_panel_mappings,
    },
}


# ── MCP JSON-RPC handler ───────────────────────────────────────

class MCPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP JSON-RPC requests."""

    def do_POST(self):
        if self.path != "/mcp":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            request = json.loads(body)
        except Exception:
            self.send_error(400, "Invalid JSON")
            return

        method = request.get("method", "")
        req_id = request.get("id")

        if method == "tools/list":
            result = _handle_list_tools()
        elif method == "tools/call":
            result = _handle_call_tool(request.get("params", {}))
        else:
            result = {"error": f"Unknown method: {method}"}

        response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def do_GET(self):
        """Health check endpoint."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "server": "mcp-light",
                "version": "1.3.0",
                "phase": 3,
            }).encode("utf-8"))
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        """Suppress default logging to stderr."""
        pass


def _handle_list_tools():
    """Return list of available tools."""
    tools_list = []
    for name, info in TOOLS.items():
        tools_list.append({
            "name": name,
            "description": info["description"],
        })
    return {"tools": tools_list}


def _handle_call_tool(params):
    """Call a tool by name with arguments."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name not in TOOLS:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        handler = TOOLS[tool_name]["handler"]
        # Pass query argument for search tools
        if tool_name in ("search_context", "search_verdicts"):
            result = handler(arguments.get("query", ""))
        elif tool_name == "get_governance_file":
            result = handler(arguments.get("name", ""))
        elif tool_name in ("get_flow", "get_flow_steps"):
            result = handler(arguments.get("flow_key", ""))
        elif tool_name == "get_role":
            result = handler(arguments.get("role_key", ""))
        else:
            result = handler()

        return {
            "content": [
                {
                    "type": "text",
                    "text": str(result),
                }
            ]
        }
    except Exception as e:
        return {"error": str(e)}


# ── Main ───────────────────────────────────────────────────────

def main():
    server = HTTPServer((HOST, PORT), MCPHandler)
    print(f"mcp-light v1.0.0 — Phase 1 (read-only context)")
    print(f"Listening on http://{HOST}:{PORT}/mcp")
    print(f"Health check: http://{HOST}:{PORT}/health")
    print(f"Allowed roots: {len(ALLOWED_ROOTS)}")
    print(f"Available tools: {len(TOOLS)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
