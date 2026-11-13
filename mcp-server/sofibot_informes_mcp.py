"""Sofibot MCP server for functionality 1, writing reports (docs/10-api-informes.md).

For AI assistants (Claude Code, Claude Desktop, Codex...) on the author's computer. A thin
layer over the portal's report-code API (/api/code): the Gold schema of the author's tables,
the published reports and report drafts. No tool returns data or accepts SQL, and nothing
the assistant writes is built until a reviewer publishes it.

The author signs in with their Microsoft account the first time (sofibot_entra.py).

    pip install -r requirements.txt
    python sofibot_informes_mcp.py      (started by the AI client, with the settings of sofibot_entra.py)
"""
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import sofibot_entra

mcp = FastMCP("Sofibot informes", instructions=(
    "Sofibot has two separate connectors and THE USER chooses which one to use: 'Sofibot informes' (create reports; you never see data) and 'Sofibot consultas' (query data; you see the results). Use this connector only when the user has chosen it in this conversation, by name or unmistakably ('crea un informe en Sofibot' is informes; 'consulta en Sofibot cuánto...' is consultas). If a request could fit either, or the user has not chosen, do not call any tool: ask first, in the user's language, for example: '¿Quieres que cree un informe en Sofibot (sin ver los datos) o que consulte los datos ahora?'. Never use both connectors in the same conversation: if the user wants the other one, ask them to start a new conversation for it. "
    "You write Sofibot reports without ever seeing data: never put in the code values, names or "
    "figures seen in a query or elsewhere; everything is computed by the report's SQL. "
    "Start with describe_schema and follow its "
    "report_guide. Create a draft, write generate.py and report.json from the schema, run check_draft "
    "until it passes (static check: no code runs), then submit_draft when the user asks. A reviewer "
    "previews, publishes and builds every report. Never try to read data by other means."
))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def call(method: str, route: str, payload: dict | None = None) -> dict:
    return sofibot_entra.call(method, f"/api/code/{route}", payload)


@mcp.tool(annotations=READ)
def describe_schema() -> dict:
    """Sofibot informes (the user must have chosen it): Gold tables and views of the user's tables
    (columns, types, descriptions) plus report_guide, the steps and API for writing a report. No data."""
    return call("GET", "schema")


@mcp.tool(annotations=READ)
def list_reports() -> dict:
    """Published reports: slug, name, description and the Gold tables each reads."""
    return call("GET", "reports")


@mcp.tool(annotations=READ)
def list_drafts() -> dict:
    """Report drafts: slug, name, status (draft, submitted, published, rejected), comment and files."""
    return call("GET", "drafts")


@mcp.tool(annotations=WRITE)
def create_draft(slug: str, name: str = "", table: str = "", description: str = "", from_report: bool = False) -> dict:
    """Create a draft from the template (name and main Gold table, e.g. gold.ventas_mes_tienda) or,
    with from_report=true, as a copy of the published report with that slug. slug: lowercase-with-hyphens."""
    return call("POST", "drafts", {"slug": slug, "name": name, "table": table, "description": description,
                                   "from_report": from_report})


@mcp.tool(annotations=READ)
def read_file(slug: str, name: str) -> dict:
    """Read report.json or a Python file (e.g. generate.py) of a draft."""
    return call("GET", f"drafts/{quote(slug, safe='')}/files/{quote(name, safe='')}")


@mcp.tool(annotations=WRITE)
def write_file(slug: str, name: str, content: str) -> dict:
    """Write report.json or a Python file (lowercase name) of a draft, replacing it."""
    return call("PUT", f"drafts/{quote(slug, safe='')}/files/{quote(name, safe='')}", {"content": content})


@mcp.tool(annotations=DELETE)
def delete_draft(slug: str) -> dict:
    """Delete a draft. Published reports are not affected."""
    return call("DELETE", f"drafts/{quote(slug, safe='')}")


@mcp.tool(annotations=READ)
def check_draft(slug: str) -> dict:
    """Static check: report.json, Python syntax and Gold tables against the schema. Runs no code."""
    return call("POST", f"drafts/{quote(slug, safe='')}/check")


@mcp.tool(annotations=SEND)
def submit_draft(slug: str) -> dict:
    """Check, then send the draft to a reviewer, who previews and publishes it. Only when the user asks for it."""
    return call("POST", f"drafts/{quote(slug, safe='')}/submit")


@mcp.tool(annotations=READ)
def draft_status(slug: str) -> dict:
    """Status of a draft, who did what and, if rejected, the reviewer's comment."""
    return call("GET", f"drafts/{quote(slug, safe='')}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
