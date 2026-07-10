"""Rich CLI output + Plotly HTML rendering."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .data import AssetInfo
from .indicators import IndicatorSpec, overlay_columns, subpane_specs
from .timeframes import RangeSpec

console = Console()


def _fmt_money(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}${x:,.2f}"


def _fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def _chg_style(x: float) -> str:
    if x > 0:
        return "bold green"
    if x < 0:
        return "bold red"
    return "bold"


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]alpp[/]  ·  Alpaca charts  ·  paper-friendly CLI",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def print_asset_confirm(asset: AssetInfo, role: str = "ticker") -> None:
    """Show semantic name confirmation for a resolved symbol."""
    title = "Primary" if role == "ticker" else "Comparison"
    body = Text()
    body.append(asset.symbol, style="bold white")
    body.append("  —  ", style="dim")
    body.append(asset.name, style="bold cyan")
    meta = (
        f"{asset.exchange or '—'}  ·  {asset.asset_class or '—'}  ·  "
        f"{'tradable' if asset.tradable else 'not tradable'}  ·  {asset.status or '—'}"
    )
    console.print(
        Panel(
            body,
            title=f"[bold]{title} confirmed[/]",
            subtitle=f"[dim]{meta}[/]",
            border_style="green" if role == "ticker" else "blue",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def _fmt_vol(x: float | None) -> str:
    if x is None:
        return "—"
    if x >= 1_000_000:
        return f"{x / 1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x / 1_000:.1f}K"
    return f"{x:,.0f}"


def _fmt_px(x: float | None) -> str:
    if x is None:
        return "—"
    return f"${x:,.2f}"


def _row_pct(label: str, val: float | None, table: Table) -> None:
    if val is None:
        table.add_row(label, "—")
    else:
        table.add_row(label, Text(_fmt_pct(val), style=_chg_style(val)))


def print_cli(
    asset: AssetInfo,
    rng: RangeSpec,
    stats: dict,
    indicators: list[IndicatorSpec],
    compare: AssetInfo | None,
    compare_stats: dict | None,
    rel: pd.DataFrame | None,
    context: dict | None = None,
    compare_context: dict | None = None,
) -> None:
    header = Table.grid(padding=(0, 1))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Symbol", f"[bold]{asset.symbol}[/]  [dim]{asset.name}[/]")
    header.add_row(
        "Meta",
        f"{asset.exchange}  ·  {asset.asset_class}  ·  "
        f"{'tradable' if asset.tradable else 'not tradable'}  ·  {asset.status}",
    )
    header.add_row("Window", f"{rng.label.upper()}  ·  {rng.bar}  ·  {rng.description}")
    header.add_row("Bars", f"{stats['bars']}   {stats['start']} → {stats['end']}")

    snap = (context or {}).get("snapshot") or {}
    trail = (context or {}).get("trailing") or {}

    # --- Session / quote ---
    session = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold dim",
        title="Session",
        title_style="bold",
        pad_edge=False,
        expand=True,
    )
    session.add_column("Metric")
    session.add_column("Value", justify="right")

    last = snap.get("last") if snap.get("last") is not None else stats.get("last")
    session.add_row("Last", _fmt_px(last))
    session.add_row("Prev close", _fmt_px(snap.get("prev_close")))
    if snap.get("day_pct") is not None:
        session.add_row(
            "Day chg",
            Text(
                f"{_fmt_pct(snap['day_pct'])}  ({_fmt_money(snap.get('day_change') or 0)})",
                style=_chg_style(snap["day_pct"]),
            ),
        )
    session.add_row(
        "Day range",
        f"{_fmt_px(snap.get('day_low'))} – {_fmt_px(snap.get('day_high'))}",
    )
    session.add_row("Day open", _fmt_px(snap.get("day_open")))
    session.add_row("Day VWAP", _fmt_px(snap.get("day_vwap")))
    session.add_row("Day volume", _fmt_vol(snap.get("day_volume")))
    if snap.get("bid") is not None or snap.get("ask") is not None:
        spread = snap.get("spread")
        spread_s = f"  spr {_fmt_px(spread)}" if spread is not None else ""
        session.add_row(
            "Bid / Ask",
            f"{_fmt_px(snap.get('bid'))} / {_fmt_px(snap.get('ask'))}{spread_s}",
        )

    # --- Window performance (selected TF) ---
    window = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold dim",
        title=f"Window ({rng.label.upper()})",
        title_style="bold",
        pad_edge=False,
        expand=True,
    )
    window.add_column("Metric")
    window.add_column("Value", justify="right")
    pct = stats["pct"]
    nom = stats["nominal"]
    window.add_row("Open→Last", f"{_fmt_px(stats.get('open'))} → {_fmt_px(stats.get('last'))}")
    window.add_row("Change %", Text(_fmt_pct(pct), style=_chg_style(pct)))
    window.add_row("Change $", Text(_fmt_money(nom), style=_chg_style(nom)))
    window.add_row("High / Low", f"{_fmt_px(stats['high'])} / {_fmt_px(stats['low'])}")
    if stats.get("volume_avg") is not None:
        window.add_row("Avg bar vol", _fmt_vol(stats["volume_avg"]))
    if indicators:
        window.add_row("Indicators", ", ".join(s.label() for s in indicators))

    # --- 52w / trailing ---
    profile = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold dim",
        title="Profile (≈52w)",
        title_style="bold",
        pad_edge=False,
        expand=True,
    )
    profile.add_column("Metric")
    profile.add_column("Value", justify="right")

    if trail.get("error"):
        profile.add_row("Status", f"[yellow]{trail['error'][:60]}[/]")
    else:
        hi, lo = trail.get("week52_high"), trail.get("week52_low")
        profile.add_row("52w high", _fmt_px(hi))
        profile.add_row("52w low", _fmt_px(lo))
        if trail.get("from_52w_high_pct") is not None:
            profile.add_row(
                "From 52w high",
                Text(
                    _fmt_pct(trail["from_52w_high_pct"]),
                    style=_chg_style(trail["from_52w_high_pct"]),
                ),
            )
        if trail.get("from_52w_low_pct") is not None:
            profile.add_row(
                "From 52w low",
                Text(
                    _fmt_pct(trail["from_52w_low_pct"]),
                    style=_chg_style(trail["from_52w_low_pct"]),
                ),
            )
        pos = trail.get("week52_range_pos_pct")
        if pos is not None:
            profile.add_row("Range position", f"{pos:.1f}%  [dim](0=low · 100=high)[/]")
        profile.add_row("Avg vol 20d", _fmt_vol(trail.get("avg_volume_20")))
        profile.add_row("Avg vol 50d", _fmt_vol(trail.get("avg_volume_50")))
        rvol = trail.get("relative_volume")
        if rvol is not None:
            profile.add_row("Rel volume", f"{rvol:.2f}×  vs 20d avg")
        if trail.get("atr14") is not None:
            profile.add_row("ATR(14)", _fmt_px(trail["atr14"]))
        _row_pct("1w return", trail.get("ret_1w_pct"), profile)
        _row_pct("1m return", trail.get("ret_1m_pct"), profile)
        _row_pct("3m return", trail.get("ret_3m_pct"), profile)
        _row_pct("6m return", trail.get("ret_6m_pct"), profile)
        _row_pct("1y return", trail.get("ret_1y_pct"), profile)

    console.print(Panel(header, border_style="cyan", box=box.ROUNDED, title="[bold]alpp[/]"))
    # side-by-side if wide enough; rich Columns
    from rich.columns import Columns

    console.print(Columns([session, window, profile], equal=True, expand=True))

    if compare and compare_stats:
        ct = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold dim",
            title=f"vs {compare.symbol}  ·  {compare.name}",
            title_style="bold blue",
        )
        ct.add_column("Field")
        ct.add_column(asset.symbol, justify="right")
        ct.add_column(compare.symbol, justify="right")

        cs = (compare_context or {}).get("snapshot") or {}
        ct_ = (compare_context or {}).get("trailing") or {}
        c_last = cs.get("last") if cs.get("last") is not None else compare_stats.get("last")

        ct.add_row("Last", _fmt_px(last), _fmt_px(c_last))
        ct.add_row(
            f"Window {rng.label.upper()} %",
            Text(_fmt_pct(stats["pct"]), style=_chg_style(stats["pct"])),
            Text(
                _fmt_pct(compare_stats["pct"]),
                style=_chg_style(compare_stats["pct"]),
            ),
        )
        if snap.get("day_pct") is not None or cs.get("day_pct") is not None:
            ct.add_row(
                "Day %",
                Text(
                    _fmt_pct(snap["day_pct"]) if snap.get("day_pct") is not None else "—",
                    style=_chg_style(snap["day_pct"]) if snap.get("day_pct") is not None else "",
                ),
                Text(
                    _fmt_pct(cs["day_pct"]) if cs.get("day_pct") is not None else "—",
                    style=_chg_style(cs["day_pct"]) if cs.get("day_pct") is not None else "",
                ),
            )
        ct.add_row(
            "52w high",
            _fmt_px(trail.get("week52_high")),
            _fmt_px(ct_.get("week52_high")),
        )
        ct.add_row(
            "52w low",
            _fmt_px(trail.get("week52_low")),
            _fmt_px(ct_.get("week52_low")),
        )
        for label, key in (
            ("1m %", "ret_1m_pct"),
            ("3m %", "ret_3m_pct"),
            ("1y %", "ret_1y_pct"),
        ):
            a_v, b_v = trail.get(key), ct_.get(key)
            ct.add_row(
                label,
                Text(_fmt_pct(a_v), style=_chg_style(a_v)) if a_v is not None else "—",
                Text(_fmt_pct(b_v), style=_chg_style(b_v)) if b_v is not None else "—",
            )
        if rel is not None and not rel.empty:
            spread = float(rel["primary_pct"].iloc[-1] - rel["compare_pct"].iloc[-1])
            ct.add_row(
                "Relative (window)",
                Text(_fmt_pct(spread), style=_chg_style(spread)),
                "—",
            )
        console.print(ct)


def _heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Return frame with HA open/high/low/close columns."""
    ha = df[["timestamp", "open", "high", "low", "close"]].copy()
    o = ha["open"].astype(float)
    h = ha["high"].astype(float)
    l = ha["low"].astype(float)
    c = ha["close"].astype(float)
    ha_close = (o + h + l + c) / 4.0
    ha_open = o.copy()
    ha_open.iloc[0] = (o.iloc[0] + c.iloc[0]) / 2.0
    for i in range(1, len(ha)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
    ha_high = pd.concat([h, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([l, ha_open, ha_close], axis=1).min(axis=1)
    out = ha.copy()
    out["open"] = ha_open
    out["high"] = ha_high
    out["low"] = ha_low
    out["close"] = ha_close
    return out


def _normalize_change_mode(mode: str) -> str:
    key = (mode or "both").strip().lower()
    if key in ("pct", "percent", "%"):
        return "pct"
    if key in ("nominal", "dollar", "$", "usd"):
        return "nominal"
    return "both"


def _window_change_customdata(df: pd.DataFrame, change_display: str) -> list[str]:
    """Per-bar window Δ labels for Plotly hover (rebased to first close)."""
    mode = _normalize_change_mode(change_display)
    if df.empty or "close" not in df.columns:
        return []
    first = float(df["close"].iloc[0])
    if first == 0:
        return [""] * len(df)
    lines: list[str] = []
    for close in df["close"].astype(float):
        pct = (close / first - 1.0) * 100.0
        nom = close - first
        parts: list[str] = []
        if mode in ("pct", "both"):
            parts.append(_fmt_pct(pct))
        if mode in ("nominal", "both"):
            parts.append(_fmt_money(nom))
        lines.append("  ".join(parts) if parts else "—")
    return lines


def _ohlc_hovertemplate(change_display: str) -> str:
    mode = _normalize_change_mode(change_display)
    delta_label = "Window Δ"
    if mode == "pct":
        delta_label = "Window Δ %"
    elif mode == "nominal":
        delta_label = "Window P/L"
    return (
        "%{x|%b %d, %Y %H:%M}<br>"
        "O %{open:,.2f}  H %{high:,.2f}  L %{low:,.2f}  C %{close:,.2f}<br>"
        f"{delta_label}: %{{customdata[0]}}"
        "<extra></extra>"
    )


def _price_hovertemplate(change_display: str) -> str:
    mode = _normalize_change_mode(change_display)
    delta_label = "Window Δ"
    if mode == "pct":
        delta_label = "Window Δ %"
    elif mode == "nominal":
        delta_label = "Window P/L"
    return (
        "%{x|%b %d, %Y %H:%M}<br>"
        "Price: %{y:,.2f}<br>"
        f"{delta_label}: %{{customdata[0]}}"
        "<extra></extra>"
    )


def _fib_levels(df: pd.DataFrame) -> list[tuple[float, str, str]]:
    """Classic retracement levels from window high/low (swing)."""
    hi = float(df["high"].astype(float).max())
    lo = float(df["low"].astype(float).min())
    span = hi - lo
    if span <= 0:
        return []
    # ratio, label, color
    ratios = [
        (0.0, "0% (low)", "#78909c"),
        (0.236, "23.6%", "#42a5f5"),
        (0.382, "38.2%", "#66bb6a"),
        (0.5, "50%", "#ffa726"),
        (0.618, "61.8%", "#ab47bc"),
        (0.786, "78.6%", "#26c6da"),
        (1.0, "100% (high)", "#ef5350"),
    ]
    return [(lo + span * r, lab, col) for r, lab, col in ratios]


def _add_price_trace(
    fig,
    go,
    df: pd.DataFrame,
    symbol: str,
    chart_style: str,
    *,
    change_display: str = "both",
) -> None:
    """Primary price pane by chart style."""
    style = (chart_style or "candle").lower()
    plot_df = df
    name = symbol
    hover_delta = _window_change_customdata(plot_df, change_display)
    customdata = [[line] for line in hover_delta]

    if style == "heikin":
        plot_df = _heikin_ashi(df)
        name = f"{symbol} HA"
        style = "candle"  # render as filled candles

    o = plot_df["open"]
    h = plot_df["high"]
    l = plot_df["low"]
    c = plot_df["close"]
    x = plot_df["timestamp"]

    if style in ("candle", "fib"):
        fig.add_trace(
            go.Candlestick(
                x=x,
                open=o,
                high=h,
                low=l,
                close=c,
                name=name,
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                increasing_fillcolor="#26a69a",
                decreasing_fillcolor="#ef5350",
                customdata=customdata,
                hovertemplate=_ohlc_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )
    elif style in ("hollow", "fib_hollow", "empty", "empty_candle"):
        fig.add_trace(
            go.Candlestick(
                x=x,
                open=o,
                high=h,
                low=l,
                close=c,
                name=name,
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                increasing_fillcolor="rgba(0,0,0,0)",
                decreasing_fillcolor="#ef5350",
                customdata=customdata,
                hovertemplate=_ohlc_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )
    elif style in ("bar", "ohlc"):
        fig.add_trace(
            go.Ohlc(
                x=x,
                open=o,
                high=h,
                low=l,
                close=c,
                name=name,
                increasing_line_color="#26a69a",
                decreasing_line_color="#ef5350",
                customdata=customdata,
                hovertemplate=_ohlc_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )
    elif style == "area":
        fig.add_trace(
            go.Scatter(
                x=x,
                y=c,
                mode="lines",
                name=name,
                line=dict(color="#42a5f5", width=1.6),
                fill="tozeroy",
                fillcolor="rgba(66,165,245,0.15)",
                customdata=customdata,
                hovertemplate=_price_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )
    elif style in ("markers", "line_markers"):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=c,
                mode="lines+markers",
                name=name,
                line=dict(color="#42a5f5", width=1.5),
                marker=dict(size=4, color="#90caf9"),
                customdata=customdata,
                hovertemplate=_price_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )
    else:  # line
        fig.add_trace(
            go.Scatter(
                x=x,
                y=c,
                mode="lines",
                name=name,
                line=dict(color="#42a5f5", width=1.8),
                customdata=customdata,
                hovertemplate=_price_hovertemplate(change_display),
            ),
            row=1,
            col=1,
        )

    if style in ("fib", "fib_hollow"):
        for price, lab, col in _fib_levels(df):
            fig.add_hline(
                y=price,
                line_dash="dot",
                line_color=col,
                line_width=1,
                annotation_text=lab,
                annotation_position="right",
                annotation_font_size=10,
                annotation_font_color=col,
                row=1,
                col=1,
            )


def format_change_label(
    stats: dict,
    mode: str = "both",
    *,
    compare_stats: dict | None = None,
    compare_symbol: str | None = None,
) -> str:
    """Build window change text: pct | nominal | both."""
    mode = (mode or "both").lower()
    chg = stats.get("pct")
    nom = stats.get("nominal")
    parts: list[str] = []
    if mode in ("pct", "percent", "%", "both"):
        if chg is not None:
            parts.append(_fmt_pct(float(chg)))
    if mode in ("nominal", "dollar", "$", "both"):
        if nom is not None:
            parts.append(_fmt_money(float(nom)))
    label = "  ".join(parts) if parts else ""
    if compare_stats and compare_symbol and mode in ("pct", "percent", "%", "both"):
        cp = compare_stats.get("pct")
        if cp is not None:
            label = f"{label} · vs {compare_symbol} {_fmt_pct(float(cp))}".strip(" ·")
    elif compare_stats and compare_symbol and mode in ("nominal", "dollar", "$"):
        cn = compare_stats.get("nominal")
        if cn is not None:
            label = f"{label} · vs {compare_symbol} {_fmt_money(float(cn))}".strip(" ·")
    return label


def write_html(
    path: Path,
    asset: AssetInfo,
    rng: RangeSpec,
    df: pd.DataFrame,
    stats: dict,
    indicators: list[IndicatorSpec],
    compare: AssetInfo | None,
    compare_df: pd.DataFrame | None,
    rel: pd.DataFrame | None,
    compare_stats: dict | None,
    chart_style: str = "candle",
    change_display: str = "both",
) -> Path:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        raise SystemExit("plotly is required for --html. pip install plotly") from exc

    symbol = asset.symbol
    style = (chart_style or "candle").lower()
    style_label = style.replace("_", " ")
    subs = subpane_specs(indicators)
    rows = 1 + len(subs)
    has_rel = compare is not None and rel is not None and not rel.empty
    if has_rel:
        rows += 1

    row_heights = [0.55] + [0.45 / max(rows - 1, 1)] * (rows - 1)
    titles = [f"{symbol} · {asset.name} · {style_label}"]
    for s in subs:
        titles.append(s.label())
    if has_rel and compare:
        titles.append(f"% rebased · {symbol} vs {compare.symbol}")

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=titles,
    )

    _add_price_trace(fig, go, df, symbol, style, change_display=change_display)

    colors = ["#42a5f5", "#ab47bc", "#ffa726", "#66bb6a", "#26c6da"]
    for i, col in enumerate(overlay_columns(indicators)):
        if col not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df[col],
                mode="lines",
                name=col.upper(),
                line=dict(width=1.4, color=colors[i % len(colors)]),
            ),
            row=1,
            col=1,
        )

    row = 2
    for spec in subs:
        p = spec.params
        if spec.name == "rsi":
            col = f"rsi_{p[0]}"
            if col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[col],
                        mode="lines",
                        name=col.upper(),
                        line=dict(color="#7e57c2", width=1.5),
                    ),
                    row=row,
                    col=1,
                )
                fig.add_hline(y=70, line_dash="dot", line_color="#888", row=row, col=1)
                fig.add_hline(y=30, line_dash="dot", line_color="#888", row=row, col=1)
        elif spec.name == "macd":
            fast, slow, signal = p
            tag = f"{fast}_{slow}_{signal}"
            mcol = "macd" if (fast, slow, signal) == (12, 26, 9) else f"macd_{tag}"
            scol = (
                "macd_signal"
                if (fast, slow, signal) == (12, 26, 9)
                else f"macd_signal_{tag}"
            )
            hcol = (
                "macd_hist"
                if (fast, slow, signal) == (12, 26, 9)
                else f"macd_hist_{tag}"
            )
            if mcol in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[mcol],
                        mode="lines",
                        name="MACD",
                        line=dict(color="#29b6f6", width=1.3),
                    ),
                    row=row,
                    col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[scol],
                        mode="lines",
                        name="Signal",
                        line=dict(color="#ff7043", width=1.2),
                    ),
                    row=row,
                    col=1,
                )
                fig.add_trace(
                    go.Bar(
                        x=df["timestamp"],
                        y=df[hcol],
                        name="Hist",
                        marker_color="#90a4ae",
                    ),
                    row=row,
                    col=1,
                )
        elif spec.name == "stoch":
            kcol, dcol = f"stoch_k_{p[0]}", f"stoch_d_{p[0]}"
            if kcol in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[kcol],
                        mode="lines",
                        name="%K",
                        line=dict(color="#42a5f5", width=1.3),
                    ),
                    row=row,
                    col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[dcol],
                        mode="lines",
                        name="%D",
                        line=dict(color="#ffa726", width=1.2),
                    ),
                    row=row,
                    col=1,
                )
                fig.add_hline(y=80, line_dash="dot", line_color="#888", row=row, col=1)
                fig.add_hline(y=20, line_dash="dot", line_color="#888", row=row, col=1)
        elif spec.name == "vol_sma":
            if "volume_plot" in df.columns:
                fig.add_trace(
                    go.Bar(
                        x=df["timestamp"],
                        y=df["volume_plot"],
                        name="Volume",
                        marker_color="#546e7a",
                    ),
                    row=row,
                    col=1,
                )
            vcol = f"vol_sma_{p[0]}"
            if vcol in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[vcol],
                        mode="lines",
                        name=vcol.upper(),
                        line=dict(color="#ffee58", width=1.3),
                    ),
                    row=row,
                    col=1,
                )
        else:
            # generic single-series subpane
            candidates = [
                f"{spec.name}_{'_'.join(str(x) for x in p)}" if p else spec.name,
                f"{spec.name}_{p[0]}" if p else spec.name,
                spec.name,
            ]
            col = next((c for c in candidates if c in df.columns), None)
            if col:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df[col],
                        mode="lines",
                        name=col.upper(),
                        line=dict(color="#26c6da", width=1.4),
                    ),
                    row=row,
                    col=1,
                )
        row += 1

    if has_rel and compare is not None:
        fig.add_trace(
            go.Scatter(
                x=rel["timestamp"],
                y=rel["primary_pct"],
                mode="lines",
                name=f"{symbol} %",
                line=dict(color="#26a69a", width=1.6),
            ),
            row=row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=rel["timestamp"],
                y=rel["compare_pct"],
                mode="lines",
                name=f"{compare.symbol} %",
                line=dict(color="#42a5f5", width=1.6),
            ),
            row=row,
            col=1,
        )
        fig.add_hline(y=0, line_dash="dot", line_color="#666", row=row, col=1)

    change_bit = format_change_label(
        stats,
        change_display,
        compare_stats=compare_stats,
        compare_symbol=compare.symbol if compare else None,
    )
    subtitle_parts = [
        p
        for p in (
            change_bit,
            f"last ${stats['last']:,.2f}",
            rng.bar,
            style_label,
        )
        if p
    ]
    subtitle = " · ".join(subtitle_parts)

    fig.update_layout(
        title=dict(
            text=f"{symbol} · {asset.name}<br><sup>{rng.label.upper()} · {subtitle}</sup>"
        ),
        template="plotly_dark",
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        height=280 + 220 * rows,
        margin=dict(l=50, r=30, t=90, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#333")
    fig.update_yaxes(showgrid=True, gridcolor="#333")

    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(path), include_plotlyjs="cdn", full_html=True)
    return path
