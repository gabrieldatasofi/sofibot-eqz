from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html import escape
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from .dynamic import (DATE_KINDS, DYNAMIC_CSS, DYNAMIC_JS, KPI_FORMATS, Dataset, DynamicChart, DynamicKPI,
                      DynamicTable, Filter, chart_traces, evaluate, format_value, label as category_label, plain)
from .excel import FORMATS, infer_format
from .formatting import MONTHS, display_value, excel_value, grouped as _grouped  # noqa: F401


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
        "excel": "Excel", "download_filtered": "Download the rows shown, with the current filters and order, as an Excel sheet",
        "download_table": "Download this table as an Excel sheet", "download_chart": "Download the chart data as an Excel sheet",
        "category": "Category", "value": "Value", "series": "Series",
        "filters": "Filters", "from": "{label} from", "to": "to", "reset": "Reset filters",
        "granularity": "{title}: granularity", "active": "({count} active)",
    },
    "es": {
        "back": "Todos los informes", "notes": "Notas", "generated": "Generado el {when} con Sofibot Reports.",
        "preview": "Vista previa: {shown} de {total} filas", "all_rows": "{total} filas",
        "full": "Ver tabla completa", "search": "Buscar filas", "close": "Cerrar", "matches": "{shown} de {total} filas",
        "all": "Todos", "more": "Mostrar más", "sort": "Ordenar por {column}", "filter": "Filtrar por {column}", "views": "{title}: vistas",
        "source": "Fuente", "layer_table": "Tabla {layer}", "gold_kind": "Tabla Gold de agregados",
        "grain": "una fila por {grain}", "derived": "deriva de", "architecture": "Verla en la arquitectura del warehouse",
        "excel": "Excel", "download_filtered": "Descargar en una hoja de Excel las filas que se ven, con los filtros y el orden actuales",
        "download_table": "Descargar esta tabla en una hoja de Excel", "download_chart": "Descargar los datos del gráfico en una hoja de Excel",
        "category": "Categoría", "value": "Valor", "series": "Serie",
        "filters": "Filtros", "from": "{label} desde", "to": "hasta", "reset": "Quitar filtros",
        "granularity": "{title}: granularidad", "active": "({count} activos)",
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
    download: bool = True  # Excel button with the data of the view on screen

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
    formats: dict[str, str] = field(default_factory=dict)
    download: bool = True

    def kinds(self) -> list[str | None]:
        return [self.formats.get(column) for column in self.columns]

    def payload(self, lang: str) -> dict[str, Any]:
        """Rows as display text, plus the real values of typed columns for sorting and the Excel download."""
        kinds = self.kinds()
        rows = [list(row) for row in self.rows]
        return {
            "title": self.title, "columns": [str(column) for column in self.columns], "kinds": kinds,
            "rows": [[display_value(value, kinds[index], lang) for index, value in enumerate(row)] for row in rows],
            "values": {str(index): [excel_value(row[index]) for row in rows]
                       for index, kind in enumerate(kinds) if kind not in (None, "text")},
            "pageSize": self.page_size,
        }


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
        self.components: list[Chart | Table | DynamicChart | DynamicTable] = []
        self.notes: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.datasets: dict[str, Dataset] = {}
        self.filters: list[Filter] = []
        self.dynamic_kpis: list[DynamicKPI] = []

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
        formats: dict[str, str] | None = None,
        download: bool = True,
    ) -> "Report":
        """Tables show a short preview; the full table opens on demand.

        With `filters` (column names, may be empty) the table is interactive in the page
        instead: search box, one dropdown per filter column, sortable headers and
        `page_size` rows per page with "Show more".

        Pass real values (numbers, dates, Decimals) and `formats` like Workbook.add_sheet
        (eur, usd, percent, integer, number, date, datetime, month, text); columns left out
        get one from their values. The page shows them formatted and the Excel button
        (`download`, on by default) exports the rows shown as real numbers and dates.
        Text cells are shown and exported as they are.

        `source` names the warehouse table the rows come from (a TableSource
        to include its layer, grain and lineage)."""
        if isinstance(source, str):
            source = TableSource(source, source.split(".")[0])
        columns = [str(column) for column in columns]
        rows = [list(row) for row in rows]
        filters = None if filters is None else list(filters)
        unknown = [name for name in filters or [] if name not in columns]
        if unknown:
            raise ValueError(f"Filter columns not in table: {', '.join(unknown)}")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        for index, row in enumerate(rows, start=1):
            if len(row) != len(columns):
                raise ValueError(f"Table {title}: row {index} has {len(row)} values, expected {len(columns)}")
        formats = dict(formats or {})
        unknown = [key for key in formats if key not in columns]
        bad = [value for value in formats.values() if value not in FORMATS]
        if unknown or bad:
            raise ValueError(f"Invalid formats: unknown columns {unknown}, unknown formats {bad}")
        for index, column in enumerate(columns):
            if column not in formats and (kind := infer_format(row[index] for row in rows)):
                formats[column] = kind
        self.components.append(Table(title, columns, rows, width, source, filters, page_size, formats, download))
        return self

    # --- Report-level filters (sofibot_eqz.dynamic) -------------------------------------------

    def add_dataset(self, name: str, columns: Iterable[str], rows: Iterable[Iterable[Any]], *,
                    formats: dict[str, str] | None = None) -> "Report":
        """Aggregated rows embedded in the page for the report filters, dynamic KPIs, charts and tables.

        Keep them aggregated (e.g. month x store): every row travels inside the page. `formats`
        like add_table (dates get `date`, month starts are best given `month`)."""
        columns = [str(column) for column in columns]
        rows = [list(row) for row in rows]
        if name in self.datasets:
            raise ValueError(f"Duplicate dataset: {name}")
        if len(set(columns)) != len(columns):
            raise ValueError("Dataset column names must be unique")
        for index, row in enumerate(rows, start=1):
            if len(row) != len(columns):
                raise ValueError(f"Dataset {name}: row {index} has {len(row)} values, expected {len(columns)}")
        formats = self._check_formats(dict(formats or {}), columns)
        for index, column in enumerate(columns):
            if column not in formats and (kind := infer_format(row[index] for row in rows)):
                formats[column] = kind
        self.datasets[name] = Dataset(name, columns, [[plain(value) for value in row] for row in rows], formats)
        return self

    def add_filter(self, label: str, column: str, *, kind: str = "select", default: Any = None,
                   compare: bool = False, labels: dict | None = None) -> "Report":
        """A filter in the bar above the report. It applies to every dynamic KPI, chart and table
        whose dataset has `column`. kind="range" gives from/to selectors over the ordered values
        (default (from, to)); "select" one value or all (default None = all). compare=True (numeric
        select, e.g. year) makes measure.previous()/vs_previous() use value - 1."""
        if kind not in {"select", "range"} or (compare and kind != "select"):
            raise ValueError("Filters are 'select' or 'range'; only a select filter can be the comparison period")
        if not any(column in dataset.columns for dataset in self.datasets.values()):
            raise ValueError(f"Filter column {column} is in no dataset (add_dataset first)")
        if kind == "range" and default is not None:
            default = tuple(plain(value) for value in default)
        elif default is not None:
            default = plain(default)
        self.filters.append(Filter(label, column, kind, default, compare, {plain(k): v for k, v in (labels or {}).items()}))
        return self

    def add_dynamic_kpi(self, label: str, dataset: str, measure, *, format: str = "number", detail: str = "") -> "Report":
        """KPI recomputed with the filters. format: currency (USD), eur, usd, integer, number, percent,
        change (relative vs previous) or pp (percentage points)."""
        self._check_measures(dataset, [measure])
        if format not in KPI_FORMATS:
            raise ValueError(f"KPI format must be one of {', '.join(sorted(KPI_FORMATS))}")
        self.dynamic_kpis.append(DynamicKPI(label, dataset, measure, format, detail))
        return self

    def add_dynamic_chart(self, title: str, dataset: str, x, series, *, kind: str = "line", order: str = "x",
                          top: int | None = None, x_sort: str | None = None, width: str = "half", height: int = 380,
                          layout: dict | None = None, download: bool = True) -> "Report":
        """Chart recomputed with the filters. series: [(name, measure) or (name, measure, color)];
        x: a column, or {button label: column} to let the reader switch granularity (day/month/year);
        kind: line, bar or hbar; order="desc" sorts by the first series, `top` keeps the first n."""
        for name, value, allowed in (("kind", kind, ("line", "bar", "hbar")), ("order", order, ("x", "desc")),
                                     ("width", width, ("half", "full"))):
            if value not in allowed:
                raise ValueError(f'add_dynamic_chart("{title}"): {name}={value!r} is not supported; use one of '
                                 f'{", ".join(repr(a) for a in allowed)}'
                                 + ('. order="desc" sorts by the first series' if name == "order" else ""))
        series = [tuple(item) for item in series]
        self._check_measures(dataset, [item[1] for item in series], [*(x.values() if isinstance(x, dict) else [x]),
                                                                       *([x_sort] if x_sort else [])])
        self.components.append(DynamicChart(title, dataset, x, series, kind, order, top, x_sort, width, height,
                                            layout or {}, download))
        return self

    def add_dynamic_table(self, title: str, dataset: str, columns: Iterable[str], measures: Iterable = (), *,
                          headers: dict[str, str] | None = None, formats: dict[str, str] | None = None,
                          filters: Iterable[str] = (), order: str = "desc", page_size: int = 25, width: str = "full",
                          source: TableSource | str | None = None, download: bool = True) -> "Report":
        """Interactive table recomputed with the filters; its Excel button downloads what it shows.

        Without measures it lists the filtered dataset rows (`columns` of the dataset): a custom
        extract. With measures, [(header, measure, format)], it groups by `columns` and adds one
        column per measure, sorted by the first measure (order="desc") or not ("none").
        `headers` renames dataset columns; `filters` adds in-table dropdowns (header names)."""
        columns = [str(column) for column in columns]
        measures = [tuple(item) for item in measures]
        self._check_measures(dataset, [item[1] for item in measures], columns)
        if any(measure.period != "current" or measure.change for _, measure, *_ in measures):
            raise ValueError("Dynamic tables show current-period measures only")
        if order not in {"desc", "none"} or width not in {"half", "full"} or page_size < 1:
            raise ValueError("Unsupported dynamic table options")
        if isinstance(source, str):
            source = TableSource(source, source.split(".")[0])
        table = DynamicTable(title, dataset, columns, measures, dict(headers or {}), dict(formats or {}), list(filters),
                             order, page_size, width, source, download)
        names = [table.header(column) for column in columns] + [item[0] for item in measures]
        if len(set(names)) != len(names):
            raise ValueError("Table column names must be unique")
        unknown = [name for name in table.filters if name not in names]
        if unknown:
            raise ValueError(f"Filter columns not in table: {', '.join(unknown)}")
        self._check_formats(table.formats, columns)
        for item in measures:
            if len(item) < 3 or item[2] not in FORMATS:
                raise ValueError(f"Measure {item[0]}: give a format ({', '.join(FORMATS)})")
        self.components.append(table)
        return self

    @staticmethod
    def _check_formats(formats: dict[str, str], columns: list[str]) -> dict[str, str]:
        unknown = [key for key in formats if key not in columns]
        bad = [value for value in formats.values() if value not in FORMATS]
        if unknown or bad:
            raise ValueError(f"Invalid formats: unknown columns {unknown}, unknown formats {bad}")
        return formats

    def _check_measures(self, dataset: str, measures: list, columns: Iterable[str] = ()) -> None:
        data = self.datasets.get(dataset)
        if data is None:
            raise ValueError(f"Unknown dataset: {dataset} (add_dataset first)")
        needed = list(columns) + [name for measure in measures for name in (measure.column, measure.denominator) if name]
        missing = [name for name in needed if name not in data.columns]
        if missing:
            raise ValueError(f"Columns not in dataset {dataset}: {', '.join(missing)}")

    def _filter_state(self) -> list:
        """Filter options from the datasets and the default state used for the first render."""
        state = []
        for item in self.filters:
            values = {row[dataset.columns.index(item.column)] for dataset in self.datasets.values()
                      if item.column in dataset.columns for row in dataset.rows}
            item.options = sorted((value for value in values if value is not None), key=lambda value: (str(type(value)), value))
            if item.kind == "range":
                low, high = item.default or (None, None)
                low = low if low in item.options else (item.options[0] if item.options else None)
                high = high if high in item.options else (item.options[-1] if item.options else None)
                state.append((low, high))
            else:
                state.append(item.default if item.default in item.options else "")
        return state

    def _filter_kind(self, column: str) -> str | None:
        return next((dataset.formats.get(column) for dataset in self.datasets.values() if column in dataset.columns), None)

    def _render_filters(self, state: list) -> str:
        if not self.filters:
            return ""
        text = LABELS[self.lang]
        parts = []
        for number, item in enumerate(self.filters):
            kind = self._filter_kind(item.column)
            show = lambda value: str(item.labels.get(value, category_label(value, kind, self.lang)))
            options = list(enumerate(item.options))
            if item.kind == "range":
                bounds = [item.options.index(value) if value in item.options else 0 for value in state[number]]
                for caption, default, everything in ((text["from"].format(label=item.label), bounds[0], 0),
                                                      (text["to"], bounds[1], max(len(options) - 1, 0))):
                    html_options = "".join(f'<option value="{i}"{" selected" if i == default else ""}>{escape(show(value))}</option>'
                                           for i, value in options)
                    parts.append(f'<label class="filter"><span>{escape(caption)}</span><select data-filter="{number}" '
                                 f'data-default="{default}" data-all="{everything}">{html_options}</select></label>')
            else:
                default = str(item.options.index(state[number])) if state[number] != "" else ""
                html_options = "".join(f'<option value="{i}"{" selected" if str(i) == default else ""}>{escape(show(value))}</option>'
                                       for i, value in options)
                parts.append(f'<label class="filter"><span>{escape(item.label)}</span><select data-filter="{number}" '
                             f'data-default="{default}" data-all=""><option value="">{escape(text["all"])}</option>'
                             f'{html_options}</select></label>')
        return (f'<section class="panel filters" aria-label="{escape(text["filters"], quote=True)}">'
                f'<h2>{escape(text["filters"])}<span class="active-count" aria-live="polite"></span></h2>'
                f'{"".join(parts)}<button type="button" class="button ghost reset">{escape(text["reset"])}</button></section>')

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
        for number, kpi in enumerate(self.dynamic_kpis):
            value = evaluate(self.datasets[kpi.dataset], self.filters, self._state, kpi.measure)
            sentiment = ""
            if kpi.format in {"change", "pp"} and value is not None:
                sentiment = " positive" if value > 0 else " negative" if value < 0 else " neutral"
            cards.append(
                f'<article class="kpi{sentiment}" data-dynamic-kpi="{number}"><span>{escape(kpi.label)}</span>'
                f'<div class="kpi-value"><strong>{escape(format_value(value, kpi.format, self.lang))}</strong>'
                f'<small>{escape(kpi.detail)}</small></div></article>'
            )
        return "".join(cards)

    def _static_chart(self, chart: DynamicChart, chart_id: str) -> Chart:
        """First render of a dynamic chart; DYNAMIC_JS redraws it when the filters change."""
        traces = chart_traces(chart, self.datasets[chart.dataset], self.filters, self._state, self.lang)
        static = Chart(chart.title, traces, chart.layout, chart.width, chart.height, download=chart.download)
        static.granularity = chart.x if isinstance(chart.x, dict) else None
        static.category = chart.x if isinstance(chart.x, str) else None
        self._dynamic_charts.append({"id": chart_id, "dataset": chart.dataset, "x": chart.x, "kind": chart.kind,
                                     "order": chart.order, "top": chart.top, "x_sort": chart.x_sort,
                                     "series": [[name, measure.to_json(), *rest] for name, measure, *rest in chart.series]})
        return static

    def _render_dynamic_table(self, table: DynamicTable, table_id: str, width_class: str) -> str:
        """Explorer table whose rows DYNAMIC_JS computes from the dataset on every filter change."""
        dataset = self.datasets[table.dataset]
        kinds = ([table.formats.get(column, dataset.formats.get(column)) for column in table.columns]
                 + [item[2] for item in table.measures])
        headers = [table.header(column) for column in table.columns] + [item[0] for item in table.measures]
        self._dynamic_tables.append({"id": table_id, "dataset": table.dataset, "title": table.title,
                                     "columns": table.columns, "headers": headers, "kinds": kinds,
                                     "measures": [measure.to_json() for _, measure, *_ in table.measures],
                                     "order": table.order, "pageSize": table.page_size})
        payload = {"title": table.title, "columns": headers, "kinds": kinds, "rows": [], "values": {},
                   "pageSize": table.page_size, "dynamic": True}
        return self._explorer_html(table.title, table_id, width_class, headers,
                                   {headers.index(name): [] for name in table.filters}, payload, table.source, table.download)

    def _render_components(self) -> tuple[str, list[dict[str, Any]]]:
        html_parts: list[str] = []
        charts: list[dict[str, Any]] = []
        for index, component in enumerate(self.components):
            width_class = "wide" if component.width == "full" else ""
            if isinstance(component, DynamicTable):
                html_parts.append(self._render_dynamic_table(component, f"table-{index}", width_class))
                continue
            if isinstance(component, DynamicChart):
                component = self._static_chart(component, f"chart-{index}")
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
                if getattr(component, "granularity", None):
                    label = LABELS[self.lang]["granularity"].format(title=component.title)
                    buttons = "".join(f'<button type="button" data-chart="{chart_id}" data-granularity="{escape(column, quote=True)}"'
                                      f'{" class=" + chr(34) + "active" + chr(34) if position == 0 else ""}>{escape(name)}</button>'
                                      for position, (name, column) in enumerate(component.granularity.items()))
                    controls = f'<div class="chart-controls" role="group" aria-label="{escape(label, quote=True)}">{buttons}</div>'
                download =self._download_button("download_chart", chart=chart_id) if component.download else ""
                chart_header = (
                    f'<div class="chart-header"><h2>{escape(component.title)}</h2>'
                    f'<div class="head-actions">{controls}{download}</div></div>'
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
                        "title": component.title,
                        "category": getattr(component, "category", None),
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

    def _download_button(self, label: str, **data: str) -> str:
        """Excel button; REPORT_JS builds the .xlsx in the browser from the data already in the page."""
        title = escape(LABELS[self.lang][label], quote=True)
        attributes = "".join(f' data-download-{key}="{escape(value, quote=True)}"' for key, value in data.items())
        return (f'<button type="button" class="button ghost download"{attributes} title="{title}" aria-label="{title}">'
                f'{EXCEL_ICON}{escape(LABELS[self.lang]["excel"])}</button>')

    def _render_explorer(self, table: Table, table_id: str, width_class: str) -> str:
        """Interactive in-page table; rows travel as JSON and are rendered by REPORT_JS."""
        text = LABELS[self.lang]
        data = table.payload(self.lang)
        rows = data["rows"]
        selects: dict[int, list[str]] = {}
        for name in table.filters:
            column = table.columns.index(name)
            raw = data["values"].get(str(column))
            if raw is None:
                ordered = sorted({row[column] for row in rows}, key=_sort_key)
            else:  # typed column: order by the real value, not by its text
                first = {}
                for row, value in zip(rows, raw):
                    first.setdefault(row[column], value)
                ordered = sorted(first, key=lambda shown: (not isinstance(first[shown], (int, float)),
                                                           first[shown] if isinstance(first[shown], (int, float)) else 0,
                                                           _sort_key(shown)))
            selects[column] = ordered
        return self._explorer_html(table.title, table_id, width_class, table.columns, selects, data, table.source,
                                   table.download)

    def _explorer_html(self, title: str, table_id: str, width_class: str, columns: list[str],
                       selects: dict[int, list[str]], data: dict, source: TableSource | None, download: bool) -> str:
        text = LABELS[self.lang]
        dropdowns = ""
        for column, ordered in selects.items():
            name = columns[column]
            options = "".join(f'<option value="{escape(value, quote=True)}">{escape(value)}</option>' for value in ordered)
            label = text["filter"].format(column=name)
            dropdowns += (f'<label class="filter"><span>{escape(name)}</span><select data-column="{column}" '
                          f'aria-label="{escape(label, quote=True)}"><option value="">{escape(text["all"])}</option>'
                          f'{options}</select></label>')
        selects = dropdowns
        headers = "".join(
            f'<th><button type="button" class="sort" data-column="{index}" '
            f'aria-label="{escape(text["sort"].format(column=column), quote=True)}">{escape(str(column))}</button></th>'
            for index, column in enumerate(columns))
        source = self._render_source(source) if source else ""
        payload = _json_for_script(data)
        download = self._download_button("download_filtered", table=table_id) if download else ""
        return (f'<article class="panel table-panel explorer {width_class}" id="{table_id}"><div class="table-head"><div>'
                f'<h2>{escape(title)}</h2><p class="table-count" aria-live="polite"></p></div>'
                f'<div class="head-actions">{download}</div></div>{source}'
                f'<div class="explorer-tools"><label class="filter search"><span>{escape(text["search"])}</span>'
                f'<input type="search"></label>{selects}</div>'
                f'<div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody></tbody></table></div>'
                f'<button type="button" class="button ghost more" hidden>{escape(text["more"])}</button>'
                f'<script type="application/json" class="explorer-data">{payload}</script></article>')

    def _render_table(self, table: Table, table_id: str, width_class: str) -> str:
        if table.filters is not None:
            return self._render_explorer(table, table_id, width_class)
        text = LABELS[self.lang]
        payload = table.payload(self.lang)
        rows = payload["rows"]
        headers = "".join(f"<th>{escape(str(column))}</th>" for column in table.columns)
        body = "".join("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>"
                       for row in rows[:PREVIEW_ROWS])
        total = len(rows)
        count = (text["preview"].format(shown=PREVIEW_ROWS, total=_grouped(total, 0, self.lang)) if total > PREVIEW_ROWS
                 else text["all_rows"].format(total=_grouped(total, 0, self.lang)))
        button = (f'<button type="button" class="button ghost" data-table="{table_id}">{escape(text["full"])} '
                  f'({_grouped(total, 0, self.lang)})</button>' if total > PREVIEW_ROWS else "")
        download = self._download_button("download_table", table=table_id) if table.download else ""
        source = self._render_source(table.source) if table.source else ""
        # The full rows travel as JSON: rendered when the dialog opens, exported by the Excel button.
        data = (f'<script type="application/json" class="table-data">{_json_for_script(payload)}</script>'
                if button or download else "")
        return (f'<article class="panel table-panel {width_class}" id="{table_id}"><div class="table-head"><div>'
                f'<h2>{escape(table.title)}</h2><p class="table-count">{escape(count)}</p></div>'
                f'<div class="head-actions">{button}{download}</div></div>{source}'
                f'<div class="table-scroll"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'
                f'{data}</article>')

    def render(self) -> str:
        text = LABELS[self.lang]
        self._state = self._filter_state()
        self._dynamic_charts: list[dict] = []
        self._dynamic_tables: list[dict] = []
        components_html, charts = self._render_components()
        filters = self._render_filters(self._state)
        dynamic = ""
        if self.filters or self.dynamic_kpis or self._dynamic_charts or self._dynamic_tables:
            dynamic = "window.REPORT_DYNAMIC=" + _json_for_script({
                "datasets": {name: {"columns": data.columns, "rows": data.rows, "formats": data.formats}
                             for name, data in self.datasets.items()},
                "filters": [{"column": item.column, "kind": item.kind, "compare": item.compare, "options": item.options}
                            for item in self.filters],
                "kpis": [{"dataset": kpi.dataset, "measure": kpi.measure.to_json(), "format": kpi.format}
                         for kpi in self.dynamic_kpis],
                "charts": self._dynamic_charts, "tables": self._dynamic_tables}) + ";"
        notes = "".join(f"<li>{escape(note)}</li>" for note in self.notes)
        notes_section = f'<section class="notes"><h2>{escape(text["notes"])}</h2><ul>{notes}</ul></section>' if notes else ""
        generated = datetime.now().astimezone().strftime("%d %b %Y, %H:%M %Z")
        chart_payload = _json_for_script(charts)
        kpi_style = f' style="grid-template-columns:repeat({self.kpi_columns},minmax(0,1fr))"' if self.kpi_columns else ""
        links = "".join(f'<a href="{escape(href, quote=True)}">{escape(label)}</a>' for label, href in self.links)
        nav = f'<nav class="report-nav">{links}</nav>' if links else ""
        subtitle = f'<p class="subtitle">{escape(self.subtitle)}</p>' if self.subtitle else ""
        kpis = f'<section class="kpis"{kpi_style}>{self._render_kpis()}</section>' if self.kpis or self.dynamic_kpis else ""
        labels = _json_for_script({key: text[key] for key in ("search", "close", "matches", "category", "value", "series",
                                                               "all", "active")}
                                  | {"report": self.title, "formats": FORMATS, "lang": self.lang, "months": MONTHS[self.lang]})
        return f"""<!doctype html>
<html lang="{self.lang}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(self.title)}</title><script src="plotly.min.js"></script>
<style>{REPORT_CSS}{DYNAMIC_CSS}</style></head><body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="/dashboard"><img src="assets/datasofi-white.png" alt="Datasofi" width="70" height="34"><span class="brand-divider" aria-hidden="true"></span><span class="brand-product">Sofibot <strong>Reports</strong></span></a>
<a class="back" href="/dashboard">← {escape(text["back"])}</a></div></header>
<main>
<header class="report-head"><h1>{escape(self.title)}</h1><p>{escape(self.description)}</p>{subtitle}{nav}</header>
{filters}{kpis}<section class="grid">{components_html}</section>{notes_section}
<footer>{escape(text["generated"].format(when=generated))}</footer></main>
<dialog class="table-dialog" id="table-dialog" aria-labelledby="table-dialog-title"><div class="dialog-head"><h2 id="table-dialog-title"></h2><button type="button" class="dialog-close" aria-label="{escape(text["close"], quote=True)}">×</button></div>
<div class="dialog-tools"><input type="search" placeholder="{escape(text["search"], quote=True)}" aria-label="{escape(text["search"], quote=True)}"><span class="table-count" aria-live="polite"></span></div>
<div class="table-scroll dialog-scroll"><table><thead></thead><tbody></tbody></table></div></dialog>
<script>const charts={chart_payload};const labels={labels};{dynamic}{FORMAT_JS}{REPORT_JS}{DYNAMIC_JS}{XLSX_JS}</script>
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
.head-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:flex-end}
.button.download{padding:6px 11px;font-size:13px;gap:6px}
.button.download svg{width:16px;height:16px;flex:none;color:var(--teal)}
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
  Plotly.react(chart.id,chart.views[button.dataset.view],layout,config);chart.view=button.dataset.view;
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
// Rows are {text, i}: the display text and the row index into data.values (real values of typed columns).
const realValue=(data,item,c)=>data.values[c]?data.values[c][item.i]:(item.text[c]===''?null:item.text[c]);
document.querySelectorAll('.explorer').forEach(panel=>{
  let data=JSON.parse(panel.querySelector('.explorer-data').textContent);
  let items=data.rows.map((text,i)=>({text,i}));
  const search=panel.querySelector('input[type=search]'),selects=[...panel.querySelectorAll('select')];
  const body=panel.querySelector('tbody'),count=panel.querySelector('.table-count'),more=panel.querySelector('.more');
  const number=value=>{if(typeof value==='number')return value;if(value===null)return null;
    const n=Number(value.replace(/[,$%\\s]/g,''));return value.trim()!==''&&Number.isFinite(n)?n:null;};
  let sort=null,direction=1,limit=data.pageSize;
  function rows(){
    const query=search.value.trim().toLocaleLowerCase();
    const chosen=selects.filter(s=>s.value).map(s=>[Number(s.dataset.column),s.value]);
    const result=items.filter(({text})=>chosen.every(([c,v])=>text[c]===v)&&(!query||text.some(v=>v.toLocaleLowerCase().includes(query))));
    if(sort!==null)result.sort((a,b)=>{const p=realValue(data,a,sort),q=realValue(data,b,sort);
      if(p===null||q===null)return (p===null)-(q===null);  // empty cells last in both directions
      const x=number(p),y=number(q);
      return direction*(x!==null&&y!==null?x-y:x!==null?-1:y!==null?1:String(p).localeCompare(String(q),undefined,{numeric:true}));});
    return result;
  }
  function render(){
    const matched=rows(),shown=matched.slice(0,limit);
    body.replaceChildren(...shown.map(({text})=>{const tr=document.createElement('tr');
      tr.append(...text.map(value=>{const td=document.createElement('td');td.textContent=value;return td;}));return tr;}));
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
  panel.exportRows=rows;  // the Excel button exports every matching row (not only the page shown), in this order
  panel.tableData=()=>data;
  // Tables fed by the report filters (DYNAMIC_JS) get new rows here; their dropdowns follow the rows.
  panel.setData=next=>{
    data=next;items=data.rows.map((text,i)=>({text,i}));
    selects.forEach(s=>{
      const c=Number(s.dataset.column),keep=s.value,first=new Map();
      items.forEach(item=>{if(item.text[c]!==''&&!first.has(item.text[c]))first.set(item.text[c],realValue(data,item,c));});
      const shown=[...first.keys()].sort((a,b)=>compareValues(first.get(a),first.get(b)));
      s.replaceChildren(new Option(labels.all,''),...shown.map(text=>new Option(text,text)));
      s.value=first.has(keep)?keep:'';
    });
    limit=data.pageSize;render();
  };
  render();
});
document.querySelectorAll('[data-download-table]').forEach(button=>button.addEventListener('click',()=>{
  const panel=document.getElementById(button.dataset.downloadTable);
  const data=panel.tableData?panel.tableData():JSON.parse(panel.querySelector('.table-data').textContent);
  const items=panel.exportRows?panel.exportRows():data.rows.map((text,i)=>({text,i}));
  downloadXlsx(data.title,data.columns,data.kinds,items.map(item=>data.columns.map((_,c)=>realValue(data,item,c))));
}));
document.querySelectorAll('[data-download-chart]').forEach(button=>button.addEventListener('click',()=>{
  const chart=charts.find(item=>item.id===button.dataset.downloadChart);if(!chart)return;
  const plotted=document.getElementById(chart.id)?.data;  // what is drawn now: view, granularity, report filters
  const traces=plotted&&plotted.length?plotted:chart.view?chart.views[chart.view]:chart.traces;
  const series=traces.filter(t=>t.visible!==false).map((t,index)=>{
    const pie=t.type==='pie',flip=t.orientation==='h',values=(pie?t.values:flip?t.x:t.y)||[];
    const categories=(pie?t.labels:flip?t.y:t.x)||values.map((_,i)=>i+1);
    return {name:String(t.name||(traces.length>1?labels.series+' '+(index+1):labels.value)),categories,values};
  });
  const plain=v=>v===undefined||v===null||(typeof v==='number'&&!Number.isFinite(v))?null:v;
  const same=series.every(s=>JSON.stringify(s.categories)===JSON.stringify(series[0].categories));
  const title=chart.title+(chart.view?' ('+chart.view+')':'');
  if(series.length&&same){
    downloadXlsx(title,[chart.category||labels.category,...series.map(s=>s.name)],[null,...series.map(()=> 'number')],
      series[0].categories.map((c,i)=>[plain(c),...series.map(s=>plain(s.values[i]))]));
  }else{
    downloadXlsx(title,[labels.series,labels.category,labels.value],[null,null,'number'],
      series.flatMap(s=>s.categories.map((c,i)=>[s.name,plain(c),plain(s.values[i])])));
  }
}));"""

# Formatting in the browser, the same as sofibot_eqz.formatting (display_value, excel_value) and
# dynamic.format_value. Function declarations: available to every script block of the page.
FORMAT_JS = r"""
function grouped(n,d){const es=labels.lang==='es',s=Math.abs(n).toFixed(d),[i,f]=s.split('.');
  return (n<0?'-':'')+i.replace(/\B(?=(\d{3})+(?!\d))/g,es?'.':',')+(f?(es?',':'.')+f:'');}
function isoParts(v){const m=/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(v);
  return m?{y:+m[1],mo:+m[2],d:+m[3],h:m[4]?+m[4]:null,mi:m[5]?+m[5]:0,s:m[6]?+m[6]:0}:null;}
const DATE_KINDS=['date','datetime','month'];
function formatCell(v,kind){
  if(v===null||v===undefined)return '';
  if(typeof v==='boolean'||kind==='text')return String(v);
  if(typeof v==='string'){
    const p=DATE_KINDS.includes(kind)?isoParts(v):null;if(!p)return v;
    const two=n=>String(n).padStart(2,'0');
    if(kind==='month')return labels.months[p.mo-1]+' '+p.y;
    const day=two(p.d)+'/'+two(p.mo)+'/'+p.y;
    return p.h!==null&&kind!=='date'?day+' '+two(p.h)+':'+two(p.mi):day;
  }
  if(typeof v!=='number'||!Number.isFinite(v))return '';
  const es=labels.lang==='es';
  if(kind==='percent')return grouped(v*100,1)+(es?' %':'%');
  if(kind==='eur'||kind==='currency')return es?grouped(v,2)+' €':'€'+grouped(v,2);
  if(kind==='usd')return '$'+grouped(v,2);
  if(kind==='integer'||(!kind&&Number.isInteger(v)))return grouped(v,0);
  return grouped(v,2);
}
function formatKpi(v,kind){
  if(v===null||v===undefined||!Number.isFinite(v))return '—';
  const es=labels.lang==='es',pct=es?' %':'%',sign=v>0?'+':'';
  if(kind==='currency'||kind==='usd')return '$'+grouped(v,0);
  if(kind==='eur')return es?grouped(v,0)+' €':'€'+grouped(v,0);
  if(kind==='integer')return grouped(v,0);
  if(kind==='percent')return grouped(v*100,1)+pct;
  if(kind==='change')return sign+grouped(v*100,1)+pct;
  if(kind==='pp')return sign+grouped(v*100,2)+' pp';
  return grouped(v,2);
}
function categoryLabel(v,kind){return v===null||v===undefined?'':DATE_KINDS.includes(kind)?formatCell(v,kind):String(v);}
function toExcel(v,kind){
  if(v===null||v===undefined)return null;
  if(typeof v==='number')return Number.isFinite(v)?v:null;
  if(typeof v==='boolean')return String(v);
  const p=typeof v==='string'&&DATE_KINDS.includes(kind)?isoParts(v):null;
  if(p)return (Date.UTC(p.y,p.mo-1,p.d,p.h||0,p.mi,p.s)-Date.UTC(1899,11,30))/86400000;
  return v;
}
function compareValues(a,b){
  if(a===null||b===null)return (a===null)-(b===null);
  if(typeof a==='number'&&typeof b==='number')return a-b;
  return String(a).localeCompare(String(b),undefined,{numeric:true});
}
"""

# Minimal .xlsx writer: one worksheet with a bold blue header, autofilter, frozen first row and
# the number formats of excel.FORMATS, zipped without compression. No external library needed.
XLSX_JS = r"""
const crcTable=(()=>{const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;t[n]=c>>>0;}return t;})();
function crc32(bytes){let c=0xFFFFFFFF;for(let i=0;i<bytes.length;i++)c=crcTable[(c^bytes[i])&255]^(c>>>8);return (c^0xFFFFFFFF)>>>0;}
function zipStore(files){
  const encoder=new TextEncoder(),parts=[],central=[];let offset=0;
  for(const file of files){
    const name=encoder.encode(file.name),data=encoder.encode(file.text),crc=crc32(data);
    const local=new Uint8Array(30+name.length),l=new DataView(local.buffer);
    [[0,0x04034b50,4],[4,20,2],[6,0x0800,2],[12,0x21,2],[14,crc,4],[18,data.length,4],[22,data.length,4],[26,name.length,2]]
      .forEach(([at,value,size])=>size===4?l.setUint32(at,value,true):l.setUint16(at,value,true));
    local.set(name,30);
    const entry=new Uint8Array(46+name.length),e=new DataView(entry.buffer);
    [[0,0x02014b50,4],[4,20,2],[6,20,2],[8,0x0800,2],[14,0x21,2],[16,crc,4],[20,data.length,4],[24,data.length,4],[28,name.length,2],[42,offset,4]]
      .forEach(([at,value,size])=>size===4?e.setUint32(at,value,true):e.setUint16(at,value,true));
    entry.set(name,46);
    parts.push(local,data);central.push(entry);offset+=local.length+data.length;
  }
  const size=central.reduce((total,entry)=>total+entry.length,0),end=new Uint8Array(22),d=new DataView(end.buffer);
  d.setUint32(0,0x06054b50,true);d.setUint16(8,files.length,true);d.setUint16(10,files.length,true);
  d.setUint32(12,size,true);d.setUint32(16,offset,true);
  return new Blob([...parts,...central,end],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
}
function xlsxBlob(sheetName,columns,kinds,rows){
  const xml=value=>String(value).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g,'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const letter=index=>{let s='';for(let n=index+1;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
  const names=Object.keys(labels.formats),style=kind=>kind&&names.includes(kind)?names.indexOf(kind)+2:0;
  const cell=(value,ref,s)=>value===null||value===undefined||value===''?(s?`<c r="${ref}" s="${s}"/>`:'')
    :typeof value==='number'?`<c r="${ref}" s="${s}"><v>${value}</v></c>`
    :`<c r="${ref}" s="${s}" t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
  const lines=[`<row r="1">${columns.map((name,c)=>cell(String(name),letter(c)+1,1)).join('')}</row>`];
  rows.forEach((row,r)=>lines.push(`<row r="${r+2}">${row.map((value,c)=>cell(value,letter(c)+(r+2),style(kinds[c]))).join('')}</row>`));
  const widths=columns.map((name,c)=>Math.min(60,Math.max(10,String(name).length+6,
    ...rows.slice(0,500).map(row=>row[c]===null?0:typeof row[c]==='number'?String(Math.round(row[c])).length+6:String(row[c]).length+2))));
  const last=letter(Math.max(columns.length-1,0))+(rows.length+1);
  const ns='xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"',head='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
  const rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships',pkg='http://schemas.openxmlformats.org/package/2006/relationships';
  const sheet=head+`<worksheet ${ns}><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`
    +`<cols>${widths.map((w,c)=>`<col min="${c+1}" max="${c+1}" width="${w}" customWidth="1"/>`).join('')}</cols>`
    +`<sheetData>${lines.join('')}</sheetData><autoFilter ref="A1:${last}"/></worksheet>`;
  const formats=names.map((kind,i)=>`<numFmt numFmtId="${164+i}" formatCode="${xml(labels.formats[kind])}"/>`).join('');
  const xfs=names.map((kind,i)=>`<xf numFmtId="${164+i}" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>`).join('');
  const styles=head+`<styleSheet ${ns}><numFmts count="${names.length}">${formats}</numFmts>`
    +'<fonts count="2"><font><sz val="11"/><name val="Roboto"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Roboto"/></font></fonts>'
    +'<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    +'<fill><patternFill patternType="solid"><fgColor rgb="FF2C3968"/><bgColor indexed="64"/></patternFill></fill></fills>'
    +'<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    +'<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    +`<cellXfs count="${names.length+2}"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>`
    +`<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>${xfs}</cellXfs>`
    +'<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  const quoted="'"+sheetName.replace(/'/g,"''")+"'";
  const book=head+`<workbook ${ns} xmlns:r="${rel}"><sheets><sheet name="${xml(sheetName)}" sheetId="1" r:id="rId1"/></sheets>`
    +`<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">${xml(quoted)}!$A$1:$${last.replace(/(\d+)$/,'$$$1')}</definedName></definedNames></workbook>`;
  const main='application/vnd.openxmlformats-officedocument.spreadsheetml';
  return zipStore([
    {name:'[Content_Types].xml',text:head+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      +'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
      +`<Override PartName="/xl/workbook.xml" ContentType="${main}.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="${main}.worksheet+xml"/>`
      +`<Override PartName="/xl/styles.xml" ContentType="${main}.styles+xml"/></Types>`},
    {name:'_rels/.rels',text:head+`<Relationships xmlns="${pkg}"><Relationship Id="rId1" Type="${rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>`},
    {name:'xl/workbook.xml',text:book},
    {name:'xl/_rels/workbook.xml.rels',text:head+`<Relationships xmlns="${pkg}"><Relationship Id="rId1" Type="${rel}/worksheet" Target="worksheets/sheet1.xml"/>`
      +`<Relationship Id="rId2" Type="${rel}/styles" Target="styles.xml"/></Relationships>`},
    {name:'xl/worksheets/sheet1.xml',text:sheet},
    {name:'xl/styles.xml',text:styles},
  ]);
}
function downloadXlsx(title,columns,kinds,rows){
  const sheet=(title.replace(/[\[\]:*?\/\\]/g,'-').trim()||'Datos').slice(0,31);
  const file=(labels.report+' - '+title).replace(/[\\\/:*?"<>|\u0000-\u001F]/g,'-').replace(/\s+/g,' ').trim().slice(0,150)+'.xlsx';
  const link=document.createElement('a');link.href=URL.createObjectURL(xlsxBlob(sheet,columns,kinds,rows));link.download=file;
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),10000);
}"""

EXCEL_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/>'
              '<path d="M3 9h18M9 3v6M12 12v6M9 15l3 3 3-3"/></svg>')
