#!/usr/bin/env python3
"""mcp-light — Local read-only MCP context server for DPMtF.

Phase 3: Read-only context + SQLite (fixed queries).
No write access, no shell execution, no free SQL.

Listens on 127.0.0.1:9135/mcp (FastMCP streamable-http transport).
"""

import json
import os
import re
import sqlite3

from mcp.server.fastmcp import FastMCP

# mcp-light — read-only MCP context server for DPMtF.
# Transport: FastMCP streamable-http. The 22 tool_* functions below are the
# same read-only logic from phases 1-4, now registered with FastMCP.
# host/port/streamable_http_path are CONSTRUCTOR kwargs (not run() kwargs) in mcp 1.28.1.
# Bind address from the environment, loopback by default.
#
# Loopback was the whole security model: nothing else could reach it, so
# nothing needed authentication. That still holds for Father's own roles and
# is why the default has not moved.
#
# A LightWorker on another machine cannot reach loopback. Rather than widen
# this instance -- 0.0.0.0 would also expose it on the wifi LAN and on three
# docker bridges, which is a surface that is easy to forget -- a SECOND
# instance is started bound to the Tailscale address. The server is entirely
# read-only (22 tools, no INSERT/UPDATE/DELETE, no writes), so two instances
# over one database cannot conflict, and Father's thirteen role configs keep
# pointing at loopback and are unaffected by anything the worker does.
#
# Note what changes for the remote one: there is no authentication, so the
# tailnet becomes the boundary. Anything on the tailnet can read governance,
# flows, roles and verdicts.
mcp = FastMCP(
    "mcp-light",
    host=os.environ.get("MCP_LIGHT_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_LIGHT_PORT", "9135")),
    streamable_http_path="/mcp",
)

# ── Configuration ──────────────────────────────────────────────

# Ecosystem roots. Resolved from the environment so this server carries no
# hardcoded absolute path (the same rule its own validate_frontend_code
# enforces on other people's code). The defaults expand against $HOME, which
# reproduces the historical /home/svend layout without embedding it.
WEBUI_ROOT = os.environ.get("DPMTF_WEBUI_ROOT", os.path.expanduser("~/DPMtF-WebUI"))
FLOWS_ROOT = os.environ.get("DPMTF_FLOWS_ROOT", os.path.expanduser("~/flows"))
ALLOCATOR_ROOT = os.environ.get(
    "DPMTF_ALLOCATOR_ROOT", os.path.expanduser("~/model-allocator")
)

INDEX_HTML_PATH = os.path.join(WEBUI_ROOT, "templates", "index.html")

# Whitelisted directories — only these may be read
ALLOWED_ROOTS = [
    os.path.join(WEBUI_ROOT, "docs", "governance-templates-v2"),
    os.path.join(WEBUI_ROOT, "docs", "prompt-runs"),
    os.path.join(WEBUI_ROOT, "templates"),
    os.path.join(WEBUI_ROOT, "static", "js"),
    os.path.join(FLOWS_ROOT, "strict_review", "verdicts"),
]

FRONTEND_IMPACT_BLOCK = """## Frontend Impact

- Frontend impact: <what changes in the UI>
- index.html impact: <yes/no, what changes>
- Panel group/subgroup: <which group, which subgroup>
- Existing panel reused: <yes/no, which>
- New panel needed: <yes/no, why>
- New labels: <label_key list, or 'none'>
- Label reuse checked: <result of find_reusable_label, or 'n/a'>
- Locales seeded: <en-US, da-DK, de-DE, es-ES for every new label, or 'n/a'>
- Frontend verification: <how to verify the change>"""

NO_FRONTEND_IMPACT_BLOCK = """## Frontend Impact

No frontend impact.

Reason: <why frontend is not affected>"""

# ── Database configuration (Phase 3) ───────────────────────────

DB_PATH = os.path.join(WEBUI_ROOT, "databases", "dpmtf.db")

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

@mcp.tool(name="get_frontend_governance", description="Return content from FRONTEND_GOVERNANCE.md")
def tool_get_frontend_governance() -> str:
    path = _resolve_governance_file("30_FRONTEND_GOVERNANCE.md")
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "30_FRONTEND_GOVERNANCE.md not found in allowed roots."


@mcp.tool(name="get_governance_index", description="Return list of governance v2 templates and their purpose")
def tool_get_governance_index() -> str:
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


@mcp.tool(name="get_governance_file", description="Return a specific governance template by name (e.g. 11_SCOPE.md)")
def tool_get_governance_file(name: str) -> str:
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


@mcp.tool(name="get_required_frontend_impact_block", description="Return the standard Frontend Impact block for output. Pass has_impact=false to get the 'No frontend impact.' variant.")
def tool_get_required_frontend_impact_block(has_impact: bool = True) -> str:
    # One block, never both: concatenating them emitted two contradictory
    # "## Frontend Impact" headings and an agent copying the result produced a
    # malformed block. The caller states which case applies.
    return FRONTEND_IMPACT_BLOCK if has_impact else NO_FRONTEND_IMPACT_BLOCK


@mcp.tool(name="get_panel_groups", description="Return known panel groups (Daily, Journals, Reports, Periodic, Setup)")
def tool_get_panel_groups() -> str:
    return "Daily, Journals, Reports, Periodic, Setup"


@mcp.tool(name="get_panel_subgroups", description="Return known panel subgroups with their keys and titles")
def tool_get_panel_subgroups() -> str:
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


@mcp.tool(name="get_existing_panels", description="Return existing panels with keys, titles, and locations")
def tool_get_existing_panels() -> str:
    """Return existing panels from index.html structure."""
    index_path = INDEX_HTML_PATH
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


@mcp.tool(name="get_index_structure", description="Return a short overview of index.html structure")
def tool_get_index_structure() -> str:
    """Return a short overview of index.html structure."""
    index_path = INDEX_HTML_PATH
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


@mcp.tool(name="search_context", description="Search for a query in allowed governance/context files")
def tool_search_context(query: str) -> str:
    """Search for a query in allowed governance files."""
    if not query or len(query) < 2:
        return "Error: Query must be at least 2 characters."

    results = []
    unreadable = []
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
            except OSError as e:
                # Surface the miss: a swallowed read makes an unreadable file
                # indistinguishable from "not there", i.e. a false negative.
                unreadable.append(f"{fname}: [unreadable: {e}]")

    footer = ("\n\nWARNING — files skipped, results may be incomplete:\n"
              + "\n".join(unreadable)) if unreadable else ""
    if not results:
        return f"No results found for: {query}{footer}"
    return "\n".join(results[:50]) + footer  # Max 50 result lines


@mcp.tool(name="search_verdicts", description="Search for a query in verdict files")
def tool_search_verdicts(query: str) -> str:
    """Search for a query in verdict files."""
    if not query or len(query) < 2:
        return "Error: Query must be at least 2 characters."

    verdicts_dir = os.path.join(FLOWS_ROOT, "strict_review", "verdicts")
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


@mcp.tool(name="get_flow", description="Return flow details from database (Phase 3)")
def tool_get_flow(flow_key: str) -> str:
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


@mcp.tool(name="get_role", description="Return role details from database (Phase 3)")
def tool_get_role(role_key: str) -> str:
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


@mcp.tool(name="get_flow_steps", description="Return steps for a flow from database (Phase 3)")
def tool_get_flow_steps(flow_key: str) -> str:
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


@mcp.tool(name="get_panel_subgroups_dynamic", description="Return panel subgroups from database (Phase 3)")
def tool_get_panel_subgroups_dynamic() -> str:
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


@mcp.tool(name="get_panel_mappings", description="Return panel subgroup mappings from database (Phase 3)")
def tool_get_panel_mappings() -> str:
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


# ── Review helpers (Phase 4) ───────────────────────────────────


@mcp.tool(name="validate_frontend_impact", description="Check if a text contains a valid Frontend Impact section (Phase 4)")
def tool_validate_frontend_impact(report_text: str) -> str:
    """Check if a text contains a valid Frontend Impact section.

    Returns pass/fail with details about what's missing.
    """
    if not report_text:
        return json.dumps({
            "status": "fail",
            "reason": "Empty report text — cannot validate.",
            "missing": ["Frontend Impact section"],
        }, indent=2)

    text_lower = report_text.lower()

    # Check for Frontend Impact heading
    has_heading = "frontend impact" in text_lower
    has_no_impact = "no frontend impact" in text_lower

    if not has_heading and not has_no_impact:
        return json.dumps({
            "status": "fail",
            "reason": "Missing Frontend Impact section.",
            "required": "Add '## Frontend Impact' with impact details or 'No frontend impact' with reason.",
        }, indent=2)

    # "No frontend impact" must have a reason
    if has_no_impact and not has_heading:
        # Find the line after "No frontend impact"
        lines = report_text.split("\n")
        has_reason = False
        for i, line in enumerate(lines):
            if "no frontend impact" in line.lower():
                # Check next few lines for "Reason:" or non-empty content
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip().lower().startswith("reason"):
                        has_reason = True
                        break
                    if lines[j].strip() and not lines[j].strip().startswith("#"):
                        has_reason = True
                        break
                break
        if not has_reason:
            return json.dumps({
                "status": "fail",
                "reason": "'No frontend impact' declared but no reason given.",
                "required": "Add 'Reason: <why frontend is not affected>' after 'No frontend impact'.",
            }, indent=2)
        return json.dumps({
            "status": "pass",
            "reason": "No frontend impact — reason provided.",
        }, indent=2)

    # Full Frontend Impact section — check required fields
    required_fields = [
        "frontend impact",
        "index.html impact",
        "panel group",
        "existing panel",
        "new panel",
        "frontend verification",
    ]
    missing = [f for f in required_fields if f not in text_lower]

    if missing:
        return json.dumps({
            "status": "fail",
            "reason": f"Missing required fields: {', '.join(missing)}",
            "required_format": FRONTEND_IMPACT_BLOCK,
        }, indent=2)

    # i18n declaration (2026-08-08): a report that declares NEW labels must
    # also declare the label-reuse check and the four mandatory locales.
    # Reports declaring 'New labels: none' (or predating the field) pass.
    new_labels_match = re.search(r"new labels?\s*:\s*(.+)", text_lower)
    if new_labels_match:
        declared = new_labels_match.group(1).strip()
        declares_new = declared and not declared.startswith(
            ("none", "n/a", "no ", "-"))
        if declares_new:
            i18n_missing = []
            if "label reuse" not in text_lower:
                i18n_missing.append(
                    "Label reuse checked (run find_reusable_label first)")
            if "locales seeded" not in text_lower:
                i18n_missing.append(
                    "Locales seeded (en-US, da-DK, de-DE, es-ES)")
            if i18n_missing:
                return json.dumps({
                    "status": "fail",
                    "reason": "New labels declared without i18n evidence: "
                              + "; ".join(i18n_missing),
                    "required_format": FRONTEND_IMPACT_BLOCK,
                }, indent=2)

    return json.dumps({
        "status": "pass",
        "reason": "All required Frontend Impact fields present.",
    }, indent=2)


@mcp.tool(name="find_reusable_panel", description="Suggest an existing panel that could be reused (Phase 4)")
def tool_find_reusable_panel(feature_name: str) -> str:
    """Suggest an existing panel that could be reused for a feature.

    Searches index.html for panels with similar names or purposes.
    """
    if not feature_name:
        return "Error: feature_name is required."

    index_path = INDEX_HTML_PATH
    if not _is_allowed_path(index_path):
        return "Error: index.html not accessible."

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading index.html: {e}"

    # Extract all panels with their sections
    panels = []
    for match in re.finditer(
        r'<section[^>]*id="([^"]*)"[^>]*>.*?<h[23][^>]*data-slot="([^"]*)"[^>]*>([^<]*)</h[23]>',
        content, re.DOTALL
    ):
        sec_id, slot, title = match.group(1), match.group(2), match.group(3).strip()
        panels.append({"id": sec_id, "slot": slot, "title": title})

    # Score panels by relevance to feature_name
    feature_lower = feature_name.lower()
    scored = []
    for p in panels:
        score = 0
        title_lower = p["title"].lower()
        slot_lower = p["slot"].lower()
        # Direct word match
        for word in feature_lower.split():
            if word in title_lower:
                score += 3
            if word in slot_lower:
                score += 2
            if word in p["id"].lower():
                score += 1
        if score > 0:
            scored.append({**p, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        return json.dumps({
            "suggestion": "No similar panels found. Consider creating a new panel.",
            "all_panels": [f"{p['id']} — {p['title']}" for p in panels],
        }, indent=2)

    return json.dumps({
        "feature": feature_name,
        "best_match": f"{scored[0]['id']} — {scored[0]['title']} (score={scored[0]['score']})",
        "candidates": [f"{p['id']} — {p['title']} (score={p['score']})" for p in scored[:5]],
    }, indent=2)


@mcp.tool(name="suggest_panel_location", description="Suggest panel group/subgroup for a new feature (Phase 4)")
def tool_suggest_panel_location(feature_name: str) -> str:
    """Suggest which panel group and subgroup a new feature should use.

    Based on the feature name and existing panel structure.
    """
    if not feature_name:
        return "Error: feature_name is required."

    feature_lower = feature_name.lower()

    # Define group characteristics
    groups = {
        "daily": ["daily", "today", "current", "now", "active", "session"],
        "journals": ["journal", "log", "history", "record", "note"],
        "reports": ["report", "export", "summary", "stats", "analysis"],
        "periodic": ["phase", "plan", "planning", "periodic", "schedule", "project"],
        "setup": ["setup", "config", "settings", "admin", "manage", "role", "flow",
                   "bridge", "convention", "system", "database", "profile", "machine"],
    }

    # Score each group
    scores = {}
    for group, keywords in groups.items():
        score = sum(1 for kw in keywords if kw in feature_lower)
        if score > 0:
            scores[group] = score

    if not scores:
        best_group = "setup"
        reason = "No specific keywords matched — defaulting to Setup"
    else:
        best_group = max(scores, key=scores.get)
        reason = f"Matched keywords: {', '.join(k for k in groups[best_group] if k in feature_lower)}"

    # Get existing subgroups for the suggested group
    conn = _get_db_connection()
    try:
        table = _safe_table("panel_subgroups")
        rows = conn.execute(
            f"SELECT subgroup_key, title_da, sort_order FROM {table} "
            f"WHERE group_name = ? AND is_visible = 1 ORDER BY sort_order",
            (best_group,),
        ).fetchall()
        existing = [f"{r['subgroup_key']} — {r['title_da']}" for r in rows]
    finally:
        conn.close()

    return json.dumps({
        "feature": feature_name,
        "suggested_group": best_group,
        "reason": reason,
        "existing_subgroups": existing,
        "next_sort_order": len(existing) + 1 if existing else 1,
        "suggested_subgroup_key": f"sg_{best_group}_{feature_name.replace(' ', '_').lower()[:20]}",
    }, indent=2)


# ── Coding-standard enforcement (Phase 5, 2026-08-08) ──────────

# The four mandatory locales per 12_CODING_STANDARD.md.
MANDATORY_LOCALES = ("en-US", "da-DK", "de-DE", "es-ES")

# Known project i18n databases (read-only). Keyed by project name so the
# tool surface never accepts arbitrary filesystem paths.
I18N_DBS = {
    "dpmtf": DB_PATH,
    "model-allocator": os.path.join(ALLOCATOR_ROOT, "allocator.db"),
}


def _open_i18n_db(project):
    """Open a whitelisted project's i18n database read-only."""
    db_path = I18N_DBS.get(project)
    if not db_path:
        raise ValueError(
            f"Unknown project '{project}'. Known: {', '.join(sorted(I18N_DBS))}"
        )
    if not os.path.isfile(db_path):
        raise ValueError(f"Database for '{project}' not found: {db_path}")
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _i18n_schema(conn):
    """Detect schema variant: Father joins translations on label_id,
    skeleton-born projects join on label_key. Also note is_active columns."""
    label_cols = {r[1] for r in conn.execute("PRAGMA table_info(ui_labels)")}
    trans_cols = {r[1] for r in
                  conn.execute("PRAGMA table_info(ui_label_translations)")}
    join_key = "label_id" if ("label_id" in label_cols and
                              "label_id" in trans_cols) else "label_key"
    return {
        "join_key": join_key,
        "labels_active": "is_active" in label_cols,
        "trans_active": "is_active" in trans_cols,
        "has_description": "description" in label_cols,
    }


@mcp.tool(name="validate_i18n_completeness",
          description="Report labels missing any of the 4 mandatory locales "
                      "(en-US, da-DK, de-DE, es-ES) in a project's i18n DB (Phase 5)")
def tool_validate_i18n_completeness(project: str = "dpmtf") -> str:
    """List every active label that lacks a translation in one or more of
    the four mandatory locales. The fix is adding translations — never
    deleting labels (12_CODING_STANDARD.md)."""
    try:
        conn = _open_i18n_db(project)
    except ValueError as e:
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)

    try:
        schema = _i18n_schema(conn)
        jk = schema["join_key"]
        where_label = "WHERE l.is_active = 1" if schema["labels_active"] else ""
        and_trans = "AND t.is_active = 1" if schema["trans_active"] else ""
        rows = conn.execute(
            f"SELECT l.label_key, "
            f"GROUP_CONCAT(DISTINCT t.locale) AS locales "
            f"FROM ui_labels l "
            f"LEFT JOIN ui_label_translations t "
            f"ON t.{jk} = l.{jk} {and_trans} "
            f"{where_label} GROUP BY l.{jk} ORDER BY l.label_key",
        ).fetchall()
    except sqlite3.Error as e:
        conn.close()
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)
    finally:
        if conn:
            conn.close()

    incomplete = []
    locale_counts = {loc: 0 for loc in MANDATORY_LOCALES}
    for r in rows:
        present = set((r["locales"] or "").split(",")) - {""}
        for loc in MANDATORY_LOCALES:
            if loc in present:
                locale_counts[loc] += 1
        missing = [loc for loc in MANDATORY_LOCALES if loc not in present]
        if missing:
            incomplete.append({"label_key": r["label_key"],
                               "missing": missing})

    truncated = len(incomplete) > 200
    return json.dumps({
        "status": "pass" if not incomplete else "fail",
        "project": project,
        "total_labels": len(rows),
        "labels_incomplete": len(incomplete),
        "per_locale_coverage": locale_counts,
        "mandatory_locales": list(MANDATORY_LOCALES),
        "incomplete": incomplete[:200],
        "truncated": truncated,
        "rule": "Every label MUST have all four mandatory locales. "
                "Fix by ADDING translations, never by deleting labels.",
    }, indent=2)


# Mechanical auto-fail patterns from 12_CODING_STANDARD.md. Each entry:
# (compiled regex, severity, message). Heuristic text checks are warnings —
# a human/reviewer judges them; regex cannot read intent.
_CODE_CHECKS = [
    (re.compile(r"\.innerHTML\s*="), "auto_fail",
     "innerHTML assignment — use createElement()/textContent/appendChild()/replaceChildren()"),
    (re.compile(r"\binsertAdjacentHTML\s*\("), "auto_fail",
     "insertAdjacentHTML — same risk as innerHTML; build DOM nodes instead"),
    (re.compile(r"\bdocument\.write\s*\("), "auto_fail",
     "document.write — prohibited"),
    (re.compile(r"/home/svend"), "auto_fail",
     "Hardcoded /home/svend path — use config getters or env vars"),
    (re.compile(r"\bvar\s+[A-Za-z_$]"), "fail",
     "var declaration — use const (default) or let"),
    (re.compile(r"<\w[^>]*\sstyle=\""), "fail",
     "Inline style attribute — use CSS classes"),
    (re.compile(r"\.textContent\s*=\s*[\"'][^\"']*[A-Za-z]{3,}[^\"']*[\"']"),
     "warning",
     "String literal assigned to textContent — user-facing text MUST go through lbl(key, fallback)"),
]


@mcp.tool(name="validate_frontend_code",
          description="Mechanically check JS/HTML code text against the "
                      "12_CODING_STANDARD auto-fail patterns (Phase 5)")
def tool_validate_frontend_code(code_text: str, filename: str = "") -> str:
    """Scan code text for the prohibited frontend patterns. Auto-fail and
    fail findings block; warnings need reviewer judgement. This is a
    mechanical net under review — passing it does not replace review."""
    if not code_text:
        return json.dumps({"status": "error",
                           "reason": "Empty code_text."}, indent=2)

    findings = []
    for lineno, line in enumerate(code_text.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") \
                or stripped.startswith("/*") or stripped.startswith("#"):
            continue
        for pattern, severity, message in _CODE_CHECKS:
            if pattern.search(line):
                # lbl(...) fallbacks are the sanctioned literal usage.
                if severity == "warning" and "lbl(" in line:
                    continue
                findings.append({"line": lineno, "severity": severity,
                                 "message": message,
                                 "code": line.strip()[:160]})

    blocking = [f for f in findings if f["severity"] in ("auto_fail", "fail")]
    warnings = [f for f in findings if f["severity"] == "warning"]
    status = ("fail" if blocking
              else "pass_with_warnings" if warnings else "pass")
    return json.dumps({
        "status": status,
        "filename": filename or None,
        "blocking": blocking,
        "warnings": warnings,
        "note": "Mechanical check only — passing does not replace review. "
                "Warnings require reviewer judgement (a regex cannot read intent).",
    }, indent=2)


@mcp.tool(name="find_reusable_label",
          description="findOrCreate for labels: find an existing label with "
                      "the same text (and description) to map a slot to, or "
                      "get the create-SQL for all 4 mandatory locales (Phase 5)")
def tool_find_reusable_label(text: str, description: str = "",
                             project: str = "dpmtf") -> str:
    """The FIND half of find-or-create for labels.

    Slot keys are unique, but when several slots need the same text and
    help text there is no reason for several identical labels — map the
    new slot to the existing label instead. Call this BEFORE creating any
    label (12_CODING_STANDARD.md makes that check mandatory)."""
    if not text or not text.strip():
        return json.dumps({"status": "error",
                           "reason": "text is required."}, indent=2)
    try:
        conn = _open_i18n_db(project)
    except ValueError as e:
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)

    try:
        schema = _i18n_schema(conn)
        where_active = "AND l.is_active = 1" if schema["labels_active"] else ""
        exact = conn.execute(
            f"SELECT l.label_key, l.default_text, l.description "
            f"FROM ui_labels l "
            f"WHERE lower(l.default_text) = lower(?) {where_active}",
            (text.strip(),),
        ).fetchall()
        partial = conn.execute(
            f"SELECT l.label_key, l.default_text, l.description "
            f"FROM ui_labels l "
            f"WHERE l.default_text LIKE ? {where_active} "
            f"AND lower(l.default_text) != lower(?) LIMIT 10",
            (f"%{text.strip()}%", text.strip()),
        ).fetchall()
    except sqlite3.Error as e:
        conn.close()
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)
    finally:
        if conn:
            conn.close()

    def _entry(r):
        return {"label_key": r["label_key"],
                "default_text": r["default_text"],
                "description": r["description"]}

    # An exact match on text+description is a REUSE verdict; text-only
    # matches are candidates the implementer judges.
    desc = (description or "").strip().lower()
    reuse = [
        _entry(r) for r in exact
        if not desc or (r["description"] or "").strip().lower() == desc
    ]

    if reuse:
        return json.dumps({
            "status": "reuse",
            "project": project,
            "matches": reuse,
            "action": "Map your slot to the existing label — do NOT create "
                      "a new one.",
            "sql": ("INSERT INTO ui_text_slot_labels (slot_key, label_key) "
                    f"VALUES ('<your_slot_key>', '{reuse[0]['label_key']}');"),
        }, indent=2)

    return json.dumps({
        "status": "create",
        "project": project,
        "text_only_matches": [_entry(r) for r in exact],
        "partial_matches": [_entry(r) for r in partial],
        "action": "No identical label exists — create one, seeding ALL FOUR "
                  "mandatory locales, then map the slot.",
        "mandatory_locales": list(MANDATORY_LOCALES),
        "sql_template": [
            "INSERT INTO ui_labels (label_key, default_text, description) "
            "VALUES ('<label_key>', '<default_text>', '<description>');",
            "-- one row per mandatory locale (en-US, da-DK, de-DE, es-ES):",
            "INSERT INTO ui_label_translations (label_key, locale, translated_text) "
            "VALUES ('<label_key>', '<locale>', '<translation>');",
            "INSERT INTO ui_text_slot_labels (slot_key, label_key) "
            "VALUES ('<your_slot_key>', '<label_key>');",
        ],
        "note": "Father's schema keys translations by label_id, not "
                "label_key — use scripts/i18n_lib.py find_or_create_label() "
                "there instead of raw SQL.",
    }, indent=2)


@mcp.tool(name="find_duplicate_labels",
          description="Report label groups with identical text and help text "
                      "that should be merged into one label (Phase 5)")
def tool_find_duplicate_labels(project: str = "dpmtf") -> str:
    """Find labels that duplicate each other (same default_text and same
    description). Slots must be unique; identical labels need not be.
    Merge = keep one, remap the other slots, deactivate the rest."""
    try:
        conn = _open_i18n_db(project)
    except ValueError as e:
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)

    try:
        schema = _i18n_schema(conn)
        where_active = "WHERE l.is_active = 1" if schema["labels_active"] else ""
        rows = conn.execute(
            f"SELECT l.default_text, "
            f"COALESCE(l.description, '') AS description, "
            f"GROUP_CONCAT(l.label_key) AS keys, COUNT(*) AS n "
            f"FROM ui_labels l {where_active} "
            f"GROUP BY lower(l.default_text), "
            f"lower(COALESCE(l.description, '')) "
            f"HAVING n > 1 ORDER BY n DESC",
        ).fetchall()
    except sqlite3.Error as e:
        conn.close()
        return json.dumps({"status": "error", "reason": str(e)}, indent=2)
    finally:
        if conn:
            conn.close()

    groups = [{"default_text": r["default_text"],
               "description": r["description"],
               "label_keys": (r["keys"] or "").split(","),
               "count": r["n"]} for r in rows]
    return json.dumps({
        "status": "pass" if not groups else "duplicates_found",
        "project": project,
        "duplicate_groups": groups,
        "merge_procedure": [
            "1. Pick ONE label to keep (the oldest / most-referenced).",
            "2. Repoint slots: UPDATE ui_text_slot_labels SET label_key = "
            "'<kept>' WHERE label_key = '<duplicate>';",
            "3. Deactivate the duplicate (is_active = 0) — never DELETE.",
        ],
    }, indent=2)


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
