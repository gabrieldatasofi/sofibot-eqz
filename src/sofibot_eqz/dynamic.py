"""Report-level filters: KPIs, charts and tables recomputed in the browser from embedded aggregates.

A report embeds one or more datasets (already aggregated Gold rows, e.g. month x store)
and declares filters over their columns. Every dynamic KPI, chart and table reads a
dataset, applies the filters whose column it has, and aggregates with a Measure. The same
aggregation runs here in Python for the first render and in DYNAMIC_JS in the page.

Measures never average stored ratios: a ratio is sum(numerator) / sum(denominator).
Adapted from sofibot-project (web/sofibot_reports/dynamic.py).
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .formatting import display_value, grouped

KPI_FORMATS = {"currency", "eur", "usd", "integer", "number", "percent", "change", "pp"}
DATE_KINDS = {"date", "datetime", "month"}


@dataclass(frozen=True)
class Measure:
    kind: str                      # sum | ratio | distinct
    column: str
    denominator: str | None = None
    scale: float = 1.0
    period: str = "current"        # current | previous (the compare filter's value minus one)
    change: bool = False           # current vs previous: relative for sum/distinct, difference for ratio

    def previous(self) -> "Measure":
        return replace(self, period="previous")

    def vs_previous(self) -> "Measure":
        return replace(self, change=True)

    def to_json(self) -> dict:
        return {"kind": self.kind, "column": self.column, "denominator": self.denominator, "scale": self.scale,
                "period": self.period, "change": self.change}


def Sum(column: str) -> Measure:
    return Measure("sum", column)


def Ratio(numerator: str, denominator: str, scale: float = 1.0) -> Measure:
    """sum(numerator) / sum(denominator) over the filtered rows; never an average of row ratios."""
    return Measure("ratio", numerator, denominator, scale)


def Distinct(column: str) -> Measure:
    """Distinct non-empty values (e.g. stores with sales); empty values are not counted."""
    return Measure("distinct", column)


def plain(value: Any) -> Any:
    """Dataset cells as JSON values: Decimal -> float, dates -> ISO text."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def parse_date(value: Any) -> Any:
    """ISO text back to date/datetime, for labels."""
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    except ValueError:
        return value


@dataclass
class Dataset:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    formats: dict[str, str] = field(default_factory=dict)


@dataclass
class Filter:
    label: str
    column: str
    kind: str = "select"           # select (one value or all) | range (from / to over ordered values)
    default: Any = None            # select: value; range: (from, to)
    compare: bool = False          # numeric select whose value - 1 is the "previous" period
    labels: dict = field(default_factory=dict)
    options: list = field(default_factory=list)


@dataclass
class DynamicKPI:
    label: str
    dataset: str
    measure: Measure
    format: str = "number"
    detail: str = ""


@dataclass
class DynamicChart:
    title: str
    dataset: str
    x: str | dict                  # column, or {button label: column} to switch granularity
    series: list                   # [(name, Measure) or (name, Measure, color)]
    kind: str = "line"             # line | bar | hbar
    order: str = "x"               # x (ascending) | desc (by the first series)
    top: int | None = None
    x_sort: str | None = None      # column that orders x (e.g. month number for month names)
    width: str = "half"
    height: int = 380
    layout: dict = field(default_factory=dict)
    download: bool = True


@dataclass
class DynamicTable:
    title: str
    dataset: str
    columns: list[str]             # dataset columns shown (the group when there are measures)
    measures: list                 # [(header, Measure, format)]; empty = filtered dataset rows
    headers: dict = field(default_factory=dict)
    formats: dict = field(default_factory=dict)
    filters: list[str] = field(default_factory=list)
    order: str = "desc"            # desc (by the first measure) | none (dataset order)
    page_size: int = 25
    width: str = "full"
    source: Any = None
    download: bool = True

    def header(self, column: str) -> str:
        return self.headers.get(column, column)


def _apply(rows, columns, filters, state, shift=0):
    index = {name: i for i, name in enumerate(columns)}
    kept = rows
    for number, item in enumerate(filters):
        if item.column not in index:
            continue
        position, value = index[item.column], state[number]
        if item.kind == "range":
            order = {option: i for i, option in enumerate(item.options)}
            low, high = order.get(value[0], 0), order.get(value[1], len(item.options) - 1)
            kept = [row for row in kept if row[position] in order and low <= order[row[position]] <= high]
        elif value not in (None, ""):
            target = value - shift if item.compare else value
            kept = [row for row in kept if row[position] == target]
    return kept


def _total(rows, columns, measure):
    index = {name: i for i, name in enumerate(columns)}
    if measure.kind == "distinct":
        return len({row[index[measure.column]] for row in rows if row[index[measure.column]] not in (None, "")})
    numbers = [row[index[measure.column]] for row in rows if row[index[measure.column]] is not None]
    numerator = sum(float(value) for value in numbers)
    if measure.kind == "sum":
        return numerator if numbers else None  # NULL means no data, not zero
    denominator = sum(float(row[index[measure.denominator]] or 0) for row in rows)
    return numerator / denominator * measure.scale if denominator else None


def evaluate(dataset, filters, state, measure, rows=None):
    """Value of a measure for the filtered rows (``rows`` restricts to one chart group)."""
    def value(shift):
        selected = _apply(dataset.rows if rows is None else rows, dataset.columns, filters, state, shift)
        return _total(selected, dataset.columns, measure)

    compare = any(item.compare and item.column in dataset.columns and state[i] not in (None, "")
                  for i, item in enumerate(filters))
    if measure.period == "previous" or measure.change:
        if not compare:
            return None
        previous = value(1)
        if not measure.change:
            return previous
        current = value(0)
        if current is None or previous is None:
            return None
        return current - previous if measure.kind == "ratio" else (current / previous - 1 if previous else None)
    return value(0)


def chart_traces(chart, dataset, filters, state, lang):
    """Initial Plotly traces for a dynamic chart (the browser recomputes them on every filter change)."""
    x = chart.x if isinstance(chart.x, str) else next(iter(chart.x.values()))
    index = {name: i for i, name in enumerate(dataset.columns)}
    groups, order = {}, {}
    for row in dataset.rows:
        groups.setdefault(row[index[x]], []).append(row)
        if chart.x_sort:
            order[row[index[x]]] = row[index[chart.x_sort]]
    values = {key: [evaluate(dataset, filters, state, measure, rows) for _, measure, *_ in chart.series]
              for key, rows in groups.items()}
    keys = [key for key in groups if any(value is not None for value in values[key])]
    if chart.order == "desc":
        keys.sort(key=lambda key: values[key][0] if values[key][0] is not None else float("-inf"), reverse=True)
    else:
        keys.sort(key=lambda key: (order.get(key, key) is None, order.get(key, key)))
    if chart.top:
        keys = keys[:chart.top]
    kind = dataset.formats.get(x)
    traces = []
    for position, (name, _measure, *rest) in enumerate(chart.series):
        color = rest[0] if rest else None
        ys = [values[key][position] for key in keys]
        labels = [label(key, kind, lang) for key in keys]
        trace = ({"x": ys[::-1], "y": labels[::-1], "type": "bar", "orientation": "h"} if chart.kind == "hbar" else
                 {"x": labels, "y": ys, "type": "bar"} if chart.kind == "bar" else
                 {"x": labels, "y": ys, "type": "scatter", "mode": "lines+markers"})
        trace["name"] = name
        if color:
            trace["marker" if chart.kind != "line" else "line"] = {"color": color}
        traces.append(trace)
    return traces


def label(value: Any, kind: str | None, lang: str) -> str:
    """Text for a category (filter option, chart axis): dates formatted, everything else as is."""
    if value is None:
        return ""
    if kind in DATE_KINDS:
        return display_value(parse_date(value), kind, lang)
    return str(value)


def format_value(value, kind, lang):
    if value is None:
        return "—"
    if kind in ("currency", "usd"):
        return "$" + grouped(value, 0, lang)
    if kind == "eur":
        return grouped(value, 0, lang) + " €" if lang == "es" else "€" + grouped(value, 0, lang)
    if kind == "integer":
        return grouped(value, 0, lang)
    if kind == "percent":
        return grouped(value * 100, 1, lang) + (" %" if lang == "es" else "%")
    if kind == "change":
        return ("+" if value > 0 else "") + grouped(value * 100, 1, lang) + (" %" if lang == "es" else "%")
    if kind == "pp":
        return ("+" if value > 0 else "") + grouped(value * 100, 2, lang) + " pp"
    return grouped(value, 2, lang)


DYNAMIC_CSS = """
.filters{position:sticky;top:64px;z-index:15;display:flex;flex-wrap:wrap;gap:12px 16px;align-items:flex-end;padding:14px 18px;margin-bottom:18px}
.filters h2{flex-basis:100%;margin:0;font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}
.filters .reset{margin-left:auto}
.filters .active-count{font-weight:500;color:var(--orange);text-transform:none;letter-spacing:0;margin-left:6px}
@media(max-width:800px){.filters{position:static}}
"""

# Runs after REPORT_JS (explorer tables expose panel.setData) and before XLSX_JS.
DYNAMIC_JS = r"""
(() => {
  const spec = window.REPORT_DYNAMIC; if (!spec) return;
  const controls = [...document.querySelectorAll('[data-filter]')];
  const state = () => spec.filters.map((f, i) => {
    const own = controls.filter(c => +c.dataset.filter === i);
    if (f.kind === 'range') return [f.options[+own[0].value], f.options[+own[1].value]];
    const v = own[0].value; return v === '' ? '' : f.options[+v];
  });
  const apply = (ds, rows, values, shift) => {
    let kept = rows;
    spec.filters.forEach((f, i) => {
      const pos = ds.columns.indexOf(f.column); if (pos < 0) return;
      if (f.kind === 'range') {
        const order = new Map(f.options.map((o, k) => [o, k])), lo = order.get(values[i][0]), hi = order.get(values[i][1]);
        kept = kept.filter(r => { const k = order.get(r[pos]); return k !== undefined && k >= lo && k <= hi; });
      } else if (values[i] !== '') {
        const target = f.compare ? values[i] - shift : values[i];
        kept = kept.filter(r => r[pos] === target);
      }
    });
    return kept;
  };
  const total = (ds, rows, m) => {
    const col = ds.columns.indexOf(m.column);
    if (m.kind === 'distinct') return new Set(rows.map(r => r[col]).filter(v => v !== null && v !== '')).size;
    const nums = rows.map(r => r[col]).filter(v => v !== null), num = nums.reduce((s, v) => s + Number(v), 0);
    if (m.kind === 'sum') return nums.length ? num : null;
    const den = rows.reduce((s, r) => s + Number(r[ds.columns.indexOf(m.denominator)] || 0), 0);
    return den ? num / den * m.scale : null;
  };
  const evaluate = (ds, values, m, rows) => {
    const value = shift => total(ds, apply(ds, rows || ds.rows, values, shift), m);
    const compare = spec.filters.some((f, i) => f.compare && ds.columns.includes(f.column) && values[i] !== '');
    if (m.period === 'previous' || m.change) {
      if (!compare) return null;
      const prev = value(1); if (!m.change) return prev;
      const cur = value(0); if (cur === null || prev === null) return null;
      return m.kind === 'ratio' ? cur - prev : (prev ? cur / prev - 1 : null);
    }
    return value(0);
  };
  const granularity = {};
  const traces = (c, values) => {
    const ds = spec.datasets[c.dataset], x = granularity[c.id] || (typeof c.x === 'string' ? c.x : Object.values(c.x)[0]);
    const xi = ds.columns.indexOf(x), si = c.x_sort ? ds.columns.indexOf(c.x_sort) : -1, groups = new Map(), order = new Map();
    ds.rows.forEach(r => { if (!groups.has(r[xi])) groups.set(r[xi], []); groups.get(r[xi]).push(r); if (si >= 0) order.set(r[xi], r[si]); });
    const vals = new Map([...groups].map(([k, rows]) => [k, c.series.map(s => evaluate(ds, values, s[1], rows))]));
    let keys = [...groups.keys()].filter(k => vals.get(k).some(v => v !== null));
    if (c.order === 'desc') keys.sort((a, b) => (vals.get(b)[0] ?? -Infinity) - (vals.get(a)[0] ?? -Infinity));
    else keys.sort((a, b) => { const p = order.has(a) ? order.get(a) : a, q = order.has(b) ? order.get(b) : b; return p < q ? -1 : p > q ? 1 : 0; });
    if (c.top) keys = keys.slice(0, c.top);
    const kind = ds.formats[x];
    return c.series.map((s, n) => {
      const ys = keys.map(k => vals.get(k)[n]), names = keys.map(k => categoryLabel(k, kind));
      const t = c.kind === 'hbar' ? {x: ys.slice().reverse(), y: names.slice().reverse(), type: 'bar', orientation: 'h'}
        : c.kind === 'bar' ? {x: names, y: ys, type: 'bar'} : {x: names, y: ys, type: 'scatter', mode: 'lines+markers'};
      t.name = s[0]; if (s[2]) t[c.kind === 'line' ? 'line' : 'marker'] = {color: s[2]};
      return t;
    });
  };
  // Table data in the explorer format: display text plus real values (Excel-ready) of typed columns.
  const tableData = (t, values) => {
    const ds = spec.datasets[t.dataset], idx = t.columns.map(c => ds.columns.indexOf(c)), rows = apply(ds, ds.rows, values, 0);
    let out;
    if (!t.measures.length) out = rows.map(r => idx.map(i => r[i]));
    else {
      const groups = new Map();
      rows.forEach(r => { const key = JSON.stringify(idx.map(i => r[i])); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(r); });
      out = [...groups].map(([key, rs]) => [...JSON.parse(key), ...t.measures.map(m => total(ds, rs, m))]);
      if (t.order === 'desc') out.sort((a, b) => (b[idx.length] ?? -Infinity) - (a[idx.length] ?? -Infinity));
    }
    const typed = t.kinds.map((k, c) => k && k !== 'text' ? c : -1).filter(c => c >= 0);
    return {title: t.title, columns: t.headers, kinds: t.kinds, pageSize: t.pageSize, dynamic: true,
            rows: out.map(r => r.map((v, c) => formatCell(v, t.kinds[c]))),
            values: Object.fromEntries(typed.map(c => [String(c), out.map(r => toExcel(r[c], t.kinds[c]))]))};
  };
  const kpiCard = (k, v, card) => {
    card.querySelector('strong').textContent = formatKpi(v, k.format);
    if (k.format === 'change' || k.format === 'pp') card.className = 'kpi ' + (v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral');
  };
  const count = document.querySelector('.filters .active-count');
  const render = () => {
    const values = state();
    spec.kpis.forEach((k, i) => kpiCard(k, evaluate(spec.datasets[k.dataset], values, k.measure), document.querySelector(`[data-dynamic-kpi="${i}"]`)));
    spec.charts.forEach(c => {
      const chart = charts.find(item => item.id === c.id);
      Plotly.react(c.id, traces(c, values), chart.layout, {responsive: true, displaylogo: false});
    });
    spec.tables.forEach(t => document.getElementById(t.id).setData(tableData(t, values)));
    if (count) {
      const changed = controls.filter(c => c.value !== c.dataset.all).length;
      count.textContent = changed ? labels.active.replace('{count}', changed) : '';
    }
  };
  controls.forEach(c => c.addEventListener('change', render));
  document.querySelector('.filters .reset')?.addEventListener('click', () => {
    controls.forEach(c => { c.value = c.dataset.default; }); render();
  });
  document.querySelectorAll('[data-granularity]').forEach(button => button.addEventListener('click', () => {
    granularity[button.dataset.chart] = button.dataset.granularity;
    button.parentElement.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === button));
    render();
  }));
  render();
})();
"""
