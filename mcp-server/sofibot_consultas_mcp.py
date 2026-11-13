"""Sofibot MCP server for functionality 2, data queries (docs/11-consultas.md).

For the user's own AI (Claude Code, Claude Desktop, Codex...) on their computer. A thin layer
over the query service (/api/query): the catalog of what the user may ask, structured queries
(measures by dimensions, filters, period; never SQL) and the record of how each question
ended. Sofibot checks the user's roles and tables on every call and records who asked what.

The results ARE the company's data and reach the provider of the AI the user is running: use
it only with the AI account the company has approved.

    pip install -r requirements.txt
    python sofibot_consultas_mcp.py      (started by the AI client, with the settings of sofibot_entra.py)
"""
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import sofibot_entra

mcp = FastMCP("Sofibot consultas", instructions=(
    "Sofibot has two separate connectors and THE USER chooses which one to use: 'Sofibot informes' (create reports; you never see data) and 'Sofibot consultas' (query data; you see the results). Use this connector only when the user has chosen it in this conversation, by name or unmistakably ('crea un informe en Sofibot' is informes; 'consulta en Sofibot cuánto...' is consultas). If a request could fit either, or the user has not chosen, do not call any tool: ask first, in the user's language, for example: '¿Quieres que cree un informe en Sofibot (sin ver los datos) o que consulte los datos ahora?'. Never use both connectors in the same conversation: if the user wants the other one, ask them to start a new conversation for it. "
    "To create or publish a report the user must use the 'Sofibot informes' connector, in a new conversation. "
    "You answer questions about the company's data through Sofibot, with the signed-in user's permissions. "
    "Start with describe_catalog: use only its tables, measures and dimensions, and respect its rules. "
    "Map the question to measures, dimensions, filters and a period of whole months (YYYY-MM); if it is "
    "ambiguous (which measure, which period), ask before querying. Run run_query and answer only from its "
    "rows: never invent or estimate numbers, null means no data (not zero), and say when the result was "
    "truncated. Ratios come from the catalog's ratio measures, never from averaging. In the answer, state "
    "the table, measures, dimensions and period you used. After EVERY question, also the ones you cannot "
    "answer because the catalog has no such data, call record_outcome once with the outcome, the user's "
    "question and the query_ids you used: that is how the data team learns what people need."
))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


@mcp.tool(annotations=READ)
def describe_catalog() -> dict:
    """Sofibot consultas (the user must have chosen it): what the user may ask: their Gold tables, each
    with measures (sum, ratio or distinct count, with format and description), dimensions, whether it has a
    monthly period, and rules. Plus max_rows."""
    return sofibot_entra.call("GET", "/api/query/catalog")


@mcp.tool(annotations=READ)
def run_query(table: str, measures: list[str], dimensions: list[str] | None = None,
              filters: list[dict] | None = None, period_from: str | None = None, period_to: str | None = None,
              order_by: str | None = None, descending: bool = True, limit: int | None = None,
              question_id: str | None = None) -> dict:
    """Run a query on one catalog table.

    measures / dimensions: names from describe_catalog (no dimensions = totals).
    filters: [{"dimension": "tienda", "values": ["Madrid", "Bilbao"]}].
    period_from / period_to: whole months, YYYY-MM, both included (only tables with a period).
    order_by: one of the requested measures or dimensions. limit: rows (capped by max_rows).
    question_id: any id you choose to group the queries of one question.
    Returns query_id, columns, rows, truncated, and each measure's format. null = no data.
    """
    payload = {"table": table, "measures": measures, "dimensions": dimensions or [], "filters": filters or []}
    if period_from or period_to:
        payload["period"] = {"from": period_from or period_to, "to": period_to or period_from}
    if order_by:
        payload["order"] = {"by": order_by, "desc": descending}
    if limit:
        payload["limit"] = limit
    if question_id:
        payload["question_id"] = question_id[:64]
    return sofibot_entra.call("POST", "/api/query", payload)


@mcp.tool(annotations=SEND)
def record_outcome(outcome: str, question: str, reason: str = "", query_ids: list[str] | None = None,
                   question_id: str | None = None) -> dict:
    """Record how a question ended. Call it once per question, after answering or failing to.

    outcome: respondida (answered) | no_disponible (the catalog has no such data, or not for this user) |
    ambigua (needed clarification that did not come) | rechazada (outside the limits) | error.
    question: the user's question in their words. reason: one short sentence. query_ids: from run_query.
    """
    payload = {"outcome": outcome, "question": question[:2000], "reason": reason[:500],
               "query_ids": (query_ids or [])[:50], "model": os.environ.get("SOFIBOT_AI", "")[:100]}
    if question_id:
        payload["question_id"] = question_id[:64]
    return sofibot_entra.call("POST", "/api/query/outcome", payload)


if __name__ == "__main__":
    mcp.run(transport="stdio")
