# mcp-light — verified FastMCP API (Task 1 / Phase 2 findings)

**mcp SDK version:** 1.28.1 (installed in `venv/`, pinned in `requirements.txt`)
**FastMCP import:** `from mcp.server.fastmcp import FastMCP`

## Constructor (where host/port/path live)

`FastMCP.__init__` relevant kwargs:

```python
FastMCP(
    name="mcp-light",
    host="127.0.0.1",            # default 127.0.0.1
    port=9135,                   # default 8000
    streamable_http_path="/mcp", # default "/mcp" — matches our target
    # transport_security auto-handled for 127.0.0.1 (DNS-rebind protection)
)
```

**Important:** `host`, `port`, and `streamable_http_path` are CONSTRUCTOR
kwargs, NOT `run()` kwargs. `streamable_http_path` defaults to `/mcp`, but we
set it explicitly per CLAUDE.md (no guesswork).

## run() signature

```python
def run(self, transport: Literal["stdio","sse","streamable-http"] = "stdio",
        mount_path: str | None = None) -> None
```

For `streamable-http`, `mount_path` is unused (it is for SSE). Host/port/path
come from the constructor. So the `__main__` block is:

```python
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

(NOT `mcp.run(host=..., port=..., path=...)` — that signature does not exist
in this SDK version.)

## Tool registration

`FastMCP.tool` signature supports `name=` and `description=`:

```python
@mcp.tool(name="get_governance_index", description="Return list of governance v2 templates and their purpose")
def tool_get_governance_index() -> str:
    ...
```

`name=` lets the public tool name differ from the function name — required
here because functions are named `tool_get_*` but public names must be
`get_*` (frozen list).

## /health decision

Dropped. FastMCP's constructor exposes no trivial custom-route hook, and the
aggressive plan says: do not block on `/health`, do not add a sidecar, do not
reintroduce BaseHTTPServer. Liveness is verified via:

```bash
systemctl status mcp-light --no-pager
journalctl -u mcp-light -n 80 --no-pager
```

plus the MCP client `list_tools` handshake (Phase 7).

## Transport security

`transport_security` is auto-enabled for host `127.0.0.1` (DNS-rebinding
protection). Local clients (opencode, claude) connecting to
`http://127.0.0.1:9135/mcp` are not blocked. If a client is blocked in
Phase 7, revisit.
