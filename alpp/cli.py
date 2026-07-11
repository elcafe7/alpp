"""alpp CLI — rich interface with ticker name confirmation + live symbol complete."""

from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import __version__
from .chart_picker import DEFAULT_CHART, normalize_chart, prompt_chart_style
from .charts import ChartInfo, default_chart_dirs, scan_chart_dirs
from .creds import (
    ensure_credentials,
    import_alpaca_profiles,
    login_interactive,
    logout_profile,
    print_status,
    set_default_profile,
)
from .data import (
    AssetInfo,
    fetch_bars,
    fetch_market_context,
    normalize_compare,
    period_stats,
    resolve_asset,
    set_active_credentials,
)
from .history import (
    HistoryRun,
    clear_history,
    history_path,
    last_indicators_for,
    list_runs,
    recent_tickers,
    record_run,
)
from .ind_picker import prompt_indicators
from .indicators import IndicatorSpec, apply_indicators, parse_indicators
from .render import console, print_asset_confirm, print_banner, print_cli, write_html
from .symbols import (
    SymbolIndex,
    catalog_status,
    ensure_catalog,
    make_command_completer,
    make_list_completer,
    prompt_ticker_live,
    symbols_path,
    update_symbols,
)
from .tf_picker import prompt_timeframe
from .timeframes import resolve_range

CHANGE_DISPLAY_CHOICES = ("pct", "nominal", "both")


@dataclass
class SessionSeed:
    """Prefill from history / saved chart when user picks a prior run."""

    symbol: str | None = None
    timeframe: str | None = None
    indicators: list[IndicatorSpec] = field(default_factory=list)
    compare: str | None = None
    chart_style: str | None = None
    change_display: str | None = None
    open_html: Path | None = None  # open only, skip fetch
    from_label: str = ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alpp",
        description=(
            "Alpaca chart CLI: TICKER + TIMEFRAME, optional indicators / comparison. "
            "Live ticker complete from Nasdaq lists; confirms semantic name. "
            "Remembers recent tickers/overlays; browse saved HTML charts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  alpp                              # interactive rich UI (ticker complete)
  alpp AAPL ytd
  alpp AAPL ytd --ind sma:20,rsi --vs SPY --html --open
  alpp history tickers
  alpp history charts
  alpp symbols update
  alpp auth login

timeframes (interactive): ↑↓/jk · 0-9 hotkeys · or type ytd/1d/…
compare / indicators / chart styles: prompts on TTY (or flags)

interactive: type a ticker (ajax) or type "history" for:
  history › tickers   prior sessions — re-run
  history › charts    saved HTML — existing (open) or regenerate (fresh data)
""",
    )
    p.add_argument("ticker", nargs="?", default=None, help="Symbol, e.g. AAPL")
    p.add_argument(
        "timeframe",
        nargs="?",
        default=None,
        help="Range preset (default: ytd)",
    )
    p.add_argument(
        "-i",
        "--ind",
        "--indicator",
        dest="indicator",
        default=None,
        help="Comma-separated indicators",
    )
    p.add_argument(
        "--vs",
        "--compare",
        dest="compare",
        default=None,
        help="Comparison symbol (%% rebased), e.g. SPY",
    )
    p.add_argument(
        "--html",
        nargs="?",
        const="AUTO",
        default=None,
        help="Write HTML chart (optional path; default ~/alpp/out/)",
    )
    p.add_argument(
        "--chart",
        default=None,
        help=(
            "HTML chart style: candle, hollow, bar, line, area, heikin, "
            "fib, fib_hollow, markers (prompts if --html and omitted on TTY)"
        ),
    )
    p.add_argument(
        "--change",
        dest="change_display",
        choices=["pct", "percent", "nominal", "dollar", "both", "$", "%"],
        default=None,
        help="HTML title change label: pct | nominal | both (prompts with --html on TTY)",
    )
    p.add_argument("--open", action="store_true", help="Open HTML in browser")
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip interactive ticker confirmation",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary table (still confirms unless -y)",
    )
    p.add_argument(
        "--refresh-symbols",
        action="store_true",
        help="Force-refresh symbol list before running",
    )
    p.add_argument(
        "-p",
        "--profile",
        default=None,
        help="Credential profile: paper, live, or custom name (default: saved default)",
    )
    p.add_argument("--version", action="version", version=f"alpp {__version__}")
    return p


def default_html_path(symbol: str, tf: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "alpp" / "out" / f"{symbol.upper()}_{tf}_{stamp}.html"


def _load_index(force_refresh: bool = False) -> SymbolIndex | None:
    """Load Nasdaq catalog; auto-fetch if missing/stale. Never hard-fails."""
    try:
        cat = ensure_catalog(max_age_hours=24 * 7, force=force_refresh)
        return SymbolIndex(cat)
    except Exception as exc:  # noqa: BLE001
        # FTP/network glitch — fall back to any on-disk cache
        cached = SymbolIndex.load()
        if cached is None:
            console.print(
                f"[yellow]Symbol list unavailable:[/] {exc}  "
                "[dim]· later: alpp symbols update[/]"
            )
        return cached

def _print_recent_section(
    runs: list[HistoryRun],
    *,
    limit: int = 8,
    show_back: bool = False,
) -> None:
    if not runs:
        console.print(
            "  [dim]history › tickers[/]  "
            "(empty — sessions are remembered after each chart)"
        )
        return
    tbl = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        padding=(0, 1),
        expand=False,
    )
    tbl.add_column("#", style="bold cyan", width=3)
    tbl.add_column("setup", style="bold")
    tbl.add_column("when", style="dim")
    for i, run in enumerate(runs[:limit], 1):
        when = run.ts.replace("T", " ").replace("Z", "") if run.ts else "—"
        if len(when) > 16:
            when = when[:16]
        tbl.add_row(str(i), run.label(), when)
    if show_back:
        tbl.add_row("0", "[dim]← back (Enter)[/]", "")
    console.print(
        Panel(
            tbl,
            title="[bold]history › tickers[/]",
            border_style="cyan",
            padding=(0, 1),
        )
    )


def _print_saved_charts_section(
    charts: list[ChartInfo],
    *,
    limit: int = 10,
    show_back: bool = False,
) -> None:
    if not charts:
        dirs = " · ".join(str(d) for d in default_chart_dirs()[:2])
        console.print(f"  [dim]history › charts[/]  (none in {dirs})")
        return
    tbl = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        padding=(0, 1),
        expand=False,
    )
    tbl.add_column("#", style="bold green", width=3)
    tbl.add_column("chart", style="bold")
    tbl.add_column("when", style="dim", width=12)
    tbl.add_column("file", style="dim", overflow="ellipsis", max_width=28)
    for i, ch in enumerate(charts[:limit], 1):
        tbl.add_row(str(i), ch.label(), ch.age_label(), ch.path.name)
    if show_back:
        tbl.add_row("0", "[dim]← back (Enter)[/]", "", "")
    console.print(
        Panel(
            tbl,
            title="[bold]history › charts[/]",
            border_style="green",
            padding=(0, 1),
        )
    )


def _seed_from_run(run: HistoryRun) -> SessionSeed:
    return SessionSeed(
        symbol=run.symbol,
        timeframe=run.timeframe,
        indicators=run.indicator_specs(),
        compare=run.compare,
        chart_style=run.chart_style,
        change_display=run.change_display,
        from_label=run.label(),
    )


def _seed_from_chart(ch: ChartInfo, *, open_only: bool = False) -> SessionSeed:
    if open_only:
        return SessionSeed(open_html=ch.path, from_label=ch.label())
    return SessionSeed(
        symbol=ch.symbol or None,
        timeframe=ch.timeframe,
        indicators=ch.indicator_specs(),
        compare=ch.compare,
        chart_style=ch.chart_style,
        change_display=ch.change_display,
        from_label=ch.label(),
    )


def _is_history_command(raw: str) -> bool:
    t = raw.strip().lower().replace("›", ">").replace(">", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t == "history" or t.startswith("history ")


def _history_route(raw: str) -> str | None:
    """Return 'tickers', 'charts', or None if only 'history'."""
    t = raw.strip().lower().replace("›", " ").replace(">", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("history tickers", "history ticker", "history sessions"):
        return "tickers"
    if t in ("history charts", "history chart", "history html"):
        return "charts"
    if t == "history":
        return None
    # "history › tickers" already normalized
    if "ticker" in t:
        return "tickers"
    if "chart" in t or "html" in t:
        return "charts"
    return None


def _prompt_ajax(
    message: str,
    completer,
    *,
    hint: str,
    default: str = "",
) -> str:
    return prompt_ticker_live(
        None,
        message=message,
        default=default,
        hint=hint,
        completer=completer,
    )


def _history_pick_tickers() -> SessionSeed | None:
    """
    Load previous ticker sessions immediately and pick one to re-run.
    No extra filter step — list is shown; user enters a number (default #1).
    """
    runs = list_runs(limit=40)
    if not runs:
        console.print(
            "  [dim]history › tickers[/]  empty — nothing recorded yet"
        )
        return None

    # Show full list right away (this is the load)
    console.print()
    _print_recent_section(runs, limit=40, show_back=True)
    console.print()

    while True:
        # default 0 → Enter means back
        raw = Prompt.ask(
            "[bold cyan]history › tickers[/]  re-run #",
            default="0",
        ).strip()
        if not raw or raw.lower() in ("0", "b", "back", "q", "esc"):
            return None
        m = re.match(r"#?\s*(\d+)", raw)
        if m:
            n = int(m.group(1))
            if n == 0:
                return None
            if 1 <= n <= len(runs):
                seed = _seed_from_run(runs[n - 1])
                console.print(f"  [dim]replay[/]  {seed.from_label}")
                return seed
            console.print(
                f"[yellow]No #{n} — type 1–{len(runs)}, or Enter back[/]"
            )
            continue
        # also accept exact symbol match → most recent run for that ticker
        want = raw.upper()
        for r in runs:
            if r.symbol == want or (r.compare and r.compare == want):
                seed = _seed_from_run(r)
                console.print(f"  [dim]replay[/]  {seed.from_label}")
                return seed
        console.print(
            f"[yellow]Type 1–{len(runs)} to re-run, or Enter/0 back[/]"
        )

def _history_pick_charts() -> SessionSeed | None:
    """
    Load saved HTML charts immediately and pick one by #.
    No extra filter step — then existing (open) vs regenerate (fresh data).
    """
    charts = scan_chart_dirs(limit=40)
    if not charts:
        console.print("  [dim]history › charts[/]  no HTML in out/")
        for d in default_chart_dirs()[:3]:
            console.print(f"    [dim]· {d}[/]")
        return None

    # Show full list right away (this is the load)
    console.print()
    _print_saved_charts_section(charts, limit=40, show_back=True)
    console.print()

    ch: ChartInfo | None = None
    while ch is None:
        # default 0 → Enter means back
        raw = Prompt.ask(
            "[bold cyan]history › charts[/]  pick #",
            default="0",
        ).strip()
        if not raw or raw.lower() in ("0", "b", "back", "q", "esc"):
            return None
        m = re.match(r"#?\s*(\d+)", raw)
        if m:
            n = int(m.group(1))
            if n == 0:
                return None
            if 1 <= n <= len(charts):
                ch = charts[n - 1]
                break
            console.print(
                f"[yellow]No #{n} — type 1–{len(charts)}, or Enter back[/]"
            )
            continue
        # symbol / label shortcut → first matching chart
        want = raw.upper()
        for c in charts:
            if c.symbol == want or want in c.label().upper():
                ch = c
                break
        if ch is None:
            console.print(
                f"[yellow]Type 1–{len(charts)} to pick, or Enter/0 back[/]"
            )

    assert ch is not None
    console.print(f"  [dim]chart[/]  {ch.label()}")
    console.print(f"  [dim]file[/]   {ch.path.name}")

    # existing (open HTML) vs regenerate (same params, fresh data)
    while True:
        raw = Prompt.ask(
            "[bold cyan]history › charts[/]  "
            "[1] existing  ·  [2] regenerate  ·  [0] back",
            default="0",
            show_choices=False,
        ).strip().lower()
        if not raw or raw in ("0", "b", "back", "q", "esc"):
            # re-show chart list
            return _history_pick_charts()
        if raw in ("1", "existing", "e", "open", "view"):
            seed = _seed_from_chart(ch, open_only=True)
            console.print(f"  [bold]open[/]  {seed.from_label}")
            return seed
        if raw in ("2", "regenerate", "r", "regen", "replay", "rerun"):
            seed = _seed_from_chart(ch, open_only=False)
            console.print(f"  [dim]regenerate[/]  {seed.from_label}")
            return seed
        console.print(
            "[yellow]Type [bold]1[/] existing, [bold]2[/] regenerate, "
            "or Enter/0 back[/]"
        )


def _run_history_command(raw: str) -> SessionSeed | None:
    """Dispatch history › tickers | history › charts (lazy load)."""
    route = _history_route(raw)
    if route is None:
        # typed bare "history" — pick route via ajax
        route_items = [
            ("history › tickers", "prior sessions · re-run overlays"),
            ("history › charts", "saved HTML · existing or regenerate"),
        ]
        raw2 = _prompt_ajax(
            "history",
            make_list_completer(route_items),
            hint="tickers · charts · tab",
        )
        if not raw2:
            return None
        route = _history_route(
            raw2 if raw2.lower().startswith("history") else f"history {raw2}"
        )
        if route is None:
            low = raw2.lower()
            if "ticker" in low:
                route = "tickers"
            elif "chart" in low or "html" in low:
                route = "charts"
    if route == "tickers":
        return _history_pick_tickers()
    if route == "charts":
        return _history_pick_charts()
    console.print("[yellow]history › tickers  or  history › charts[/]")
    return None


def _prompt_ticker(
    index: SymbolIndex | None,
    *,
    default: str = "",
) -> str | SessionSeed:
    """
    Simple rich ticker prompt (original UX) + optional history command.

    Type a symbol (ajax directory) or type "history" for:
      history › tickers | history › charts
    """
    completer = make_command_completer(index)
    while True:
        raw = prompt_ticker_live(
            index,
            message="Ticker",
            default=default,
            hint="type name or symbol · tab · or history",
            completer=completer,
        )
        if not raw and default:
            raw = default
        if not raw:
            console.print(
                "[yellow]Enter a symbol (e.g. AAPL) or type [bold]history[/][/]"
            )
            continue
        if _is_history_command(raw):
            seed = _run_history_command(raw)
            if seed is not None:
                return seed
            continue
        return raw.strip()

def _prompt_timeframe(default: str = "ytd") -> str:
    """Type, arrow-nav, or 0-9 hotkeys."""
    return prompt_timeframe(default=default, console=console)


def _normalize_change_display(raw: str | None) -> str:
    if not raw:
        return "both"
    key = raw.strip().lower()
    if key in ("pct", "percent", "%"):
        return "pct"
    if key in ("nominal", "dollar", "$", "usd"):
        return "nominal"
    if key in ("both", "all"):
        return "both"
    raise SystemExit(f"Unknown change display {raw!r}. Use: pct, nominal, both")


def _prompt_change_display(default: str = "both") -> str:
    """Ask how to show window performance on the HTML chart."""
    console.print(
        "[bold cyan]HTML change label[/]  "
        "[dim][1] percent ±%  ·  [2] nominal ±$  ·  [3] both[/]"
    )
    raw = Prompt.ask(
        "Show window change as",
        choices=["1", "2", "3", "pct", "percent", "%", "nominal", "dollar", "$", "both"],
        default="3" if default == "both" else ("1" if default == "pct" else "2"),
        show_choices=False,
    ).strip().lower()
    if raw in ("1", "pct", "percent", "%"):
        return "pct"
    if raw in ("2", "nominal", "dollar", "$"):
        return "nominal"
    return "both"


def confirm_asset(
    symbol: str,
    role: str = "ticker",
    auto_yes: bool = False,
    index: SymbolIndex | None = None,
) -> AssetInfo:
    # Local directory hint first (fast)
    local = index.get(symbol) if index else None
    if local:
        console.print(
            f"  [dim]list[/]  [bold]{local['symbol']}[/]  —  {local.get('name','')}  "
            f"[dim]({local.get('exchange','')}"
            f"{' · ETF' if local.get('etf') else ''})[/]"
        )

    with console.status(f"[cyan]Resolving {symbol.upper()} via Alpaca…[/]", spinner="dots"):
        asset = resolve_asset(symbol)
    print_asset_confirm(asset, role=role)

    if local and local.get("name") and local["name"] != asset.name:
        console.print(
            f"  [dim]note[/]  directory name differs from Alpaca: [cyan]{local['name']}[/]"
        )

    if auto_yes:
        return asset
    label = "Use this ticker?" if role == "ticker" else "Use this comparison?"
    if not Confirm.ask(label, default=True):
        raise SystemExit("Aborted.")
    return asset


def cmd_auth(argv: list[str]) -> int:
    """alpp auth login|status|logout|use"""
    print_banner()
    sub = argv[0] if argv else "status"
    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage: [bold]alpp auth login[/] | [bold]import-alpaca[/] | "
            "[bold]status[/] | [bold]logout[/] | [bold]use PROFILE[/]"
        )
        return 0

    if sub in ("import-alpaca", "import", "import_alpaca"):
        return import_alpaca_profiles(console=console)

    if sub == "login":
        profile = "paper"
        i = 1
        while i < len(argv):
            arg = argv[i]
            if arg in ("--paper",):
                profile = "paper"
            elif arg in ("--live",):
                profile = "live"
            elif arg in ("--profile", "-p") and i + 1 < len(argv):
                i += 1
                profile = argv[i]
            elif not arg.startswith("-"):
                profile = arg
            i += 1
        login_interactive(profile=profile, console=console)
        return 0

    if sub in ("status", "info", "show"):
        return print_status(console=console)

    if sub in ("logout", "clear", "remove"):
        profile = None
        if len(argv) > 1 and not argv[1].startswith("-"):
            profile = argv[1]
        logout_profile(profile, console=console)
        return 0

    if sub in ("use", "switch", "default"):
        if len(argv) < 2:
            raise SystemExit("Usage: alpp auth use paper|live|PROFILE")
        set_default_profile(argv[1], console=console)
        return 0

    console.print(f"[red]Unknown auth subcommand:[/] {sub}")
    console.print(
        "Use: alpp auth login | import-alpaca | status | logout | use PROFILE"
    )
    return 2


def cmd_symbols(argv: list[str]) -> int:
    """alpp symbols update|status"""
    print_banner()
    sub = argv[0] if argv else "status"
    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage: [bold]alpp symbols update[/] | [bold]alpp symbols status[/]"
        )
        return 0
    if sub == "update":
        with console.status(
            "[cyan]Downloading nasdaqlisted.txt + otherlisted.txt…[/]",
            spinner="dots",
        ):
            cat = update_symbols()
        _print_status_from_catalog(cat)
        console.print(f"[green]Updated[/] {symbols_path()}")
        return 0
    if sub in ("status", "info", "ls"):
        st = catalog_status()
        _print_status(st)
        return 0 if st["exists"] else 1
    console.print(f"[red]Unknown symbols subcommand:[/] {sub}")
    console.print("Use: alpp symbols update | alpp symbols status")
    return 2


def cmd_history(argv: list[str]) -> int:
    """alpp history [tickers|charts|clear|path] — History › tickers | HTML charts."""
    print_banner()
    sub = (argv[0] if argv else "").strip().lower()
    rest = argv[1:]

    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage:\n"
            "  [bold]alpp history[/]                 both sections (tickers + HTML)\n"
            "  [bold]alpp history tickers[/]         History › tickers\n"
            "  [bold]alpp history charts[/]          History › HTML charts\n"
            "  [bold]alpp history charts open N[/]\n"
            "  [bold]alpp history charts rerun N[/]\n"
            "  [bold]alpp history charts path[/]\n"
            "  [bold]alpp history clear[/]           wipe session history file\n"
            "  [bold]alpp history path[/]"
        )
        return 0

    if sub in ("path", "file") and not rest:
        console.print(str(history_path()))
        return 0

    if sub in ("clear", "reset", "wipe"):
        if not Confirm.ask("Clear ticker session history?", default=False):
            return 0
        clear_history()
        console.print("[green]History › tickers cleared[/]")
        return 0

    # Interactive history when bare `alpp history` on TTY
    if not sub:
        if sys.stdin.isatty():
            seed = _run_history_command("history")
            if seed is None:
                return 0
            return _run_seeded_session(seed, profile=None)
        sub = "tickers"

    # ── History › tickers ──────────────────────────────────────────
    if sub in ("tickers", "ticker", "sessions", "runs", "list", "ls", "show"):
        if sys.stdin.isatty() and sub in ("tickers", "ticker", "sessions", "runs"):
            seed = _history_pick_tickers()
            if seed is None:
                return 0
            return _run_seeded_session(seed, profile=None)
        runs = list_runs(limit=25)
        ticks = recent_tickers(limit=15)
        _print_recent_section(runs, limit=25)
        if ticks:
            console.print(
                f"  [dim]symbols[/]  {', '.join(f'[bold]{t}[/]' for t in ticks)}"
            )
        console.print(f"  [dim]file[/]     {history_path()}")
        return 0

    # ── History › charts ───────────────────────────────────────────
    if sub in ("charts", "chart", "html", "gallery", "out"):
        return _cmd_history_charts(rest)

    console.print(f"[red]Unknown history subcommand:[/] {sub}")
    console.print("Use: alpp history tickers | charts | clear | path")
    return 2


def _cmd_history_charts(argv: list[str]) -> int:
    """alpp history charts [list|open N|regenerate N|path]"""
    sub = (argv[0] if argv else "").strip().lower()
    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage: [bold]alpp history charts[/] | [bold]open N[/] | "
            "[bold]regenerate N[/] | [bold]path[/]"
        )
        return 0
    if sub in ("path", "dirs", "dir"):
        for d in default_chart_dirs():
            mark = "✓" if d.is_dir() else "·"
            n = len(list(d.glob("*.html"))) if d.is_dir() else 0
            console.print(f"  {mark} {d}  [dim]({n} html)[/]")
        return 0

    # Interactive: pick chart → existing | regenerate
    if not sub and sys.stdin.isatty():
        seed = _history_pick_charts()
        if seed is None:
            return 0
        return _run_seeded_session(seed, profile=None)

    charts = scan_chart_dirs(limit=40)

    if sub in ("open", "o", "view", "existing") or (
        sub.isdigit() and len(argv) == 1
    ):
        if sub.isdigit():
            n = int(sub)
        elif len(argv) >= 2 and argv[1].isdigit():
            n = int(argv[1])
        else:
            raise SystemExit("Usage: alpp history charts open N")
        if not charts or n < 1 or n > len(charts):
            raise SystemExit(f"No chart #{n} (have {len(charts)})")
        ch = charts[n - 1]
        console.print(f"  [bold]open[/]  {ch.label()}")
        console.print(f"  [dim]file[/]  {ch.path}")
        webbrowser.open(ch.path.resolve().as_uri())
        return 0

    if sub in ("regenerate", "regen", "rerun", "r", "replay"):
        if len(argv) < 2 or not argv[1].isdigit():
            raise SystemExit("Usage: alpp history charts regenerate N")
        n = int(argv[1])
        if not charts or n < 1 or n > len(charts):
            raise SystemExit(f"No chart #{n} (have {len(charts)})")
        seed = _seed_from_chart(charts[n - 1], open_only=False)
        console.print(f"  [dim]regenerate[/]  {seed.from_label}")
        return _run_seeded_session(seed, profile=None)

    if sub not in ("list", "ls", "show", ""):
        console.print(f"[red]Unknown charts subcommand:[/] {sub}")
        return 2

    _print_saved_charts_section(charts, limit=25)
    if charts:
        console.print(
            "  [dim]tip[/]  [bold]alpp history charts open 1[/]  ·  "
            "[bold]alpp history charts regenerate 1[/]"
        )
    return 0


def cmd_charts(argv: list[str]) -> int:
    """Alias: alpp charts → alpp history charts."""
    return cmd_history(["charts", *argv])


def _run_seeded_session(seed: SessionSeed, *, profile: str | None) -> int:
    """Continue into the normal chart pipeline with a SessionSeed prefill."""
    if seed.open_html is not None:
        webbrowser.open(seed.open_html.resolve().as_uri())
        return 0
    if not seed.symbol:
        console.print("[red]No ticker on that history entry[/]")
        return 1
    # regenerate path: write HTML with same style by default
    return run_chart_session(
        ticker=seed.symbol,
        timeframe=seed.timeframe,
        compare=seed.compare,
        indicator_raw=None,
        seed=seed,
        profile=profile,
        interactive=True,
        yes=False,
        quiet=False,
        html="AUTO",
        chart_arg=seed.chart_style,
        change_arg=seed.change_display,
        open_html=False,
        refresh_symbols=False,
        setup_auth=True,
    )


def _print_status(st: dict) -> None:
    if not st["exists"]:
        console.print(
            Panel(
                f"[yellow]No symbol cache[/]\npath: {st['path']}\n"
                "Run: [bold]alpp symbols update[/]",
                border_style="yellow",
            )
        )
        return
    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="dim")
    tbl.add_column()
    tbl.add_row("path", st["path"])
    tbl.add_row("updated_at", str(st["updated_at"]))
    age = st.get("age_hours")
    if age is not None:
        tbl.add_row("age", f"{age:.1f} hours")
    tbl.add_row("symbols", str(st["count"]))
    sources = st.get("sources") or {}
    for key, meta in sources.items():
        fct = (meta or {}).get("file_creation_time") or "—"
        raw = (meta or {}).get("raw_count", "—")
        tbl.add_row(key, f"file_time={fct}  raw_rows={raw}")
    console.print(Panel(tbl, title="[bold]Symbol directory[/]", border_style="cyan"))


def _print_status_from_catalog(cat: dict) -> None:
    _print_status(
        {
            "path": str(symbols_path()),
            "exists": True,
            "updated_at": cat.get("updated_at"),
            "count": cat.get("count"),
            "age_hours": 0.0,
            "sources": cat.get("sources"),
        }
    )


def run_chart_session(
    *,
    ticker: str,
    timeframe: str | None = None,
    compare: str | None = None,
    indicator_raw: str | None = None,
    seed: SessionSeed | None = None,
    profile: str | None = None,
    interactive: bool = False,
    yes: bool = False,
    quiet: bool = False,
    html: str | None = None,
    chart_arg: str | None = None,
    change_arg: str | None = None,
    open_html: bool = False,
    refresh_symbols: bool = False,
    setup_auth: bool = True,
    index: SymbolIndex | None = None,
) -> int:
    """Core chart pipeline (CLI args or history seed)."""
    seed = seed or SessionSeed()

    if setup_auth:
        creds = ensure_credentials(profile=profile, console=console)
        set_active_credentials(creds)
        if creds.backend != "environment":
            mode = "paper" if creds.paper else "live"
            console.print(
                f"  [dim]auth[/]  {creds.profile} ({mode})  "
                f"[dim]· {creds.backend}[/]"
            )

    if index is None:
        if interactive or refresh_symbols:
            with console.status(
                "[cyan]Loading symbol directory…[/]", spinner="dots"
            ):
                index = _load_index(force_refresh=refresh_symbols)
        else:
            index = SymbolIndex.load()

    if index and setup_auth:
        age = ""
        st = catalog_status()
        if st.get("updated_at"):
            age = f"  ·  updated {st['updated_at']}"
        console.print(f"  [dim]directory[/]  {index.count:,} symbols{age}")

    asset = confirm_asset(ticker, role="ticker", auto_yes=yes, index=index)

    compare_asset: AssetInfo | None = None
    compare_raw = compare or seed.compare
    if interactive and not compare and sys.stdin.isatty():
        console.print()
        default_vs = bool(seed.compare)
        prompt = "Compare vs another ticker?" + (
            f" [last: {seed.compare}]" if seed.compare else ""
        )
        if Confirm.ask(prompt, default=default_vs):
            if seed.compare and Confirm.ask(f"Use {seed.compare}?", default=True):
                compare_raw = seed.compare
            else:
                compare_raw = prompt_ticker_live(index, message="Compare vs") or None
                if compare_raw == "":
                    compare_raw = None
        else:
            compare_raw = None
    if compare_raw:
        compare_asset = confirm_asset(
            compare_raw, role="compare", auto_yes=yes, index=index
        )
        if compare_asset.symbol == asset.symbol:
            raise SystemExit("Comparison symbol must differ from ticker")
        console.print(
            f"  [dim]compare[/]  [bold]{compare_asset.symbol}[/]  —  {compare_asset.name}"
        )

    tf_raw = timeframe or seed.timeframe
    if not tf_raw:
        tf_raw = _prompt_timeframe("ytd") if sys.stdin.isatty() else "ytd"
    elif timeframe is None and seed.timeframe and interactive and sys.stdin.isatty():
        tf_raw = _prompt_timeframe(seed.timeframe)
    elif timeframe is None and seed.timeframe:
        tf_raw = seed.timeframe

    rng = resolve_range(tf_raw)
    console.print(
        f"  [dim]range[/]  [bold]{rng.label.upper()}[/]  →  {rng.bar}  ({rng.description})"
    )

    if indicator_raw is not None:
        indicators = parse_indicators(indicator_raw)
    elif seed.indicators and not interactive:
        indicators = list(seed.indicators)
    elif interactive and sys.stdin.isatty():
        console.print()
        prior = list(seed.indicators) if seed.indicators else []
        if not prior:
            prior_keys = last_indicators_for(asset.symbol)
            if prior_keys:
                try:
                    prior = parse_indicators(",".join(prior_keys))
                except SystemExit:
                    prior = []
        prior_label = ", ".join(s.label() for s in prior) if prior else ""
        ask = "Overlay indicators?"
        if prior_label:
            ask = f"Overlay indicators? [last: {prior_label}]"
        if Confirm.ask(ask, default=bool(prior)):
            indicators = prompt_indicators(existing=prior or None, console=console)
            if indicators:
                console.print(
                    f"  [dim]inds[/]  {', '.join(s.label() for s in indicators)}"
                )
            else:
                console.print("  [dim]inds[/]  (none)")
        else:
            indicators = []
            console.print("  [dim]inds[/]  (price only)")
    elif seed.indicators:
        indicators = list(seed.indicators)
        console.print(
            f"  [dim]inds[/]  {', '.join(s.label() for s in indicators)}"
        )
    else:
        indicators = []

    with console.status(
        f"[cyan]Fetching {asset.symbol} bars + profile…[/]", spinner="dots"
    ):
        df = fetch_bars(asset.symbol, rng)
        df = apply_indicators(df, indicators)
        stats = period_stats(df)
        context = fetch_market_context(asset.symbol)

    compare_df = None
    compare_stats = None
    compare_context = None
    rel = None
    if compare_asset:
        with console.status(
            f"[cyan]Fetching {compare_asset.symbol} bars + profile…[/]",
            spinner="dots",
        ):
            compare_df = fetch_bars(compare_asset.symbol, rng)
            compare_stats = period_stats(compare_df)
            rel = normalize_compare(df, compare_df)
            compare_context = fetch_market_context(compare_asset.symbol)

    if not quiet:
        print_cli(
            asset,
            rng,
            stats,
            indicators,
            compare_asset,
            compare_stats,
            rel,
            context=context,
            compare_context=compare_context,
        )

    html_opt = html
    if interactive and html_opt is None and sys.stdin.isatty():
        if Confirm.ask("Write HTML chart?", default=False):
            html_opt = "AUTO"

    chart_style = DEFAULT_CHART
    change_display = "both"
    written: Path | None = None
    if html_opt is not None:
        if chart_arg:
            chart_style = normalize_chart(chart_arg)
        elif seed.chart_style and (yes or not sys.stdin.isatty()):
            chart_style = normalize_chart(seed.chart_style)
        elif sys.stdin.isatty() and not yes:
            console.print()
            default_style = seed.chart_style or DEFAULT_CHART
            chart_style = prompt_chart_style(default_style, console=console)
            console.print(f"  [dim]chart[/]  [bold]{chart_style}[/]")
        elif chart_arg is None and yes:
            chart_style = (
                normalize_chart(seed.chart_style)
                if seed.chart_style
                else DEFAULT_CHART
            )

        if change_arg:
            change_display = _normalize_change_display(change_arg)
        elif seed.change_display and (yes or not sys.stdin.isatty()):
            change_display = _normalize_change_display(seed.change_display)
        elif sys.stdin.isatty() and not yes:
            console.print()
            change_display = _prompt_change_display(seed.change_display or "both")
            console.print(f"  [dim]change[/]  [bold]{change_display}[/]")
        else:
            change_display = "both"

        path = (
            default_html_path(asset.symbol, rng.label)
            if html_opt == "AUTO"
            else Path(html_opt)
        )
        with console.status(
            f"[cyan]Rendering HTML ({chart_style}, {change_display})…[/]",
            spinner="dots",
        ):
            written = write_html(
                path,
                asset,
                rng,
                df,
                stats,
                indicators,
                compare_asset,
                compare_df,
                rel,
                compare_stats,
                chart_style=chart_style,
                change_display=change_display,
            )
        console.print(
            f"  [bold]html[/]     [link=file://{written.resolve()}]{written}[/]  "
            f"[dim]({chart_style} · {change_display})[/]"
        )
        if open_html or (
            interactive and Confirm.ask("Open in browser?", default=True)
        ):
            webbrowser.open(written.resolve().as_uri())

    try:
        record_run(
            symbol=asset.symbol,
            timeframe=rng.label,
            indicators=indicators,
            compare=compare_asset.symbol if compare_asset else None,
            chart_style=chart_style if html_opt is not None else None,
            change_display=change_display if html_opt is not None else None,
            html=written,
        )
    except OSError as exc:
        console.print(f"[dim]history not saved: {exc}[/]")

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry — Ctrl+C / Ctrl+D exit cleanly (no traceback)."""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        console.print("\n  [dim]interrupted[/]")
        return 130
    except EOFError:
        console.print("\n  [dim]bye[/]")
        return 0


def _main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Subcommands
    if argv and argv[0] in ("auth", "login", "credentials", "creds"):
        return cmd_auth(argv[1:])

    if argv and argv[0] in ("symbols", "symbol", "tickers", "sym"):
        return cmd_symbols(argv[1:])

    if argv and argv[0] in ("history", "hist", "recent"):
        return cmd_history(argv[1:])

    if argv and argv[0] in ("charts", "chart", "gallery", "html"):
        return cmd_charts(argv[1:])

    args = build_parser().parse_args(argv)
    print_banner()
    seed = SessionSeed()
    interactive = args.ticker is None
    force = args.refresh_symbols

    creds = ensure_credentials(profile=args.profile, console=console)
    set_active_credentials(creds)
    if creds.backend != "environment":
        mode = "paper" if creds.paper else "live"
        console.print(
            f"  [dim]auth[/]  {creds.profile} ({mode})  "
            f"[dim]· {creds.backend}[/]"
        )

    # Always try catalog (downloads Nasdaq list on first run / when stale).
    # FTP failure is non-fatal — ticker still works typed manually.
    with console.status("[cyan]Loading symbol directory…[/]", spinner="dots"):
        index = _load_index(force_refresh=force)

    if index:
        age = ""
        st = catalog_status()
        if st.get("updated_at"):
            age = f"  ·  updated {st['updated_at']}"
        console.print(f"  [dim]directory[/]  {index.count:,} symbols{age}")
    else:
        console.print(
            "  [dim]directory[/]  unavailable  "
            "(run [bold]alpp symbols update[/] when online / FTP works)"
        )
    # Simple rich UI: ticker ajax (or type "history" → tickers | charts)
    if args.ticker is None:
        picked = _prompt_ticker(index)
        if isinstance(picked, SessionSeed):
            seed = picked
            if seed.open_html is not None:
                console.print(f"  [bold]open[/]  {seed.from_label}")
                console.print(f"  [dim]file[/]  {seed.open_html}")
                webbrowser.open(seed.open_html.resolve().as_uri())
                return 0
            if not seed.symbol:
                raise SystemExit("Could not read ticker from that entry")
            ticker = seed.symbol
            # regenerate from history › charts: refresh HTML with live data
            return run_chart_session(
                ticker=ticker,
                timeframe=seed.timeframe or args.timeframe,
                compare=seed.compare or args.compare,
                indicator_raw=args.indicator,
                seed=seed,
                profile=args.profile,
                interactive=True,
                yes=args.yes,
                quiet=args.quiet,
                html="AUTO",
                chart_arg=seed.chart_style or args.chart,
                change_arg=seed.change_display or args.change_display,
                open_html=args.open,
                refresh_symbols=False,
                setup_auth=False,
                index=index,
            )
        ticker = picked
    else:
        ticker = args.ticker

    return run_chart_session(
        ticker=ticker,
        timeframe=args.timeframe,
        compare=args.compare,
        indicator_raw=args.indicator,
        seed=seed,
        profile=args.profile,
        interactive=interactive,
        yes=args.yes,
        quiet=args.quiet,
        html=args.html,
        chart_arg=args.chart,
        change_arg=args.change_display,
        open_html=args.open,
        refresh_symbols=False,
        setup_auth=False,
        index=index,
    )


if __name__ == "__main__":
    raise SystemExit(main())
