from dataclasses import dataclass, field
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def _sort_key(value: str):
    """Numbers (with thousands separators, $ or %) first, then text in natural order ("Store 2" < "Store 10")."""
    try:
        return (0, float(value.replace(",", "").replace("$", "").replace("%", "").strip()), ())
    except ValueError:
        return (1, 0.0, tuple((0, int(part), "") if part.isdigit() else (1, 0, part)
                              for part in re.split(r"(\d+)", value.casefold()) if part))


ASSETS = Path(__file__).resolve().parent / "assets"
# Copied next to each report so it renders in Datasofi type and branding offline too.
BUNDLED_ASSETS = {
    "assets/datasofi-white.png": ASSETS / "brand" / "datasofi-white.png",
    **{f"assets/fonts/{name}": ASSETS / "fonts" / "roboto" / name
       for name in ("Roboto-Regular.ttf", "Roboto-Medium.ttf", "Roboto-Bold.ttf", "LICENSE.txt")},
}
PREVIEW_ROWS = 5
LABELS = {
    "en": {
        "back": "All reports", "notes": "Notes", "generated": "Generated {when} with Sofibot Reports.",
        "preview": "Preview: {shown} of {total} rows", "all_rows": "{total} rows",
        "full": "View full table", "search": "Search rows", "close": "Close", "matches": "{shown} of {total} rows",
        "all": "All", "more": "Show more", "sort": "Sort by {column}", "filter": "Filter by {column}", "views": "{title}: views",
        "source": "Source", "layer_table": "{layer} table", "gold_kind": "Gold aggregate table",
        "grain": "one row per {grain}", "derived": "derived from", "architecture": "See it in the warehouse architecture",
    },
    "es": {
        "back": "Todos los informes", "notes": "Notas", "generated": "Generado el {when} con Sofibot Reports.",
        "preview": "Vista previa: {shown} de {total} filas", "all_rows": "{total} filas",
        "full": "Ver tabla completa", "search": "Buscar filas", "close": "Cerrar", "matches": "{shown} de {total} filas",
        "all": "Todos", "more": "Mostrar más", "sort": "Ordenar por {column}", "filter": "Filtrar por {column}", "views": "{title}: vistas",
        "source": "Fuente", "layer_table": "Tabla {layer}", "gold_kind": "Tabla Gold de agregados",
        "grain": "una fila por {grain}", "derived": "deriva de", "architecture": "Verla en la arquitectura del warehouse",
    },
}


@dataclass
class KPI:
    label: str
    value: Any
    detail: str = ""
    format: str | None = None

    def display_value(self) -> str:
        if self.format == "currency":
            return f"${float(self.value):,.0f}"
        if self.format == "percent":
            return f"{float(self.value):.1%}"
        if self.format == "integer":
            return f"{int(self.value):,}"
        if self.format == "number":
            return f"{float(self.value):,.2f}"
        return str(self.value)


@dataclass
class Chart:
    title: str
    traces: list[dict[str, Any]]
    layout: dict[str, Any] = field(default_factory=dict)
    width: str = "half"
    height: int = 380
    views: dict[str, list[dict[str, Any]]] | None = None
    view_layouts: dict[str, dict[str, Any]] | None = None

    @classmethod
    def bar(
        cls, title: str, labels: Iterable, values: Iterable, *, orientation: str = "v", width: str = "half"
    ) -> "Chart":
        if orientation == "h":
            trace = {"x": list(values), "y": list(labels), "type": "bar", "orientation": "h"}
        else:
            trace = {"x": list(labels), "y": list(values), "type": "bar"}
        return cls(title, [trace], width=width)

    @classmethod
    def line(cls, title: str, labels: Iterable, values: Iterable, *, width: str = "full") -> "Chart":
        return cls(
            title,
            [{"x": list(labels), "y": list(values), "type": "scatter", "mode": "lines+markers"}],
            width=width,
        )

    @classmethod
    def pie(cls, title: str, labels: Iterable, values: Iterable, *, width: str = "half") -> "Chart":
        return cls(title, [{"labels": list(labels), "values": list(values), "type": "pie", "hole": 0.45}], width=width)

    @classmethod
    def day_month_comparison(
        cls,
        title: str,
        *,
        daily_labels: Iterable,
        daily_current: Iterable,
        daily_previous: Iterable,
        monthly_labels: Iterable,
        monthly_current: Iterable,
        monthly_previous: Iterable,
        current_label: str,
        previous_label: str,
        color: str,
        previous_color: str,
        fill_color: str,
        previous_fill_color: str,
        yaxis_title: str,
        tickprefix: str = "",
        width: str = "half",
        height: int = 480,
    ) -> "Chart":
        daily_labels = list(daily_labels)
        monthly_labels = list(monthly_labels)

        def traces(labels: list, current: Iterable, previous: Iterable) -> list[dict[str, Any]]:
            return [
                {
                    "x": labels,
                    "y": list(previous),
                    "type": "scatter",
                    "mode": "lines",
                    "name": f"{previous_label} (PY)",
                    "line": {"width": 2, "color": previous_color, "dash": "dot"},
                    "fill": "tozeroy",
                    "fillcolor": previous_fill_color,
                },
                {
                    "x": labels,
                    "y": list(current),
                    "type": "scatter",
                    "mode": "lines",
                    "name": current_label,
                    "line": {"width": 3, "color": color},
                    "fill": "tozeroy",
                    "fillcolor": fill_color,
                },
            ]

        daily_traces = traces(daily_labels, daily_current, daily_previous)
        monthly_traces = traces(monthly_labels, monthly_current, monthly_previous)
        date_axis = {
            "range": [daily_labels[0], daily_labels[-1]],
            "tickformat": "%d/%m/%Y",
            "rangeselector": {
                "x": 0.02,
                "xanchor": "left",
                "y": 1.01,
                "yanchor": "bottom",
                "buttons": [
                    {"count": 1, "label": "1m", "step": "month", "stepmode": "backward"},
                    {"count": 3, "label": "3m", "step": "month", "stepmode": "backward"},
                    {"count": 6, "label": "6m", "step": "month", "stepmode": "backward"},
                    {"count": 1, "label": "1y", "step": "year", "stepmode": "backward"},
                    {"label": "All", "step": "all"},
                ],
            },
            "rangeslider": {"visible": True, "thickness": 0.08},
        }
        yaxis = {"title": yaxis_title}
        if tickprefix:
            yaxis["tickprefix"] = tickprefix
        return cls(
            title,
            daily_traces,
            layout={"xaxis": date_axis, "yaxis": yaxis},
            width=width,
            height=height,
            views={"Daily": daily_traces, "Monthly": monthly_traces},
            view_layouts={
                "Daily": {"xaxis": {"tickformat": "%d/%m/%Y"}},
                "Monthly": {"xaxis": {"tickformat": "%m/%Y"}},
            },
        )


@dataclass
class TableSource:
    """Warehouse table a report table was computed from, shown above the table."""
    table: str
    layer: str = ""
    grain: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    href: str | None = None


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: Iterable[Iterable[Any]]
    width: str = "full"
    source: TableSource | None = None
    filters: list[str] | None = None
    page_size: int = 25


class Report:
    def __init__(
        self,
        title: str,
        description: str = "",
        subtitle: str = "",
        kpi_columns: int | None = None,
        lang: str = "en",
    ) -> None:
        if lang not in LABELS:
            raise ValueError(f"Unsupported report language: {lang}")
        self.lang = lang
        self.title = title
        self.description = description
        self.subtitle = subtitle
        self.kpi_columns = kpi_columns
        self.kpis: list[KPI] = []
        self.components: list[Chart | Table] = []
        self.notes: list[str] = []
        self.links: list[tuple[str, str]] = []

    @classmethod
    def from_manifest(
        cls,
        project_dir: Path,
        *,
        subtitle: str = "",
        kpi_columns: int | None = None,
        lang: str = "en",
    ) -> "Report":
        manifest = json.loads((project_dir / "report.json").read_text(encoding="utf-8"))
        return cls(manifest["name"], manifest.get("description", ""), subtitle, kpi_columns, lang)

    def add_kpi(self, label: str, value: Any, *, detail: str = "", format: str | None = None) -> "Report":
        self.kpis.append(KPI(label, value, detail, format))
        return self

    def add_chart(self, chart: Chart) -> "Report":
        if chart.width not in {"half", "full"}:
            raise ValueError("Chart width must be 'half' or 'full'")
        self.components.append(chart)
        return self

    def add_table(
        self,
        title: str,
        columns: Iterable[str],
        rows: Iterable[Iterable[Any]],
        *,
        width: str = "full",
        source: TableSource | str | None = None,
        filters: Iterable[str] | None = None,
        page_size: int = 25,
    ) -> "Report":
        """Tables show a short preview; the full table opens on demand.

        With `filters` (column names, may be empty) the table is interactive in the page
        instead: search box, one dropdown per filter column, sortable headers and
        `page_size` rows per page with "Show more".

        `source` names the warehouse table the rows come from (a TableSource
        to include its layer, grain and lineage)."""
        if isinstance(source, str):
            source = TableSource(source, source.split(".")[0])
        columns = list(columns)
        filters = None if filters is None else list(filters)
        unknown = [name for name in filters or [] if name not in columns]
        if unknown:
            raise ValueError(f"Filter columns not in table: {', '.join(unknown)}")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self.components.append(Table(title, columns, [list(row) for row in rows], width, source, filters, page_size))
        return self

    def add_link(self, label: str, href: str) -> "Report":
        """Navigation shown under the report title, e.g. sibling pages of a report."""
        self.links.append((label, href))
        return self

    def add_note(self, text: str) -> "Report":
        self.notes.append(text)
        return self

    def _render_kpis(self) -> str:
        cards = []
        for kpi in self.kpis:
            sentiment = ""
            if kpi.format == "percent":
                numeric_value = float(kpi.value)
                sentiment = " positive" if numeric_value > 0 else " negative" if numeric_value < 0 else " neutral"
            cards.append(
                f'<article class="kpi{sentiment}"><span>{escape(kpi.label)}</span>'
                f'<div class="kpi-value"><strong>{escape(kpi.display_value())}</strong>'
                f'<small>{escape(kpi.detail)}</small></div></article>'
            )
        return "".join(cards)

    def _render_components(self) -> tuple[str, list[dict[str, Any]]]:
        html_parts: list[str] = []
        charts: list[dict[str, Any]] = []
        for index, component in enumerate(self.components):
            width_class = "wide" if component.width == "full" else ""
            if isinstance(component, Chart):
                chart_id = f"chart-{index}"
                controls = ""
                if component.views:
                    button_parts = []
                    for view_index, label in enumerate(component.views):
                        active_class = ' class="active"' if view_index == 0 else ""
                        button_parts.append(
                            f'<button type="button" data-chart="{chart_id}" data-view="{escape(label)}"'
                            f'{active_class}>{escape(label)}</button>'
                        )
                    buttons = "".join(button_parts)
                    views_label = LABELS[self.lang]["views"].format(title=component.title)
                    controls = f'<div class="chart-controls" role="group" aria-label="{escape(views_label, quote=True)}">{buttons}</div>'
                chart_header = (
                    f'<div class="chart-header"><h2>{escape(component.title)}</h2>{controls}</div>'
                )
                html_parts.append(
                    f'<article class="panel {width_class}">{chart_header}<div id="{chart_id}" '
                    f'class="chart" style="height:{int(component.height)}px"></div></article>'
                )
                layout = {
                    "margin": {"l": 65, "r": 25, "t": 78, "b": 65},
                    "paper_bgcolor": "white",
                    "plot_bgcolor": "white",
                    "font": {"family": "Roboto, Arial, sans-serif", "color": "#2C3968"},
                    "colorway": ["#2C3968", "#D16B1B", "#279CDB", "#5DAEAB", "#8BB8EF", "#E8C295", "#8DD9BD", "#B9DEF5"],
                    "xaxis": {"gridcolor": "#eef2f7", "linecolor": "#dfe5ee"},
                    "yaxis": {"gridcolor": "#eef2f7", "zerolinecolor": "#dfe5ee"},
                    "legend": {
                        "orientation": "h",
                        "yanchor": "bottom",
                        "y": 1.11,
                        "xanchor": "left",
                        "x": 0.02,
                    },
                    **component.layout,
                }
                charts.append(
                    {
                        "id": chart_id,
                        "traces": component.traces,
                        "layout": layout,
                        "views": component.views,
                        "viewLayouts": component.view_layouts,
                    }
                )
            else:
                html_parts.append(self._render_table(component, f"table-{index}", width_class))
        return "".join(html_parts), charts

    def _render_source(self, source: TableSource) -> str:
        text = LABELS[self.lang]
        layer = source.layer or source.table.split(".")[0]
        kind = text["gold_kind"] if layer == "gold" else text["layer_table"].format(layer=layer.title())
        grain = f' · {escape(text["grain"].format(grain=" × ".join(source.grain)))}' if source.grain else ""
        parents = (f' · {escape(text["derived"])} ' + ", ".join(f"<code>{escape(parent)}</code>" for parent in source.parents)
                   if source.parents else "")
        link = (f'<a class="source-link" href="{escape(source.href, quote=True)}">{escape(text["architecture"])} →</a>'
                if source.href else "")
        return (f'<div class="source-strip"><span class="layer-tag {escape(layer, quote=True)}">{escape(layer)}</span>'
                f'<span><strong>{escape(kind)}</strong> · {escape(text["source"])} <code>{escape(source.table)}</code>'
                f'{grain}{parents}</span>{link}</div>')

    def _render_explorer(self, table: Table, table_id: str, width_class: str) -> str:
        """Interactive in-page table; rows travel as JSON and are rendered by REPORT_JS."""
        text = LABELS[self.lang]
        rows = [[str(value) for value in row] for row in table.rows]
        selects = ""
        for name in table.filters:
            column = table.columns.index(name)
            options = "".join(f'<option value="{escape(value, quote=True)}">{escape(value)}</option>'
                              for value in sorted({row[column] for row in rows}, key=_sort_key))
            label = text["filter"].format(column=name)
            selects += (f'<label class="filter"><span>{escape(name)}</span><select data-column="{column}" '
                        f'aria-label="{escape(label, quote=True)}"><option value="">{escape(text["all"])}</option>'
                        f'{options}</select></label>')
        headers = "".join(
            f'<th><button type="button" class="sort" data-column="{index}" '
            f'aria-label="{escape(text["sort"].format(column=column), quote=True)}">{escape(str(column))}</button></th>'
            for index, column in enumerate(table.columns))
        source = self._render_source(table.source) if table.source else ""
        payload = _json_for_script({"columns": [str(c) for c in table.columns], "rows": rows, "pageSize": table.page_size})
        return (f'<article class="panel table-panel explorer {width_class}" id="{table_id}"><div class="table-head"><div>'
                f'<h2>{escape(table.title)}</h2><p class="table-count" aria-live="polite"></p></div></div>{source}'
                f'<div class="explorer-tools"><label class="filter search"><span>{escape(text["search"])}</span>'
                f'<input type="search"></label>{selects}</div>'
                f'<div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody></tbody></table></div>'
                f'<button type="button" class="button ghost more" hidden>{escape(text["more"])}</button>'
                f'<script type="application/json" class="explorer-data">{payload}</script></article>')

    def _render_table(self, table: Table, table_id: str, width_class: str) -> str:
        if table.filters is not None:
            return self._render_explorer(table, table_id, width_class)
        text = LABELS[self.lang]
        rows = list(table.rows)
        headers = "".join(f"<th>{escape(str(column))}</th>" for column in table.columns)
        body = "".join("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
                       for row in rows[:PREVIEW_ROWS])
        total = len(rows)
        count = (text["preview"].format(shown=PREVIEW_ROWS, total=f"{total:,}") if total > PREVIEW_ROWS
                 else text["all_rows"].format(total=f"{total:,}"))
        button = (f'<button type="button" class="button ghost" data-table="{table_id}">{escape(text["full"])} '
                  f'({total:,})</button>' if total > PREVIEW_ROWS else "")
        source = self._render_source(table.source) if table.source else ""
        # The full rows travel as JSON and are only rendered when the dialog opens.
        payload = _json_for_script({"title": table.title, "columns": [str(c) for c in table.columns],
                                    "rows": [[str(value) for value in row] for row in rows]}) if button else ""
        data = f'<script type="application/json" class="table-data">{payload}</script>' if button else ""
        return (f'<article class="panel table-panel {width_class}" id="{table_id}"><div class="table-head"><div>'
                f'<h2>{escape(table.title)}</h2><p class="table-count">{escape(count)}</p></div>{button}</div>{source}'
                f'<div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'
                f'{data}</article>')

    def render(self) -> str:
        text = LABELS[self.lang]
        components_html, charts = self._render_components()
        notes = "".join(f"<li>{escape(note)}</li>" for note in self.notes)
        notes_section = f'<section class="notes"><h2>{escape(text["notes"])}</h2><ul>{notes}</ul></section>' if notes else ""
        generated = datetime.now().astimezone().strftime("%d %b %Y, %H:%M %Z")
        chart_payload = _json_for_script(charts)
        kpi_style = f' style="grid-template-columns:repeat({self.kpi_columns},minmax(0,1fr))"' if self.kpi_columns else ""
        links = "".join(f'<a href="{escape(href, quote=True)}">{escape(label)}</a>' for label, href in self.links)
        nav = f'<nav class="report-nav">{links}</nav>' if links else ""
        subtitle = f'<p class="subtitle">{escape(self.subtitle)}</p>' if self.subtitle else ""
        kpis = f'<section class="kpis"{kpi_style}>{self._render_kpis()}</section>' if self.kpis else ""
        labels = _json_for_script({key: text[key] for key in ("search", "close", "matches")})
        return f"""<!doctype html>
<html lang="{self.lang}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(self.title)}</title><script src="plotly.min.js"></script>
<style>{REPORT_CSS}</style></head><body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="/dashboard"><img src="assets/datasofi-white.png" alt="Datasofi" width="70" height="34"><span class="brand-divider" aria-hidden="true"></span><span class="brand-product">Sofibot <strong>Reports</strong></span></a>
<a class="back" href="/dashboard">← {escape(text["back"])}</a></div></header>
<main>
<header class="report-head"><h1>{escape(self.title)}</h1><p>{escape(self.description)}</p>{subtitle}{nav}</header>
{kpis}<section class="grid">{components_html}</section>{notes_section}
<footer>{escape(text["generated"].format(when=generated))}</footer></main>
<dialog class="table-dialog" id="table-dialog" aria-labelledby="table-dialog-title"><div class="dialog-head"><h2 id="table-dialog-title"></h2><button type="button" class="dialog-close" aria-label="{escape(text["close"], quote=True)}">×</button></div>
<div class="dialog-tools"><input type="search" placeholder="{escape(text["search"], quote=True)}" aria-label="{escape(text["search"], quote=True)}"><span class="table-count" aria-live="polite"></span></div>
<div class="table-scroll dialog-scroll"><table><thead></thead><tbody></tbody></table></div></dialog>
<script>const charts={chart_payload};const labels={labels};{REPORT_JS}</script>
</body></html>"""

    def write(self, output_dir: Path, *, plotly_source: Path | None = None) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if plotly_source is None:
            plotly_source = ASSETS / "plotly.min.js"
        if not plotly_source.is_file():
            raise FileNotFoundError(f"Plotly JavaScript asset not found: {plotly_source}")
        index_path = output_dir / "index.html"
        index_path.write_text(self.render(), encoding="utf-8")
        shutil.copyfile(plotly_source, output_dir / "plotly.min.js")
        # Fonts and logo travel with the report; without them it falls back to Arial and alt text.
        for target, source in BUNDLED_ASSETS.items():
            if source.is_file():
                (output_dir / target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, output_dir / target)
        return index_path


# Datasofi report style: brand HEX from config/datasofi-style.json, matching the Contoso Data Portal.
REPORT_CSS = """
@font-face{font-family:Roboto;src:url('assets/fonts/Roboto-Regular.ttf');font-weight:400;font-display:swap}
@font-face{font-family:Roboto;src:url('assets/fonts/Roboto-Medium.ttf');font-weight:500;font-display:swap}
@font-face{font-family:Roboto;src:url('assets/fonts/Roboto-Bold.ttf');font-weight:700;font-display:swap}
:root{--blue:#2C3968;--orange:#D16B1B;--cyan:#279CDB;--teal:#5DAEAB;--muted:#566173;--line:#dfe5ee;--soft:#f4f7fb;
  --ok:#17663b;--bad:#a52b2b;--shadow:0 10px 30px #2c39680d}
*{box-sizing:border-box}
body{margin:0;background:var(--soft);color:var(--blue);font:16px/1.5 Roboto,Arial,sans-serif}
a{color:var(--blue)}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--orange);outline-offset:3px}
code{font-family:Consolas,'Cascadia Mono',monospace;font-size:.92em}
.topbar{background:var(--blue);color:#fff;position:sticky;top:0;z-index:20;box-shadow:0 2px 14px #0000001f}
.topbar-inner{max-width:1280px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:24px;padding:10px 24px;min-height:64px}
.brand{display:flex;align-items:center;gap:14px;color:#fff;text-decoration:none}
.brand img{height:34px;width:auto;display:block}
.brand-divider{width:1px;height:28px;background:#ffffff4d}
.brand-product{font-size:15px;white-space:nowrap}
.back{color:#dfe5f3;text-decoration:none;font-size:14px;font-weight:500;padding:9px 14px;border-radius:9px;white-space:nowrap}
.back:hover{background:#ffffff14;color:#fff}
main{max-width:1280px;margin:auto;padding:28px 24px 56px}
.report-head{position:relative;overflow:hidden;border-radius:22px;padding:34px 38px;margin-bottom:22px;color:#fff;background:linear-gradient(120deg,#2C3968 0%,#3b4a80 55%,#D16B1B 140%);box-shadow:0 20px 50px #2c396833}
.report-head:after{content:"";position:absolute;right:-90px;top:-90px;width:320px;height:320px;border-radius:50%;border:56px solid #ffffff10;pointer-events:none}
.report-head h1{margin:0 0 8px;font-size:clamp(26px,3.6vw,38px);line-height:1.15;letter-spacing:-.4px}
.report-head p{margin:0;color:#e3e8f4;max-width:760px}
.report-head .subtitle{display:inline-block;margin-top:14px;padding:4px 12px;border-radius:20px;background:#ffffff1f;color:#fff;font-size:13px;font-weight:500}
.report-nav{position:relative;z-index:1;display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.report-nav a{color:#fff;text-decoration:none;font-size:14px;font-weight:500;padding:7px 14px;border-radius:9px;background:#ffffff1a;border:1px solid #ffffff2e}
.report-nav a:hover{background:#ffffff33}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:18px}
.kpi,.panel,.notes{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}
.kpi{display:grid;grid-template-rows:1fr 1fr;padding:14px 16px;min-width:0;min-height:108px;border-top:4px solid var(--blue)}
.kpi:nth-child(4n+2){border-top-color:var(--orange)}.kpi:nth-child(4n+3){border-top-color:var(--cyan)}.kpi:nth-child(4n+4){border-top-color:var(--teal)}
.kpi>span{display:flex;align-items:flex-start;color:var(--muted);font-size:11px;font-weight:500;line-height:1.25;text-transform:uppercase;letter-spacing:.6px}
.kpi-value{display:flex;flex-direction:column;justify-content:flex-end;min-width:0}
.kpi strong{display:block;margin:0 0 3px;font-size:22px;line-height:1.1}
.kpi small{display:block;min-height:13px;color:var(--muted);font-size:12px}
.kpi.positive strong{color:var(--ok)}.kpi.negative strong{color:var(--bad)}.kpi.neutral strong{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.panel{position:relative;padding:16px;min-width:0}
.wide{grid-column:1/-1}
.chart{width:100%}
.chart-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:4px 6px 0}
.chart-header h2,.table-head h2,.notes h2{margin:0;font-size:18px;line-height:32px}
.chart-controls{display:flex;flex:0 0 auto;padding:3px;background:#e9edf6;border-radius:9px}
.chart-controls button{border:0;border-radius:7px;padding:6px 11px;background:transparent;color:var(--muted);font:500 12px Roboto,Arial,sans-serif;cursor:pointer}
.chart-controls button.active{background:#fff;color:var(--blue);box-shadow:inset 0 -2px 0 var(--orange),0 1px 4px #2c396822}
.table-panel{padding:22px}
.table-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap;margin-bottom:12px}
.table-count{margin:0;color:var(--muted);font-size:13px}
.button{display:inline-flex;align-items:center;gap:8px;border-radius:9px;padding:9px 16px;font:500 14px Roboto,Arial,sans-serif;cursor:pointer;white-space:nowrap;background:#fff;color:var(--blue);border:1px solid #c9d2e0}
.button:hover{background:var(--soft);border-color:var(--blue)}
.source-strip{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin:0 0 14px;padding:10px 14px;border-radius:12px;background:#fbf6e9;border:1px solid #efdfb4;font-size:13px}
.source-strip code{background:#fff;border-radius:5px;padding:1px 6px}
.source-link{margin-left:auto;font-weight:500;color:#7a5306;text-decoration:none;white-space:nowrap}
.source-link:hover{text-decoration:underline}
.layer-tag{display:inline-flex;font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;padding:3px 9px;border-radius:6px;color:#fff;background:#566173}
.layer-tag.bronze{background:#a35a1d}.layer-tag.silver{background:#5d6b85}.layer-tag.gold{background:#b07c12}
.table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{background:#f7f9fc;color:var(--muted);font-size:12px;font-weight:500;letter-spacing:.3px;position:sticky;top:0}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:#f9fbfd}
.notes{padding:22px 26px;margin-top:18px}
.notes ul{margin:10px 0 0;padding-left:20px;display:grid;gap:6px;color:#3c4766;font-size:14px}
footer{margin-top:20px;font-size:13px;color:var(--muted)}
.table-dialog{width:min(1100px,calc(100vw - 32px));max-height:calc(100vh - 48px);padding:0;border:0;border-radius:18px;box-shadow:0 30px 80px #1b234259;color:var(--blue)}
.table-dialog::backdrop{background:#1b234266}
.table-dialog[open]{display:flex;flex-direction:column}
.dialog-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 22px 8px}
.dialog-head h2{margin:0;font-size:20px}
.dialog-close{width:38px;height:38px;border-radius:50%;border:1px solid var(--line);background:#fff;font-size:24px;line-height:1;color:var(--blue);cursor:pointer;flex:none}
.dialog-tools{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:6px 22px 14px}
.dialog-tools input{font:14px Roboto,Arial,sans-serif;color:var(--blue);padding:9px 12px;border:1px solid #c9d2e0;border-radius:9px;min-width:260px}
.dialog-scroll{margin:0 22px 22px;overflow:auto;flex:1}
.explorer-tools{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin:0 0 14px}
.filter{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted);font-weight:500}
.filter input,.filter select{font:14px Roboto,Arial,sans-serif;color:var(--blue);padding:8px 10px;border:1px solid #c9d2e0;border-radius:9px;background:#fff;min-width:150px}
.filter.search input{min-width:240px}
.explorer .table-scroll{max-height:560px;overflow:auto}
.sort{all:unset;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.sort:after{content:"↕";color:#b3bccb;font-size:11px}
.sort[data-direction=asc]:after{content:"▲";color:var(--orange)}.sort[data-direction=desc]:after{content:"▼";color:var(--orange)}
.sort:focus-visible,select:focus-visible{outline:3px solid var(--orange);outline-offset:3px}
.explorer .more{margin-top:12px}.explorer .more[hidden]{display:none}
@media(max-width:1100px){.kpis[style]{grid-template-columns:repeat(4,minmax(0,1fr))!important}}
@media(max-width:800px){.filter,.filter input,.filter select,.filter.search input{min-width:0;width:100%}.grid{grid-template-columns:1fr}.wide{grid-column:auto}.kpis[style]{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  main{padding:20px 16px 40px}.topbar-inner{padding:10px 16px}.report-head{padding:26px 22px}.source-link{margin-left:0}.dialog-tools input{min-width:0;width:100%}}
@media(max-width:480px){.brand-divider,.brand-product{display:none}}
/* The server adds a floating account button at the top right; keep it clear and in portal colors. */
@media(max-width:1400px){.topbar-inner{padding-right:64px}}
#sofibot-login-status summary{background:#D16B1B!important}
"""

REPORT_JS = """const config={responsive:true,displaylogo:false};charts.forEach(c=>Plotly.newPlot(c.id,c.traces,c.layout,config));
document.querySelectorAll('.chart-controls button').forEach(button=>button.addEventListener('click',()=>{
  const chart=charts.find(item=>item.id===button.dataset.chart);if(!chart||!chart.views)return;
  const patch=chart.viewLayouts?.[button.dataset.view]||{};
  const layout={...chart.layout,...patch,xaxis:{...(chart.layout.xaxis||{}),...(patch.xaxis||{})}};
  Plotly.react(chart.id,chart.views[button.dataset.view],layout,config);
  button.parentElement.querySelectorAll('button').forEach(item=>item.classList.toggle('active',item===button));
}));
(()=>{
  const dialog=document.getElementById('table-dialog');if(!dialog)return;
  const search=dialog.querySelector('input'),count=dialog.querySelector('.table-count'),head=dialog.querySelector('thead'),body=dialog.querySelector('tbody');
  const cell=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;};
  let data=null;
  function fill(){
    const query=search.value.trim().toLocaleLowerCase();
    const rows=data.rows.filter(row=>!query||row.some(value=>value.toLocaleLowerCase().includes(query)));
    body.replaceChildren(...rows.map(row=>{const tr=document.createElement('tr');tr.append(...row.map(value=>cell('td',value)));return tr;}));
    count.textContent=labels.matches.replace('{shown}',rows.length.toLocaleString()).replace('{total}',data.rows.length.toLocaleString());
  }
  document.querySelectorAll('[data-table]').forEach(button=>button.addEventListener('click',()=>{
    data=JSON.parse(document.querySelector('#'+button.dataset.table+' .table-data').textContent);
    dialog.querySelector('h2').textContent=data.title;
    const tr=document.createElement('tr');tr.append(...data.columns.map(name=>cell('th',name)));head.replaceChildren(tr);
    search.value='';fill();dialog.showModal();search.focus();
  }));
  search.addEventListener('input',fill);
  dialog.querySelector('.dialog-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
})();
document.querySelectorAll('.explorer').forEach(panel=>{
  const data=JSON.parse(panel.querySelector('.explorer-data').textContent);
  const search=panel.querySelector('input[type=search]'),selects=[...panel.querySelectorAll('select')];
  const body=panel.querySelector('tbody'),count=panel.querySelector('.table-count'),more=panel.querySelector('.more');
  const number=value=>{const n=Number(value.replace(/[,$%\\s]/g,''));return value.trim()!==''&&Number.isFinite(n)?n:null;};
  let sort=null,direction=1,limit=data.pageSize;
  function rows(){
    const query=search.value.trim().toLocaleLowerCase();
    const chosen=selects.filter(s=>s.value).map(s=>[Number(s.dataset.column),s.value]);
    const result=data.rows.filter(row=>chosen.every(([c,v])=>row[c]===v)&&(!query||row.some(v=>v.toLocaleLowerCase().includes(query))));
    if(sort!==null)result.sort((a,b)=>{const x=number(a[sort]),y=number(b[sort]);
      return direction*(x!==null&&y!==null?x-y:x!==null?-1:y!==null?1:a[sort].localeCompare(b[sort],undefined,{numeric:true}));});
    return result;
  }
  function render(){
    const matched=rows(),shown=matched.slice(0,limit);
    body.replaceChildren(...shown.map(row=>{const tr=document.createElement('tr');
      tr.append(...row.map(value=>{const td=document.createElement('td');td.textContent=value;return td;}));return tr;}));
    count.textContent=labels.matches.replace('{shown}',shown.length.toLocaleString()).replace('{total}',matched.length.toLocaleString());
    more.hidden=matched.length<=limit;
  }
  const reset=()=>{limit=data.pageSize;render();};
  search.addEventListener('input',reset);selects.forEach(s=>s.addEventListener('change',reset));
  more.addEventListener('click',()=>{limit+=data.pageSize;render();});
  panel.querySelectorAll('.sort').forEach(button=>button.addEventListener('click',()=>{
    const column=Number(button.dataset.column);direction=sort===column?-direction:-1;sort=column;
    panel.querySelectorAll('.sort').forEach(b=>{b.removeAttribute('data-direction');b.closest('th').removeAttribute('aria-sort');});
    button.dataset.direction=direction===1?'asc':'desc';
    button.closest('th').setAttribute('aria-sort',direction===1?'ascending':'descending');render();}));
  render();
});"""
